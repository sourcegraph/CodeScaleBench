using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;

namespace UtilityChain.Core.Events;

/// <summary>
///     Contract that all in-process domain events published by UtilityChain
///     must implement. It purposely keeps a very small footprint to avoid
///     coupling the eventing layer to any external message-bus abstraction.
/// </summary>
public interface IBlockchainEvent
{
    /// <summary>
    ///     The moment the event was first raised, expressed as UTC.
    /// </summary>
    DateTimeOffset OccurredOn { get; }
}

/// <summary>
///     Raised by the consensus engine once a new block has been appended to
///     the canonical chain. Consumers may react to this event to update read
///     models, clear the mem-pool, distribute staking rewards, trigger
///     governance state transitions, or forward telemetry to an external
///     monitoring stack.
/// </summary>
public sealed class BlockAddedEvent : IBlockchainEvent
{
    /// <inheritdoc />
    public DateTimeOffset OccurredOn { get; }

    /// <summary>
    ///     Zero-based height of the committed block.
    /// </summary>
    public long Height { get; }

    /// <summary>
    ///     Digest of the block header (chain-specific hashing algorithm).
    /// </summary>
    public string Hash { get; }

    /// <summary>
    ///     Public address of the validator / miner that produced the block.
    /// </summary>
    public string ProducerAddress { get; }

    /// <summary>
    ///     Hashes of all transactions included in the block (read-only).
    /// </summary>
    public IReadOnlyCollection<string> TransactionHashes { get; }

    /// <summary>
    ///     Amount of time it took the node to validate and commit the block.
    /// </summary>
    public TimeSpan ValidationDuration { get; }

    /// <summary>
    ///     True if the block caused a chain re-organization (e.g., it replaced
    ///     one or more blocks that were previously considered canonical).
    /// </summary>
    public bool IsReorg { get; }

    /// <summary>
    ///     Creates a new <see cref="BlockAddedEvent" /> instance.
    /// </summary>
    /// <param name="height">Height of the committed block.</param>
    /// <param name="hash">Hash of the committed block.</param>
    /// <param name="producerAddress">Validator/miner address.</param>
    /// <param name="transactionHashes">Hashes of transactions contained in the block.</param>
    /// <param name="validationDuration">
    ///     Time spent validating the block. Negative values are not allowed.
    /// </param>
    /// <param name="isReorg">Whether the block replaced any canonical blocks.</param>
    /// <param name="occurredOn">
    ///     Optional override for <see cref="OccurredOn"/> (defaults to <see cref="DateTimeOffset.UtcNow"/>).
    /// </param>
    /// <exception cref="ArgumentNullException">
    ///     Thrown if <paramref name="hash"/>, <paramref name="producerAddress"/>, or
    ///     <paramref name="transactionHashes" /> is <c>null</c>.
    /// </exception>
    /// <exception cref="ArgumentOutOfRangeException">
    ///     Thrown if <paramref name="height" /> is negative or
    ///     <paramref name="validationDuration" /> is negative.
    /// </exception>
    public BlockAddedEvent(
        long height,
        string hash,
        string producerAddress,
        IEnumerable<string> transactionHashes,
        TimeSpan validationDuration,
        bool isReorg,
        DateTimeOffset? occurredOn = null)
    {
        if (height < 0)
            throw new ArgumentOutOfRangeException(nameof(height), "Block height cannot be negative.");

        Hash = !string.IsNullOrWhiteSpace(hash)
            ? hash
            : throw new ArgumentNullException(nameof(hash));

        ProducerAddress = !string.IsNullOrWhiteSpace(producerAddress)
            ? producerAddress
            : throw new ArgumentNullException(nameof(producerAddress));

        if (transactionHashes is null)
            throw new ArgumentNullException(nameof(transactionHashes));

        TransactionHashes = new ReadOnlyCollection<string>(new List<string>(transactionHashes));

        if (validationDuration < TimeSpan.Zero)
            throw new ArgumentOutOfRangeException(nameof(validationDuration), "Duration cannot be negative.");

        ValidationDuration = validationDuration;
        Height               = height;
        IsReorg              = isReorg;
        OccurredOn           = occurredOn ?? DateTimeOffset.UtcNow;
    }

    /// <summary>
    ///     Convenience factory method that constructs an event instance from an
    ///     existing domain <see cref="BlockHeader" /> object.
    /// </summary>
    /// <remarks>
    ///     The method is intentionally lenient: it throws on <c>null</c> input
    ///     but otherwise delegates detailed validation to the main constructor,
    ///     ensuring a single point of truth.
    /// </remarks>
    public static BlockAddedEvent FromHeader(
        BlockHeader header,
        IReadOnlyCollection<string> transactionHashes,
        TimeSpan validationDuration,
        bool isReorg = false)
    {
        if (header is null)
            throw new ArgumentNullException(nameof(header));

        return new BlockAddedEvent(
            header.Height,
            header.Hash,
            header.Producer,
            transactionHashes ?? throw new ArgumentNullException(nameof(transactionHashes)),
            validationDuration,
            isReorg,
            header.Timestamp);
    }

    public override string ToString()
    {
        var hashPreview = Hash.Length > 8 ? Hash[..8] : Hash;
        return $"[BlockAddedEvent] Height={Height} Hash={hashPreview}... Tx={TransactionHashes.Count} Reorg={IsReorg}";
    }
}

/// <summary>
///     Minimal representation of a block header used strictly for the
///     <see cref="BlockAddedEvent"/> factory overload. The full-fledged
///     header type lives in the consensus module; this lightweight record
///     prevents a hard dependency from the events sub-package on the entire
///     consensus stack, thereby reducing compilation time and coupling.
/// </summary>
public sealed record BlockHeader(
    long          Height,
    string        Hash,
    string        Producer,
    DateTimeOffset Timestamp);