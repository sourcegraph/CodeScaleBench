```csharp
using System;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Polly;
using Polly.Wrap;

namespace PaletteStream.Transformer.Transformers.Implementations
{
    /// <summary>
    /// Transformation strategy that enriches incoming data records with additional
    /// information fetched from an external REST API (e.g. look-ups, geo-coding, etc.).
    ///
    /// The strategy:
    /// * De-duplicates look-ups per batch to minimise external calls
    /// * Employs an IMemoryCache to avoid redundant requests across batches
    /// * Wraps <see cref="HttpClient"/> calls in a Polly policy (retry + circuit-breaker)
    /// * Emits detailed logs for observability
    /// </summary>
    /// <remarks>
    /// Example usage:
    /// 
    ///     var strategy = new EnrichWithApiDataStrategy(
    ///         httpClient,
    ///         new MemoryCache(new MemoryCacheOptions()),
    ///         logger,
    ///         Options.Create(new EnrichWithApiDataOptions
    ///         {
    ///             BaseUrl = "https://api.example.com/v2/metadata",
    ///             ApiKey = "...secret...",
    ///         }));
    /// 
    ///     var enriched = await strategy.TransformAsync(records, cancellationToken);
    /// </remarks>
    public sealed class EnrichWithApiDataStrategy : ITransformationStrategy<IDictionary<string, object>>
    {
        private const string DefaultCachePrefix = "PaletteStream.Transform.Cache.";
        private readonly HttpClient _httpClient;
        private readonly IMemoryCache _cache;
        private readonly ILogger<EnrichWithApiDataStrategy> _logger;
        private readonly EnrichWithApiDataOptions _options;
        private readonly AsyncPolicyWrap<HttpResponseMessage> _policy;

        public EnrichWithApiDataStrategy(
            HttpClient httpClient,
            IMemoryCache cache,
            ILogger<EnrichWithApiDataStrategy> logger,
            IOptions<EnrichWithApiDataOptions> optionsAccessor)
        {
            _httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
            _cache      = cache      ?? throw new ArgumentNullException(nameof(cache));
            _logger     = logger     ?? throw new ArgumentNullException(nameof(logger));
            _options    = optionsAccessor?.Value ?? throw new ArgumentNullException(nameof(optionsAccessor));

            if (string.IsNullOrWhiteSpace(_options.BaseUrl))
                throw new ArgumentException($"{nameof(_options.BaseUrl)} must be provided.");

            // Compose resilience pipeline
            _policy = Policy<HttpResponseMessage>
                .Handle<HttpRequestException>()
                .OrResult(r => r.StatusCode == HttpStatusCode.InternalServerError
                               || r.StatusCode == HttpStatusCode.BadGateway
                               || r.StatusCode == HttpStatusCode.ServiceUnavailable
                               || r.StatusCode == HttpStatusCode.GatewayTimeout)
                .WaitAndRetryAsync(
                    _options.MaxRetryAttempts,
                    attempt => TimeSpan.FromSeconds(Math.Pow(2, attempt)),
                    (outcome, timespan, attempt, _) =>
                    {
                        _logger.LogWarning(
                            outcome.Exception,
                            "Transient error talking to External API (attempt {Attempt}/{Max}). Delaying for {Delay}.",
                            attempt,
                            _options.MaxRetryAttempts,
                            timespan);
                    })
                .WrapAsync(
                    Policy<HttpResponseMessage>
                        .Handle<HttpRequestException>()
                        .OrResult(r => r.StatusCode == HttpStatusCode.InternalServerError)
                        .CircuitBreakerAsync(
                            _options.CircuitBreakerFailureThreshold,
                            _options.CircuitBreakerDuration,
                            onBreak: (outcome, breakDelay) =>
                                _logger.LogWarning(
                                    outcome.Exception,
                                    "Circuit opened for {BreakDelay} due to {Status}.",
                                    breakDelay,
                                    outcome.Result?.StatusCode),
                            onReset: () => _logger.LogInformation("Circuit closed."),
                            onHalfOpen: () => _logger.LogInformation("Circuit in half-open state.")));
        }

        /// <inheritdoc />
        public async Task<IReadOnlyCollection<IDictionary<string, object>>> TransformAsync(
            IReadOnlyCollection<IDictionary<string, object>> records,
            CancellationToken cancellationToken = default)
        {
            if (records is null) throw new ArgumentNullException(nameof(records));
            if (records.Count == 0) return ImmutableArray<IDictionary<string, object>>.Empty;

            _logger.LogDebug("Starting enrichment of {Count} record(s).", records.Count);

            // Collect unique look-up keys (e.g. iso country codes) present in the batch
            var distinctKeys = records
                .Select(r => r.TryGetValue(_options.LookupFieldName, out var v) ? v?.ToString() : null)
                .Where(k => !string.IsNullOrWhiteSpace(k))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToArray();

            // Fetch enrichment payloads in parallel, employing caching
            var fetchedPayloads = await FetchPayloadsAsync(distinctKeys, cancellationToken).ConfigureAwait(false);

            // Project results onto original record list
            foreach (var record in records)
            {
                if (!record.TryGetValue(_options.LookupFieldName, out var keyObj) ||
                    keyObj is null) continue;

                var key = keyObj.ToString() ?? string.Empty;
                if (fetchedPayloads.TryGetValue(key, out var enrichment))
                {
                    ApplyProjection(record, enrichment);
                }
            }

            _logger.LogInformation("Enrichment finished. Enriched {Count} record(s).", records.Count);
            return records.ToImmutableArray();
        }

        #region Helpers

        /// <summary>
        /// Invokes the external API for the provided keys, respecting internal caching.
        /// </summary>
        private async Task<Dictionary<string, JsonElement>> FetchPayloadsAsync(
            IReadOnlyCollection<string> keys,
            CancellationToken ct)
        {
            var result = new Dictionary<string, JsonElement>(StringComparer.OrdinalIgnoreCase);
            if (keys.Count == 0) return result;

            var tasks = keys.Select(k => FetchSingleAsync(k, ct)).ToArray();
            var payloads = await Task.WhenAll(tasks).ConfigureAwait(false);

            foreach ((string key, JsonElement? payload) in payloads)
            {
                if (payload.HasValue)
                {
                    result[key] = payload.Value;
                }
            }

            return result;
        }

        /// <summary>
        /// Fetches a single look-up entry, consulting cache first.
        /// Returns null when no payload could be resolved.
        /// </summary>
        private async Task<(string Key, JsonElement? Payload)> FetchSingleAsync(
            string key,
            CancellationToken ct)
        {
            var cacheKey = $"{DefaultCachePrefix}{key}";
            if (_cache.TryGetValue(cacheKey, out JsonElement cached))
            {
                _logger.LogDebug("Cache hit for key {Key}.", key);
                return (key, cached);
            }

            try
            {
                using var request = BuildHttpRequest(key);
                var response = await _policy.ExecuteAsync(
                    async token => await _httpClient.SendAsync(request, token).ConfigureAwait(false),
                    ct).ConfigureAwait(false);

                if (!response.IsSuccessStatusCode)
                {
                    _logger.LogWarning("Failed to fetch enrichment for {Key} (Status: {Status}).",
                        key, response.StatusCode);
                    return (key, null);
                }

                var contentStream = await response.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
                var payload = await JsonSerializer.DeserializeAsync<JsonElement>(contentStream, cancellationToken: ct)
                              .ConfigureAwait(false);

                // Store in cache
                _cache.Set(cacheKey, payload, _options.CacheDuration);

                return (key, payload);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                throw;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Unhandled error while fetching enrichment for {Key}.", key);
                return (key, null);
            }
        }

        private HttpRequestMessage BuildHttpRequest(string key)
        {
            var uri = $"{_options.BaseUrl.TrimEnd('/')}/{WebUtility.UrlEncode(key)}";
            var request = new HttpRequestMessage(HttpMethod.Get, uri);

            if (!string.IsNullOrWhiteSpace(_options.ApiKey))
            {
                request.Headers.Add("Authorization", $"Bearer {_options.ApiKey}");
            }

            foreach (var header in _options.CustomHeaders)
            {
                request.Headers.TryAddWithoutValidation(header.Key, header.Value);
            }

            return request;
        }

        /// <summary>
        /// Projects enrichment payload onto an existing record in-place.
        /// </summary>
        private void ApplyProjection(IDictionary<string, object> record, JsonElement enrichment)
        {
            foreach (var mapping in _options.ProjectionMap)
            {
                if (enrichment.TryGetProperty(mapping.ApiField, out var apiValue))
                {
                    record[mapping.TargetField] = apiValue.GetString() ?? string.Empty;
                }
            }
        }

        #endregion
    }

    #region Supporting types

    /// <summary>
    /// Strongly-typed options for <see cref="EnrichWithApiDataStrategy"/>.
    /// </summary>
    public sealed class EnrichWithApiDataOptions
    {
        /// <summary>The external service base URL (e.g. https://api.example.com/v1/geo)</summary>
        public string BaseUrl { get; init; } = string.Empty;

        /// <summary>Optional static API key used for all calls.</summary>
        public string? ApiKey { get; init; }

        /// <summary>Key within input records whose value is used to perform look-ups (e.g. "country_code").</summary>
        public string LookupFieldName { get; init; } = "code";

        /// <summary>Mapping of API response fields => record target fields.</summary>
        public IReadOnlyCollection<ProjectionMapping> ProjectionMap { get; init; } = new[]
        {
            new ProjectionMapping {ApiField = "name", TargetField = "CountryName"},
            new ProjectionMapping {ApiField = "population", TargetField = "Population"}
        };

        /// <summary>Additional request headers.</summary>
        public IReadOnlyDictionary<string, string> CustomHeaders { get; init; } = new Dictionary<string, string>();

        /// <summary>Duration results will be cached in memory.</summary>
        public TimeSpan CacheDuration { get; init; } = TimeSpan.FromHours(12);

        /// <summary>Max retry attempts for transient errors.</summary>
        public int MaxRetryAttempts { get; init; } = 3;

        /// <summary>Number of consecutive failures before circuit opens.</summary>
        public int CircuitBreakerFailureThreshold { get; init; } = 5;

        /// <summary>Duration circuit remains open before half-open probing starts.</summary>
        public TimeSpan CircuitBreakerDuration { get; init; } = TimeSpan.FromMinutes(1);
    }

    /// <summary>
    /// Describes how a single field from the API response is projected
    /// onto an output record field.
    /// </summary>
    public sealed class ProjectionMapping
    {
        public string ApiField { get; init; } = string.Empty;
        public string TargetField { get; init; } = string.Empty;
    }

    /// <summary>
    /// Simple abstraction for transformation strategies to plug into the ETL Pipeline.
    /// </summary>
    /// <typeparam name="T">Data record type to be transformed.</typeparam>
    public interface ITransformationStrategy<T>
    {
        /// <summary>Transforms a batch of records.</summary>
        Task<IReadOnlyCollection<T>> TransformAsync(
            IReadOnlyCollection<T> records,
            CancellationToken cancellationToken = default);
    }

    #endregion
}
```