using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Linq;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace UtilityChain.TransactionProcessing;

/// <summary>
/// Coordinates the full transaction-lifecycle pipeline: validation, persistence, broadcasting,
/// consensus pre-checks, and state-change notifications.  
/// The processor is intentionally stateless except for a bounded in-memory
/// inflight queue to guarantee back-pressure and prevent mem-exhaustion DoS vectors.
/// </summary>
public sealed class TransactionProcessor : ITransactionProcessor, IAsyncDisposable
{
    private const int DefaultQueueCapacity = 4_096;

    private readonly Channel<TransactionEnvelope> _queue;
    private readonly ILogger<TransactionProcessor> _logger;
    private readonly IEnumerable<ITransactionValidator> _validators;
    private readonly ITransactionRepository _repository;
    private readonly IConsensusOracle _consensusOracle;
    private readonly IPeerBroadcaster _broadcaster;
    private readonly IEventBus _eventBus;
    private readonly CancellationTokenSource _cts = new();
    private readonly Task _worker;

    /// <summary>
    /// Initializes a new <see cref="TransactionProcessor"/> instance.
    /// All dependencies are expected to be wired through DI.
    /// </summary>
    public TransactionProcessor(
        ILogger<TransactionProcessor> logger,
        IEnumerable<ITransactionValidator> validators,
        ITransactionRepository repository,
        IConsensusOracle consensusOracle,
        IPeerBroadcaster broadcaster,
        IEventBus eventBus,
        TransactionProcessorOptions? options = null)
    {
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        _validators = validators?.ToArray() ?? throw new ArgumentNullException(nameof(validators));
        _repository = repository ?? throw new ArgumentNullException(nameof(repository));
        _consensusOracle = consensusOracle ?? throw new ArgumentNullException(nameof(consensusOracle));
        _broadcaster = broadcaster ?? throw new ArgumentNullException(nameof(broadcaster));
        _eventBus = eventBus ?? throw new ArgumentNullException(nameof(eventBus));

        options ??= TransactionProcessorOptions.Default;
        _queue = Channel.CreateBounded<TransactionEnvelope>(
            new BoundedChannelOptions(options.QueueCapacity ?? DefaultQueueCapacity)
            {
                AllowSynchronousContinuations = false,
                FullMode = BoundedChannelFullMode.Wait
            });

        _worker = Task.Factory.StartNew(ProcessLoopAsync,
            _cts.Token,
            TaskCreationOptions.LongRunning,
            TaskScheduler.Default).Unwrap();
    }

    #region ITransactionProcessor

    /// <inheritdoc/>
    public async ValueTask SubmitAsync(Transaction transaction, CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(transaction);

        if (!await _queue.Writer.WaitToWriteAsync(ct).ConfigureAwait(false))
        {
            throw new InvalidOperationException("Transaction queue is closed.");
        }

        // Avoid leaking user token into background pipeline
        var envelope = new TransactionEnvelope(transaction, DateTimeOffset.UtcNow);
        await _queue.Writer.WriteAsync(envelope, ct).ConfigureAwait(false);
    }

    #endregion

    #region Background Processing

