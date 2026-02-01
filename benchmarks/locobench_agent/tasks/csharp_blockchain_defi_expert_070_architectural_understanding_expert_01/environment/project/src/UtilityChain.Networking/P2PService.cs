```csharp
using System;
using System.Buffers;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Channels;
using System.Threading.Tasks;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace UtilityChain.Networking;

/// <summary>
///     High-level service responsible for peer-to-peer networking.  The service boots a <see cref="TcpListener"/>
///     to accept inbound connections, dials out to seed peers, and performs a minimal handshake
///     (UtilityChain version / network-id exchange).  Once a peer is authenticated it is tracked in
///     <see cref="_peers"/> and participates in broadcast / gossip operations through an
///     internal channel pump.
/// </summary>
public sealed class P2PService : BackgroundService, IP2PService, IDisposable
{
    private const int HandshakeTimeoutSeconds = 5;
    private const int ReceiveBufferSize      = 32 * 1024; // 32KiB reasonable default
    private const int SendBufferSize         = 32 * 1024;

    private readonly ILogger<P2PService>               _logger;
    private readonly P2PSettings                       _settings;
    private readonly IEventBus                         _eventBus;
    private readonly TcpListener                       _listener;
    private readonly ConcurrentDictionary<string, PeerConnection> _peers;
    private readonly Channel<OutboundEnvelope>         _outbound; // Multiplexer for all outbound messages

    private bool _disposed;

    public P2PService(
        ILogger<P2PService> logger,
        P2PSettings settings,
        IEventBus eventBus)
    {
        _logger    = logger  ?? throw new ArgumentNullException(nameof(logger));
        _settings  = settings ?? throw new ArgumentNullException(nameof(settings));
        _eventBus  = eventBus ?? throw new ArgumentNullException(nameof(eventBus));

        // Data structures
        _peers    = new ConcurrentDictionary<string, PeerConnection>(StringComparer.Ordinal);
        _outbound = Channel.CreateUnbounded<OutboundEnvelope>(new UnboundedChannelOptions
        {
            SingleReader = true,
            SingleWriter = false
        });

        // Network listener
        _listener = new TcpListener(IPAddress.Any, _settings.Port)
        {
            Server =
            {
                NoDelay         = true,
                ReceiveBufferSize = ReceiveBufferSize,
                SendBufferSize    = SendBufferSize
            }
        };
    }

    #region BackgroundService overrides

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("P2PService starting on port {Port}", _settings.Port);
        _listener.Start();

        // Kick off parallel tasks
        var acceptLoop    = AcceptLoopAsync(stoppingToken);
        var outboundLoop  = OutboundPumpAsync(stoppingToken);
        var seedDialLoop  = DialSeedsAsync(stoppingToken);

        await Task.WhenAll(acceptLoop, outboundLoop, seedDialLoop).ConfigureAwait(false);
    }

    public override async Task StopAsync(CancellationToken cancellationToken)
    {
        _logger.LogInformation("P2PService stopping…");

        _listener.Stop();

        foreach (var (_, peer) in _peers)
        {
            peer.Dispose();
        }

        // Ensure channel completes to flush outbound pump
        _outbound.Writer.TryComplete();

        await base.StopAsync(cancellationToken).ConfigureAwait(false);
    }

    #endregion

    #region Accept / Dial

    private async Task AcceptLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                var client = await _listener.AcceptTcpClientAsync(ct).ConfigureAwait(false);
                _ = HandleNewConnectionAsync(client, ct);
            }
            catch (OperationCanceledException)
            {
                // Service is shutting down
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Unexpected error in accept loop.");
            }
        }
    }

    private async Task DialSeedsAsync(CancellationToken ct)
    {
        foreach (var seed in _settings.SeedNodes)
        {
            if (ct.IsCancellationRequested) break;

            try
            {
                await DialAsync(seed, ct).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "Failed to dial seed {Seed}", seed);
            }
        }
    }

    private async Task DialAsync(IPEndPoint endPoint, CancellationToken ct)
    {
        if (_peers.ContainsKey(endPoint.ToString())) return;

        using var client = new TcpClient
        {
            NoDelay          = true,
            ReceiveBufferSize = ReceiveBufferSize,
            SendBufferSize    = SendBufferSize
        };

        await client.ConnectAsync(endPoint, ct).ConfigureAwait(false);
        await HandleNewConnectionAsync(client, ct, outboundInitiator: true).ConfigureAwait(false);
    }

    #endregion

    #region Connection handler

    private async Task HandleNewConnectionAsync(
        TcpClient client,
        CancellationToken ct,
        bool outboundInitiator = false)
    {
        var remoteEndPoint = client.Client.RemoteEndPoint?.ToString();
        if (remoteEndPoint == null)
        {
            client.Dispose();
            return;
        }

        // Enforce peer limit
        if (_peers.Count >= _settings.MaxPeers)
        {
            _logger.LogDebug("Rejecting {Peer} – peer limit reached.", remoteEndPoint);
            client.Close();
            return;
        }

        NetworkStream stream = client.GetStream();

        var peer = new PeerConnection(client, stream, _settings, _logger);
        if (!_peers.TryAdd(remoteEndPoint, peer))
        {
            client.Close();
            return;
        }

        _logger.LogInformation(
            "Peer {Peer} {Direction}",
            remoteEndPoint,
            outboundInitiator ? "dialed" : "connected");

        try
        {
            // Perform handshake
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(HandshakeTimeoutSeconds));
            using var linkedCts = CancellationTokenSource.CreateLinkedTokenSource(ct, cts.Token);

            await DoHandshakeAsync(peer, outboundInitiator, linkedCts.Token).ConfigureAwait(false);

            // Start receive loop
            _ = ReceiveLoopAsync(peer, ct);
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Handshake with {Peer} failed.", remoteEndPoint);
            DropPeer(remoteEndPoint);
        }
    }

    private async Task DoHandshakeAsync(PeerConnection peer, bool outboundInitiator, CancellationToken ct)
    {
        // Build handshake payload
        var hello = new HelloPayload
        {
            NodeId    = _settings.NodeId,
            NetworkId = _settings.NetworkId,
            Timestamp = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
            Version   = _settings.ProtocolVersion,
            Services  = _settings.Services
        };

        if (outboundInitiator)
        {
            await peer.SendAsync(hello, ct).ConfigureAwait(false);
            var remoteHello = await peer.ReceiveAsync<HelloPayload>(ct).ConfigureAwait(false);
            ValidateHandshake(remoteHello);
        }
        else
        {
            var remoteHello = await peer.ReceiveAsync<HelloPayload>(ct).ConfigureAwait(false);
            ValidateHandshake(remoteHello);
            await peer.SendAsync(hello, ct).ConfigureAwait(false);
        }

        peer.IsReady = true;
        _eventBus.Publish(new PeerConnectedEvent(peer.ToPeerInfo()));
    }

    private void ValidateHandshake(HelloPayload remoteHello)
    {
        if (remoteHello.NetworkId != _settings.NetworkId)
            throw new InvalidDataException($"Network mismatch. Local={_settings.NetworkId}, Remote={remoteHello.NetworkId}");

        if (remoteHello.Version != _settings.ProtocolVersion)
            _logger.LogWarning("Protocol version mismatch. Local={Local}, Remote={Remote}",
                _settings.ProtocolVersion, remoteHello.Version);
    }

    #endregion

    #region Receive / Broadcast

    private async Task ReceiveLoopAsync(PeerConnection peer, CancellationToken ct)
    {
        try
        {
            while (!ct.IsCancellationRequested && peer.IsReady)
            {
                var header = await peer.ReceiveAsync<MessageHeader>(ct).ConfigureAwait(false);
                var payloadType = MessageRegistry.Resolve(header.Type);
                var payload     = await peer.ReceiveAsync(payloadType, header.Length, ct).ConfigureAwait(false);

                // Dispatch to event bus
                _eventBus.Publish(new NetworkMessageEvent(peer.ToPeerInfo(), payload));
            }
        }
        catch (IOException)
        {
            // peer closed connection
        }
        catch (OperationCanceledException)
        {
            // shutting down
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Unexpected error processing peer {Peer}", peer.RemoteEndPoint);
        }
        finally
        {
            DropPeer(peer.RemoteEndPoint);
        }
    }

    public async Task BroadcastAsync(object message, CancellationToken ct = default)
    {
        if (!_outbound.Writer.TryWrite(new OutboundEnvelope(null, message)))
        {
            await _outbound.Writer.WriteAsync(new OutboundEnvelope(null, message), ct).ConfigureAwait(false);
        }
    }

    public async Task SendToAsync(string nodeId, object message, CancellationToken ct = default)
    {
        if (!_outbound.Writer.TryWrite(new OutboundEnvelope(nodeId, message)))
        {
            await _outbound.Writer.WriteAsync(new OutboundEnvelope(nodeId, message), ct).ConfigureAwait(false);
        }
    }

    private async Task OutboundPumpAsync(CancellationToken ct)
    {
        await foreach (var envelope in _outbound.Reader.ReadAllAsync(ct).ConfigureAwait(false))
        {
            if (envelope.TargetNodeId is null)
            {
                foreach (var (_, peer) in _peers)
                {
                    _ = SafeSendAsync(peer, envelope.Payload, ct);
                }
            }
            else
            {
                if (_peers.TryGetValue(envelope.TargetNodeId, out var peer))
                {
                    _ = SafeSendAsync(peer, envelope.Payload, ct);
                }
            }
        }
    }

    private async Task SafeSendAsync(PeerConnection peer, object payload, CancellationToken ct)
    {
        try
        {
            await peer.SendAsync(payload, ct).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Failed to send message to {Peer}", peer.RemoteEndPoint);
            DropPeer(peer.RemoteEndPoint);
        }
    }

    #endregion

    #region Helpers

    private void DropPeer(string endPoint)
    {
        if (_peers.TryRemove(endPoint, out var peer))
        {
            peer.Dispose();
            _eventBus.Publish(new PeerDisconnectedEvent(peer.ToPeerInfo()));
            _logger.LogInformation("Peer {Peer} disconnected.", endPoint);
        }
    }

    #endregion

    #region IDisposable

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _listener.Stop();
    }

    #endregion

    #region Internal types

    private sealed record OutboundEnvelope(string? TargetNodeId, object Payload);

    /// <summary>
    /// Wrapper around TCP client / stream with helpers for framing and JSON serialization.
    /// </summary>
    private sealed class PeerConnection : IDisposable
    {
        private readonly TcpClient    _client;
        private readonly NetworkStream _stream;
        private readonly ILogger      _logger;
        private readonly ArrayPool<byte> _bufferPool = ArrayPool<byte>.Shared;
        private readonly JsonSerializerOptions _jsonOpts = new(JsonSerializerDefaults.Web);

        private readonly int _maxMessageSize;

        public bool   IsReady        { get; set; }
        public string RemoteEndPoint { get; }
        public string NodeId         { get; private set; } = string.Empty;

        public PeerConnection(TcpClient client, NetworkStream stream, P2PSettings settings, ILogger logger)
        {
            _client    = client;
            _stream    = stream;
            _logger    = logger;
            _maxMessageSize = settings.MaxMessageSize;
            RemoteEndPoint  = client.Client.RemoteEndPoint?.ToString() ?? "unknown";
        }

        #region Send

        public async Task SendAsync(object payload, CancellationToken ct = default)
        {
            var payloadJson = JsonSerializer.SerializeToUtf8Bytes(payload, payload.GetType(), _jsonOpts);
            if (payloadJson.Length > _maxMessageSize)
                throw new InvalidOperationException("Payload exceeds max-message-size.");

            var header = new MessageHeader
            {
                Type   = payload.GetType().FullName!,
                Length = payloadJson.Length
            };

            // Serialize header
            var headerJson = JsonSerializer.SerializeToUtf8Bytes(header, _jsonOpts);
            var headerLenBytes = BitConverter.GetBytes(headerJson.Length);

            // Write header length + header + payload
            await _stream.WriteAsync(headerLenBytes, ct).ConfigureAwait(false);
            await _stream.WriteAsync(headerJson, ct).ConfigureAwait(false);
            await _stream.WriteAsync(payloadJson, ct).ConfigureAwait(false);
        }

        #endregion

        #region Receive

        public async Task<T> ReceiveAsync<T>(CancellationToken ct = default) where T : notnull
        {
            var header = await ReceiveAsync<MessageHeader>(ct).ConfigureAwait(false);
            var payload = await ReceiveAsync(typeof(T), header.Length, ct).ConfigureAwait(false);
            return (T)payload;
        }

        public async Task<object> ReceiveAsync(Type type, int bytes, CancellationToken ct = default)
        {
            var buffer = _bufferPool.Rent(bytes);
            try
            {
                await FillBufferAsync(buffer, bytes, ct).ConfigureAwait(false);
                return JsonSerializer.Deserialize(buffer.AsSpan(0, bytes), type, _jsonOpts)!;
            }
            finally
            {
                _bufferPool.Return(buffer);
            }
        }

        private async Task<MessageHeader> ReceiveAsync<MessageHeader>(CancellationToken ct)
        {
            // Read header length (4 bytes)
            var lenBytes = _bufferPool.Rent(sizeof(int));
            try
            {
                await FillBufferAsync(lenBytes, sizeof(int), ct).ConfigureAwait(false);
                var headerLen = BitConverter.ToInt32(lenBytes, 0);

                var headerBuffer = _bufferPool.Rent(headerLen);
                try
                {
                    await FillBufferAsync(headerBuffer, headerLen, ct).ConfigureAwait(false);
                    return JsonSerializer.Deserialize<MessageHeader>(headerBuffer.AsSpan(0, headerLen), _jsonOpts)!;
                }
                finally
                {
                    _bufferPool.Return(headerBuffer);
                }
            }
            finally
            {
                _bufferPool.Return(lenBytes);
            }
        }

        private async Task FillBufferAsync(byte[] buffer, int count, CancellationToken ct)
        {
            var offset = 0;
            while (offset < count)
            {
                var read = await _stream.ReadAsync(buffer.AsMemory(offset, count - offset), ct).ConfigureAwait(false);
                if (read == 0) throw new IOException("Remote closed connection.");
                offset += read;
            }
        }

        #endregion

        public PeerInfo ToPeerInfo() => new(NodeId, RemoteEndPoint);

        public void Dispose()
        {
            try { _stream.Dispose(); } catch { }
            try { _client.Close(); } catch { }
        }
    }

    #endregion
}

#region Interfaces, DTOs, and options (typically in their own files – consolidated here for brevity)

/// <summary>Abstraction used by components to broadcast or unicast network messages.</summary>
public interface IP2PService
{
    Task BroadcastAsync(object message, CancellationToken ct = default);
    Task SendToAsync(string nodeId, object message, CancellationToken ct = default);
}

/// <summary>Lightweight in-process event bus.</summary>
public interface IEventBus
{
    void Publish<TEvent>(TEvent @event);
}

public sealed record PeerInfo(string NodeId, string EndPoint);

public sealed record PeerConnectedEvent(PeerInfo Peer);
public sealed record PeerDisconnectedEvent(PeerInfo Peer);

/// <summary>Wraps any inbound message payload along with the sender information.</summary>
public sealed record NetworkMessageEvent(PeerInfo Peer, object Payload);

/// <summary>Minimal header prepended to every message.</summary>
public sealed class MessageHeader
{
    public string Type  { get; init; } = string.Empty;
    public int    Length { get; init; }
}

/// <summary>First message exchanged between nodes.</summary>
public sealed class HelloPayload
{
    public string NodeId      { get; init; } = string.Empty;
    public string NetworkId   { get; init; } = string.Empty;
    public string Version     { get; init; } = string.Empty;
    public long   Timestamp   { get; init; }
    public string Services    { get; init; } = string.Empty;
}

/// <summary>Node networking settings (bound into DI via IOptions or manual configuration).</summary>
public sealed class P2PSettings
{
    public int    Port            { get; init; } = 30303;
    public string NodeId          { get; init; } = Guid.NewGuid().ToString("N");
    public string NetworkId       { get; init; } = "utilitychain-mainnet";
    public string ProtocolVersion { get; init; } = "1.0";
    public string Services        { get; init; } = string.Empty;
    public int    MaxPeers        { get; init; } = 50;
    public int    MaxMessageSize  { get; init; } = 1_048_576; // 1 MiB
    public IReadOnlyCollection<IPEndPoint> SeedNodes { get; init; } = Array.Empty<IPEndPoint>();
}

/// <summary>
///     Resolves <see cref="MessageHeader.Type"/> strings into CLRs types registered by
///     the networking module.  In real production code this might inspect loaded assemblies
///     or rely on Source-Generators.
/// </summary>
public static class MessageRegistry
{
    private static readonly ConcurrentDictionary<string, Type> _map = new();

    public static void Register<T>() => _map[typeof(T).FullName!] = typeof(T);

    public static Type Resolve(string type)
    {
        if (_map.TryGetValue(type, out var t)) return t;
        throw new InvalidDataException($"Unknown message type: {type}");
    }
}

#endregion
```