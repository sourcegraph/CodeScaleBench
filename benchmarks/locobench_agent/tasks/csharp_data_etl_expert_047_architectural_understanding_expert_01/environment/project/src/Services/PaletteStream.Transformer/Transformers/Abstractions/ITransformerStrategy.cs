using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace PaletteStream.Transformer.Transformers.Abstractions
{
    /// <summary>
    /// Contract for a strategy-pattern transformer that converts an incoming data “pigment”
    /// (<typeparamref name="TIn"/>) into a new colour or texture (<typeparamref name="TOut"/>).
    ///
    /// Implementations must be thread-safe and stateless; any per-execution state should be
    /// stored on <see cref="TransformationContext"/> so that the pipeline can be replayed,
    /// checkpointed, or forked deterministically.
    /// </summary>
    /// <typeparam name="TIn">Type of the raw input payload.</typeparam>
    /// <typeparam name="TOut">Type of the transformed output payload.</typeparam>
    public interface ITransformerStrategy<in TIn, TOut>
    {
        /// <summary>
        /// Gets a unique, stable identifier for this transformer.
        /// </summary>
        string Id { get; }

        /// <summary>
        /// Gets a human-readable display name that can be surfaced in the Studio UI.
        /// </summary>
        string DisplayName { get; }

        /// <summary>
        /// Gets the capability flags supported by the transformer.
        /// </summary>
        TransformationCapability Capability { get; }

        /// <summary>
        /// Executes the transformation asynchronously.
        /// </summary>
        /// <param name="input">Input pigment.</param>
        /// <param name="context">Ambient transformation context.</param>
        /// <param name="cancellationToken">Cancellation token.</param>
        /// <returns>Transformed pigment.</returns>
        /// <exception cref="TransformationException">
        /// Thrown when the transformer encounters a non-recoverable error.
        /// </exception>
        Task<TOut> TransformAsync(
            TIn input,
            TransformationContext context,
            CancellationToken cancellationToken = default);

        /// <summary>
        /// Determines whether the current transformer can handle the supplied context.
        /// Used by the dispatcher to build an optimal pipeline ahead of execution.
        /// </summary>
        /// <param name="context">Ambient transformation context.</param>
        /// <returns>
        /// <see langword="true"/> if the transformer can handle the context; otherwise <see langword="false"/>.
        /// </returns>
        ValueTask<bool> CanHandleAsync(TransformationContext context);
    }

    /// <summary>
    /// Flags describing the capabilities of a transformer strategy.
    /// </summary>
    [Flags]
    public enum TransformationCapability
    {
        None            = 0,
        Aggregation     = 1 << 0,
        Enrichment      = 1 << 1,
        Anonymisation   = 1 << 2,
        Validation      = 1 << 3,
        GpuAccelerated  = 1 << 4,
        Streaming       = 1 << 5
    }

    /// <summary>
    /// Lightweight context object that flows through the entire transformation pipeline.
    /// Provides a place to store ambient metadata and correlation details.
    /// </summary>
    public sealed class TransformationContext
    {
        private readonly Dictionary<string, object> _items = new(StringComparer.OrdinalIgnoreCase);

        public TransformationContext(Guid correlationId, string tenantId, IDictionary<string, object>? tags = null)
        {
            CorrelationId = correlationId;
            TenantId = tenantId ?? throw new ArgumentNullException(nameof(tenantId));

            if (tags is null) return;

            foreach (var (key, value) in tags)
            {
                _items[key] = value;
            }
        }

        /// <summary>
        /// Gets the correlation identifier used for tracing and logging.
        /// </summary>
        public Guid CorrelationId { get; }

        /// <summary>
        /// Gets the tenant identifier (multi-tenant support).
        /// </summary>
        public string TenantId { get; }

        /// <summary>
        /// Gets free-form key/value storage scoped to the current pipeline execution.
        /// </summary>
        public IDictionary<string, object> Items => _items;

        /// <summary>
        /// Indexer shortcut for <see cref="Items"/>.
        /// </summary>
        /// <param name="key">Item key.</param>
        public object? this[string key]
        {
            get => _items.TryGetValue(key, out var value) ? value : null;
            set => _items[key] = value ?? throw new ArgumentNullException(nameof(value));
        }
    }

    /// <summary>
    /// Exception that wraps non-recoverable errors occurring within a transformer strategy.
    /// The ETL orchestrator will catch this and trigger compensating actions.
    /// </summary>
    public sealed class TransformationException : Exception
    {
        public TransformationException(string message)
            : base(message)
        { }

        public TransformationException(string message, Exception innerException)
            : base(message, innerException)
        { }
    }
}