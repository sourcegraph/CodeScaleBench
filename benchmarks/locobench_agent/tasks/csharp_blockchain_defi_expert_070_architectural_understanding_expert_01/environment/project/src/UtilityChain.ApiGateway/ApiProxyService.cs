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
using Microsoft.Extensions.Options;
using Polly;
using Polly.Extensions.Http;

namespace UtilityChain.ApiGateway;

/// <summary>
///     Production-grade proxy that funnels outbound HTTP and GraphQL requests
///     from the API-Gateway layer to in-process or side-car modules (staking,
///     consensus, governance, etc.).  A resilient PolicyWrap (retry + circuit
///     breaker) is applied per request and correlation information is
///     propagated through custom headers for end-to-end observability.
/// </summary>
public sealed class ApiProxyService : IApiProxyService, IDisposable
{
    private const string CorrelationHeader = "x-correlation-id";

    private readonly IHttpClientFactory _httpClientFactory;
    private readonly ILogger<ApiProxyService> _logger;
    private readonly ApiGatewayOptions _options;
    private readonly AsyncPolicyWrap<HttpResponseMessage> _resiliencyPolicy;
    private readonly JsonSerializerOptions _jsonOptions;
    private bool _disposed;

    public ApiProxyService(
        IHttpClientFactory httpClientFactory,
        IOptions<ApiGatewayOptions> options,
        ILogger<ApiProxyService> logger)
    {
        _httpClientFactory = httpClientFactory ?? throw new ArgumentNullException(nameof(httpClientFactory));
        _logger            = logger            ?? throw new ArgumentNullException(nameof(logger));
        _options           = options?.Value    ?? throw new ArgumentNullException(nameof(options));

        _jsonOptions = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            Converters = { new JsonStringEnumConverter(JsonNamingPolicy.CamelCase) }
        };

        _resiliencyPolicy = BuildResiliencyPolicy();
    }

    /// <inheritdoc />
    public Task<TResult> ForwardRestAsync<TResult>(
        Module          module,
        HttpMethod      method,
        string          relativePath,
        object?         payload          = null,
        IDictionary<string, string>? headers = null,
        CancellationToken              ct    = default)
        => SendAsync<TResult>(module, $"{relativePath}", method, payload, headers, ct);

    /// <inheritdoc />
    public Task<TResult> ForwardGraphQLAsync<TResult>(
        Module          module,
        string          query,
        object?         variables        = null,
        IDictionary<string, string>? headers = null,
        CancellationToken              ct    = default)
    {
        var requestBody = new
        {
            query,
            variables
        };

        return SendAsync<TResult>(module, "graphql", HttpMethod.Post, requestBody, headers, ct);
    }

    /// <summary>
    ///     Centralized send logic wired with Polly policy, error handling, and
    ///     correlation tracking.
    /// </summary>
    private async Task<TResult> SendAsync<TResult>(
        Module          module,
        string          relativePath,
        HttpMethod      method,
        object?         payload,
        IDictionary<string, string>? headers,
        CancellationToken              ct)
    {
        ThrowIfDisposed();

        if (!_options.UpstreamBaseUrls.TryGetValue(module, out var baseUrl))
            throw new ApiProxyException($"Missing upstream URL configuration for module '{module}'.");

        var client = _httpClientFactory.CreateClient(nameof(ApiProxyService));
        client.Timeout = TimeSpan.FromSeconds(_options.TimeoutSeconds);

        var request = new HttpRequestMessage(method, new Uri(new Uri(baseUrl), relativePath));

        // Set correlation id.
        var correlationId = ActivityCorrelation.CurrentId;
        request.Headers.Add(CorrelationHeader, correlationId);

        // Custom headers from caller.
        if (headers is not null)
        {
            foreach (var (key, value) in headers)
                request.Headers.TryAddWithoutValidation(key, value);
        }

        if (payload != null)
        {
            var json = JsonSerializer.Serialize(payload, _jsonOptions);
            request.Content = new StringContent(json, Encoding.UTF8, "application/json");
        }

        _logger.LogDebug("Proxying {Method} {Url} (Module: {Module}, CorrelationId: {CorrelationId})",
            method, request.RequestUri, module, correlationId);

        HttpResponseMessage response;
        try
        {
            response = await _resiliencyPolicy.ExecuteAsync(
                (ct2) => client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct2), ct);
        }
        catch (Exception ex) when (ex is TaskCanceledException or OperationCanceledException)
        {
            _logger.LogWarning(ex, "Request to {Url} was canceled or timed-out.", request.RequestUri);
            throw new ApiProxyException("Upstream request timed-out.", ex);
        }

        await using var _ = response.Content; // Ensure content disposal.

        if (response.StatusCode == HttpStatusCode.NoContent)
            return default!; // Caller expects default value on 204.

        if (!response.IsSuccessStatusCode)
        {
            var error = await response.Content.ReadAsStringAsync(ct);
            _logger.LogError("Upstream returned non-success status code {StatusCode}: {Message}",
                response.StatusCode, error);
            throw new ApiProxyException($"Upstream error {response.StatusCode}. {error}");
        }

        var stream = await response.Content.ReadAsStreamAsync(ct);
        var result = await JsonSerializer.DeserializeAsync<TResult>(stream, _jsonOptions, ct);

        return result ?? throw new ApiProxyException("Unable to deserialize upstream response.");
    }

    private static AsyncPolicyWrap<HttpResponseMessage> BuildResiliencyPolicy()
    {
        // Retry (3x exponential backoff) + circuit-breaker (open 30s after 5 consecutive faults).
        var retry = HttpPolicyExtensions
            .HandleTransientHttpError()
            .WaitAndRetryAsync(3, retryAttempt => TimeSpan.FromMilliseconds(Math.Pow(2, retryAttempt) * 200));

        var breaker = HttpPolicyExtensions
            .HandleTransientHttpError()
            .CircuitBreakerAsync(5, TimeSpan.FromSeconds(30));

        return Policy.WrapAsync(retry, breaker);
    }

    private void ThrowIfDisposed()
    {
        if (_disposed)
            throw new ObjectDisposedException(nameof(ApiProxyService));
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
    }
}

