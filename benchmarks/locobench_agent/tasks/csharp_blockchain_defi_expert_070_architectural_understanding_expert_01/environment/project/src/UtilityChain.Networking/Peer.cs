```csharp
using System;
using System.Buffers;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace UtilityChain.Networking;

/// <summary>
/// Represents a full–duplex connection to another UtilityChain node.  A <see cref="Peer"/>
/// encapsulates TCP connectivity, protocol-level hand-shaking, message framing,
/// serialization, and a lightweight reactive event hub.  Peers are designed for
/// long-lived operation: once <see cref="ConnectAsync"/> succeeds the instance will
/// maintain its own send/receive loops until disposed.
/// </summary>
public sealed class Peer : IAsyncDisposable, IObservable<PeerMessage>
{
    private const int DefaultPort = 48333;
    private const int ProtocolVersion = 70016;
    private const int HandshakeTimeoutSeconds = 8;
    private const int ReceiveBufferSize = 64 * 1024;
    private const int SendBufferSize = 64 * 1024;
    private const int MaxMessageSize = 4 * 1024 * 1024; // 4 MiB, sanity limit

    private readonly ILogger<Peer> _logger;
    private readonly TcpClient _client;
    private readonly NetworkStream _networkStream;
    private readonly CancellationTokenSource _cts = new();
    private readonly Channel<NetworkMessage> _outbound;
    private readonly List<IObserver<PeerMessage>> _observers = new();

    private readonly byte[] _receiveBuffer = new byte[ReceiveBufferSize];
    private readonly ArrayBufferWriter<byte> _inboundWriter = new();

    private Task? _receiveLoopTask;
    private Task? _sendLoopTask;
    private int _disposed;

    private PeerState _state = PeerState.Created;

    public IPEndPoint RemoteEndPoint { get; }
    public IPEndPoint LocalEndPoint => (IPEndPoint)_client.Client.LocalEndPoint!;
    public ImmutableDictionary<string, object> Metadata { get; private set; } = ImmutableDictionary<string, object>.Empty;

    public Peer(IPEndPoint endpoint, ILogger<Peer> logger, int outboundQueueCapacity = 512)
    {
        RemoteEndPoint = endpoint ?? throw new ArgumentNullException(nameof(endpoint));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));

        _client = new TcpClient(AddressFamily.InterNetworkV6)
        {
            NoDelay = true,
            ReceiveBufferSize = ReceiveBufferSize,
            SendBufferSize = SendBufferSize
        };
        _outbound = Channel.CreateBounded<NetworkMessage>(new BoundedChannelOptions(outboundQueueCapacity)
        {
            FullMode = BoundedChannelFullMode.Wait,
            SingleWriter = false,
            SingleReader = true
        });

        _networkStream = null!; // will be assigned in ConnectAsync
    }

    #region Public API

    /// <summary>
    /// Starts an outbound connection and performs protocol handshake. Must be called once.
    /// </summary>
    public async Task ConnectAsync(CancellationToken externalToken = default)
    {
        ThrowIfDisposed();

        if (_state != PeerState.Created)
            throw new InvalidOperationException($"Peer is already in state {_state}.");

        _state = PeerState.Connecting;
        using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(_cts.Token, externalToken);
        var ct = linkedCts.Token;

        _logger.LogInformation("Connecting to peer {Remote}…", RemoteEndPoint);

        try
        {
            await _client.ConnectAsync(RemoteEndPoint.Address, RemoteEndPoint.Port == 0 ? DefaultPort : RemoteEndPoint.Port, ct)
                         .ConfigureAwait(false);
        }
        catch (OperationCanceledException oce) when (ct.IsCancellationRequested)
        {
            _logger.LogDebug(oce, "Connection to {Remote} cancelled.", RemoteEndPoint);
            throw;
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to connect to peer {Remote}.", RemoteEndPoint);
            throw;
        }

        Debug.Assert(_client.Connected);
        _networkStream = _client.GetStream();

        _receiveLoopTask = Task.Run(() => ReceiveLoopAsync(ct), ct);
        _sendLoopTask = Task.Run(() => SendLoopAsync(ct), ct);

        _state = PeerState.Handshaking;

        // Perform protocol handshake
        await PerformHandshakeAsync(ct).ConfigureAwait(false);

        _state = PeerState.Connected;
        _logger.LogInformation("Peer {Remote} connected.", RemoteEndPoint);
    }

    /// <summary>
    /// Queue a message to be sent asynchronously.  Throws <see cref="InvalidOperationException"/>
    /// if the peer is not fully connected.
    /// </summary>
    public ValueTask EnqueueMessageAsync(NetworkMessage message, CancellationToken ct = default)
    {
        ThrowIfDisposed();

        if (_state != PeerState.Connected)
            throw new InvalidOperationException("Peer is not ready to send messages.");

        ArgumentNullException.ThrowIfNull(message);

        return _outbound.Writer.WriteAsync(message, ct);
    }

    public IDisposable Subscribe(IObserver<PeerMessage> observer)
    {
        if (observer is null) throw new ArgumentNullException(nameof(observer));
        lock (_observers)
        {
            _observers.Add(observer);
        }

        // Immediately push state info
        observer.OnNext(new PeerMessage(this, PeerEventType.StateChanged));

        return new Unsubscriber(_observers, observer);
    }

    #endregion

    #region Handshake

    private async Task PerformHandshakeAsync(CancellationToken ct)
    {
        var versionMsg = NetworkMessage.Create("version", VersionPayload());
        await _outbound.Writer.WriteAsync(versionMsg, ct).ConfigureAwait(false);

        var (command, payload) = await WaitForMessageAsync(new[] { "version", "verack" }, ct)
            .ConfigureAwait(false);

        if (command == "version")
        {
            ParseRemoteVersion(payload);
            (command, _) = await WaitForMessageAsync(new[] { "verack" }, ct)
                .ConfigureAwait(false);
        }

        if (command != "verack")
            throw new ProtocolException($"Expected 'verack' message but got '{command}'.");

        // send ack
        var verAck = NetworkMessage.Create("verack", ReadOnlyMemory<byte>.Empty);
        await _outbound.Writer.WriteAsync(verAck, ct).ConfigureAwait(false);
    }

    private async Task<(string command, ReadOnlyMemory<byte> payload)> WaitForMessageAsync(
        IReadOnlySet<string> expected, CancellationToken ct)
    {
        TaskCompletionSource<(string, ReadOnlyMemory<byte>)> tcs = new(TaskCreationOptions.RunContinuationsAsynchronously);

        using CancellationTokenRegistration reg = ct.Register(static s => ((TaskCompletionSource<(string, ReadOnlyMemory<byte>)>)s!)
            .TrySetCanceled(), tcs);

        using var sub = Subscribe(new AnonymousObserver<PeerMessage>(msg =>
        {
            if (msg.EventType == PeerEventType.IncomingMessage &&
                expected.Contains(msg.Message.Command))
            {
                tcs.TrySetResult((msg.Message.Command, msg.Message.Payload));
            }
        }));

        return await tcs.Task.ConfigureAwait(false);
    }

    private static ReadOnlyMemory<byte> VersionPayload()
    {
        Span<byte> buf = stackalloc byte[24];
        BitConverter.TryWriteBytes(buf[..4], ProtocolVersion);
        RandomNumberGenerator.Fill(buf[4..24]);
        return buf.ToArray();
    }

    private void ParseRemoteVersion(ReadOnlyMemory<byte> payload)
    {
        if (payload.Length < 4) throw new ProtocolException("version payload too short.");
        int remoteVer = BitConverter.ToInt32(payload.Span[..4]);
        Metadata = Metadata.SetItem("protocol", remoteVer);
    }

    #endregion

    #region Receive / Send loops

    private async Task ReceiveLoopAsync(CancellationToken ct)
    {
        try
        {
            while (!ct.IsCancellationRequested)
            {
                int bytesRead = await _networkStream.ReadAsync(_receiveBuffer, ct).ConfigureAwait(false);
                if (bytesRead == 0) break; // connection closed

                _inboundWriter.Write(new ReadOnlySpan<byte>(_receiveBuffer, 0, bytesRead));
                await ProcessInboundBufferAsync(ct).ConfigureAwait(false);
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Receive loop terminated abnormally for peer {Remote}.", RemoteEndPoint);
        }
        finally
        {
            await DisposeAsync().ConfigureAwait(false);
        }
    }

    private async Task ProcessInboundBufferAsync(CancellationToken ct)
    {
        ReadOnlySequence<byte> seq = new(_inboundWriter.WrittenMemory);
        SequenceReader<byte> reader = new(seq);

        while (TryReadFrame(ref reader, out var message))
        {
            Publish(new PeerMessage(this, PeerEventType.IncomingMessage, message));
        }

        // preserve any incomplete data
        var remaining = reader.UnreadSpan.ToArray();
        _inboundWriter.Reset();
        _inboundWriter.Write(remaining);
        await Task.CompletedTask;
    }

    private static bool TryReadFrame(ref SequenceReader<byte> reader, out NetworkMessage message)
    {
        const int headerSize = 24; // 12 bytes magic+command, 4 payload length, 4 checksum, 4 reserved

        message = default!;
        if (reader.Remaining < headerSize) return false;

        // Magic & command
        Span<byte> header = stackalloc byte[headerSize];
        if (!reader.TryCopyTo(header)) return false;

        string command = System.Text.Encoding.ASCII.GetString(header[4..16]).TrimEnd('\0');
        int length = BitConverter.ToInt32(header[16..20]);

        if (length < 0 || length > MaxMessageSize) throw new ProtocolException("invalid payload length.");

        if (reader.Remaining < headerSize + length) return false;

        reader.Advance(headerSize);
        ReadOnlySpan<byte> payload = reader.Sequence.Slice(reader.Position, length).FirstSpan;

        reader.Advance(length);

        message = NetworkMessage.Create(command, payload.ToArray());
        return true;
    }

    private async Task SendLoopAsync(CancellationToken ct)
    {
        try
        {
            while (await _outbound.Reader.WaitToReadAsync(ct).ConfigureAwait(false))
            {
                while (_outbound.Reader.TryRead(out var msg))
                {
                    await WriteFrameAsync(msg, ct).ConfigureAwait(false);
                    Publish(new PeerMessage(this, PeerEventType.OutgoingMessage, msg));
                }
            }
        }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Send loop terminated abnormally for peer {Remote}.", RemoteEndPoint);
        }
        finally
        {
            await DisposeAsync().ConfigureAwait(false);
        }
    }

    private async Task WriteFrameAsync(NetworkMessage msg, CancellationToken ct)
    {
        using var memory = MemoryPool<byte>.Shared.Rent(msg.Payload.Length + 24);
        var buffer = memory.Memory.Span;

        // Magic = 0xF9BEB4D9
        buffer[0] = 0xF9;
        buffer[1] = 0xBE;
        buffer[2] = 0xB4;
        buffer[3] = 0xD9;

        // Command (12 bytes null-padded)
        var cmdBytes = System.Text.Encoding.ASCII.GetBytes(msg.Command);
        cmdBytes.CopyTo(buffer[4..16]);
        // len
        BitConverter.TryWriteBytes(buffer[16..20], msg.Payload.Length);
        // simplistic checksum—first 4 bytes of SHA256
        Span<byte> hash = stackalloc byte[32];
        SHA256.HashData(msg.Payload.Span, hash);
        hash[..4].CopyTo(buffer[20..24]);

        msg.Payload.Span.CopyTo(buffer[24..]);

        await _networkStream.WriteAsync(buffer[..(24 + msg.Payload.Length)], ct).ConfigureAwait(false);
    }

    #endregion

    #region Helpers

    private void Publish(PeerMessage message)
    {
        IObserver<PeerMessage>[] snapshot;
        lock (_observers)
        {
            snapshot = _observers.ToArray();
        }

        foreach (var obs in snapshot)
        {
            try
            {
                obs.OnNext(message);
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "Observer threw during OnNext.");
            }
        }
    }

    private void ThrowIfDisposed()
    {
        if (Volatile.Read(ref _disposed) != 0) throw new ObjectDisposedException(nameof(Peer));
    }

    #endregion

    #region Dispose

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0) return;

        _logger.LogDebug("Disposing peer {Remote}.", RemoteEndPoint);

        _state = PeerState.Disconnecting;
        try
        {
            _cts.Cancel();

            if (_sendLoopTask is { } send) await CatchAsync(send);
            if (_receiveLoopTask is { } recv) await CatchAsync(recv);
        }
        catch { /* ignored */ }
        finally
        {
            _networkStream?.Dispose();
            if (_client.Connected)
            {
                try { _client.Close(); } catch { /* ignored */ }
            }

            lock (_observers)
            {
                foreach (var o in _observers) { o.OnCompleted(); }
                _observers.Clear();
            }

            _cts.Dispose();
            _state = PeerState.Disposed;
        }

        static async Task CatchAsync(Task task)
        {
            try { await task.ConfigureAwait(false); }
            catch { /* ignored */ }
        }
    }

    #endregion

    #region Nested

    private sealed class Unsubscriber : IDisposable
    {
        private readonly List<IObserver<PeerMessage>> _list;
        private readonly IObserver<PeerMessage> _observer;

        public Unsubscriber(List<IObserver<PeerMessage>> list, IObserver<PeerMessage> observer)
        {
            _list = list;
            _observer = observer;
        }

        public void Dispose()
        {
            lock (_list)
            {
                _list.Remove(_observer);
            }
        }
    }

    private sealed class AnonymousObserver<T> : IObserver<T>
    {
        private readonly Action<T> _handler;
        public AnonymousObserver(Action<T> handler) => _handler = handler;

        public void OnCompleted() { }
        public void OnError(Exception error) { }
        public void OnNext(T value) => _handler(value);
    }

    #endregion
}

#region Auxiliary Types

/// <summary>
/// Represents a raw wire-message exchanged between peers.
/// </summary>
/// <param name="Command">ASCII command identifier (e.g. "tx", "block")</param>
/// <param name="Payload">Opaque binary payload; interpretation is left to
/// upper layers.</param>
public readonly record struct NetworkMessage(string Command, ReadOnlyMemory<byte> Payload)
{
    public static NetworkMessage Create(string cmd, ReadOnlyMemory<byte> payload)
        => new(cmd ?? throw new ArgumentNullException(nameof(cmd)), payload);

    public override string ToString() => $"{Command} ({Payload.Length} bytes)";
}

/// <summary>
/// Wrapper delivered to subscribers of <see cref="Peer"/>.
/// </summary>
public sealed record PeerMessage(
    Peer Peer,
    PeerEventType EventType,
    NetworkMessage Message = default);

public enum PeerEventType
{
    StateChanged,
    IncomingMessage,
    OutgoingMessage
}

public enum PeerState
{
    Created,
    Connecting,
    Handshaking,
    Connected,
    Disconnecting,
    Disposed
}

public sealed class ProtocolException : Exception
{
    public ProtocolException(string message) : base(message) { }
}

#endregion
```