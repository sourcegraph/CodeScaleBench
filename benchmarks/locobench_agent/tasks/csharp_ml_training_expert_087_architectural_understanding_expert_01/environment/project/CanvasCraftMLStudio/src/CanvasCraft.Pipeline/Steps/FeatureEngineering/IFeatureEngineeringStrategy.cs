```csharp
// File: CanvasCraftMLStudio/src/CanvasCraft.Pipeline/Steps/FeatureEngineering/IFeatureEngineeringStrategy.cs

using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Core.Catalog;
using CanvasCraft.Core.Data;
using CanvasCraft.Core.Diagnostics;

namespace CanvasCraft.Pipeline.Steps.FeatureEngineering
{
    /// <summary>
    ///     Defines a contract for a plug-and-play feature-engineering “brush”.
    ///     Concrete implementations are discovered by the <see cref="FeatureEngineeringFactory"/>
    ///     at runtime and chained together by the MLOps Pipeline to construct a
    ///     reproducible <see cref="FeatureSet"/> for downstream model-training steps.
    ///     
    ///     The interface purposefully keeps a high signal/low noise surface area:
    ///       1. <see cref="CanExecute"/> tells the orchestrator whether the strategy is applicable
    ///          for the current <see cref="FeatureEngineeringContext"/>.
    ///       2. <see cref="ExecuteAsync"/> contains the transformation logic. All I/O must be async
    ///          to keep pipeline runs scalable.
    ///     
    ///     Implementations should be side-effect free and rely on the supplied
    ///     <see cref="IDataCatalog"/> instance for any external data access.
    /// </summary>
    public interface IFeatureEngineeringStrategy
    {
        /// <summary>
        ///     Human-readable name used for audit logs and experiment tracking.
        /// </summary>
        string Name { get; }

        /// <summary>
        ///     Describes the attributes this strategy supports (e.g. “Image”, “Text”, “Audio”).
        ///     The flags allow the factory to mix-and-match multiple strategies that
        ///     operate on different modalities within the same dataset.
        /// </summary>
        FeatureEngineeringCapability Capability { get; }

        /// <summary>
        ///     Checks whether the strategy should execute for the provided context.
        ///     The orchestration layer uses the result to short-circuit inapplicable strategies,
        ///     keeping pipeline runs efficient.
        /// </summary>
        /// <remarks>
        ///     Implementations should run fast and avoid any expensive I/O inside this method.
        /// </remarks>
        /// <param name="context">Execution context (dataset signature, experiment metadata, etc.).</param>
        /// <returns><c>true</c> when this strategy can run; otherwise, <c>false</c>.</returns>
        bool CanExecute(FeatureEngineeringContext context);

        /// <summary>
        ///     Performs the actual feature-engineering transformation.
        /// </summary>
        /// <param name="context">Execution context (dataset snapshot, hyper-parameters, etc.).</param>
        /// <param name="cancellationToken">Propagates cancellation from the upstream controller.</param>
        /// <returns>A <see cref="FeatureEngineeringResult"/> containing the engineered <see cref="FeatureSet"/>
        ///          as well as any metrics or artifacts produced during execution.</returns>
        /// <exception cref="OperationCanceledException">Thrown when the operation is canceled.</exception>
        /// <exception cref="FeatureEngineeringException">Thrown on unrecoverable failures.</exception>
        Task<FeatureEngineeringResult> ExecuteAsync(
            FeatureEngineeringContext context,
            CancellationToken cancellationToken = default);
    }

    #region Boilerplate Contracts

    /// <summary>
    ///     Bit-flag enumeration describing what modalities a strategy can process.
    ///     Multiple flags can be combined to express multi-modal strategies.
    /// </summary>
    [Flags]
    public enum FeatureEngineeringCapability
    {
        None        = 0,
        Tabular     = 1 << 0,
        Image       = 1 << 1,
        Text        = 1 << 2,
        Audio       = 1 << 3,
        Video       = 1 << 4,
        TimeSeries  = 1 << 5,
        GeoSpatial  = 1 << 6,
        Custom      = 1 << 31 // Reserved for user-defined extensions
    }

    /// <summary>
    ///     Carries contextual information into a feature-engineering strategy.
    ///     The pipeline populates this struct so that strategies remain stateless.
    /// </summary>
    public sealed class FeatureEngineeringContext
    {
        public FeatureEngineeringContext(
            DatasetVersion dataset,
            ExperimentMetadata experiment,
            IDictionary<string, object>? hyperParameters,
            IDataCatalog catalog,
            ILogger logger)
        {
            Dataset        = dataset;
            Experiment     = experiment;
            HyperParameters = hyperParameters ?? new Dictionary<string, object>();
            Catalog        = catalog;
            Logger         = logger;
        }

        /// <summary>
        ///     The immutable dataset snapshot to operate on.
        /// </summary>
        public DatasetVersion Dataset { get; }

        /// <summary>
        ///     Metadata about the parent experiment run (tags, run-id, user, etc.).
        /// </summary>
        public ExperimentMetadata Experiment { get; }

        /// <summary>
        ///     Hyper-parameters provided by the user or auto-tuner.
        /// </summary>
        public IDictionary<string, object> HyperParameters { get; }

        /// <summary>
        ///     Accessor for centralized data assets (Feature Store, Artifact Store, etc.).
        /// </summary>
        public IDataCatalog Catalog { get; }

        /// <summary>
        ///     Strategy-specific logger instance (scoped to experiment run).
        /// </summary>
        public ILogger Logger { get; }
    }

    /// <summary>
    ///     Result object returned by every feature-engineering strategy.
    /// </summary>
    public sealed class FeatureEngineeringResult
    {
        public FeatureEngineeringResult(
            FeatureSet features,
            IReadOnlyDictionary<string, double> metrics,
            IReadOnlyDictionary<string, Uri> artifacts)
        {
            Features  = features ?? throw new ArgumentNullException(nameof(features));
            Metrics   = metrics  ?? new Dictionary<string, double>();
            Artifacts = artifacts ?? new Dictionary<string, Uri>();
        }

        /// <summary>
        ///     The set of engineered features ready for training or persistence.
        /// </summary>
        public FeatureSet Features { get; }

        /// <summary>
        ///     Any numeric metrics captured during engineering
        ///     (e.g. sparsity, information gain, compression ratio).
        /// </summary>
        public IReadOnlyDictionary<string, double> Metrics { get; }

        /// <summary>
        ///     External artifact references produced by the strategy
        ///     (e.g. PCA eigenvectors, embedding dictionaries).
        /// </summary>
        public IReadOnlyDictionary<string, Uri> Artifacts { get; }
    }

    /// <summary>
    ///     Thrown when a feature-engineering strategy fails in a non-recoverable fashion.
    /// </summary>
    public sealed class FeatureEngineeringException : Exception
    {
        public FeatureEngineeringException(string message, Exception? inner = null)
            : base(message, inner) { }
    }

    #endregion
}
```