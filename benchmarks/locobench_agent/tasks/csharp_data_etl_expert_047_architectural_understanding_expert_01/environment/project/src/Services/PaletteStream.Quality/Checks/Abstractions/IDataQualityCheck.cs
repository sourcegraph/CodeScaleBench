```csharp
// -------------------------------------------------------------------------------------------------
// PaletteStream ETL Canvas
// File: PaletteStream-ETL-Canvas/src/Services/PaletteStream.Quality/Checks/Abstractions/IDataQualityCheck.cs
//
// Copyright ©
// -------------------------------------------------------------------------------------------------
// Description:
//     Contract for implementing data-quality checks used by the PaletteStream Quality service.
//     Quality checks are executed by the orchestration layer after each transformation “brush-stroke”
//     to ensure that data pigments meet the required quality thresholds before being blended into
//     the Data Lake canvas.
// -------------------------------------------------------------------------------------------------

using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace PaletteStream.Quality.Checks.Abstractions
{
    /// <summary>
    ///     Contract that must be implemented by every data-quality check in the PaletteStream ETL pipeline.
    ///     Implementations should be stateless and thread-safe because they may be executed in parallel
    ///     by the orchestration layer.
    /// </summary>
    /// <typeparam name="T">
    ///     The type of data batch being inspected. This can range from a single record model to
    ///     an <see cref="IEnumerable{T}" /> of records or an immutable DataFrame segment.
    /// </typeparam>
    public interface IDataQualityCheck<in T>
    {
        /// <summary>
        ///     Unique technical identifier (machine-readable) of the check, e.g. <c>"PS-QC-NULL-01"</c>.
        /// </summary>
        string Id { get; }

        /// <summary>
        ///     Friendly human-readable name that will surface in dashboards and logs.
        /// </summary>
        string Name { get; }

        /// <summary>
        ///     Detailed description that explains what the rule validates and why it exists.
        /// </summary>
        string Description { get; }

        /// <summary>
        ///     Severity of the check. Determines if a failed check produces a warning,
        ///     fails the pipeline, or is merely informational.
        /// </summary>
        QualitySeverity Severity { get; }

        /// <summary>
        ///     Runs the data-quality check asynchronously.
        /// </summary>
        /// <param name="data">
        ///     The data instance/batch to validate.
        /// </param>
        /// <param name="cancellationToken">
        ///     Token that signals that the operation should be canceled. Implementations must respect
        ///     the token to keep the pipeline responsive.
        /// </param>
        /// <returns>
        ///     A <see cref="DataQualityCheckResult" /> describing whether the data passed the check and,
        ///     if not, listing any issues that were detected.
        /// </returns>
        /// <exception cref="ArgumentNullException">
        ///     Thrown if <paramref name="data" /> is <c>null</c>.
        /// </exception>
        Task<DataQualityCheckResult> EvaluateAsync(
            T data,
            CancellationToken cancellationToken = default);
    }

    /// <summary>
    ///     The severity of a data-quality rule or issue. Controls orchestration behavior.
    /// </summary>
    public enum QualitySeverity
    {
        Info = 0,
        Warning = 1,
        Error = 2,
        Critical = 3
    }

    /// <summary>
    ///     Result envelope returned by <see cref="IDataQualityCheck{T}.EvaluateAsync" />.
    /// </summary>
    public sealed record DataQualityCheckResult
    {
        private DataQualityCheckResult(
            bool isSuccessful,
            IReadOnlyCollection<DataQualityIssue>? issues)
        {
            IsSuccessful = isSuccessful;
            Issues = issues ?? Array.Empty<DataQualityIssue>();
        }

        /// <summary>
        ///     Indicates whether the check succeeded. A value of <c>false</c> means that at least
        ///     one issue was detected.
        /// </summary>
        public bool IsSuccessful { get; }

        /// <summary>
        ///     Collection of data-quality issues detected during evaluation.
        /// </summary>
        public IReadOnlyCollection<DataQualityIssue> Issues { get; }

        /// <summary>
        ///     Creates a successful result (no issues).
        /// </summary>
        public static DataQualityCheckResult Success() =>
            new(isSuccessful: true, issues: null);

        /// <summary>
        ///     Creates a failed result with a single <paramref name="issue" />.
        /// </summary>
        public static DataQualityCheckResult Failure(DataQualityIssue issue) =>
            new(isSuccessful: false, issues: new[] { issue });

        /// <summary>
        ///     Creates a failed result with multiple <paramref name="issues" />.
        /// </summary>
        public static DataQualityCheckResult Failure(
            IReadOnlyCollection<DataQualityIssue> issues) =>
            new(isSuccessful: false, issues: issues);
    }

    /// <summary>
    ///     Represents a single data-quality issue discovered during a check evaluation.
    /// </summary>
    /// <param name="Message">
    ///     Human-readable description of the violation.
    /// </param>
    /// <param name="Field">
    ///     Optional name of the offending field/column.
    /// </param>
    /// <param name="OffendingValue">
    ///     Optional string representation of the value that caused the failure.
    ///     Avoid serializing sensitive data; anonymize when necessary.
    /// </param>
    /// <param name="Severity">
    ///     Severity level of the issue; should correspond with the parent rule’s 
    ///     <see cref="IDataQualityCheck{T}.Severity"/>.
    /// </param>
    public sealed record DataQualityIssue(
        string Message,
        string? Field,
        string? OffendingValue,
        QualitySeverity Severity);
}
```