using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace UtilityChain.VM.Triggers
{
    /// <summary>
    /// Enumerates the event trigger categories supported by the UtilityChain smart–contract VM.
    /// </summary>
    public enum EventTriggerType
    {
        /// <summary>A new block has been appended to the chain.</summary>
        Block,

        /// <summary>A transaction has been confirmed.</summary>
        Transaction,

        /// <summary>A contract emitted an on‐chain event.</summary>
        Contract,

        /// <summary>Execution based on a CRON or interval schedule.</summary>
        Timer,

        /// <summary>Manual invocation through CLI/GUI or RPC.</summary>
        Manual,

        /// <summary>A value in an external data feed changed (oracle).</summary>
        DataFeed
    }

    /// <summary>
    /// Context passed to a trigger when it is evaluated or executed.
    /// The contract VM enriches this context with run-time data relevant to the active trigger.
    /// </summary>
    public sealed class EventContext
    {
        public long BlockHeight { get; }
        public string? TransactionHash { get; }
        public string? ContractAddress { get; }
        public IReadOnlyDictionary<string, object> Data { get; }

        public EventContext(
            long blockHeight,
            string? transactionHash,
            string? contractAddress,
            IDictionary<string, object>? data = null)
        {
            BlockHeight     = blockHeight;
            TransactionHash = transactionHash;
            ContractAddress = contractAddress;
            Data            = new ReadOnlyDictionary<string, object>(
                                   data ?? new Dictionary<string, object>());
        }
    }

    /// <summary>
    /// Lightweight abstraction implemented by all event triggers to enable
    /// dependency-inversion and unit-testing of the VM’s event dispatcher.
    /// </summary>
    public interface IEventTrigger
    {
        Guid                        Id          { get; }
        string                      Name        { get; }
        EventTriggerType            Type        { get; }
        IReadOnlyDictionary<string, object> Parameters { get; }

        /// <summary>
        /// Evaluates—then, if the condition delegate returns <c>true</c>, executes—the trigger’s action.
        /// </summary>
        /// <returns>
        /// <c>true</c> when the trigger fired (action executed) or <c>false</c> when the condition was not met.
        /// </returns>
        ValueTask<bool> TryFireAsync(EventContext context, CancellationToken token = default);
    }

    /// <summary>
    /// A highly-configurable, asynchronously-executed event trigger that powers
    /// the UtilityChain smart-contract automation subsystem.
    /// </summary>
    public sealed class EventTrigger : IEventTrigger, IAsyncDisposable
    {
        private readonly Func<EventContext, ValueTask<bool>> _conditionAsync;
        private readonly Func<EventContext, ValueTask>       _actionAsync;
        private readonly ILogger<EventTrigger>?              _logger;
        private readonly SemaphoreSlim                       _semaphore = new(1, 1);

        public Guid                        Id          { get; }
        public string                      Name        { get; }
        public EventTriggerType            Type        { get; }
        public IReadOnlyDictionary<string, object> Parameters { get; }

        public DateTimeOffset CreatedAt   { get; }
        public DateTimeOffset? LastFired  { get; private set; }
        public int            TimesFired { get; private set; }

        internal EventTrigger(
            string                                   name,
            EventTriggerType                         type,
            IDictionary<string, object>?             parameters,
            Func<EventContext, ValueTask<bool>>      conditionAsync,
            Func<EventContext, ValueTask>            actionAsync,
            ILogger<EventTrigger>?                   logger = null)
        {
            Name        = string.IsNullOrWhiteSpace(name)
                          ? throw new ArgumentException("Trigger name cannot be empty.", nameof(name))
                          : name;

            Type        = type;
            Parameters  = new ReadOnlyDictionary<string, object>(
                              parameters ?? new Dictionary<string, object>());
            _conditionAsync = conditionAsync
                              ?? throw new ArgumentNullException(nameof(conditionAsync));
            _actionAsync    = actionAsync
                              ?? throw new ArgumentNullException(nameof(actionAsync));
            _logger     = logger;

            Id         = Guid.NewGuid();
            CreatedAt  = DateTimeOffset.UtcNow;
        }

        /// <inheritdoc />
        public async ValueTask<bool> TryFireAsync(EventContext context,
                                                 CancellationToken token = default)
        {
            ArgumentNullException.ThrowIfNull(context);

            // Ensure that triggers do not execute concurrently.
            if (!await _semaphore.WaitAsync(0, token).ConfigureAwait(false))
            {
                // Already running; skip this cycle—idempotency is paramount.
                _logger?.LogDebug(
                    "Trigger {Name} ({Id}) skipped because a previous execution is still in progress.",
                    Name, Id);
                return false;
            }

            try
            {
                // Evaluate condition.
                if (!await _conditionAsync(context).ConfigureAwait(false))
                    return false;

                _logger?.LogDebug("Trigger {Name} conditions satisfied; executing action.", Name);

                // Execute side-effect.
                await _actionAsync(context).ConfigureAwait(false);

                LastFired  = DateTimeOffset.UtcNow;
                TimesFired++;

                _logger?.LogInformation("Trigger {Name} executed successfully.", Name);
                return true;
            }
            catch (Exception ex)
            {
                _logger?.LogError(ex, "Trigger {Name} execution failed.", Name);
                throw new EventTriggerExecutionException(Name, ex);
            }
            finally
            {
                _semaphore.Release();
            }
        }

        /// <summary>
        /// Disposes the internal semaphore to avoid handle leaks when the VM domain is unloaded.
        /// </summary>
        public ValueTask DisposeAsync()
        {
#if NET8_0_OR_GREATER
            return _semaphore.DisposeAsync();
#else
            _semaphore.Dispose();
            return ValueTask.CompletedTask;
#endif
        }
    }

    /// <summary>
    /// Builder pattern for fluent construction of immutable <see cref="EventTrigger"/> instances.
    /// </summary>
    public sealed class EventTriggerBuilder
    {
        private string?                                   _name;
        private EventTriggerType?                         _type;
        private IDictionary<string, object>?              _parameters;
        private Func<EventContext, ValueTask<bool>>?      _conditionAsync;
        private Func<EventContext, ValueTask>?            _actionAsync;
        private ILogger<EventTrigger>?                    _logger;

        private EventTriggerBuilder() { }

        public static EventTriggerBuilder Create() => new();

        public EventTriggerBuilder WithName(string name)
        {
            _name = name;
            return this;
        }

        public EventTriggerBuilder OfType(EventTriggerType type)
        {
            _type = type;
            return this;
        }

        public EventTriggerBuilder WithParameters(IDictionary<string, object> parameters)
        {
            _parameters = parameters;
            return this;
        }

        /// <summary>
        /// Defines the predicate that determines when the trigger should fire.
        /// </summary>
        public EventTriggerBuilder When(Func<EventContext, ValueTask<bool>> conditionAsync)
        {
            _conditionAsync = conditionAsync;
            return this;
        }

        /// <summary>
        /// Defines the side effect performed when the trigger fires.
        /// </summary>
        public EventTriggerBuilder Do(Func<EventContext, ValueTask> actionAsync)
        {
            _actionAsync = actionAsync;
            return this;
        }

        public EventTriggerBuilder UseLogger(ILogger<EventTrigger> logger)
        {
            _logger = logger;
            return this;
        }

        public EventTrigger Build()
        {
            if (_name is null)
                throw new InvalidOperationException("Name must be specified.");

            if (!_type.HasValue)
                throw new InvalidOperationException("Type must be specified.");

            if (_conditionAsync is null)
                throw new InvalidOperationException("Condition delegate must be specified.");

            if (_actionAsync is null)
                throw new InvalidOperationException("Action delegate must be specified.");

            return new EventTrigger(_name, _type.Value, _parameters,
                                    _conditionAsync, _actionAsync, _logger);
        }
    }

    /// <summary>
    /// Represents an error that occurred during the execution of an <see cref="EventTrigger"/>.
    /// </summary>
    public sealed class EventTriggerExecutionException : Exception
    {
        public EventTriggerExecutionException(string triggerName, Exception inner)
            : base($"An error occurred while executing trigger '{triggerName}'.", inner) { }
    }
}