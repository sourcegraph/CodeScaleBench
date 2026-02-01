```csharp
using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using Polly;
using Polly.Timeout;
using Polly.Wrap;

namespace CanvasCraft.WebApp.Services
{
    /// <summary>
    /// Contract for low-level REST communication with CanvasCraft back-end services.
    /// Abstracted behind an interface to ease testing and allow mocking.
    /// </summary>
    public interface IApiClient
    {
        Task<TResponse> GetAsync<TResponse>(string relativePath, CancellationToken ct = default);
        Task<TResponse> PostAsync<TPayload, TResponse>(string relativePath, TPayload payload, CancellationToken ct = default);
        Task<TResponse> PutAsync<TPayload, TResponse>(string relativePath, TPayload payload, CancellationToken ct = default);
        Task DeleteAsync(string relativePath, CancellationToken ct = default);
    }

    /// <summary>
    /// Wrapper around <see cref="HttpClient"/> that provides:
    ///  • Automated (de)serialization
    ///  • Structured logging
    ///  • Resilience (retry, circuit-breaker, timeout)
    ///  • Centralised error handling
    /// </summary>
    public sealed class ApiClient : IApiClient
    {
        private static readonly JsonSerializerOptions JsonOptions = new JsonSerializerOptions
        {
            PropertyNamingPolicy             = JsonNamingPolicy.CamelCase,
            DefaultIgnoreCondition           = JsonIgnoreCondition.WhenWritingNull,
            WriteIndented                    = false,
            Converters                       = { new JsonStringEnumConverter(JsonNamingPolicy.CamelCase) }
        };

        // Resilience policies — tunable via configuration if desired
        private static readonly AsyncPolicyWrap<HttpResponseMessage> ResiliencePolicy = Policy<HttpResponseMessage>
            .Handle<HttpRequestException>()
            .OrResult(r => (int)r.StatusCode >= 500 || r.StatusCode == HttpStatusCode.RequestTimeout)
            .WaitAndRetryAsync(
                retryCount: 3,
                sleepDurationProvider: attempt => TimeSpan.FromMilliseconds(200 * Math.Pow(2, attempt)),
                onRetry: (outcome, ts, attempt, ctx) =>
                {
                    if (ctx.TryGetLogger(out var logger))
                    {
                        logger.LogWarning(
                            outcome.Exception,
                            "Transient failure calling {OperationKey}. Waiting {Delay} before next retry. Attempt {Attempt}.",
                            ctx.OperationKey,
                            ts,
                            attempt);
                    }
                })
            .WrapAsync(
                Policy<HttpResponseMessage>
                    .Handle<HttpRequestException>()
                    .Or<TimeoutRejectedException>()
                    .CircuitBreakerAsync(
                        exceptionsAllowedBeforeBreaking: 5,
                        durationOfBreak: TimeSpan.FromSeconds(30),
                        onBreak: (outcome, breakDelay) =>
                        {
                            outcome.Context.TryGetLogger(out var logger);
                            logger?.LogError(outcome.Exception,
                                             "Circuit broken for {BreakDelay}.",
                                             breakDelay);
                        },
                        onReset: context =>
                        {
                            context.TryGetLogger(out var logger);
                            logger?.LogInformation("Circuit reset.");
                        }));

        private readonly HttpClient            _http;
        private readonly ILogger<ApiClient>    _logger;
        private readonly IApiTokenProvider?    _tokenProvider;

        public ApiClient(HttpClient http,
                         ILogger<ApiClient> logger,
                         IApiTokenProvider? tokenProvider = null)
        {
            _http          = http  ?? throw new ArgumentNullException(nameof(http));
            _logger        = logger ?? throw new ArgumentNullException(nameof(logger));
            _tokenProvider = tokenProvider; // optional
        }

        #region Public API methods

        public async Task<TResponse> GetAsync<TResponse>(string relativePath, CancellationToken ct = default)
        {
            var request = BuildRequest(HttpMethod.Get, relativePath);
            return await SendAsync<TResponse>(request, ct)
                .ConfigureAwait(false);
        }

        public async Task<TResponse> PostAsync<TPayload, TResponse>(string relativePath, TPayload payload, CancellationToken ct = default)
        {
            var request = BuildRequest(HttpMethod.Post, relativePath, payload);
            return await SendAsync<TResponse>(request, ct)
                .ConfigureAwait(false);
        }

        public async Task<TResponse> PutAsync<TPayload, TResponse>(string relativePath, TPayload payload, CancellationToken ct = default)
        {
            var request = BuildRequest(HttpMethod.Put, relativePath, payload);
            return await SendAsync<TResponse>(request, ct)
                .ConfigureAwait(false);
        }

        public async Task DeleteAsync(string relativePath, CancellationToken ct = default)
        {
            var request = BuildRequest(HttpMethod.Delete, relativePath);
            await SendAsync<object?>(request, ct) // discarded
                .ConfigureAwait(false);
        }

        #endregion

        #region Core send logic

        private async Task<T> SendAsync<T>(HttpRequestMessage request, CancellationToken ct)
        {
            // Bind logger to Polly context for diagnostics
            var pollyCtx = new Context(operationKey: $"{request.Method} {request.RequestUri}");
            pollyCtx.SetLogger(_logger);

            using HttpResponseMessage response = await ResiliencePolicy.ExecuteAsync(
                (ctx, token) => _http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, token),
                pollyCtx,
                ct);

            if (!response.IsSuccessStatusCode)
            {
                await HandleErrorAsync(response, ct).ConfigureAwait(false);
            }

            if (typeof(T) == typeof(object) || response.StatusCode == HttpStatusCode.NoContent)
            {
                return default!; // intentionally ignore body
            }

            await using var stream = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
            var result = await JsonSerializer.DeserializeAsync<T>(stream, JsonOptions, ct)
                         .ConfigureAwait(false);

            if (result is null)
            {
                throw new ApiClientException(
                    response.StatusCode,
                    "Unable to deserialize response content.",
                    await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false));
            }

            return result;
        }

        /// <summary>
        /// Handles non-success HTTP codes by throwing a typed <see cref="ApiClientException"/>.
        /// </summary>
        private static async Task HandleErrorAsync(HttpResponseMessage response, CancellationToken ct)
        {
            var body = await response.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            throw new ApiClientException(response.StatusCode, "API request failed.", body);
        }

        #endregion

        #region Request factory helpers

        private HttpRequestMessage BuildRequest<TPayload>(HttpMethod method, string relativePath, TPayload? payload = default)
        {
            if (string.IsNullOrWhiteSpace(relativePath))
                throw new ArgumentException("Relative path must not be empty.", nameof(relativePath));

            var request = new HttpRequestMessage(method, relativePath);

            // Attach bearer token when available
            if (_tokenProvider?.TryGetToken(out var token) == true)
            {
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
            }

            if (payload is not null)
            {
                var json   = JsonSerializer.Serialize(payload, JsonOptions);
                request.Content = new StringContent(json, Encoding.UTF8, "application/json");
            }

            _logger.LogDebug("Prepared {Method} {Url}", method, request.RequestUri);
            return request;
        }

        #endregion
    }

    #region Support types & extensions

    /// <summary>
    /// Strongly-typed exception thrown for any non-success HTTP response.
    /// </summary>
    public sealed class ApiClientException : Exception
    {
        public HttpStatusCode StatusCode { get; }
        public string?        ResponseBody { get; }

        public ApiClientException(HttpStatusCode statusCode, string message, string? responseBody)
            : base(message)
        {
            StatusCode   = statusCode;
            ResponseBody = responseBody;
        }
    }

    /// <summary>
    /// Provides authentication tokens used by <see cref="ApiClient"/>.
    /// </summary>
    public interface IApiTokenProvider
    {
        bool TryGetToken(out string? token);
    }

    internal static class PollyContextExtensions
    {
        private const string LoggerKey = "Logger";

        public static void SetLogger(this Context ctx, ILogger logger) => ctx[LoggerKey] = logger;

        public static bool TryGetLogger(this Context ctx, out ILogger? logger)
        {
            if (ctx.TryGetValue(LoggerKey, out var value) && value is ILogger l)
            {
                logger = l;
                return true;
            }

            logger = null;
            return false;
        }
    }

    #endregion
}
```