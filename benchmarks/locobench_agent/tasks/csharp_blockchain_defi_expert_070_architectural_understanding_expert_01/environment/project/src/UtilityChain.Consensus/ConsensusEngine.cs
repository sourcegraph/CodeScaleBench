```csharp
// -----------------------------------------------------------------------------
// File:    ConsensusEngine.cs
// Project: UtilityChain Core Suite – Consensus Module
// Author:  UtilityChain Engineering Team
// -----------------------------------------------------------------------------

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace UtilityChain.Consensus
{
    #region Public Contracts

    /// <summary>
    /// Describes common behaviour for a consensus algorithm plug-in.
    /// </summary>
    public interface IConsensusAlgorithm : IAsyncDisposable
    {
        ConsensusType Type { get; }

        /// <summary>
        /// Lifecycle hook for preparing consensus-specific resources.
        /// </summary>
        ValueTask InitializeAsync(CancellationToken ct = default);

        /// <summary>
        /// Executes the consensus logic for the next round
        /// and returns a proposed, yet-to-be-finalized block.
        /// </summary>
        ValueTask<Block> ProposeBlockAsync(CancellationToken ct = default);

        /// <summary>
        /// Validates and (optionally) finalizes a given block instance.
        /// </summary>
        ValueTask<bool> ValidateBlockAsync(Block block, CancellationToken ct = default);

        /// <summary>
        /// Raised when a block is irrevocably committed to chain storage.
        /// </summary>
        event EventHandler<BlockFinalizedEventArgs>? BlockFinalized;
    }

    public record ConsensusConfig
    (
        ConsensusType PreferredType,
        int MaxPendingBlocks        = 64,
        TimeSpan ProposalInterval   = default,
        TimeSpan CommitTimeout      = default
    )
    {
        public static ConsensusConfig Default => new
        (
            PreferredType: ConsensusType.ProofOfStake,
            ProposalInterval: TimeSpan.FromSeconds(3),
            CommitTimeout: TimeSpan.FromSeconds(10)
        );
    }

    /// <summary>
    /// Marker enumeration for built-in consensus algorithms supported by the suite.
    /// </summary>
    public enum ConsensusType
    {
        ProofOfStake,
        ProofOfAuthority,
        DelegatedProofOfStake
    }

    /// <summary>
    /// Encapsulates block-finalization metadata.
    /// </summary>
    public sealed class BlockFinalizedEventArgs : EventArgs
    {
        public BlockFinalizedEventArgs(Block block, DateTimeOffset committedAtUtc)
        {
            Block = block;
            CommittedAtUtc = committedAtUtc;
        }

        public Block Block { get; }
        public DateTimeOffset CommittedAtUtc { get; }
    }

    #endregion

    #region Engine

    /// <summary>
    /// High-level orchestrator that delegates runtime duties to the configured
    /// consensus plug-in while providing lifecycle, state-machine, telemetry,
    /// and back-pressure handling for the enclosing runtime.
    /// </summary>
    public sealed class ConsensusEngine : IAsyncDisposable
    {
        private enum EngineState
        {
            Created,
            Initialized,
            Running,
            Paused,
            Stopped,
            Disposed
        }

        private readonly ILogger<ConsensusEngine> _logger;
        private readonly ConsensusConfig _config;
        private readonly IConsensusAlgorithm _algorithm;
        private readonly CancellationTokenSource _cts;
        private readonly AsyncManualResetEvent _pauseReset;
        private readonly BlockingCollection<Block> _pendingBlocks;

        private volatile EngineState _state = EngineState.Created;
        private Task? _executionLoop;

        #region Ctor

        public ConsensusEngine(
            IConsensusAlgorithm algorithm,
            ConsensusConfig? config,
            ILogger<ConsensusEngine> logger)
        {
            _algorithm      = algorithm  ?? throw new ArgumentNullException(nameof(algorithm));
            _logger         = logger     ?? throw new ArgumentNullException(nameof(logger));
            _config         = config     ?? ConsensusConfig.Default;
            _cts            = new CancellationTokenSource();
            _pauseReset     = new AsyncManualResetEvent(initialState: true);
            _pendingBlocks  = new BlockingCollection<Block>(_config.MaxPendingBlocks);

            _algorithm.BlockFinalized += OnBlockFinalized;
        }

        #endregion

        #region Public API

        public ConsensusType Type => _algorithm.Type;

        public async ValueTask InitializeAsync()
        {
            EnsureState(EngineState.Created);

            _logger.LogInformation("Initializing consensus engine with algorithm: {Type}", Type);

            await _algorithm.InitializeAsync(_cts.Token).ConfigureAwait(false);

            _state = EngineState.Initialized;
        }

        public void Start()
        {
            EnsureState(EngineState.Initialized, EngineState.Paused);

            _logger.LogInformation("Starting consensus engine");

            _executionLoop ??= Task.Run(RunAsync, _cts.Token);
            _state          = EngineState.Running;

            _pauseReset.Set();
        }

        public void Pause()
        {
            EnsureState(EngineState.Running);

            _logger.LogInformation("Pausing consensus engine");
            _state = EngineState.Paused;
            _pauseReset.Reset();
        }

        public async Task StopAsync()
        {
            if (_state is EngineState.Stopped or EngineState.Disposed)
                return;

            _logger.LogInformation("Stopping consensus engine...");

            _state = EngineState.Stopped;

            _pauseReset.Set();
            _cts.Cancel();

            if (_executionLoop is { } loop)
            {
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
                await Task.WhenAny(loop, Task.Delay(Timeout.Infinite, timeout.Token))
                          .ConfigureAwait(false);
            }

            _pendingBlocks.CompleteAdding();
        }

        #endregion

        #region Internal Main Loop

        private async Task RunAsync()
        {
            _logger.LogInformation("Consensus execution loop started.");

            var ct = _cts.Token;
            var sw = new Stopwatch();

            try
            {
                while (!ct.IsCancellationRequested &&
                       _state is not (EngineState.Stopped or EngineState.Disposed))
                {
                    // Ensure engine is not paused.
                    await _pauseReset.WaitAsync(ct).ConfigureAwait(false);
                    sw.Restart();

                    try
                    {
                        // Proposal phase
                        var block = await _algorithm.ProposeBlockAsync(ct).ConfigureAwait(false);

                        if (!_pendingBlocks.TryAdd(block))
                        {
                            _logger.LogWarning(
                                "Pending block buffer full, dropping proposed block #{Height}",
                                block.Header.Height);
                            continue;
                        }

                        // Validation/commit phase (may be delegated to peers; simplified here).
                        var validated = await _algorithm.ValidateBlockAsync(block, ct)
                                                         .ConfigureAwait(false);

                        if (!validated)
                        {
                            _logger.LogWarning(
                                "Block #{Height} failed validation and will be discarded",
                                block.Header.Height);
                        }
                    }
                    catch (OperationCanceledException) when (ct.IsCancellationRequested)
                    {
                        // Graceful shutdown.
                        break;
                    }
                    catch (Exception ex)
                    {
                        _logger.LogError(ex, "Consensus iteration failed: {Message}", ex.Message);
                    }

                    // Back-pressure – ensure pacing.
                    var delay = _config.ProposalInterval - sw.Elapsed;
                    if (delay > TimeSpan.Zero)
                    {
                        try
                        {
                            await Task.Delay(delay, ct).ConfigureAwait(false);
                        }
                        catch (OperationCanceledException)
                        {
                            // ignore – shutdown or pause triggered.
                        }
                    }
                }
            }
            finally
            {
                _logger.LogInformation("Consensus execution loop terminated.");
            }
        }

        #endregion

        #region Events

        private void OnBlockFinalized(object? sender, BlockFinalizedEventArgs e)
        {
            _logger.LogInformation(
                "Block #{Height} finalized at {Time}",
                e.Block.Header.Height,
                e.CommittedAtUtc);
        }

        #endregion

        #region Helpers

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        private void EnsureState(params EngineState[] validStates)
        {
            if (Array.IndexOf(validStates, _state) < 0)
            {
                throw new InvalidOperationException(
                    $"Operation is invalid for the current engine state: {_state}");
            }
        }

        #endregion

        #region Dispose

        public async ValueTask DisposeAsync()
        {
            if (_state == EngineState.Disposed) return;

            await StopAsync().ConfigureAwait(false);

            _pendingBlocks.Dispose();
            _cts.Dispose();
            _pauseReset.Dispose();

            await _algorithm.DisposeAsync().ConfigureAwait(false);

            _state = EngineState.Disposed;
            _logger.LogInformation("Consensus engine disposed.");
        }

        #endregion
    }

    #endregion

    #region Minimal Domain Model – placeholders for other modules

    /// <summary>
    /// Extremely simplified block model; real implementation lives
    /// in UtilityChain.Storage and UtilityChain.Cryptography modules.
    /// </summary>
    public sealed class Block
    {
        public Block(BlockHeader header, IReadOnlyCollection<object> transactions)
        {
            Header       = header;
            Transactions = transactions;
        }

        public BlockHeader Header { get; }
        public IReadOnlyCollection<object> Transactions { get; }
    }

    public sealed class BlockHeader
    {
        public long Height                { get; init; }
        public string PreviousHash        { get; init; } = string.Empty;
        public DateTimeOffset Timestamp   { get; init; }
        public string MerkleRoot          { get; init; } = string.Empty;
        public string Proposer            { get; init; } = string.Empty;
        public string Signature           { get; set; } = string.Empty;
    }

    #endregion

    #region Async Helper

    /// <summary>
    /// A very lightweight async manual-reset event for intra-process coordination.
    /// </summary>
    internal sealed class AsyncManualResetEvent : IDisposable
    {
        private volatile TaskCompletionSource<bool> _tcs;

        public AsyncManualResetEvent(bool initialState = false)
        {
            _tcs = CreateTcs(initialState);
        }

        public Task WaitAsync(CancellationToken ct = default)
        {
            var tcs = _tcs;

            if (ct.IsCancellationRequested) return Task.FromCanceled(ct);
            if (tcs.Task.IsCompleted)       return tcs.Task;

            return ct.CanBeCanceled
                ? tcs.Task.WaitAsync(ct)
                : tcs.Task;
        }

        public void Set()
        {
            _tcs.TrySetResult(true);
        }

        public void Reset()
        {
            while (true)
            {
                var tcs = _tcs;
                if (!tcs.Task.IsCompleted ||
                    Interlocked.CompareExchange(ref _tcs, CreateTcs(false), tcs) == tcs)
                    break;
            }
        }

        private static TaskCompletionSource<bool> CreateTcs(bool completed) =>
            new(TaskCreationOptions.RunContinuationsAsynchronously)
            {
                { if (completed) TrySetResult(true); }
            };

        public void Dispose()
        {
            _tcs.TrySetCanceled();
        }
    }

    #endregion
}
```