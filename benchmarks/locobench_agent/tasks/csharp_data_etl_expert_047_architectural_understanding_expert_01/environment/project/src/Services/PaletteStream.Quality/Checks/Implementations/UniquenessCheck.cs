```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Quality.Checks.Implementations
{
    /// <summary>
    /// A data-quality check that verifies the values of a specified set of columns
    /// are unique across an entire data set / stream.
    ///
    /// The implementation is streaming-friendly—rows are consumed via
    /// <see cref="IAsyncEnumerable{T}"/> so that extremely large data sets can
    /// be validated without materialising them completely in memory.
    /// </summary>
    /// <remarks>
    /// • All key values are converted to <see cref="string"/> and combined into a
    ///   composite key using a non-printable separator to minimise collision risk.<br/>
    /// • A <see cref="HashSet{T}"/> keeps track of keys that have already been
    ///   observed.  For very large cardinality scenarios, consider swapping the
    ///   in-memory implementation with a Bloom filter or sliding-window sketch.<br/>
    /// • The check is deliberately fail-fast: as soon as <c>_maxErrors</c> has
    ///   been reached, evaluation stops and the current results are returned.
    /// </remarks>
    public sealed class UniquenessCheck : IQualityCheck
    {
        private const char CompositeKeySeparator = '\u241F'; // Unit Separator (␟)

        private readonly IReadOnlyList<string> _keyColumns;
        private readonly int _maxErrors;
        private readonly ILogger<UniquenessCheck> _logger;

        public string Name { get; }

        /// <summary>
        /// Creates a new <see cref="UniquenessCheck"/>.
        /// </summary>
        /// <param name="keyColumns">
        /// One or more column names whose combined values must be unique.
        /// </param>
        /// <param name="logger">
        /// Optional <see cref="ILogger"/> for diagnostics.  If not supplied,
        /// <see cref="Microsoft.Extensions.Logging.Abstractions.NullLogger{UniquenessCheck}"/>
        /// is used.
        /// </param>
        /// <param name="maxErrors">
        /// Maximum number of errors to record before returning early.
        /// Defaults to <c>1&#160;000</c>.
        /// </param>
        /// <exception cref="ArgumentException">
        /// Thrown when no <paramref name="keyColumns"/> are provided.
        /// </exception>
        public UniquenessCheck(
            IEnumerable<string> keyColumns,
            ILogger<UniquenessCheck>? logger = null,
            int maxErrors = 1_000)
        {
            if (keyColumns == null) throw new ArgumentNullException(nameof(keyColumns));

            var cols = keyColumns.Where(c => !string.IsNullOrWhiteSpace(c))
                                 .Select(c => c.Trim())
                                 .Distinct(StringComparer.OrdinalIgnoreCase)
                                 .ToArray();

            if (cols.Length == 0)
                throw new ArgumentException("At least one key column must be specified.", nameof(keyColumns));

            if (maxErrors <= 0)
                throw new ArgumentOutOfRangeException(nameof(maxErrors), "maxErrors must be positive.");

            _keyColumns = cols;
            _maxErrors  = maxErrors;
            _logger     = logger ?? Microsoft.Extensions.Logging.Abstractions.NullLogger<UniquenessCheck>.Instance;

            Name = $"UniquenessCheck[{string.Join(", ", _keyColumns)}]";
        }

        /// <inheritdoc/>
        public async Task<QualityCheckResult> EvaluateAsync(
            IAsyncEnumerable<IDictionary<string, object?>> rows,
            CancellationToken cancellationToken = default)
        {
            ArgumentNullException.ThrowIfNull(rows);

            _logger.LogInformation("Starting {CheckName}. Key columns: {KeyColumns}", Name, _keyColumns);

            var seenKeys = new HashSet<string>(StringComparer.Ordinal);
            var errors   = new List<QualityCheckError>(_maxErrors);

            var rowNumber = 0;

            try
            {
                await foreach (var row in rows.WithCancellation(cancellationToken)
                                              .ConfigureAwait(false))
                {
                    rowNumber++;

                    if (!TryBuildCompositeKey(row, out var compositeKey, out var missingColumn))
                    {
                        // Missing column => schema error.
                        var error = new QualityCheckError(
                            $"Column '{missingColumn}' was not provided in the incoming row.",
                            rowNumber,
                            missingColumn,
                            value: null);

                        LogAndAdd(error);
                        if (errors.Count >= _maxErrors) break;

                        continue;
                    }

                    if (!seenKeys.Add(compositeKey))
                    {
                        // Duplicate encountered.
                        var error = new QualityCheckError(
                            "Duplicate key detected.",
                            rowNumber,
                            string.Join(", ", _keyColumns),
                            compositeKey);

                        LogAndAdd(error);
                        if (errors.Count >= _maxErrors) break;
                    }
                }
            }
            catch (OperationCanceledException oce) when (cancellationToken.IsCancellationRequested)
            {
                _logger.LogWarning(oce, "{CheckName} was cancelled by caller after processing {Rows} rows.",
                    Name, rowNumber);

                // Propagate cancellation.
                throw;
            }
            catch (Exception ex)
            {
                // Unexpected runtime failure—wrap it inside the result object so that upstream
                // components can decide how to handle it (e.g., retry, ignore, alert).
                var error = new QualityCheckError(
                    $"Unexpected exception while evaluating uniqueness: {ex.Message}",
                    rowNumber,
                    columnName: null,
                    value: null);

                errors.Add(error);
                _logger.LogError(ex, "{CheckName} failed with an exception.", Name);
            }

            var result = new QualityCheckResult(
                isSuccessful: errors.Count == 0,
                checkName   : Name,
                errors      : errors);

            _logger.LogInformation("{CheckName} finished. Success: {Success}. Rows processed: {Rows}. Errors: {Errors}.",
                Name, result.IsSuccessful, rowNumber, errors.Count);

            return result;

            // Local helper ----------------------------------------------------
            void LogAndAdd(QualityCheckError error)
            {
                errors.Add(error);
                _logger.LogWarning("Uniqueness violation at row {Row}: {Message}", error.RowNumber, error.Message);
            }
        }

        /// <summary>
        /// Builds the composite key for the given <paramref name="row"/>.
        /// </summary>
        /// <returns>
        /// <c>true</c> if all key columns are present; otherwise <c>false</c>.
        /// </returns>
        private bool TryBuildCompositeKey(
            IDictionary<string, object?> row,
            out string compositeKey,
            out string? missingColumn)
        {
            var keyParts = new string[_keyColumns.Count];

            for (var i = 0; i < _keyColumns.Count; i++)
            {
                var column = _keyColumns[i];

                if (!row.TryGetValue(column, out var value))
                {
                    compositeKey  = string.Empty;
                    missingColumn = column;
                    return false;
                }

                keyParts[i] = value?.ToString() ?? string.Empty;
            }

            compositeKey  = string.Join(CompositeKeySeparator, keyParts);
            missingColumn = null;
            return true;
        }
    }

    #region Contracts (simplified)

    /// <summary>
    /// Contract all quality checks must implement.
    /// </summary>
    public interface IQualityCheck
    {
        /// <summary>
        /// Human-friendly name used in logs and UI.
        /// </summary>
        string Name { get; }

        /// <summary>
        /// Executes the check against the supplied row stream.
        /// </summary>
        Task<QualityCheckResult> EvaluateAsync(
            IAsyncEnumerable<IDictionary<string, object?>> rows,
            CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Result returned by a quality check.
    /// </summary>
    /// <param name="IsSuccessful">Indicates overall pass/fail state.</param>
    /// <param name="CheckName">Name of the check.</param>
    /// <param name="Errors">Collection of discovered errors (may be empty).</param>
    public sealed record QualityCheckResult(
        bool IsSuccessful,
        string CheckName,
        IReadOnlyCollection<QualityCheckError> Errors);

    /// <summary>
    /// Describes a single data-quality error discovered during evaluation.
    /// </summary>
    /// <param name="Message">Human-readable description.</param>
    /// <param name="RowNumber">1-based row index where the error occurred.</param>
    /// <param name="ColumnName">Column involved (if applicable).</param>
    /// <param name="Value">The offending value (if available).</param>
    public sealed record QualityCheckError(
        string Message,
        int    RowNumber,
        string? ColumnName,
        string? Value);

    #endregion
}
```