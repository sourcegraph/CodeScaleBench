```csharp
using System;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Globalization;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Data.Analysis;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using PaletteStream.Transformer.Events;
using PaletteStream.Transformer.Options;
using PaletteStream.Transformer.Transformers.Abstractions;

namespace PaletteStream.Transformer.Transformers.Implementations
{
    /// <summary>
    /// Replaces personally-identifiable information (PII) with irreversible tokens
    /// using hashing / masking techniques.  The strategy supports column-level
    /// configuration and emits observer events to the monitoring mesh.
    /// </summary>
    [ExcludeFromCodeCoverage]
    public sealed class AnonymizePIIStrategy : ITransformationStrategy
    {
        private readonly ILogger<AnonymizePIIStrategy> _logger;
        private readonly AnonymizationOptions _options;
        private readonly ITransformationEventBus _eventBus;
        private const string StrategyName = "AnonymizePII";

        public string Name => StrategyName;

        public AnonymizePIIStrategy(
            ILogger<AnonymizePIIStrategy> logger,
            IOptions<AnonymizationOptions> options,
            ITransformationEventBus eventBus)
        {
            _logger   = logger  ?? throw new ArgumentNullException(nameof(logger));
            _options  = options?.Value ?? throw new ArgumentNullException(nameof(options));
            _eventBus = eventBus ?? throw new ArgumentNullException(nameof(eventBus));
        }

        /// <inheritdoc/>
        public async ValueTask<DataFrame> TransformAsync(
            DataFrame input, 
            CancellationToken cancellationToken = default)
        {
            if (input == null)
                throw new ArgumentNullException(nameof(input));

            if (!_options.Enabled)
            {
                _logger.LogInformation("{Strategy}: Anonymization disabled in configuration. Returning input unchanged.", StrategyName);
                return input;
            }

            await _eventBus.PublishAsync(new TransformationStarted(StrategyName, DateTimeOffset.UtcNow), cancellationToken)
                            .ConfigureAwait(false);

            var stopwatch = System.Diagnostics.Stopwatch.StartNew();

            try
            {
                var output = input.Clone(); // Deep copy for immutability guarantees.

                foreach (var rule in _options.ColumnRules)
                {
                    cancellationToken.ThrowIfCancellationRequested();

                    if (!output.Columns.Contains(rule.ColumnName))
                    {
                        _logger.LogWarning(
                            "{Strategy}: Column '{Column}' not found in dataframe. Skipping.",
                            StrategyName, rule.ColumnName);
                        continue;
                    }

                    _logger.LogDebug("{Strategy}: Anonymizing column '{Column}' as {Type}.", StrategyName, rule.ColumnName, rule.Type);

                    switch (rule.Type)
                    {
                        case PiiType.Email:
                            HashColumn(output.Columns[rule.ColumnName], NormalizeEmail);
                            break;

                        case PiiType.Phone:
                            HashColumn(output.Columns[rule.ColumnName], NormalizePhone);
                            break;

                        case PiiType.Ssn:
                            MaskColumn(output.Columns[rule.ColumnName], 4, '*');
                            break;

                        case PiiType.FullName:
                            MaskColumn(output.Columns[rule.ColumnName], 1, '*');
                            break;

                        case PiiType.Generic:
                        default:
                            HashColumn(output.Columns[rule.ColumnName], static v => v);
                            break;
                    }
                }

                stopwatch.Stop();

                await _eventBus.PublishAsync(
                    new TransformationCompleted(
                        StrategyName, 
                        DateTimeOffset.UtcNow, 
                        stopwatch.Elapsed),
                    cancellationToken).ConfigureAwait(false);

                return output;
            }
            catch (Exception ex)
            {
                stopwatch.Stop();
                _logger.LogError(ex, "{Strategy}: Error occurred during anonymization.", StrategyName);
                await _eventBus.PublishAsync(
                    new TransformationFailed(
                        StrategyName, 
                        DateTimeOffset.UtcNow, 
                        ex),
                    cancellationToken).ConfigureAwait(false);

                throw; // bubble up – pipeline error-handling will compensate
            }
        }

        #region Column Helpers
        private static void HashColumn(DataFrameColumn column, Func<string, string> normalize)
        {
            for (var i = 0; i < column.Length; i++)
            {
                if (column[i] is not string value || string.IsNullOrWhiteSpace(value))
                    continue;

                var normalized = normalize(value);
                column[i] = Sha256Hex(normalized);
            }
        }

        private static void MaskColumn(DataFrameColumn column, int visibleTail, char maskChar)
        {
            for (var i = 0; i < column.Length; i++)
            {
                if (column[i] is not string value || string.IsNullOrEmpty(value))
                    continue;

                var tail = value[^Math.Min(visibleTail, value.Length)..];
                column[i] = new string(maskChar, Math.Max(0, value.Length - visibleTail)) + tail;
            }
        }
        #endregion

        #region Transform Helpers
        private static string Sha256Hex(string input)
        {
            using var sha = SHA256.Create();
            var bytes = sha.ComputeHash(Encoding.UTF8.GetBytes(input));
            var sb = new StringBuilder(bytes.Length * 2);
            foreach (var b in bytes)
                sb.Append(b.ToString("x2", CultureInfo.InvariantCulture));
            return sb.ToString();
        }

        private static string NormalizeEmail(string email)
        {
            // Lowercase & trim to reduce entropy before hashing
            return email.Trim().ToLowerInvariant();
        }

        private static string NormalizePhone(string phone)
        {
            // Digit-only phone representation
            return new string(phone.Where(char.IsDigit).ToArray());
        }
        #endregion
    }

    #region Options & Rules

    /// <summary>
    /// DI-bindable options that govern PII anonymization behaviour.
    /// </summary>
    public sealed class AnonymizationOptions
    {
        public bool Enabled { get; init; } = true;

        public IReadOnlyList<PiiColumnRule> ColumnRules { get; init; } = Array.Empty<PiiColumnRule>();
    }

    public sealed record PiiColumnRule(string ColumnName, PiiType Type);

    public enum PiiType
    {
        Generic,
        Email,
        Phone,
        Ssn,
        FullName
    }

    #endregion

    #region Interfaces (simplified placeholders)

    /// <summary>
    /// Minimal contract for a transformation strategy used by the ETL pipeline.
    /// </summary>
    public interface ITransformationStrategy
    {
        string Name { get; }

        ValueTask<DataFrame> TransformAsync(
            DataFrame input, 
            CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Simple event bus abstraction that the ETL observer mesh subscribes to.
    /// </summary>
    public interface ITransformationEventBus
    {
        ValueTask PublishAsync(ITransformationEvent @event, CancellationToken cancellationToken = default);
    }

    #endregion

    #region Event DTOs (simplified)

    public interface ITransformationEvent
    {
        string Strategy { get; }
        DateTimeOffset Timestamp { get; }
    }

    public sealed record TransformationStarted(
        string Strategy,
        DateTimeOffset Timestamp) : ITransformationEvent;

    public sealed record TransformationCompleted(
        string Strategy,
        DateTimeOffset Timestamp,
        TimeSpan Duration) : ITransformationEvent;

    public sealed record TransformationFailed(
        string Strategy,
        DateTimeOffset Timestamp,
        Exception Exception) : ITransformationEvent;

    #endregion
}
```