```csharp
// File: UtilityChainCoreSuite/src/UtilityChain.Core/State/StateMachine.cs
// Project: UtilityChain Core Suite (blockchain_defi)
// --------------------------------------------------
// Copyright (c) 2024 UtilityChain.
// --------------------------------------------------
// A generic, thread-safe, event-driven state-machine that powers the
// internal modules of UtilityChain (consensus, staking, governance, etc.).
//
// Design goals
//   * Minimal allocations – hot paths avoid LINQ and closures where possible
//   * Non-blocking concurrency – read-locks for query, write-locks for mutation
//   * Integration hooks – entry/exit callbacks & event-bus publishing
//   * Fluent configuration – API inspired by Stateless but dependency-free
// --------------------------------------------------
#nullable enable
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace UtilityChain.Core.State
{
    /// <summary>
    /// Lightweight event-bus abstraction decouples the <see cref="StateMachine{TState, TTrigger}"/>
    /// from concrete messaging frameworks (e.g. MediatR, MassTransit, SimpleInjector, etc.).
    /// </summary>
    public interface IEventBus
    {
        void Publish<TEvent>(TEvent @event);
    }

    /// <summary>
    /// Defines a change in state. Emitted through <see cref="IEventBus"/> whenever
    /// <see cref="StateMachine{TState, TTrigger}.FireAsync"/> successfully executes.
    /// </summary>
    public sealed record StateTransitionEvent<TState>(TState Previous, TState Current, DateTimeOffset Timestamp);

    /// <summary>
    /// Generic, asynchronous, thread-safe state-machine used throughout UtilityChain.
    /// </summary>
    /// <typeparam name="TState">Enum representing the state.</typeparam>
    /// <typeparam name="TTrigger">Enum representing the trigger/event.</typeparam>
    public sealed class StateMachine<TState, TTrigger>
        where TState : struct, Enum
        where TTrigger : struct, Enum
    {
        private readonly ReaderWriterLockSlim _lock = new(LockRecursionPolicy.NoRecursion);
        private readonly Dictionary<(TState, TTrigger), TransitionDefinition> _transitions = new();
        private readonly Dictionary<TState, StateDefinition> _stateDefinitions = new();
        private readonly ILogger _logger;
        private readonly IEventBus? _eventBus;

        private TState _currentState;

        private readonly ConcurrentDictionary<TState, List<TaskCompletionSource<TState>>> _waiters = new();

        /// <summary>
        /// Initializes a new instance of the <see cref="StateMachine{TState, TTrigger}"/>.
        /// </summary>
        public StateMachine(
            TState initialState,
            ILogger logger,
            IEventBus? eventBus = null)
        {
            _currentState = initialState;
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
            _eventBus = eventBus;

            // Ensure initial state has a definition so entry/exit hooks can be registered later.
            GetOrCreateStateDefinition(initialState);
        }

        /// <summary>
        /// Current state of the machine.
        /// </summary>
        public TState CurrentState
        {
            get
            {
                _lock.EnterReadLock();
                try
                {
                    return _currentState;
                }
                finally
                {
                    _lock.ExitReadLock();
                }
            }
        }

        /// <summary>
        /// Starts configuration of a particular state in the fluent builder.
        /// </summary>
        public StateConfiguration Configure(TState state) =>
            new(GetOrCreateStateDefinition(state), this);

        /// <summary>
        /// Attempts to fire the specified trigger and perform a transition if one is configured.
        /// Transitions are executed asynchronously so that entry/exit actions do not block the caller.
        /// </summary>
        /// <exception cref="InvalidOperationException">If trigger is not permitted in the current state.</exception>
        public async Task FireAsync(TTrigger trigger, CancellationToken cancellationToken = default)
        {
            TransitionDefinition? transition;

            _lock.EnterUpgradeableReadLock();
            try
            {
                if (!_transitions.TryGetValue((_currentState, trigger), out transition))
                {
                    _logger.LogWarning(
                        "Ignored trigger {Trigger} while in state {State}. No transition is configured.",
                        trigger, _currentState);
                    throw new InvalidOperationException(
                        $"Trigger '{trigger}' is not permitted in state '{_currentState}'.");
                }

                // Transition exists – upgrade lock so we can mutate state.
                _lock.EnterWriteLock();
                try
                {
                    var previous = _currentState;
                    _currentState = transition.Destination;

                    _logger.LogInformation(
                        "State transition: {PreviousState} --({Trigger})-> {NextState}",
                        previous, trigger, _currentState);

                    // Wake any tasks waiting for the new state.
                    if (_waiters.TryRemove(_currentState, out var list))
                    {
                        foreach (var tcs in list)
                        {
                            tcs.TrySetResult(_currentState);
                        }
                    }

                    // Publish domain event (synchronous fire-and-forget).
                    _eventBus?.Publish(new StateTransitionEvent<TState>(previous, _currentState, DateTimeOffset.UtcNow));
                }
                finally
                {
                    _lock.ExitWriteLock();
                }
            }
            finally
            {
                _lock.ExitUpgradeableReadLock();
            }

            // Execute exit / transition / entry handlers outside the critical section.
            try
            {
                cancellationToken.ThrowIfCancellationRequested();

                if (transition!.SourceDefinition.ExitAction is { } onExit)
                    await onExit(cancellationToken).ConfigureAwait(false);

                if (transition!.Action is { } onTransition)
                    await onTransition(cancellationToken).ConfigureAwait(false);

                if (transition!.DestinationDefinition.EntryAction is { } onEntry)
                    await onEntry(cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                _logger.LogWarning("State transition cancelled while executing hooks.");
                throw;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Unhandled exception in state transition hooks.");
                throw;
            }
        }

        /// <summary>
        /// Blocks asynchronously until the machine reaches <paramref name="desiredState"/> or the
        /// provided <paramref name="cancellationToken"/> is cancelled.
        /// </summary>
        public Task<TState> WaitForStateAsync(
            TState desiredState,
            CancellationToken cancellationToken = default)
        {
            // Fast-path if already in desired state.
            if (EqualityComparer<TState>.Default.Equals(CurrentState, desiredState))
                return Task.FromResult(desiredState);

            var tcs = new TaskCompletionSource<TState>(TaskCreationOptions.RunContinuationsAsynchronously);

            // Register cancellation first to avoid race conditions.
            if (cancellationToken.CanBeCanceled)
            {
                cancellationToken.Register(static obj =>
                {
                    var localTcs = (TaskCompletionSource<TState>)obj!;
                    localTcs.TrySetCanceled();
                }, tcs);
            }

            var waiters = _waiters.GetOrAdd(desiredState, _ => new List<TaskCompletionSource<TState>>());
            lock (waiters)
            {
                waiters.Add(tcs);
            }

            // Double-check after registration in case state changed meanwhile.
            if (EqualityComparer<TState>.Default.Equals(CurrentState, desiredState))
            {
                tcs.TrySetResult(desiredState);
            }

            return tcs.Task;
        }

        /// <summary>
        /// Provides fluent configuration for a single state.
        /// </summary>
        public sealed class StateConfiguration
        {
            private readonly StateDefinition _stateDefinition;
            private readonly StateMachine<TState, TTrigger> _machine;

            internal StateConfiguration(StateDefinition stateDefinition, StateMachine<TState, TTrigger> machine)
            {
                _stateDefinition = stateDefinition;
                _machine = machine;
            }

            /// <summary>
            /// Runs the provided asynchronous delegate whenever the machine
            /// enters this state.
            /// </summary>
            public StateConfiguration OnEntry(Func<CancellationToken, Task> asyncAction)
            {
                _stateDefinition.EntryAction = asyncAction ?? throw new ArgumentNullException(nameof(asyncAction));
                return this;
            }

            /// <summary>
            /// Runs the provided asynchronous delegate whenever the machine
            /// leaves this state.
            /// </summary>
            public StateConfiguration OnExit(Func<CancellationToken, Task> asyncAction)
            {
                _stateDefinition.ExitAction = asyncAction ?? throw new ArgumentNullException(nameof(asyncAction));
                return this;
            }

            /// <summary>
            /// Defines that the supplied <paramref name="trigger"/> causes a transition
            /// to <paramref name="destinationState"/>.
            /// </summary>
            public StateConfiguration Permit(
                TTrigger trigger,
                TState destinationState,
                Func<CancellationToken, Task>? asyncActionDuringTransition = null)
            {
                var destinationDefinition = _machine.GetOrCreateStateDefinition(destinationState);

                var transition = new TransitionDefinition(
                    _stateDefinition,
                    destinationDefinition,
                    asyncActionDuringTransition);

                if (!_machine._transitions.TryAdd((_stateDefinition.State, trigger), transition))
                {
                    throw new InvalidOperationException(
                        $"Trigger '{trigger}' is already configured for state '{_stateDefinition.State}'.");
                }

                return this;
            }
        }

        #region Internal DTOs
        private sealed class StateDefinition
        {
            public TState State { get; }
            public Func<CancellationToken, Task>? EntryAction { get; set; }
            public Func<CancellationToken, Task>? ExitAction { get; set; }

            public StateDefinition(TState state) => State = state;
        }

        private sealed class TransitionDefinition
        {
            public StateDefinition SourceDefinition { get; }
            public StateDefinition DestinationDefinition { get; }
            public TState Destination => DestinationDefinition.State;
            public Func<CancellationToken, Task>? Action { get; }

            public TransitionDefinition(
                StateDefinition source,
                StateDefinition destination,
                Func<CancellationToken, Task>? action)
            {
                SourceDefinition = source;
                DestinationDefinition = destination;
                Action = action;
            }
        }
        #endregion

        #region Helpers
        private StateDefinition GetOrCreateStateDefinition(TState state)
        {
            if (_stateDefinitions.TryGetValue(state, out var definition))
                return definition;

            definition = new StateDefinition(state);
            _stateDefinitions.Add(state, definition);
            return definition;
        }
        #endregion
    }
}
```