```csharp
// -------------------------------------------------------------------------------------------------
//  UtilityChain Core Suite
//  File: TransactionReceivedEvent.cs
//  Author: AI Assistant (generated)
//  Description: In-process event raised after a transaction has been received and validated.
// -------------------------------------------------------------------------------------------------

using System;
using UtilityChain.Core.Abstractions.Events;
using UtilityChain.Core.Models;
using UtilityChain.Core.Network;

namespace UtilityChain.Core.Events
{
    /// <summary>
    /// Domain event that is published by the mempool when a transaction has been received
    /// and passed stateless validation.
    /// </summary>
    /// <remarks>
    /// Subscribers include – but are not limited to – the consensus engine, wallet service, 
    /// and gossip relay pipeline.
    /// </remarks>
    public sealed class TransactionReceivedEvent : IDomainEvent
    {
        /// <summary>
        /// Unique identifier for this event instance.
        /// </summary>
        public Guid EventId { get; } = Guid.NewGuid();

        /// <summary>
        /// Timestamp (in UTC) when the event was instantiated.
        /// </summary>
        public DateTimeOffset OccurredOn { get; } = DateTimeOffset.UtcNow;

        /// <summary>
        /// The validated transaction.
        /// </summary>
        public Transaction Transaction { get; }

        /// <summary>
        /// Information about the remote peer that relayed the transaction.
        /// Null when the transaction originated locally (e.g. via RPC or CLI).
        /// </summary>
        public NetworkPeerInfo? RemotePeer { get; }

        /// <summary>
        /// Indicates whether the transaction was created locally as opposed to being relayed.
        /// </summary>
        public bool IsLocalOrigin => RemotePeer is null;

        /// <summary>
        /// Initializes a new instance of <see cref="TransactionReceivedEvent"/>.
        /// </summary>
        /// <param name="transaction">The transaction that was received.</param>
        /// <param name="remotePeer">Optional remote peer that relayed the transaction.</param>
        /// <exception cref="ArgumentNullException">
        /// Thrown when <paramref name="transaction"/> is <c>null</c>.
        /// </exception>
        public TransactionReceivedEvent(Transaction transaction, NetworkPeerInfo? remotePeer = null)
        {
            Transaction = transaction ?? throw new ArgumentNullException(nameof(transaction));
            RemotePeer = remotePeer;
        }

        /// <summary>
        /// Friendly string for structured logging.
        /// </summary>
        public override string ToString()
        {
            var source = IsLocalOrigin ? "LOCAL" : RemotePeer?.Endpoint ?? "UNKNOWN";
            return $"TxReceived: {Transaction.Id} from [{source}] at {OccurredOn:O}";
        }
    }
}
```