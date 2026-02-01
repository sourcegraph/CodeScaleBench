```csharp
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.Diagnostics;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Caching.Memory;
using Microsoft.Extensions.Logging;
using TycoonVerse.Core.Domain.Events;
using TycoonVerse.Core.Domain.Values;
using TycoonVerse.Core.DomainServices.Abstractions;

namespace TycoonVerse.Core.DomainServices;

/// <summary>
///     Handles optimal routing of in-game cargo across the global logistics graph, taking into account
///     regional events, transportation modes, delivery deadlines and player-specific cost modifiers.
/// </summary>
/// <remarks>
///     The service is intentionally stateless except for a memory cache that stores recently
///     calculated routes for performance when players batch-ship multiple orders along similar lanes.
///     All heavy calculations are fully cancellable to support background execution on mobile devices.
/// </remarks>
public sealed class LogisticsRoutingService : ILogisticsRoutingService
{
    private const string CachePrefix = "tycoonverse.routing.";
    private readonly IMemoryCache           _cache;
    private readonly ILogisticsGraphProvider _graphProvider;
    private readonly IRegionalEventService   _eventService;
    private readonly ILogger<LogisticsRoutingService> _logger;

    // Thread-safe, per-app-lifetime cache of compiled graphs keyed by world-version
    private readonly ConcurrentDictionary<string, GraphSnapshot> _graphSnapshotCache = new();

    public LogisticsRoutingService(
        IMemoryCache                         cache,
        ILogisticsGraphProvider              graphProvider,
        IRegionalEventService                eventService,
        ILogger<LogisticsRoutingService>     logger)
    {
        _cache         = cache  ?? throw new ArgumentNullException(nameof(cache));
        _graphProvider = graphProvider ?? throw new ArgumentNullException(nameof(graphProvider));
        _eventService  = eventService  ?? throw new ArgumentNullException(nameof(eventService));
        _logger        = logger        ?? throw new ArgumentNullException(nameof(logger));
    }

    /// <inheritdoc />
    public async Task<RoutePlan> GenerateRoutePlanAsync(
        Shipment          shipment,
        CancellationToken cancellationToken = default)
    {
        if (shipment is null) throw new ArgumentNullException(nameof(shipment));

        cancellationToken.ThrowIfCancellationRequested();

        // Fast path: are we inside cache?
        var cacheKey = BuildCacheKey(shipment);
        if (_cache.TryGetValue<RoutePlan>(cacheKey, out var cachedPlan))
        {
            _logger.LogDebug("Route plan cache hit for {CacheKey}", cacheKey);
            return cachedPlan with { /* clone ensures immutability */ };
        }

        // Ensure graph snapshot is ready
        var worldVersion = await _graphProvider.GetCurrentWorldVersionAsync(cancellationToken).ConfigureAwait(false);
        var graph        = await GetOrCreateGraphSnapshotAsync(worldVersion, cancellationToken).ConfigureAwait(false);

        // Load active regional events (e.g. hurricane on the Gulf coast)
        var activeEvents = await _eventService
            .GetActiveEventsAsync(shipment.RequestedDeliveryDate, cancellationToken)
            .ConfigureAwait(false);

        var routeSegments =
            ComputeOptimalPath(graph, shipment, activeEvents, cancellationToken).ToImmutableList();

        var plan = new RoutePlan(
            shipmentId:          shipment.Id,
            segments:            routeSegments,
            totalCost:           routeSegments.Sum(s => s.Cost),
            estimatedTransit:    routeSegments.Aggregate(TimeSpan.Zero, (acc, s) => acc + s.TravelTime)
        );

        // Insert into cache with absolute expiry to keep memory bounded
        _cache.Set(cacheKey, plan, TimeSpan.FromMinutes(10));

        return plan;
    }

    #region Internal helpers

    private async Task<GraphSnapshot> GetOrCreateGraphSnapshotAsync(
        string            worldVersion,
        CancellationToken cancellationToken)
    {
        if (_graphSnapshotCache.TryGetValue(worldVersion, out var snapshot))
            return snapshot;

        var graph = await _graphProvider
            .GetFullGraphAsync(cancellationToken)
            .ConfigureAwait(false);

        snapshot = new GraphSnapshot(graph, DateTimeOffset.UtcNow);
        _graphSnapshotCache.TryAdd(worldVersion, snapshot);
        return snapshot;
    }

    private static string BuildCacheKey(Shipment shipment)
    {
        return $"{CachePrefix}{shipment.Origin.Code}->{shipment.Destination.Code}:{shipment.Volume}:{shipment.Weight}:{shipment.RequestedDeliveryDate:O}";
    }

    /// <summary>
    ///     Finds the cost-optimal path from origin to destination using Dijkstra's algorithm
    ///     with dynamic edge weights that incorporate active regional events and shipment parameters.
    /// </summary>
    private IEnumerable<RouteSegment> ComputeOptimalPath(
        GraphSnapshot            graph,
        Shipment                 shipment,
        IReadOnlyCollection<RegionalEvent> activeEvents,
        CancellationToken        token)
    {
        token.ThrowIfCancellationRequested();

        var originNode      = shipment.Origin;
        var destinationNode = shipment.Destination;

        if (!graph.Nodes.Contains(originNode) || !graph.Nodes.Contains(destinationNode))
            throw new InvalidOperationException("Origin or destination node not found in graph.");

        // Priority queue keyed by total cost from origin to node
        var queue = new PriorityQueue<Location, decimal>();
        var costSoFar = new Dictionary<Location, decimal>
        {
            [originNode] = 0
        };
        var cameFrom = new Dictionary<Location, RouteEdge?>();
        queue.Enqueue(originNode, 0);

        while (queue.TryDequeue(out var current, out var currentCost))
        {
            token.ThrowIfCancellationRequested();
            if (current.Equals(destinationNode))
                break;

            foreach (var edge in graph.GetAdjacentEdges(current))
            {
                var nextNode = edge.To;
                var edgeCost = EvaluateCost(edge, shipment, activeEvents);
                var newCost  = currentCost + edgeCost;

                if (!costSoFar.TryGetValue(nextNode, out var existingCost) || newCost < existingCost)
                {
                    costSoFar[nextNode] = newCost;
                    queue.Enqueue(nextNode, newCost);
                    cameFrom[nextNode] = edge;
                }
            }
        }

        if (!cameFrom.ContainsKey(destinationNode))
            throw new RouteNotFoundException(originNode, destinationNode);

        // Reconstruct path
        var segments = new Stack<RouteSegment>();
        var node     = destinationNode;
        while (!node.Equals(originNode))
        {
            var edge = cameFrom[node]!;
            segments.Push(ToSegment(edge, shipment, activeEvents));
            node = edge.From;
        }

        return segments;
    }

    private static decimal EvaluateCost(
        RouteEdge                 edge,
        Shipment                  shipment,
        IReadOnlyCollection<RegionalEvent> activeEvents)
    {
        decimal cost = edge.BaseCostPerKm * edge.DistanceKm;

        // Volume & weight modifiers
        cost += shipment.Volume * edge.Mode.VolumeMultiplier;
        cost += shipment.Weight * edge.Mode.WeightMultiplier;

        // Time sensitivity modifier (faster modes get premium)
        var deadlineDelta = shipment.RequestedDeliveryDate - DateTime.UtcNow;
        if (deadlineDelta < TimeSpan.FromDays(2) && edge.Mode.SpeedRating >= TransportModeSpeed.High)
            cost *= 1.15m;

        // Regional event impact
        foreach (var evt in activeEvents)
        {
            if (evt.Affects(edge))
                cost *= evt.CostMultiplier;
        }

        return cost;
    }

    private static RouteSegment ToSegment(
        RouteEdge                 edge,
        Shipment                  shipment,
        IReadOnlyCollection<RegionalEvent> activeEvents)
    {
        var travelTime = TimeSpan.FromHours(edge.DistanceKm / edge.Mode.AverageKph);

        // Account for event-related delays
        foreach (var evt in activeEvents)
        {
            if (evt.Affects(edge))
                travelTime += evt.Delay;
        }

        var cost = EvaluateCost(edge, shipment, activeEvents);
        return new RouteSegment(edge.From, edge.To, edge.DistanceKm, travelTime, cost, edge.Mode);
    }

    #endregion
}

#region Abstractions & supporting records (simplified)

/// <summary>Domain-facing contract. Implementation is platform-specific.</summary>
public interface ILogisticsRoutingService
{
    Task<RoutePlan> GenerateRoutePlanAsync(Shipment shipment, CancellationToken cancellationToken = default);
}

public interface ILogisticsGraphProvider
{
    Task<LogisticsGraph> GetFullGraphAsync(CancellationToken token);
    Task<string>         GetCurrentWorldVersionAsync(CancellationToken token);
}

public interface IRegionalEventService
{
    Task<IReadOnlyCollection<RegionalEvent>> GetActiveEventsAsync(
        DateTime            at,
        CancellationToken   token);
}

/// <summary>
///     Immutable snapshot of the logistics graph at a given point in time.
///     Allows concurrent reads without locks.
/// </summary>
internal sealed record GraphSnapshot(LogisticsGraph Graph, DateTimeOffset CapturedAtUtc)
{
    public IReadOnlyCollection<Location> Nodes => Graph.Nodes;
    public IEnumerable<RouteEdge> GetAdjacentEdges(Location node) => Graph.GetAdjacentEdges(node);
}

public sealed record LogisticsGraph(
    IReadOnlyCollection<Location> Nodes,
    IReadOnlyCollection<RouteEdge> Edges)
{
    private readonly IReadOnlyDictionary<Location, List<RouteEdge>> _adjacent =
        Edges.GroupBy(e => e.From).ToDictionary(g => g.Key, g => g.ToList());

    public IEnumerable<RouteEdge> GetAdjacentEdges(Location node) =>
        _adjacent.TryGetValue(node, out var list) ? list : Array.Empty<RouteEdge>();
}

public sealed record Shipment(
    Guid      Id,
    Location  Origin,
    Location  Destination,
    decimal   Volume,
    decimal   Weight,
    DateTime  RequestedDeliveryDate);

public sealed record RoutePlan(
    Guid                     ShipmentId,
    IReadOnlyList<RouteSegment> Segments,
    decimal                  TotalCost,
    TimeSpan                 EstimatedTransit);

public sealed record RouteSegment(
    Location      From,
    Location      To,
    decimal       DistanceKm,
    TimeSpan      TravelTime,
    decimal       Cost,
    TransportMode Mode);

public sealed record RouteEdge(
    Location       From,
    Location       To,
    decimal        DistanceKm,
    decimal        BaseCostPerKm,
    TransportMode  Mode);

public sealed record Location(string Code);

public sealed record TransportMode(
    string                Name,
    decimal               BaseCostModifier,
    decimal               VolumeMultiplier,
    decimal               WeightMultiplier,
    int                   AverageKph,
    TransportModeSpeed    SpeedRating);

public enum TransportModeSpeed
{
    Low    = 1,
    Medium = 2,
    High   = 3
}

public abstract record RegionalEvent
{
    public abstract bool    Affects(RouteEdge edge);
    public abstract decimal CostMultiplier { get; }
    public abstract TimeSpan Delay { get; }
}

public sealed class RouteNotFoundException : Exception
{
    public Location Origin { get; }
    public Location Destination { get; }

    public RouteNotFoundException(Location origin, Location destination)
        : base($"Could not find a route from {origin.Code} to {destination.Code}.")
    {
        Origin      = origin;
        Destination = destination;
    }
}

#endregion
```