    private async Task ProcessLoopAsync()
    {
        _logger.LogInformation("TransactionProcessor event loop started.");

        await foreach (var envelope in _queue.Reader.ReadAllAsync(_cts.Token))
        {
            try
            {
                await HandleTransactionAsync(envelope, _cts.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (_cts.IsCancellationRequested)
            {
                // expected on shutdown
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Fatal error while handling transaction {TxHash}.  Transaction dropped.",
                    envelope.Transaction.Hash);
            }
        }

        _logger.LogInformation("TransactionProcessor event loop stopped.");
    }

    private async Task HandleTransactionAsync(TransactionEnvelope envelope, CancellationToken ct)
    {
        var tx = envelope.Transaction;
        _logger.LogDebug("Handling transaction {TxHash}.", tx.Hash);

        // 1. Run validation pipeline
        foreach (var validator in _validators)
        {
            var result = await validator.ValidateAsync(tx, ct).ConfigureAwait(false);
            if (!result.IsValid)
            {
                _logger.LogWarning("Transaction {TxHash} rejected by validator {Validator} – {Reason}.",
                    tx.Hash, validator.GetType().Name, result.Diagnostic);
                await _eventBus.PublishAsync(new TransactionRejectedEvent(tx, result.Diagnostic), ct);
                return;
            }
        }

        // 2. Consensus pre-admission check (e.g., mempool sizing, fee sufficiency)
        if (!_consensusOracle.MayAccept(tx))
        {
            _logger.LogWarning("Transaction {TxHash} did not satisfy consensus pre-check. Rejected.", tx.Hash);
            await _eventBus.PublishAsync(new TransactionRejectedEvent(tx, "Consensus conditions not met."), ct);
            return;
        }

        // 3. Persist into repository (mempool/pending state)
        try
        {
            await _repository.AddPendingAsync(tx, ct).ConfigureAwait(false);
        }
        catch (DuplicateTransactionException)
        {
            _logger.LogInformation("Duplicate transaction {TxHash} ignored.", tx.Hash);
            return;
        }

        // 4. Broadcast to peers (fire-and-forget, but log failure)
        _ = Task.Run(async () =>
        {
            try
            {
                await _broadcaster.BroadcastAsync(tx, _cts.Token).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to broadcast transaction {TxHash}.", tx.Hash);
            }
        }, CancellationToken.None);

        // 5. Notify local subscribers
        await _eventBus.PublishAsync(new TransactionAcceptedEvent(tx), ct);
        _logger.LogInformation("Transaction {TxHash} accepted.", tx.Hash);
    }

    #endregion

    #region IAsyncDisposable

    /// <inheritdoc/>
    public async ValueTask DisposeAsync()
    {
        try
        {
            _cts.Cancel();

            _queue.Writer.TryComplete();

            await _worker.ConfigureAwait(false);
        }
        finally
        {
            _cts.Dispose();
        }
    }

    #endregion

    #region Nested Types / Options

    private sealed record TransactionEnvelope(Transaction Transaction, DateTimeOffset ReceivedAtUtc);

    /// <summary>
    /// Configurable behaviour for the <see cref="TransactionProcessor"/>.
    /// Provided via DI options pattern.
    /// </summary>
    public sealed record TransactionProcessorOptions
    {
        public static readonly TransactionProcessorOptions Default = new();

        /// <summary>
        /// Maximum number of inflight items kept in memory before back-pressure triggers.
        /// </summary>
        public int? QueueCapacity { get; init; } = DefaultQueueCapacity;
    }

    #endregion
}

/* ------------------------------------------------------------------------------------------
 *  Below are domain contracts referenced by TransactionProcessor; they are intentionally
 *  minimal to avoid leaking irrelevant implementation details while keeping this file
 *  self-contained and compilable in isolation of the rest of the monolith.
 * --------------------------------------------------------------------------------------- */

#region Domain Contracts (abbreviated)

public interface ITransactionProcessor
{
    /// <summary>
    /// Queues a transaction for processing.  The call returns as soon as the
    /// transaction enters the in-memory queue; actual processing is asynchronous.
    /// </summary>
    ValueTask SubmitAsync(Transaction transaction, CancellationToken ct = default);
}

public record Transaction(
    string Hash,
    byte[] Payload,
    IReadOnlyDictionary<string, string>? Metadata = null);

public interface ITransactionValidator
{
    ValueTask<ValidationResult> ValidateAsync(Transaction transaction, CancellationToken ct = default);
}

public readonly record struct ValidationResult(bool IsValid, string? Diagnostic = null)
{
    public static readonly ValidationResult Valid = new(true);
    public static ValidationResult Invalid(string reason) => new(false, reason);
}

public interface ITransactionRepository
{
    ValueTask AddPendingAsync(Transaction tx, CancellationToken ct = default);
}

public sealed class DuplicateTransactionException : Exception
{
    public DuplicateTransactionException(string hash)
        : base($"Transaction '{hash}' already exists.") { }
}

public interface IConsensusOracle
{
    /// <summary>
    /// Lightweight admission-control check invoked before a transaction enters the mempool.
    /// Heavy cryptographic operations are expected later in the pipeline.
    /// </summary>
    bool MayAccept(Transaction tx);
}

public interface IPeerBroadcaster
{
    ValueTask BroadcastAsync(Transaction tx, CancellationToken ct = default);
}

public interface IEventBus
{
    ValueTask PublishAsync<TEvent>(TEvent @event, CancellationToken ct = default)
        where TEvent : class;
}

public sealed record TransactionAcceptedEvent(Transaction Transaction);
public sealed record TransactionRejectedEvent(Transaction Transaction, string Reason);

#endregion