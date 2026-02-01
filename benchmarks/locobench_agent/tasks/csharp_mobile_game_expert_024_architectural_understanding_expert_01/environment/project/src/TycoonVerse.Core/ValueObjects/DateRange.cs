```csharp
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Runtime.Serialization;
using System.Text.Json.Serialization;

namespace TycoonVerse.Core.ValueObjects
{
    /// <summary>
    /// Immutable value-object that represents an inclusive date range.
    /// Provides common temporal utilities such as overlap checks, intersection,
    /// and merge semantics.  
    /// </summary>
    [DebuggerDisplay("Start = {Start:u}, End = {End:u}")]
    [DataContract]
    public sealed class DateRange : 
        IEquatable<DateRange>,
        IComparable<DateRange>,
        IEnumerable<DateTimeOffset>
    {
        public static readonly DateRange Empty = new(DateTimeOffset.MinValue, DateTimeOffset.MinValue);

        /// <summary>Inclusive start of the range (UTC).</summary>
        [DataMember(Order = 1)]
        public DateTimeOffset Start { get; }

        /// <summary>Inclusive end of the range (UTC).</summary>
        [DataMember(Order = 2)]
        public DateTimeOffset End { get; }

        #region Construction

        [JsonConstructor]
        private DateRange(DateTimeOffset start, DateTimeOffset end)
        {
            if (start > end)
                throw new ArgumentException("Start of the range must be earlier than or equal to End.");

            Start = start;
            End = end;
        }

        /// <summary>
        /// Factory method that guarantees a valid range.
        /// </summary>
        public static DateRange Create(DateTimeOffset start, DateTimeOffset end) => 
            new(start, end);

        /// <summary>
        /// Creates a range representing a single point in time (zero duration).
        /// </summary>
        public static DateRange AtMoment(DateTimeOffset instant) => 
            new(instant, instant);

        /// <summary>
        /// Attempts to parse an ISO-8601 compliant string in the form
        /// "yyyy-MM-ddTHH:mm:ssZ/yyyy-MM-ddTHH:mm:ssZ".
        /// </summary>
        public static bool TryParse(string value, out DateRange? result)
        {
            result = null;
            if (string.IsNullOrWhiteSpace(value))
                return false;

            var parts = value.Split('/', 2, StringSplitOptions.TrimEntries);
            if (parts.Length != 2)
                return false;

            if (!DateTimeOffset.TryParse(parts[0], null, DateTimeStyles.AssumeUniversal, out var start) ||
                !DateTimeOffset.TryParse(parts[1], null, DateTimeStyles.AssumeUniversal, out var end))
                return false;

            if (start > end) 
                return false;

            result = new DateRange(start, end);
            return true;
        }

        #endregion

        #region Public API – Queries

        /// <summary>
        /// True if the supplied instant falls inside the range (inclusive).
        /// </summary>
        public bool Contains(DateTimeOffset instant) => 
            instant >= Start && instant <= End;

        /// <summary>
        /// Returns <c>true</c> when the two ranges overlap
        /// (at least one common instant).
        /// </summary>
        public bool Overlaps(DateRange other) =>
            Start <= other.End && End >= other.Start;

        /// <summary>
        /// Ranges are adjacent when the end of one is exactly 
        /// one tick before the start of the other.
        /// </summary>
        public bool IsAdjacentTo(DateRange other) =>
            End.AddTicks(1) == other.Start || other.End.AddTicks(1) == Start;

        /// <summary>
        /// Calculates the overlapping sub-range—returns <see cref="Empty"/> when none.
        /// </summary>
        public DateRange Intersection(DateRange other)
        {
            if (!Overlaps(other))
                return Empty;

            var start = Start > other.Start ? Start : other.Start;
            var end   = End   < other.End   ? End   : other.End;

            return new DateRange(start, end);
        }

        #endregion

        #region Public API – Mutations (return new instances)

        /// <summary>
        /// Shifts the range by the supplied duration.  
        /// Positive to move forward in time, negative to move back.
        /// </summary>
        public DateRange Shift(TimeSpan delta) =>
            new(Start.Add(delta), End.Add(delta));

        /// <summary>
        /// Extends the end of the range by the supplied duration.
        /// Duration can be negative; caller must ensure resulting range is valid.
        /// </summary>
        public DateRange ExtendEndBy(TimeSpan delta)
        {
            var newEnd = End.Add(delta);
            if (newEnd < Start)
                throw new ArgumentException("Resulting end would precede start of range.");

            return new DateRange(Start, newEnd);
        }

        /// <summary>
        /// Attempts to merge two ranges when they overlap or are adjacent.
        /// </summary>
        /// <exception cref="InvalidOperationException">
        /// Thrown when the ranges are disjoint.
        /// </exception>
        public DateRange Merge(DateRange other)
        {
            if (!Overlaps(other) && !IsAdjacentTo(other))
                throw new InvalidOperationException("Cannot merge non-overlapping, non-adjacent ranges.");

            var start = Start < other.Start ? Start : other.Start;
            var end   = End   > other.End   ? End   : other.End;
            return new DateRange(start, end);
        }

        #endregion

        #region IEnumerable<DateTimeOffset>

        /// <summary>
        /// Enumerates each day (midnight UTC) inside the range.
        /// This is useful for game mechanics such as daily cash-flow rolls.
        /// </summary>
        public IEnumerator<DateTimeOffset> GetEnumerator()
        {
            var current = Start.Date;
            var endDate = End.Date;
            while (current <= endDate)
            {
                yield return current;
                current = current.AddDays(1);
            }
        }

        IEnumerator IEnumerable.GetEnumerator() => GetEnumerator();

        #endregion

        #region Equality & Comparison

        public bool Equals(DateRange? other)
        {
            if (ReferenceEquals(null, other)) return false;
            if (ReferenceEquals(this, other)) return true;
            return Start.Equals(other.Start) && End.Equals(other.End);
        }

        public override bool Equals(object? obj) => Equals(obj as DateRange);

        public override int GetHashCode() => HashCode.Combine(Start, End);

        public static bool operator ==(DateRange? left, DateRange? right) =>
            Equals(left, right);

        public static bool operator !=(DateRange? left, DateRange? right) =>
            !Equals(left, right);

        /// <summary>
        /// Sorts by Start ascending, then by End ascending.
        /// </summary>
        public int CompareTo(DateRange? other)
        {
            if (other is null) return 1;
            var startCompare = Start.CompareTo(other.Start);
            return startCompare != 0 ? startCompare : End.CompareTo(other.End);
        }

        #endregion

        #region Overrides

        public override string ToString() => 
            $"{Start.ToString("o", CultureInfo.InvariantCulture)}/{End.ToString("o", CultureInfo.InvariantCulture)}";

        #endregion
    }
}
```