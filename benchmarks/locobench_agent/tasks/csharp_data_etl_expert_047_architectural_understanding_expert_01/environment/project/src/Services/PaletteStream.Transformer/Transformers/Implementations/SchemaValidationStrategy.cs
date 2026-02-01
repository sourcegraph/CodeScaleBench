using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json.Schema;

namespace PaletteStream.Transformer.Transformers.Implementations
{
    /// <summary>
    /// Strategy that validates incoming JSON payloads against a compiled JSON schema.
    /// Designed to be plugged into the PaletteStream ETL pipeline as a transformation step.
    /// </summary>
    public sealed class SchemaValidationStrategy : ITransformationStrategy<JToken, JToken>, IDisposable
    {
        private readonly ILogger<SchemaValidationStrategy> _logger;
        private readonly JSchema _schema;
        private readonly ISchemaViolationPublisher _violationPublisher;
        private readonly SchemaValidationOptions _options;

        /// <summary>
        /// Initializes a new instance of the <see cref="SchemaValidationStrategy"/> class.
        /// </summary>
        /// <param name="schemaJson">The JSON schema document in textual form.</param>
        /// <param name="options">Validation behaviour options.</param>
        /// <param name="logger">Structured logger.</param>
        /// <param name="violationPublisher">
        /// Optional publisher used to propagate validation-failure events to
        /// monitoring, alerting, or a dead-letter queue.
        /// </param>
        /// <exception cref="ArgumentException">Thrown when <paramref name="schemaJson"/> is null or empty.</exception>
        public SchemaValidationStrategy(
            string schemaJson,
            SchemaValidationOptions? options,
            ILogger<SchemaValidationStrategy> logger,
            ISchemaViolationPublisher? violationPublisher = null)
        {
            if (string.IsNullOrWhiteSpace(schemaJson))
            {
                throw new ArgumentException("Schema JSON must be provided.", nameof(schemaJson));
            }

            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
            _options = options ?? SchemaValidationOptions.Default;
            _violationPublisher = violationPublisher ?? NullSchemaViolationPublisher.Instance;

            _schema = JSchema.Parse(
                schemaJson,
                new JSchemaReaderSettings
                {
                    ValidateVersion = true,
                    Resolver = JSchemaUrlResolver.GetDefaultSchemaResolver()
                });

            _logger.LogInformation(
                "SchemaValidationStrategy initialised. ValidationMode: {Mode}. SchemaVersion: {Version}",
                _options.ValidationMode,
                _schema.SchemaVersion ?? "N/A");
        }

        /// <inheritdoc />
        public async Task<TransformationResult<JToken>> TransformAsync(
            JToken input,
            CancellationToken cancellationToken = default)
        {
            if (input == null)
            {
                throw new ArgumentNullException(nameof(input));
            }

            // Validate the payload and capture errors
            if (input.IsValid(_schema, out IList<string>? rawErrors))
            {
                return TransformationResult<JToken>.Success(input);
            }

            // Collect errors into an immutable list
            var errorMessages = rawErrors?.Count > 0
                ? new List<string>(rawErrors)
                : new List<string> { "Unknown schema error." };

            // Build violation event for observers
            var violation = new SchemaViolationEvent(
                correlationId: Guid.NewGuid().ToString("N"),
                occurredAtUtc: DateTime.UtcNow,
                payload: input.ToString(Formatting.None),
                schemaVersion: _schema.SchemaVersion ?? "N/A",
                errors: errorMessages);

            await _violationPublisher.PublishAsync(violation, cancellationToken)
                                     .ConfigureAwait(false);

            string combinedError = string.Join("; ", errorMessages);
            _logger.LogWarning("Schema validation failed. Errors: {Errors}", combinedError);

            return _options.ValidationMode switch
            {
                SchemaValidationMode.Raise => throw new SchemaValidationException(combinedError)
                {
                    Errors = errorMessages
                },
                SchemaValidationMode.Filter => TransformationResult<JToken>.FilteredOut,
                _ => throw new SchemaValidationException(combinedError)
            };
        }

        public void Dispose()
        {
            // Future-proofing for unmanaged resources (e.g., GPU schema execution contexts)
        }
    }

    #region ─── Supporting Types ────────────────────────────────────────────────────────────

    /// <summary>
    /// Controls how the strategy reacts to payloads that fail validation.
    /// </summary>
    public enum SchemaValidationMode
    {
        /// <summary>
        /// Throw an exception and bubble the error up the pipeline.
        /// </summary>
        Raise,

        /// <summary>
        /// Silently filter the record out and continue processing.
        /// </summary>
        Filter
    }

    /// <summary>
    /// Configuration options for <see cref="SchemaValidationStrategy"/>.
    /// </summary>
    public sealed class SchemaValidationOptions
    {
        /// <summary>
        /// Gets a default options instance (ValidationMode = Raise).
        /// </summary>
        public static SchemaValidationOptions Default { get; } = new();

        /// <summary>
        /// Gets or sets how invalid records are handled.
        /// </summary>
        public SchemaValidationMode ValidationMode { get; set; } = SchemaValidationMode.Raise;
    }

    /// <summary>
    /// Exception thrown when a payload does not conform to the target schema.
    /// </summary>
    public sealed class SchemaValidationException : Exception
    {
        public SchemaValidationException(string message)
            : base(message)
        {
        }

        /// <summary>
        /// Gets detailed validation error messages, if available.
        /// </summary>
        public ICollection<string> Errors { get; init; } = Array.Empty<string>();
    }

    /// <summary>
    /// Observer publisher used to emit schema violation events.
    /// </summary>
    public interface ISchemaViolationPublisher
    {
        Task PublishAsync(SchemaViolationEvent violationEvent, CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// No-op implementation used when no publisher is registered.
    /// </summary>
    internal sealed class NullSchemaViolationPublisher : ISchemaViolationPublisher
    {
        public static readonly NullSchemaViolationPublisher Instance = new();

        private NullSchemaViolationPublisher()
        {
        }

        public Task PublishAsync(SchemaViolationEvent violationEvent, CancellationToken cancellationToken = default)
            => Task.CompletedTask;
    }

    /// <summary>
    /// Immutable event representing a validation failure.
    /// </summary>
    public sealed record SchemaViolationEvent(
        string CorrelationId,
        DateTime OccurredAtUtc,
        string Payload,
        string SchemaVersion,
        ICollection<string> Errors);

    /// <summary>
    /// Standard transformation result wrapper.
    /// </summary>
    public readonly struct TransformationResult<TOutput>
    {
        private TransformationResult(TOutput? value, bool isSuccess, bool isFiltered)
        {
            Value = value;
            IsSuccess = isSuccess;
            IsFiltered = isFiltered;
        }

        public TOutput? Value { get; }
        public bool IsSuccess { get; }
        public bool IsFiltered { get; }

        public static TransformationResult<TOutput> Success(TOutput value) =>
            new(value, isSuccess: true, isFiltered: false);

        public static TransformationResult<TOutput> FilteredOut { get; } =
            new(default, isSuccess: false, isFiltered: true);
    }

    /// <summary>
    /// Contract implemented by all transformation strategies in the PaletteStream ETL pipeline.
    /// </summary>
    public interface ITransformationStrategy<in TInput, TOutput>
    {
        Task<TransformationResult<TOutput>> TransformAsync(TInput input, CancellationToken cancellationToken = default);
    }

    #endregion
}