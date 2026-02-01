```csharp
// --------------------------------------------------------------------------------------------------------------------
// <copyright>
//   CanvasCraft ML Studio
//   © 2024 CanvasCraft. All rights reserved.
// </copyright>
// <author>CanvasCraft Engineering Team</author>
// <summary>
//   Defines the contract for all data–preprocessing strategies that can be plugged into the
//   CanvasCraft MLOps Pipeline. Concrete implementations (e.g., NormalizationStrategy,
//   OutlierRemovalStrategy) must follow this interface so they can be discovered at runtime
//   by the Strategy & Factory layers.
// </summary>
// --------------------------------------------------------------------------------------------------------------------

#nullable enable

using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace CanvasCraft.Pipeline.Steps.DataPreprocessing
{
    /// <summary>
    /// Contract that all preprocessing strategies must satisfy.
    /// </summary>
    public interface IDataPreprocessingStrategy : IAsyncDisposable
    {
        /// <summary>
        /// Gets a stable identifier for the strategy implementation (e.g., "standard_scaler").
        /// The ID must be unique across the application so that it can be referenced in
        /// experiment-tracking metadata and audit logs.
        /// </summary>
        string StrategyId { get; }

        /// <summary>
        /// Gets a human-readable display name (e.g., "Standard Scaler (Z-Score)").
        /// </summary>
        string DisplayName { get; }

        /// <summary>
        /// Gets the <see cref="PreprocessingContext"/> produced after <see cref="Configure"/> has been
        /// invoked. The context is meant to carry stateful information (e.g., fitted parameters,
        /// feature statistics) that could be reused across multiple calls to <see cref="ExecuteAsync"/>.
        /// </summary>
        PreprocessingContext Context { get; }

        /// <summary>
        /// Configures the strategy. An implementation may lazily compute statistics or
        /// allocate resources in this step. Calling <see cref="Configure"/> twice should be
        /// idempotent; subsequent calls may be ignored or update only changed fields.
        /// </summary>
        /// <param name="options">Strongly-typed options that parameterize the strategy.</param>
        /// <exception cref="ArgumentNullException">Thrown when <paramref name="options"/> is null.</exception>
        /// <exception cref="PreprocessingException">Thrown when validation fails.</exception>
        void Configure(DataPreprocessingOptions options);

        /// <summary>
        /// Determines whether the current strategy can process the provided <paramref name="batch"/>.
        /// </summary>
        /// <remarks>
        /// A strategy may only accept certain data modalities (e.g., numeric tabular, images),
        /// or require specific schema conditions to be satisfied.
        /// </remarks>
        bool CanProcess(DataBatch batch);

        /// <summary>
        /// Executes the preprocessing step asynchronously.
        /// </summary>
        /// <param name="batch">Input batch to be transformed.</param>
        /// <param name="progress">
        /// Optional progress reporter, allowing UI layers or logging subsystems
        /// to receive fine-grained updates.
        /// </param>
        /// <param name="cancellationToken">Token that can be used to cancel execution.</param>
        /// <returns>Transformed <see cref="DataBatch"/> that downstream pipeline steps can consume.</returns>
        /// <exception cref="ArgumentNullException">Thrown when <paramref name="batch"/> is null.</exception>
        /// <exception cref="OperationCanceledException">
        /// Thrown when <paramref name="cancellationToken"/> signals cancellation.
        /// </exception>
        /// <exception cref="PreprocessingException">Thrown when preprocessing fails.</exception>
        Task<DataBatch> ExecuteAsync(
            DataBatch batch,
            IProgress<PreprocessingProgress>? progress = null,
            CancellationToken cancellationToken = default);
    }

    #region ———————————————————————————— Supporting Infrastructure ————————————————————————————

    /// <summary>
    /// Lightweight container object representing a batch of data rows plus metadata.
    /// </summary>
    public sealed record DataBatch(
        IReadOnlyList<DataArtifact> Artifacts,
        IReadOnlyDictionary<string, object>? Metadata = null)
    {
        /// <summary>
        /// Clones the current batch with a new set of artifacts while preserving metadata.
        /// </summary>
        public DataBatch WithArtifacts(IReadOnlyList<DataArtifact> newArtifacts) =>
            this with { Artifacts = newArtifacts };
    }

    /// <summary>
    /// Represents a single unit of data—could be a row, an image, an audio sample, etc.
    /// </summary>
    public sealed record DataArtifact(string Key, object Payload);

    /// <summary>
    /// Encapsulates runtime diagnostics and fitted parameters for a strategy instance.
    /// </summary>
    public sealed record PreprocessingContext(
        IReadOnlyDictionary<string, object> Parameters,
        DateTimeOffset FittedAtUtc);

    /// <summary>
    /// Strongly-typed options bag passed into <see cref="IDataPreprocessingStrategy.Configure"/>.
    /// </summary>
    public sealed record DataPreprocessingOptions
    {
        /// <summary>
        /// Gets or sets arbitrary named parameters; for simple scalar settings.
        /// </summary>
        public IDictionary<string, object> Parameters { get; init; } = new Dictionary<string, object>();

        /// <summary>
        /// Gets or sets the expected list of features that downstream components
        /// will rely on. Useful for schema validation.
        /// </summary>
        public IList<string> ExpectedFeatures { get; init; } = new List<string>();

        /// <summary>
        /// Gets or sets an optional random seed to make stochastic preprocessing steps deterministic.
        /// </summary>
        public int? RandomSeed { get; init; }
    }

    /// <summary>
    /// Emits incremental progress information during preprocessing.
    /// </summary>
    public readonly record struct PreprocessingProgress(int Completed, int Total, string? Stage = null);

    /// <summary>
    /// Domain-specific exception thrown during preprocessing.
    /// </summary>
    public sealed class PreprocessingException : Exception
    {
        public PreprocessingException(string message) : base(message) { }
        public PreprocessingException(string message, Exception innerException) : base(message, innerException) { }
    }

    #endregion
}
```