```csharp
using System;
using System.Buffers;
using System.Buffers.Binary;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using UtilityChain.Networking.Internal;

namespace UtilityChain.Networking;

/// <summary>
/// Represents a binary-encoded message exchanged between UtilityChain nodes.
/// A message is composed of a fixed-size header followed by a variable-length
/// payload and an optional ECDSA signature.
/// </summary>
public sealed class Message : IEquatable<Message>
{
    // ────────────────────────────────────────────────────────────────────────────────
    //  Header Layout (little-endian)
    //  ┌────────┬─────────┬────────┬────────────┬──────────────┬───────────────┐
    //  │ Offset │ Size    │ Field  │ Type       │ Description  │ Example       │
    //  ├────────┼─────────┼────────┼────────────┼──────────────┼───────────────┤
    //  │ 0      │ 4       │ Magic  │ UInt32     │ 0x55544331   │ 'UTC1'        │
    //  │ 4      │ 1       │ Ver    │ Byte       │ Protocol ver │ 0x01          │
    //  │ 5      │ 2       │ Cmd    │ UInt16     │ Message type │ 0x000A        │
    //  │ 7      │ 8       │ Time   │ Int64      │ Unix seconds │ 1700000000    │
    //  │ 15     │ 16      │ Id     │ Guid       │ Message ID   │ …             │
    //  │ 31     │ 4       │ Length │ Int32      │ Payload size │               │
    //  │ 35     │ 1       │ SigLen │ Byte       │ SignatureLen │ 0 or 64       │
    //  └────────┴─────────┴────────┴────────────┴──────────────┴───────────────┘
    //  Total header size = 36 bytes
    // ────────────────────────────────────────────────────────────────────────────────
    private const uint Magic = 0x5554_4331;                // 'UTC1'
    private const byte CurrentVersion = 0x01;
    private const int HeaderSize = 36;                     // Fixed

    private readonly ReadOnlyMemory<byte> _payload;
    private readonly ReadOnlyMemory<byte> _signature;      // Empty if unsigned

    private Message(
        Guid id,
        MessageCommand command,
        DateTimeOffset timestamp,
        ReadOnlyMemory<byte> payload,
        ReadOnlyMemory<byte> signature)
    {
        Id = id;
        Command = command;
        Timestamp = timestamp;
        _payload = payload;
        _signature = signature;
    }

    // ‑------ Properties ‑------------------------
    public Guid Id { get; }
    public MessageCommand Command { get; }
    public DateTimeOffset Timestamp { get; }

    public ReadOnlySpan<byte> Payload => _payload.Span;
    public ReadOnlySpan<byte> Signature => _signature.Span;
    public bool IsSigned => !_signature.IsEmpty;

    // ‑------ Factory APIs ‑---------------------

    /// <summary>
    /// Creates and optionally signs a new <see cref="Message"/>.
    /// </summary>
    /// <param name="command">Message command.</param>
    /// <param name="payload">Payload bytes.</param>
    /// <param name="signer">
    ///     ECDsa signer. If null, the message is created unsigned.
    /// </param>
    /// <returns>Signed or unsigned <see cref="Message"/>.</returns>
    public static Message Create(
        MessageCommand command,
        ReadOnlySpan<byte> payload,
        ECDsa? signer = null)
    {
        var payloadCopy = payload.ToArray(); // ensure immutability
        var id = Guid.NewGuid();
        var timestamp = DateTimeOffset.UtcNow;

        ReadOnlyMemory<byte> signature = ReadOnlyMemory<byte>.Empty;

        if (signer is not null)
        {
            Span<byte> digest = stackalloc byte[32];
            ComputeHash(id, timestamp, command, payload, digest);

            var sig = signer.SignHash(digest);
            signature = sig.AsMemory();
        }

        return new Message(id, command, timestamp, payloadCopy, signature);
    }

    // ‑------ Serialization ‑--------------------

    /// <summary>
    /// Serializes this message to a byte array suitable for network transport.
    /// </summary>
    public byte[] ToArray()
    {
        var buffer = new byte[HeaderSize + _payload.Length + _signature.Length];

        // Write header
        var span = (Span<byte>)buffer;
        BinaryPrimitives.WriteUInt32LittleEndian(span.Slice(0, 4), Magic);
        span[4] = CurrentVersion;
        BinaryPrimitives.WriteUInt16LittleEndian(span.Slice(5, 2), (ushort)Command);
        BinaryPrimitives.WriteInt64LittleEndian(span.Slice(7, 8), Timestamp.ToUnixTimeSeconds());
        Id.TryWriteBytes(span.Slice(15, 16));
        BinaryPrimitives.WriteInt32LittleEndian(span.Slice(31, 4), _payload.Length);
        span[35] = checked((byte)_signature.Length);

        // Write body
        _payload.CopyTo(buffer.AsMemory(HeaderSize));
        _signature.CopyTo(buffer.AsMemory(HeaderSize + _payload.Length));

        return buffer;
    }

    /// <summary>
    /// Parses a <see cref="Message"/> from raw bytes.
    /// </summary>
    /// <exception cref="InvalidDataException">The buffer is invalid.</exception>
    public static Message FromSpan(ReadOnlySpan<byte> buffer)
    {
        if (buffer.Length < HeaderSize)
            throw new InvalidDataException("Buffer shorter than header.");

        if (BinaryPrimitives.ReadUInt32LittleEndian(buffer) != Magic)
            throw new InvalidDataException("Invalid message prefix.");

        var version = buffer[4];
        if (version != CurrentVersion)
            throw new InvalidDataException($"Unsupported protocol version {version}.");

        var command = (MessageCommand)BinaryPrimitives.ReadUInt16LittleEndian(buffer.Slice(5, 2));
        var unixTime = BinaryPrimitives.ReadInt64LittleEndian(buffer.Slice(7, 8));
        var timestamp = DateTimeOffset.FromUnixTimeSeconds(unixTime);

        var idSpan = buffer.Slice(15, 16);
        var id = new Guid(idSpan);

        var payloadLen = BinaryPrimitives.ReadInt32LittleEndian(buffer.Slice(31, 4));
        var sigLen = buffer[35];

        var expectedLen = HeaderSize + payloadLen + sigLen;
        if (buffer.Length != expectedLen)
            throw new InvalidDataException("Buffer length does not match header specs.");

        var payload = buffer.Slice(HeaderSize, payloadLen).ToArray();
        var signature = sigLen > 0
            ? buffer.Slice(HeaderSize + payloadLen, sigLen).ToArray()
            : Array.Empty<byte>();

        return new Message(id, command, timestamp, payload, signature);
    }

    /// <summary>
    /// Verifies the message signature using a caller-supplied public key.
    /// </summary>
    /// <param name="publicKey">
    ///     ECDSA public key in X.509 SubjectPublicKeyInfo (DER) format.
    /// </param>
    /// <remarks>
    ///     Returns true for unsigned messages.
    /// </remarks>
    public bool VerifySignature(ReadOnlySpan<byte> publicKey)
    {
        if (!IsSigned)
            return true;

        using var ecdsa = ECDsa.Create();
        if (!ecdsa.TryImportSubjectPublicKeyInfo(publicKey, out _))
            throw new CryptographicException("Invalid public key.");

        Span<byte> digest = stackalloc byte[32];
        ComputeHash(Id, Timestamp, Command, _payload.Span, digest);

        return ecdsa.VerifyHash(digest, _signature.Span);
    }

    // ‑------ Utilities ‑------------------------

    private static void ComputeHash(
        Guid id,
        DateTimeOffset ts,
        MessageCommand cmd,
        ReadOnlySpan<byte> payload,
        Span<byte> output)
    {
        // hash = SHA-256(id || timestamp || cmd || payload)
        Span<byte> rented = stackalloc byte[24]; // id & ts & cmd preimage (16+8)
        id.TryWriteBytes(rented.Slice(0, 16));
        BinaryPrimitives.WriteInt64LittleEndian(rented.Slice(16, 8), ts.ToUnixTimeSeconds());

        using var sha = SHA256.Create();
        sha.TransformBlock(rented, 0, rented.Length, null, 0);

        Span<byte> cmdBytes = stackalloc byte[2];
        BinaryPrimitives.WriteUInt16LittleEndian(cmdBytes, (ushort)cmd);
        sha.TransformBlock(cmdBytes, 0, 2, null, 0);

        sha.TransformFinalBlock(MemoryMarshal.AsBytes(payload).ToArray(), 0, payload.Length);
        var digest = sha.Hash!;
        digest.CopyTo(output);
    }

    public override string ToString()
        => $"{Command} ({Id}) · {Payload.Length:n0} bytes";

    public bool Equals(Message? other)
        => other is not null && Id == other.Id;

    public override bool Equals(object? obj)
        => obj is Message m && Equals(m);

    public override int GetHashCode() => Id.GetHashCode();
}

// ‑------ Supporting Types ‑---------------------

/// <summary>
/// Network-level commands exchanged by UtilityChain nodes.
/// </summary>
public enum MessageCommand : ushort
{
    None                = 0x0000,
    // Handshake & Health
    Ping                = 0x0001,
    Pong                = 0x0002,
    NodeInfo            = 0x0003,

    // Ledger Transport
    Transaction         = 0x000A,
    Block               = 0x000B,

    // Consensus / Governance
    ConsensusVote       = 0x0010,
    CommitteeProposal   = 0x0011,
    GovernanceAction    = 0x0012,

    // Smart Contract
    ContractDeploy      = 0x0020,
    ContractEvent       = 0x0021,

    // Misc
    Alert               = 0x00FF
}

namespace UtilityChain.Networking.Internal
{
    /// <summary>
    /// Miscellaneous helpers for efficient Span/Memory interop. Internal only.
    /// </summary>
    internal static class SpanExtensions
    {
        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static void CopyTo(this ReadOnlyMemory<byte> src, Memory<byte> dest)
            => src.Span.CopyTo(dest.Span);

        [MethodImpl(MethodImplOptions.AggressiveInlining)]
        public static Span<byte> AsSpan(this byte[] array, int start, int length)
            => new Span<byte>(array, start, length);
    }
}
```