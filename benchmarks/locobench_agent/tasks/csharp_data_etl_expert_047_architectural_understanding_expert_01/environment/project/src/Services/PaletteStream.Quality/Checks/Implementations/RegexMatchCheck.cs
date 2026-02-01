```csharp
using System;
using System.Diagnostics;
using System.Globalization;
using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Quality.Checks.Implementations
{
    /// <summary>
    ///     Performs a data-quality check that validates an incoming value
    ///     against a configurable Regular Expression pattern.
    /// </summary>
    /// <remarks>
    ///     A <see cref="RegexMatchCheck"/> instance is designed to be reused
    ///     across threads and rows in an ETL pipeline and is therefore fully
    ///     thread-safe.
    /// </remarks>
    public sealed class RegexMatchCheck : IDataQualityCheck
    {
        private readonly Lazy<Regex> _compiledRegex;
        private readonly ILogger<RegexMatchCheck>? _logger;
        private readonly bool _allowNullOrEmpty;

        /// <summary>
        ///     Creates a new instance of <see cref="RegexMatchCheck"/>.
        /// </summary>
        /// <param name="code">
        ///     A short, unique identifier for this check (e.g. <c>EMAIL_REGEX</c>).
        /// </param>
        /// <param name="description">
        ///     A human-readable description that will be surfaced in dashboards
        ///     and error reports.
        /// </param>
        /// <param name="pattern">
        ///     The Regex pattern to apply.
        /// </param>
        /// <param name="options">
        ///     Optional Regex options (defaults to
        ///     <see cref="RegexOptions.Compiled"/> | <see cref="RegexOptions.CultureInvariant"/>.
        /// </param>
        /// <param name="allowNullOrEmpty">
        ///     When <c>true</c>, <c>null</c> or empty values are treated as a
        ///     success.  When <c>false</c>, they are treated as failures.
        /// </param>
        /// <param name="logger">
        ///     Optional logger instance.
        /// </param>
        /// <exception cref="ArgumentException">
        ///     Thrown when <paramref name="pattern"/> is <c>null</c> or whitespace.
        /// </exception>
        public RegexMatchCheck(
            string code,
            string description,
            string pattern,
            RegexOptions? options = null,
            bool allowNullOrEmpty = true,
            ILogger<RegexMatchCheck>? logger = null)
        {
            if (string.IsNullOrWhiteSpace(code))
                throw new ArgumentException("Code must be supplied", nameof(code));
            if (string.IsNullOrWhiteSpace(pattern))
                throw new ArgumentException("Pattern must be supplied", nameof(pattern));

            Code        = code;
            Description = description ?? throw new ArgumentNullException(nameof(description));
            _allowNullOrEmpty = allowNullOrEmpty;
            _logger = logger;

            // Use Lazy<Regex> so the pattern is compiled exactly once in a
            // thread-safe way, regardless of how many parallel Evaluate calls
            // run.
            _compiledRegex = new Lazy<Regex>(
                () => new Regex(
                    pattern,
                    (options ?? (RegexOptions.Compiled | RegexOptions.CultureInvariant)) 
                    | RegexOptions.ExplicitCapture),
                isThreadSafe: true);
        }

        /* ---------------------------  IQualityCheck  --------------------------- */

        /// <inheritdoc />
        public string Code { get; }

        /// <inheritdoc />
        public string Description { get; }

        /// <inheritdoc />
        public QualityCheckResult Evaluate(object? value, in CheckContext context)
        {
            try
            {
                if (value is null || string.IsNullOrEmpty(value.ToString()))
                {
                    return _allowNullOrEmpty
                        ? QualityCheckResult.Success(Code)
                        : QualityCheckResult.Fail(
                            Code,
                            context,
                            $"Value is {(value is null ? "null" : "an empty string")}.");
                }

                var stringValue = Convert.ToString(value, CultureInfo.InvariantCulture)!;

                var isMatch = _compiledRegex.Value.IsMatch(stringValue);

                if (isMatch)
                {
                    return QualityCheckResult.Success(Code);
                }

                return QualityCheckResult.Fail(
                    Code,
                    context,
                    $"Value '{Truncate(stringValue)}' does not match required pattern.");
            }
            catch (Exception ex)
            {
                // Defensive logging, never throw here – checks must not derail
                // the entire pipeline.
                _logger?.LogError(ex, "RegexMatchCheck ({Code}) threw an exception.", Code);

                return QualityCheckResult.Fail(
                    Code,
                    context,
                    $"Exception while executing RegexMatchCheck: {ex.Message}",
                    QualityCheckSeverity.Error);
            }
        }

        /* -------------------------  Implementation  --------------------------- */

        private static string Truncate(string input, int maxLength = 80)
        {
            return (input.Length <= maxLength)
                ? input
                : input.Substring(0, maxLength - 3) + "...";
        }
    }

    #region --- Support Contracts (kept internal for compilation purposes) ---

    /// <summary>
    ///     Represents the outcome of a data-quality evaluation.
    /// </summary>
    public readonly record struct QualityCheckResult
    {
        private QualityCheckResult(
            bool isSuccess,
            string code,
            QualityCheckSeverity severity,
            string? message,
            CheckContext context)
        {
            IsSuccess = isSuccess;
            Code      = code;
            Severity  = severity;
            Message   = message;
            Context   = context;
        }

        public bool                 IsSuccess { get; }
        public string               Code      { get; }
        public QualityCheckSeverity Severity  { get; }
        public string?              Message   { get; }
        public CheckContext         Context   { get; }

        public static QualityCheckResult Success(string code) =>
            new(true, code, QualityCheckSeverity.Info, null, CheckContext.None);

        public static QualityCheckResult Fail(
            string code,
            in CheckContext context,
            string message,
            QualityCheckSeverity severity = QualityCheckSeverity.Warning) =>
            new(false, code, severity, message, context);
    }

    /// <summary>
    ///     Provides metadata about the data record being evaluated.
    /// </summary>
    public readonly record struct CheckContext
    {
        public static readonly CheckContext None = new();

        public CheckContext(
            string? dataSet           = default,
            string? columnName        = default,
            long?   rowNumber         = default,
            Guid?   ingestionBatchId  = default)
        {
            DataSet          = dataSet;
            ColumnName       = columnName;
            RowNumber        = rowNumber;
            IngestionBatchId = ingestionBatchId;
        }

        public string? DataSet          { get; init; }
        public string? ColumnName       { get; init; }
        public long?   RowNumber        { get; init; }
        public Guid?   IngestionBatchId { get; init; }
    }

    /// <summary>
    ///     Logically groups the severity of a failed quality check.
    /// </summary>
    public enum QualityCheckSeverity
    {
        Info    = 0,
        Warning = 1,
        Error   = 2,
        Fatal   = 3
    }

    /// <summary>
    ///     Minimal interface definition for data-quality checks.
    /// </summary>
    public interface IDataQualityCheck
    {
        string Code          { get; }
        string Description   { get; }

        QualityCheckResult Evaluate(object? value, in CheckContext context);
    }

    #endregion
}
```