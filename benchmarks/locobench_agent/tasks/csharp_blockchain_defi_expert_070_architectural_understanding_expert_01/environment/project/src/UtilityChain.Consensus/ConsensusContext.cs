```csharp
// -----------------------------------------------------------------------------
//  UtilityChain Core Suite
//  File: UtilityChainCoreSuite/src/UtilityChain.Consensus/ConsensusContext.cs
// -----------------------------------------------------------------------------
//  Description
//  -----------
//  Central in-memory state container and coordinator for the consensus layer.
//  ConsensusContext subscribes to the domain event bus (Observer pattern) and
//  delegates engine-specific work to an interchangeable IConsensusEngine
//  (Strategy + Factory patterns).  It is the single source of truth for the
//  current epoch, slot, validator set, and vote receipts, enabling other
//  modules (staking, governance, API gateway) to interrogate consensus state
//  without directly coupling to the engine implementation.
// -----------------------------------------------------------------------------

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using UtilityChain.Common.Guards;
using UtilityChain.Common.Time;
using UtilityChain.Messaging;
using UtilityChain.Persistence;

namespace UtilityChain.Consensus;

/// <summary>
/// Represents the authoritative, thread-safe context object that maintains
/// the volatile consensus state for the running node.  This includes
/// coordination of epochs/slots, vote receipts, validator liveness tracking,
/// and delegated execution of the underlying consensus algorithm.
/// </summary>
public sealed class ConsensusContext : IDisposable
{
    private readonly IConsensusEngine                 _engine;
    private readonly IEventBus                        _eventBus;
    private readonly IStateStore                      _stateStore;
    private readonly ILogger<ConsensusContext>        _logger;
    private readonly ISystemClock                     _clock;

    private readonly ReaderWriterLockSlim             _stateLock = new();
    private readonly ConcurrentDictionary<Guid, Vote> _pendingVotes = new();

    // Cancellation/Task management ------------------------------------------------
    private readonly CancellationTokenSource          _cts = new();
    private Task?                                     _backgroundTask;

    // Internal mutable state ------------------------------------------------------
    private ConsensusState _state;

    public ConsensusContext(
        IConsensusEngine engine,
        IEventBus eventBus,
        IStateStore stateStore,
        ISystemClock clock,
        ILogger<ConsensusContext> logger)
    {
        _engine     = Guard.NotNull(engine);
        _eventBus   = Guard.NotNull(eventBus);
        _stateStore = Guard.NotNull(stateStore);
        _clock      = Guard.NotNull(clock);
        _logger     = Guard.NotNull(logger);

        _state = LoadOrCreateInitialState();
    }

    // -------------------------------------------------------------------------
    //  Lifecycle
    // -------------------------------------------------------------------------
    public void Start()
    {
        _logger.LogInformation("ConsensusContext starting for epoch {Epoch}.", _state.Epoch);

        // Subscribe to relevant domain events (Observer pattern)
        _eventBus.Subscribe<BlockCommittedEvent>(HandleBlockCommitted);
        _eventBus.Subscribe<VoteReceivedEvent>(HandleVoteReceived);

        // Kick off background duties (e.g. slot timer)
        _backgroundTask = Task.Factory.StartNew(
            RunSlotLoopAsync,
            _cts.Token,
            TaskCreationOptions.LongRunning,
            TaskScheduler.Default
        ).Unwrap();
    }

    public async Task StopAsync()
    {
        _logger.LogInformation("ConsensusContext stopping …");

        _cts.Cancel();
        if (_backgroundTask is not null)
        {
            try
            {
                await _backgroundTask.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                _logger.LogDebug("Consensus background task canceled.");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Consensus background task stopped with error.");
            }
        }

        _eventBus.Unsubscribe<BlockCommittedEvent>(HandleBlockCommitted);
        _eventBus.Unsubscribe<VoteReceivedEvent>(HandleVoteReceived);

        _logger.LogInformation("ConsensusContext stopped.");
    }

    public void Dispose()
    {
        _cts.Cancel();
        _cts.Dispose();
        _stateLock.Dispose();
    }

    // -------------------------------------------------------------------------
    //  Public API
    // -------------------------------------------------------------------------
    /// <summary>
    /// Returns a snapshot of the current validator set.
    /// </summary>
    public IReadOnlyList<Validator> GetCurrentValidators()
    {
        _stateLock.EnterReadLock();
        try
        {
            return _state.Validators.ToList();
        }
        finally
        {
            _stateLock.ExitReadLock();
        }
    }

    /// <summary>
    /// Attempts to retrieve a vote by its identifier from the in-memory cache.
    /// </summary>
    public bool TryGetVote(Guid voteId, [NotNullWhen(true)] out Vote? vote)
        => _pendingVotes.TryGetValue(voteId, out vote);

    // -------------------------------------------------------------------------
    //  Event Handlers (Observer pattern)
    // -------------------------------------------------------------------------
    private void HandleBlockCommitted(BlockCommittedEvent evt)
    {
        _logger.LogDebug(
            "Block {Height} committed; updating state for epoch {Epoch}.",
            evt.Block.Header.Height,
            _state.Epoch);

        _stateLock.EnterWriteLock();
        try
        {
            _state = _state with
            {
                LastBlockHash      = evt.Block.Header.Hash,
                LastBlockTimestamp = evt.Block.Header.Timestamp
            };
        }
        finally
        {
            _stateLock.ExitWriteLock();
        }
    }

    private void HandleVoteReceived(VoteReceivedEvent evt)
    {
        if (_pendingVotes.TryAdd(evt.Vote.Id, evt.Vote))
        {
            _logger.LogTrace("Vote {VoteId} queued from validator {ValidatorId}.",
                evt.Vote.Id,
                evt.Vote.ValidatorId);
        }
    }

    // -------------------------------------------------------------------------
    //  Slot Loop
    // -------------------------------------------------------------------------
    private async Task RunSlotLoopAsync()
    {
        _logger.LogInformation("Slot loop started.");
        while (!_cts.IsCancellationRequested)
        {
            try
            {
                await ExecuteSlotAsync(_cts.Token).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error executing consensus slot.");
            }
        }

        _logger.LogInformation("Slot loop exited.");
    }

    private async Task ExecuteSlotAsync(CancellationToken ct)
    {
        ConsensusState snapshot;
        _stateLock.EnterReadLock();
        try
        {
            snapshot = _state;
        }
        finally
        {
            _stateLock.ExitReadLock();
        }

        var slotStart   = _clock.UtcNow;
        var slotEnd     = slotStart.Add(snapshot.SlotDuration);

        _logger.LogDebug("Executing slot {Slot} of epoch {Epoch}.", snapshot.SlotIndex, snapshot.Epoch);

        // Strategy pattern: delegate to the configured consensus engine
        var result = await _engine.ExecuteSlotAsync(snapshot, ct).ConfigureAwait(false);

        switch (result)
        {
            case SlotResult.BlockProposed proposal:
                _eventBus.Publish(new BlockProposedEvent(proposal.Block));
                break;

            case SlotResult.Empty:
                _logger.LogTrace("Slot {Slot} completed with no block proposal.", snapshot.SlotIndex);
                break;
        }

        // Rotate to next slot
        _stateLock.EnterWriteLock();
        try
        {
            var nextSlot = (snapshot.SlotIndex + 1) % snapshot.SlotsPerEpoch;
            var epoch    = snapshot.Epoch + (nextSlot == 0 ? 1UL : 0UL);

            _state = snapshot with
            {
                SlotIndex   = nextSlot,
                Epoch       = epoch,
                SlotStarted = slotStart
            };
        }
        finally
        {
            _stateLock.ExitWriteLock();
        }

        var delay = slotEnd - _clock.UtcNow;
        if (delay > TimeSpan.Zero)
        {
            await Task.Delay(delay, ct).ConfigureAwait(false);
        }
    }

    // -------------------------------------------------------------------------
    //  Private helpers
    // -------------------------------------------------------------------------
    private ConsensusState LoadOrCreateInitialState()
    {
        try
        {
            var persisted = _stateStore.Get<ConsensusState>("ConsensusState");
            if (persisted is not null)
            {
                _logger.LogInformation("Loaded consensus state from persistence.");
                return persisted;
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Unable to load persisted consensus state. Falling back to default.");
        }

        // Defaults for a newly bootstrapped chain
        var genesisValidators = _stateStore.Get<IReadOnlyList<Validator>>("GenesisValidators")
                               ?? Array.Empty<Validator>();

        return new ConsensusState(
            epoch:               0UL,
            slotIndex:           0,
            slotsPerEpoch:       64,
            slotDuration:        TimeSpan.FromSeconds(3),
            validators:          genesisValidators,
            lastBlockHash:       null,
            lastBlockTimestamp:  DateTimeOffset.MinValue,
            slotStarted:         _clock.UtcNow
        );
    }

    // -------------------------------------------------------------------------
    //  Data/DTO records
    // -------------------------------------------------------------------------
    private sealed record ConsensusState(
        ulong               Epoch,
        int                 SlotIndex,
        int                 SlotsPerEpoch,
        TimeSpan            SlotDuration,
        IReadOnlyList<Validator> Validators,
        string?             LastBlockHash,
        DateTimeOffset      LastBlockTimestamp,
        DateTimeOffset      SlotStarted);

    public sealed record Validator(
        string             Id,
        string             PublicKey,
        bool               IsActive,
        ulong              Stake);

    // -------------------------------------------------------------------------
    //  Event payloads (internal to ConsensusContext for brevity)
    // -------------------------------------------------------------------------
    public sealed record BlockCommittedEvent(Block Block);
    public sealed record BlockProposedEvent(Block Block);
    public sealed record VoteReceivedEvent(Vote Vote);

    // -------------------------------------------------------------------------
    //  Simplified stand-in types
    // -------------------------------------------------------------------------
    public sealed record Vote(Guid Id, string ValidatorId, byte[] Signature);
    public sealed record Block(BlockHeader Header);

    public sealed record BlockHeader(
        ulong            Height,
        string           Hash,
        DateTimeOffset   Timestamp);

    // -------------------------------------------------------------------------
    //  Slot execution results
    // -------------------------------------------------------------------------
    public abstract record SlotResult
    {
        public sealed record BlockProposed(Block Block) : SlotResult;
        public sealed record Empty                      : SlotResult;
    }
}
```