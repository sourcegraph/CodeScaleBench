```csharp
// -------------------------------------------------------------------------------------------------
// CanvasCraft ML Studio
// File: CanvasCraft.Core/Interfaces/Services/IMessageBus.cs
// Description: Contract for the internal message bus that powers the Observer-style event system
//              across the MLOps pipeline. A thin abstraction layer designed to keep domain
//              services decoupled from the concrete transport (e.g. RabbitMQ, Azure Service Bus,
//              in-memory testing harness).
// -------------------------------------------------------------------------------------------------
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace CanvasCraft.Core.Interfaces.Services
{
    /// <summary>
    /// Marker interface for all messages that travel through <see cref="IMessageBus"/>.
    /// </summary>
    public interface IMessage
    {
        /// <summary>
        /// Globally unique identifier for the message instance.
        /// </summary>
        Guid Id { get; }

        /// <summary>
        /// UTC timestamp indicating when the message was created.
        /// </summary>
        DateTimeOffset TimestampUtc { get; }

        /// <summary>
        /// Optional bag of key/value pairs for meta-data or tracing headers.
        /// </summary>
        IReadOnlyDictionary<string, string> Headers { get; }
    }

    /// <summary>
    /// Represents a one-way notification that expresses something that already happened.
    /// </summary>
    public interface IDomainEvent : IMessage { }

    /// <summary>
    /// Represents an instruction to perform a task. Should be handled exactly once.
    /// </summary>
    public interface ICommand : IMessage { }

    /// <summary>
    /// Represents a request that expects a response of type <typeparamref name="TResponse"/>.
    /// </summary>
    /// <typeparam name="TResponse">The type of the expected response.</typeparam>
    public interface IRequest<TResponse> : IMessage { }

    /// <summary>
    /// Options that influence how a subscription behaves.
    /// </summary>
    public sealed class SubscriptionOptions
    {
        /// <summary>
        /// Maximum number of concurrent message handlers allowed. Default is <see cref="Environment.ProcessorCount"/>.
        /// </summary>
        public int MaxDegreeOfParallelism { get; init; } = Environment.ProcessorCount;

        /// <summary>
        /// Defines the Quality-of-Service level desired for this subscription.
        /// </summary>
        public QoS QualityOfService { get; init; } = QoS.AtLeastOnce;

        /// <summary>
        /// Indicates whether the subscription should automatically retry failed messages.
        /// </summary>
        public bool EnableRetry { get; init; } = true;

        /// <summary>
        /// If <see cref="EnableRetry"/> is true, defines the maximum number of retry attempts.
        /// </summary>
        public int MaxRetryAttempts { get; init; } = 5;
    }

    /// <summary>
    /// Quality of Service guarantees offered by the bus implementation.
    /// </summary>
    public enum QoS
    {
        /// <summary>
        /// Message may be delivered zero or more times.
        /// </summary>
        AtMostOnce,

        /// <summary>
        /// Message will be delivered at least once. Handlers must be idempotent.
        /// </summary>
        AtLeastOnce,

        /// <summary>
        /// Message will be delivered exactly once. Requires support from underlying broker.
        /// </summary>
        ExactlyOnce
    }

    /// <summary>
    /// The core abstraction that enables publish/subscribe, command dispatching and request/response
    /// semantics for the entire CanvasCraft platform.
    /// </summary>
    public interface IMessageBus
    {
        #region Publish / Send

        /// <summary>
        /// Publishes a domain event to all registered subscribers. Best effort fan-out.
        /// </summary>
        /// <typeparam name="TEvent">Concrete type of the event.</typeparam>
        /// <param name="event">The event instance to publish.</param>
        /// <param name="cancellationToken">Token to cancel the operation.</param>
        Task PublishAsync<TEvent>(
            TEvent @event,
            CancellationToken cancellationToken = default)
            where TEvent : IDomainEvent;

        /// <summary>
        /// Sends a command that should be processed by exactly one handler.
        /// </summary>
        /// <typeparam name="TCommand">Concrete type of the command.</typeparam>
        /// <param name="command">The command instance to send.</param>
        /// <param name="cancellationToken">Token to cancel the operation.</param>
        Task SendAsync<TCommand>(
            TCommand command,
            CancellationToken cancellationToken = default)
            where TCommand : ICommand;

        /// <summary>
        /// Issues a request and asynchronously awaits a single response.
        /// </summary>
        /// <typeparam name="TRequest">Concrete type of the request.</typeparam>
        /// <typeparam name="TResponse">Type of the expected response.</typeparam>
        /// <param name="request">The request payload.</param>
        /// <param name="timeout">
        /// Optional timeout. When <c>null</c>, uses the bus implementation’s default value.
        /// </param>
        /// <param name="cancellationToken">Token to cancel the operation.</param>
        /// <returns>The response object of type <typeparamref name="TResponse"/>.</returns>
        Task<TResponse> RequestAsync<TRequest, TResponse>(
            TRequest request,
            TimeSpan? timeout = null,
            CancellationToken cancellationToken = default)
            where TRequest : IRequest<TResponse>;
        #endregion

        #region Subscribe

        /// <summary>
        /// Subscribes to domain events of type <typeparamref name="TEvent"/>.
        /// </summary>
        /// <typeparam name="TEvent">The event type.</typeparam>
        /// <param name="handler">Delegate that processes the event.</param>
        /// <param name="options">Subscription tuning options.</param>
        /// <param name="cancellationToken">Token to cancel the subscription.</param>
        /// <returns>
        /// A disposable that, when disposed, will gracefully unsubscribe and release resources.
        /// </returns>
        IDisposable Subscribe<TEvent>(
            Func<TEvent, CancellationToken, Task> handler,
            SubscriptionOptions? options = null,
            CancellationToken cancellationToken = default)
            where TEvent : IDomainEvent;

        /// <summary>
        /// Registers a command handler.
        /// </summary>
        /// <typeparam name="TCommand">The command type.</typeparam>
        /// <param name="handler">Delegate that processes the command.</param>
        /// <param name="options">Subscription tuning options.</param>
        /// <param name="cancellationToken">Token to cancel the subscription.</param>
        IDisposable RegisterCommandHandler<TCommand>(
            Func<TCommand, CancellationToken, Task> handler,
            SubscriptionOptions? options = null,
            CancellationToken cancellationToken = default)
            where TCommand : ICommand;

        /// <summary>
        /// Registers a request handler that can reply with <typeparamref name="TResponse"/>.
        /// </summary>
        /// <typeparam name="TRequest">The request type.</typeparam>
        /// <typeparam name="TResponse">The response type.</typeparam>
        /// <param name="handler">Delegate that processes the request and returns a response.</param>
        /// <param name="options">Subscription tuning options.</param>
        /// <param name="cancellationToken">Token to cancel the subscription.</param>
        IDisposable RegisterRequestHandler<TRequest, TResponse>(
            Func<TRequest, CancellationToken, Task<TResponse>> handler,
            SubscriptionOptions? options = null,
            CancellationToken cancellationToken = default)
            where TRequest : IRequest<TResponse>;
        #endregion
    }
}
```