/// <summary>
///     Simple ambient correlation container.  In a full implementation this
///     would integrate with a distributed tracing system such as OpenTelemetry.
/// </summary>
internal static class ActivityCorrelation
{
    private static readonly AsyncLocal<string> _correlationId = new();

    public static string CurrentId
    {
        get
        {
            if (_correlationId.Value is { Length: > 0 })
                return _correlationId.Value;

            var id = Guid.NewGuid().ToString("N");
            _correlationId.Value = id;
            return id;
        }
        set => _correlationId.Value = value;
    }
}

/// <summary>
///     DI contract for the proxy service.
/// </summary>
public interface IApiProxyService
{
    Task<TResult> ForwardRestAsync<TResult>(
        Module          module,
        HttpMethod      method,
        string          relativePath,
        object?         payload = null,
        IDictionary<string, string>? headers = null,
        CancellationToken ct = default);

    Task<TResult> ForwardGraphQLAsync<TResult>(
        Module          module,
        string          query,
        object?         variables = null,
        IDictionary<string, string>? headers = null,
        CancellationToken ct = default);
}

/// <summary>
///     Resolved from appsettings.{env}.json or an equivalent source.
/// </summary>
public sealed class ApiGatewayOptions
{
    /// <summary>
    ///     Mapping between internal modules and their base URLs
    ///     (e.g. "staking": "http://localhost:7001/").
    /// </summary>
    public required Dictionary<Module, string> UpstreamBaseUrls { get; init; }

    /// <summary>
    ///     Global timeout in seconds applied to all outbound calls.
    /// </summary>
    public int TimeoutSeconds { get; init; } = 30;
}

/// <summary>
///     Well-known modules addressable by the gateway.
/// </summary>
public enum Module
{
    Staking,
    Consensus,
    Governance,
    Token,
    Nft,
    SmartContracts
}

/// <summary>
///     Thrown when the proxy cannot satisfy the request due to configuration
///     errors, upstream connectivity problems, or serialization issues.
/// </summary>
public class ApiProxyException : Exception
{
    public ApiProxyException(string message) : base(message) { }

    public ApiProxyException(string message, Exception inner) : base(message, inner) { }
}