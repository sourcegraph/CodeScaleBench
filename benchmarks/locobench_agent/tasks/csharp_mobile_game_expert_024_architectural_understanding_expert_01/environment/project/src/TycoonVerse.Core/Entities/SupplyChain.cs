```csharp
// File: TycoonVerse/src/TycoonVerse.Core/Entities/SupplyChain.cs

using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Diagnostics.CodeAnalysis;
using System.Linq;
using TycoonVerse.Core.Exceptions;
using TycoonVerse.Core.Primitives;

namespace TycoonVerse.Core.Entities
{
    /// <summary>
    /// Aggregate root that represents the entire supply-chain network for a single player corporation.
    /// Every modification (adding facilities, routing, shipments) is captured as a domain event so that
    /// external layers (analytics, persistence, UI) can react without violating the domain boundary.
    /// 
    /// NOTE: This entity is designed to be fully deterministic and offline-friendly; all IDs are client-
    /// generated GUIDs and the internal state is immutable outside of Aggregate methods.
    /// </summary>
    public sealed class SupplyChain : AggregateRoot<Guid>
    {
        #region Nested Types

        public enum TransportMode
        {
            Truck,
            Rail,
            OceanFreight,
            AirCargo,
            Drone
        }

        /// <summary>
        /// Immutable value object that represents monetary cost in the game’s reference currency.
        /// </summary>
        public readonly struct Money : IComparable<Money>, IEquatable<Money>
        {
            public static readonly Money Zero = new(0m);

            public decimal Amount { get; }

            public Money(decimal amount)
            {
                if (amount < 0) throw new DomainValidationException("Money cannot be negative.");
                Amount = amount;
            }

            public Money Add(Money other) => new(Amount + other.Amount);
            public Money Subtract(Money other)
            {
                if (other.Amount > Amount) throw new DomainValidationException("Resulting money cannot be negative.");
                return new Money(Amount - other.Amount);
            }

            public int CompareTo(Money other) => Amount.CompareTo(other.Amount);
            public bool Equals(Money other) => Amount == other.Amount;
            public override bool Equals(object? obj) => obj is Money money && Equals(money);
            public override int GetHashCode() => Amount.GetHashCode();
            public override string ToString() => Amount.ToString("C");

            public static Money operator +(Money a, Money b) => a.Add(b);
            public static Money operator -(Money a, Money b) => a.Subtract(b);
        }

        /// <summary>
        /// Immutable value object that encapsulates CO₂ equivalent footprint.
        /// </summary>
        public readonly struct CarbonFootprint : IComparable<CarbonFootprint>, IEquatable<CarbonFootprint>
        {
            public static readonly CarbonFootprint Zero = new(0m);

            /// <summary>
            /// Amount in kilograms of CO₂ equivalent.
            /// </summary>
            public decimal Kg { get; }

            public CarbonFootprint(decimal kg)
            {
                if (kg < 0) throw new DomainValidationException("Carbon footprint cannot be negative.");
                Kg = kg;
            }

            public CarbonFootprint Add(CarbonFootprint other) => new(Kg + other.Kg);
            public int CompareTo(CarbonFootprint other) => Kg.CompareTo(other.Kg);
            public bool Equals(CarbonFootprint other) => Kg == other.Kg;
            public override bool Equals(object? obj) => obj is CarbonFootprint footprint && Equals(footprint);
            public override int GetHashCode() => Kg.GetHashCode();
            public override string ToString() => $"{Kg:N2} kg CO₂e";
        }

        /// <summary>
        /// A physical node in the supply-chain graph.
        /// </summary>
        public sealed class Facility
        {
            public Guid Id { get; }
            public string Name { get; }
            public FacilityType Type { get; }
            public int Capacity { get; private set; } // Daily handling units

            public Facility(Guid id, string name, FacilityType type, int capacity)
            {
                if (capacity <= 0) throw new DomainValidationException("Capacity must be positive.");
                Id = id;
                Name = name ?? throw new ArgumentNullException(nameof(name));
                Type = type;
                Capacity = capacity;
            }

            internal void IncreaseCapacity(int delta)
            {
                if (delta <= 0) throw new DomainValidationException("Delta must be positive.");
                Capacity += delta;
            }

            internal bool TryReserveCapacity(int units)
            {
                if (units <= 0) return false;
                if (Capacity < units) return false;

                Capacity -= units;
                return true;
            }

            public override string ToString() => $"{Name} ({Type})";
        }

        public enum FacilityType
        {
            Factory,
            Warehouse,
            Port,
            Store
        }

        /// <summary>
        /// Directed edge between two facilities.
        /// </summary>
        public sealed class TransportRoute
        {
            public Guid Id { get; }
            public Guid OriginId { get; }
            public Guid DestinationId { get; }
            public TransportMode Mode { get; }
            public TimeSpan LeadTime { get; }          // Average lead time per shipment
            public Money CostPerUnit { get; }
            public CarbonFootprint FootprintPerUnit { get; }

            public TransportRoute(
                Guid id,
                Guid originId,
                Guid destinationId,
                TransportMode mode,
                TimeSpan leadTime,
                Money costPerUnit,
                CarbonFootprint footprintPerUnit)
            {
                if (originId == destinationId)
                    throw new DomainValidationException("Origin and destination cannot be the same.");

                Id = id;
                OriginId = originId;
                DestinationId = destinationId;
                Mode = mode;
                LeadTime = leadTime;
                CostPerUnit = costPerUnit;
                FootprintPerUnit = footprintPerUnit;
            }
        }

        /// <summary>
        /// Represents a scheduled shipment flowing through the supply chain.
        /// Persisting this as part of the aggregate allows deterministic replay of logistics.
        /// </summary>
        public sealed class Shipment
        {
            public Guid Id { get; }
            public Guid RouteId { get; }
            public int Units { get; }
            public DateTimeOffset DepartureDate { get; }
            public DateTimeOffset EstimatedArrival => DepartureDate + LeadTime;
            public Money TotalCost => CostPerUnit * Units;
            public CarbonFootprint TotalFootprint => FootprintPerUnit * Units;

            // Cached for easier access
            internal TimeSpan LeadTime { get; }
            internal Money CostPerUnit { get; }
            internal CarbonFootprint FootprintPerUnit { get; }

            public Shipment(Guid id, Guid routeId, int units, DateTimeOffset departureDate,
                TimeSpan leadTime, Money costPerUnit, CarbonFootprint footprintPerUnit)
            {
                if (units <= 0) throw new DomainValidationException("Units must be positive.");

                Id = id;
                RouteId = routeId;
                Units = units;
                DepartureDate = departureDate;
                LeadTime = leadTime;
                CostPerUnit = costPerUnit;
                FootprintPerUnit = footprintPerUnit;
            }
        }

        #endregion

        #region Fields

        private readonly Dictionary<Guid, Facility> _facilities = new();
        private readonly Dictionary<Guid, TransportRoute> _routes = new();
        private readonly List<Shipment> _shipments = new();

        #endregion

        #region Constructors

        private SupplyChain() : base(Guid.NewGuid()) { } // For ORM/Serialization

        public SupplyChain(Guid id) : base(id) { }

        #endregion

        #region Properties

        public IReadOnlyCollection<Facility> Facilities => new ReadOnlyCollection<Facility>(_facilities.Values.ToList());

        public IReadOnlyCollection<TransportRoute> Routes => new ReadOnlyCollection<TransportRoute>(_routes.Values.ToList());

        public IReadOnlyCollection<Shipment> Shipments => new ReadOnlyCollection<Shipment>(_shipments);

        #endregion

        #region Public API – Facilities

        /// <summary>
        /// Registers a new facility. Throws if the <paramref name="facilityId"/> already exists.
        /// </summary>
        public void RegisterFacility(Guid facilityId, string name, FacilityType type, int capacity)
        {
            if (_facilities.ContainsKey(facilityId))
                throw new DomainValidationException($"Facility with id '{facilityId}' already exists.");

            var facility = new Facility(facilityId, name, type, capacity);
            _facilities.Add(facility.Id, facility);

            RaiseDomainEvent(new FacilityRegisteredDomainEvent(Id, facility));
        }

        /// <summary>
        /// Up-scales an existing facility’s daily capacity.
        /// </summary>
        public void IncreaseFacilityCapacity(Guid facilityId, int delta)
        {
            if (!_facilities.TryGetValue(facilityId, out var facility))
                throw new DomainValidationException($"No facility found with id '{facilityId}'.");

            facility.IncreaseCapacity(delta);

            RaiseDomainEvent(new FacilityCapacityIncreasedDomainEvent(Id, facilityId, delta));
        }

        #endregion

        #region Public API – Routes

        public void AddRoute(Guid routeId,
                             Guid originFacilityId,
                             Guid destinationFacilityId,
                             TransportMode mode,
                             TimeSpan leadTime,
                             decimal costPerUnit,
                             decimal footprintPerUnitKg)
        {
            if (_routes.ContainsKey(routeId))
                throw new DomainValidationException($"Route with id '{routeId}' already exists.");

            ValidateFacilityExists(originFacilityId);
            ValidateFacilityExists(destinationFacilityId);

            var route = new TransportRoute(
                routeId,
                originFacilityId,
                destinationFacilityId,
                mode,
                leadTime,
                new Money(costPerUnit),
                new CarbonFootprint(footprintPerUnitKg));

            _routes.Add(route.Id, route);

            RaiseDomainEvent(new RouteAddedDomainEvent(Id, route));
        }

        #endregion

        #region Public API – Shipments

        /// <summary>
        /// Books a new shipment on an existing route and reserves capacity on the origin facility.
        /// </summary>
        public void BookShipment(Guid shipmentId, Guid routeId, int units, DateTimeOffset departureDate)
        {
            if (_shipments.Any(s => s.Id == shipmentId))
                throw new DomainValidationException($"Shipment with id '{shipmentId}' already exists.");

            if (!_routes.TryGetValue(routeId, out var route))
                throw new DomainValidationException($"Route with id '{routeId}' not found.");

            // Reserve capacity on the origin facility for the departure day.
            var originFacility = _facilities[route.OriginId];
            if (!originFacility.TryReserveCapacity(units))
                throw new DomainValidationException($"Insufficient capacity on facility '{originFacility.Name}'.");

            var shipment = new Shipment(
                shipmentId,
                routeId,
                units,
                departureDate,
                route.LeadTime,
                route.CostPerUnit,
                route.FootprintPerUnit);

            _shipments.Add(shipment);

            RaiseDomainEvent(new ShipmentBookedDomainEvent(Id, shipment));
        }

        #endregion

        #region Queries

        /// <summary>
        /// Returns the estimated lead time between two facilities, selecting the cheapest route if
        /// multiple exist. Returns null if no route can be found.
        /// </summary>
        public TimeSpan? EstimateLeadTime(Guid originId, Guid destinationId)
        {
            var candidateRoutes = _routes.Values
                                         .Where(r => r.OriginId == originId && r.DestinationId == destinationId)
                                         .ToList();

            if (!candidateRoutes.Any()) return null;

            // Cheap-then-fast heuristic
            var cheapest = candidateRoutes.MinBy(r => r.CostPerUnit);
            return cheapest!.LeadTime;
        }

        /// <summary>
        /// Aggregates the total cost and carbon footprint for all scheduled shipments in the current fiscal year.
        /// </summary>
        public (Money totalCost, CarbonFootprint totalFootprint) GetFiscalYearLogisticsImpact(int fiscalYear)
        {
            var shipmentsInYear = _shipments.Where(s => s.DepartureDate.Year == fiscalYear);
            var totalCost = shipmentsInYear.Aggregate(Money.Zero, (sum, s) => sum + s.TotalCost);
            var totalFootprint = shipmentsInYear.Aggregate(CarbonFootprint.Zero, (sum, s) => sum.Add(s.TotalFootprint));

            return (totalCost, totalFootprint);
        }

        #endregion

        #region Helpers

        private void ValidateFacilityExists(Guid facilityId)
        {
            if (!_facilities.ContainsKey(facilityId))
                throw new DomainValidationException($"Facility with id '{facilityId}' does not exist.");
        }

        #endregion

        #region Domain Events

        private void RaiseDomainEvent(IDomainEvent domainEvent) => DomainEvents.Raise(domainEvent);

        public sealed record FacilityRegisteredDomainEvent(Guid SupplyChainId, Facility Facility) : IDomainEvent;
        public sealed record FacilityCapacityIncreasedDomainEvent(Guid SupplyChainId, Guid FacilityId, int Delta) : IDomainEvent;
        public sealed record RouteAddedDomainEvent(Guid SupplyChainId, TransportRoute Route) : IDomainEvent;
        public sealed record ShipmentBookedDomainEvent(Guid SupplyChainId, Shipment Shipment) : IDomainEvent;

        #endregion
    }

    #region Supporting Infrastructure (Primitives & Exceptions)

    // These are minimal abstractions that normally live elsewhere in the Core project.
    // They are included here for compilation completeness.

    public interface IDomainEvent { }

    public static class DomainEvents
    {
        // Observer pattern – decouples aggregate from concrete handlers
        private static readonly List<IObserver<IDomainEvent>> _observers = new();

        public static void Raise(IDomainEvent domainEvent)
        {
            foreach (var observer in _observers) observer.OnNext(domainEvent);
        }

        public static IDisposable Subscribe(IObserver<IDomainEvent> observer)
        {
            _observers.Add(observer);
            return new Unsubscriber(_observers, observer);
        }

        private sealed class Unsubscriber : IDisposable
        {
            private readonly List<IObserver<IDomainEvent>> _list;
            private readonly IObserver<IDomainEvent> _observer;

            public Unsubscriber(List<IObserver<IDomainEvent>> list, IObserver<IDomainEvent> observer)
            {
                _list = list;
                _observer = observer;
            }

            public void Dispose() => _list.Remove(_observer);
        }
    }

    /// <summary>
    /// Base class for entities that expose a natural key.
    /// </summary>
    public abstract class Entity<TId> : IEquatable<Entity<TId>>
        where TId : notnull
    {
        public TId Id { get; }

        protected Entity(TId id) => Id = id;

        public bool Equals(Entity<TId>? other) => other is not null && EqualityComparer<TId>.Default.Equals(Id, other.Id);
        public override bool Equals(object? obj) => obj is Entity<TId> other && Equals(other);
        public override int GetHashCode() => Id!.GetHashCode();
    }

    /// <summary>
    /// Aggregate root with domain event support.
    /// </summary>
    public abstract class AggregateRoot<TId> : Entity<TId>
        where TId : notnull
    {
        protected AggregateRoot(TId id) : base(id) { }
    }

    namespace Exceptions
    {
        public sealed class DomainValidationException : Exception
        {
            public DomainValidationException(string message) : base(message) { }
        }
    }

    namespace Primitives
    {
        public static class EnumerableExtensions
        {
            /// <summary>
            /// Returns the element that yields the minimum value according to the supplied selector.
            /// Performs only a single enumeration.
            /// </summary>
            public static TSource? MinBy<TSource, TKey>(this IEnumerable<TSource> source,
                                                        Func<TSource, TKey> selector)
                where TKey : IComparable<TKey>
            {
                if (source is null) throw new ArgumentNullException(nameof(source));
                if (selector is null) throw new ArgumentNullException(nameof(selector));

                using var enumerator = source.GetEnumerator();
                if (!enumerator.MoveNext()) return default;

                var min = enumerator.Current;
                var minKey = selector(min);

                while (enumerator.MoveNext())
                {
                    var current = enumerator.Current;
                    var currentKey = selector(current);

                    if (currentKey.CompareTo(minKey) < 0)
                    {
                        min = current;
                        minKey = currentKey;
                    }
                }

                return min;
            }

            public static SupplyChain.Money operator *(SupplyChain.Money money, int multiplier)
                => new SupplyChain.Money(money.Amount * multiplier);

            public static SupplyChain.CarbonFootprint operator *(SupplyChain.CarbonFootprint footprint, int multiplier)
                => new SupplyChain.CarbonFootprint(footprint.Kg * multiplier);
        }
    }

    #endregion
}
```