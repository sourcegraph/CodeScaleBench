```csharp
// File: TycoonVerse/src/TycoonVerse.Infrastructure/Networking/ApiClient.cs
#nullable enable
using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using Polly;
using Polly.Retry;

namespace TycoonVerse.Infrastructure.Networking
{
    /// <summary>
    /// Thread–safe, resilient HTTP client used by the infrastructure layer to
    /// communicate with first- and third-party backends.  All requests flow through this class
    /// so that authentication, connectivity detection, metrics, and offline persistence
    /// are handled consistently across the game.
    /// </summary>
    public sealed class ApiClient : IApiClient, IDisposable
    {
        /* -----------------------------------------------------------------
         * Fields
         * -----------------------------------------------------------------*/

        private readonly HttpClient _httpClient;
        private readonly IAuthenticationProvider _authProvider;
        private readonly IConnectivityService _connectivity;
        private readonly IOfflineRequestStore _offlineStore;
        private readonly ILogger<ApiClient> _logger;
        private readonly JsonSerializerOptions _jsonOptions;
        private readonly AsyncRetryPolicy<HttpResponseMessage> _retryPolicy;

        private bool _disposed;

        /* -----------------------------------------------------------------
         * Constructor
         * -----------------------------------------------------------------*/

        public ApiClient(
            HttpClient httpClient,
            IAuthenticationProvider authProvider,
            IConnectivityService connectivity,
            IOfflineRequestStore offlineStore,
            ILogger<ApiClient> logger,
            JsonSerializerOptions? jsonOptions = null)
        {
            _httpClient     = httpClient  ?? throw new ArgumentNullException(nameof(httpClient));
            _authProvider   = authProvider ?? throw new ArgumentNullException(nameof(authProvider));
            _connectivity   = connectivity ?? throw new ArgumentNullException(nameof(connectivity));
            _offlineStore   = offlineStore ?? throw new ArgumentNullException(nameof(offlineStore));
            _logger         = logger       ?? throw new ArgumentNullException(nameof(logger));

            _jsonOptions = jsonOptions ?? new JsonSerializerOptions
            {
                PropertyNamingPolicy        = JsonNamingPolicy.CamelCase,
                DefaultIgnoreCondition      = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull,
                PropertyNameCaseInsensitive = true
            };

            // Exponential back-off retry (100ms, 200ms, 400ms)
            _retryPolicy = Policy<HttpResponseMessage>
                .Handle<HttpRequestException>()
                .OrResult(r => r.StatusCode is HttpStatusCode.InternalServerError or HttpStatusCode.BadGateway
                                        or HttpStatusCode.GatewayTimeout or HttpStatusCode.ServiceUnavailable)
                .WaitAndRetryAsync(
                    retryCount: 3,
                    sleepDurationProvider: retryAttempt => TimeSpan.FromMilliseconds(100 * Math.Pow(2, retryAttempt)),
                    onRetry: (outcome, delay, retryAttempt, ctx) =>
                    {
                        _logger.LogWarning(
                            outcome.Exception,
                            "HTTP retry {RetryAttempt}. Waiting {Delay}ms. StatusCode={StatusCode}",
                            retryAttempt,
                            delay.TotalMilliseconds,
                            outcome.Result?.StatusCode);
                    });
        }

        /* -----------------------------------------------------------------
         * Public API
         * -----------------------------------------------------------------*/

        /// <inheritdoc />
        public async Task<TResponse?> SendAsync<TResponse>(
            ApiRequest request,
            CancellationToken cancellationToken = default)
        {
            if (request is null) throw new ArgumentNullException(nameof(request));
            ThrowIfDisposed();

            if (!_connectivity.IsOnline)
            {
                await QueueOfflineAsync(request, cancellationToken).ConfigureAwait(false);
                return default;
            }

            // Attach auth token just-in-time
            await EnsureAuthorizationHeaderAsync(cancellationToken).ConfigureAwait(false);

            using var httpRequest = BuildHttpRequestMessage(request);

            HttpResponseMessage? response = null;
            try
            {
                response = await _retryPolicy.ExecuteAsync(
                    ct => _httpClient.SendAsync(httpRequest, HttpCompletionOption.ResponseHeadersRead, ct),
                    cancellationToken).ConfigureAwait(false);

                // If connectivity died mid request, store and bubble
                if (!_connectivity.IsOnline)
                {
                    await QueueOfflineAsync(request, cancellationToken).ConfigureAwait(false);
                    return default;
                }

                if (response.IsSuccessStatusCode)
                {
                    // Fast-path for void result
                    if (typeof(TResponse) == typeof(VoidType))
                        return default;

                    // Read the JSON body
                    var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);

                    var result = await JsonSerializer.DeserializeAsync<TResponse>(
                        stream,
                        _jsonOptions,
                        cancellationToken).ConfigureAwait(false);

                    return result;
                }

                // Unauthorized? Token might be expired – attempt refresh once.
                if (response.StatusCode == HttpStatusCode.Unauthorized)
                {
                    _logger.LogInformation("401 Unauthorized received. Refreshing bearer token.");
                    await _authProvider.RefreshTokenAsync(cancellationToken).ConfigureAwait(false);

                    // Re-attach new token
                    await EnsureAuthorizationHeaderAsync(cancellationToken).ConfigureAwait(false);

                    response = await _httpClient.SendAsync(httpRequest, cancellationToken).ConfigureAwait(false);

                    if (response.IsSuccessStatusCode)
                    {
                        return await response.Content.ReadFromJsonAsync<TResponse>(
                            _jsonOptions,
                            cancellationToken).ConfigureAwait(false);
                    }
                }

                // Let caller decide how to handle API-level errors
                string errorPayload = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
                throw new ApiException(
                    response.StatusCode,
                    $"Request to {request.Endpoint} failed with code {(int)response.StatusCode} ({response.StatusCode}).",
                    errorPayload);
            }
            finally
            {
                response?.Dispose();
            }
        }

        /// <inheritdoc />
        public async Task FlushOfflineQueueAsync(CancellationToken cancellationToken = default)
        {
            ThrowIfDisposed();

            if (!_connectivity.IsOnline)
                return;

            IReadOnlyCollection<ApiRequest> pending = await _offlineStore.ReadAllAsync(cancellationToken).ConfigureAwait(false);
            if (pending.Count == 0)
                return;

            _logger.LogInformation("Flushing {Count} queued API requests.", pending.Count);

            foreach (var req in pending)
            {
                try
                {
                    await SendAsync<VoidType>(req, cancellationToken).ConfigureAwait(false);
                    await _offlineStore.RemoveAsync(req.Id, cancellationToken).ConfigureAwait(false);
                }
                catch (Exception ex) when (!ex.IsFatal())
                {
                    _logger.LogWarning(ex, "Failed to flush queued request {RequestId}. It will be retried later.", req.Id);
                    // Do not throw; continue processing the remainder.
                }
            }
        }

        /* -----------------------------------------------------------------
         * IDisposable
         * -----------------------------------------------------------------*/

        public void Dispose()
        {
            if (_disposed) return;

            _httpClient?.Dispose();
            _disposed = true;
            GC.SuppressFinalize(this);
        }

        /* -----------------------------------------------------------------
         * Internal helpers
         * -----------------------------------------------------------------*/

        private async Task QueueOfflineAsync(ApiRequest request, CancellationToken cancellationToken)
        {
            _logger.LogInformation("Enqueuing request {RequestId} for offline processing.", request.Id);
            await _offlineStore.SaveAsync(request, cancellationToken).ConfigureAwait(false);
        }

        private async Task EnsureAuthorizationHeaderAsync(CancellationToken cancellationToken)
        {
            string? token = await _authProvider.GetAccessTokenAsync(cancellationToken).ConfigureAwait(false);
            if (string.IsNullOrEmpty(token))
                return;

            if (_httpClient.DefaultRequestHeaders.Authorization?.Parameter != token)
            {
                _httpClient.DefaultRequestHeaders.Authorization =
                    new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", token);
            }
        }

        private static HttpRequestMessage BuildHttpRequestMessage(ApiRequest request)
        {
            var httpRequest = new HttpRequestMessage(request.Method, request.Endpoint);

            // Headers
            foreach (var (key, value) in request.Headers)
            {
                httpRequest.Headers.TryAddWithoutValidation(key, value);
            }

            // Body
            if (request.Body is not null)
            {
                if (request.Body is HttpContent directContent)
                {
                    httpRequest.Content = directContent;
                }
                else
                {
                    string json = JsonSerializer.Serialize(request.Body, request.Body.GetType(), request.SerializerOptions);
                    httpRequest.Content = new StringContent(json, Encoding.UTF8, "application/json");
                }
            }

            return httpRequest;
        }

        private void ThrowIfDisposed()
        {
            if (_disposed)
                throw new ObjectDisposedException(nameof(ApiClient));
        }

        /* -----------------------------------------------------------------
         * Nested / helper classes & extensions
         * -----------------------------------------------------------------*/

        /// <summary>
        /// Marker type used when a caller doesn't expect a payload (equivalent to 'void').
        /// </summary>
        private sealed class VoidType { }

    }

    /* -----------------------------------------------------------------
     * Interfaces & contracts
     * -----------------------------------------------------------------*/

    public interface IApiClient
    {
        /// <summary>
        /// Sends a request to the API endpoint, automatically attaching authentication
        /// and applying resiliency policies.
        /// </summary>
        /// <typeparam name="TResponse">CLR type used to deserialize the JSON response.</typeparam>
        /// <param name="request">Request details.</param>
        /// <param name="cancellationToken">Cancellation token passed downstream.</param>
        /// <returns>Deserialized response instance when available; <c>null</c> for void endpoints or if queued offline.</returns>
        Task<TResponse?> SendAsync<TResponse>(ApiRequest request, CancellationToken cancellationToken = default);

        /// <summary>
        /// Attempts to send any API requests that were captured while the device was offline.
        /// </summary>
        Task FlushOfflineQueueAsync(CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Contract representing a serializable API request that can be replayed when connectivity returns.
    /// </summary>
    public sealed class ApiRequest
    {
        public Guid Id { get; } = Guid.NewGuid();
        public Uri Endpoint { get; init; }
        public HttpMethod Method { get; init; } = HttpMethod.Get;
        public object? Body { get; init; }
        public IReadOnlyDictionary<string, string> Headers { get; init; } = new Dictionary<string, string>();
        public JsonSerializerOptions SerializerOptions { get; init; } = new();

        public ApiRequest(Uri endpoint, HttpMethod method = null!, object? body = null, IReadOnlyDictionary<string, string>? headers = null)
        {
            Endpoint = endpoint ?? throw new ArgumentNullException(nameof(endpoint));
            Method   = method   ?? HttpMethod.Get;
            Body     = body;
            if (headers is not null)
                Headers = headers;
        }

        // Parameterless ctor for (de)serialization
        private ApiRequest() {}
    }

    /// <summary>
    /// Handles retrieving and refreshing access tokens.
    /// </summary>
    public interface IAuthenticationProvider
    {
        Task<string?> GetAccessTokenAsync(CancellationToken cancellationToken);
        Task RefreshTokenAsync(CancellationToken cancellationToken);
    }

    /// <summary>
    /// Detects internet connectivity changes.
    /// </summary>
    public interface IConnectivityService
    {
        bool IsOnline { get; }
    }

    /// <summary>
    /// Persists requests that need to be replayed when connectivity returns.
    /// </summary>
    public interface IOfflineRequestStore
    {
        Task SaveAsync(ApiRequest request, CancellationToken cancellationToken);
        Task<IReadOnlyCollection<ApiRequest>> ReadAllAsync(CancellationToken cancellationToken);
        Task RemoveAsync(Guid requestId, CancellationToken cancellationToken);
    }

    /// <summary>
    /// Exception that represents non-successful HTTP responses returned from remote API endpoints.
    /// </summary>
    public sealed class ApiException : Exception
    {
        public HttpStatusCode StatusCode { get; }
        public string? ResponseBody { get; }

        public ApiException(HttpStatusCode statusCode, string message, string? responseBody = null, Exception? inner = null)
            : base(message, inner)
        {
            StatusCode = statusCode;
            ResponseBody = responseBody;
        }
    }

    internal static class ExceptionExtensions
    {
        // Determines whether an exception is considered fatal to the application.
        public static bool IsFatal(this Exception ex) =>
            ex is OutOfMemoryException
            or StackOverflowException
            or AccessViolationException;
    }
}
```