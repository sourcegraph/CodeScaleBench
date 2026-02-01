```csharp
// File: CanvasCraftMLStudio/src/CanvasCraft.Pipeline/Steps/FeatureEngineering/OneHotEncodingPalette.cs

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using Microsoft.Data.Analysis;

namespace CanvasCraft.Pipeline.Steps.FeatureEngineering
{
    #region Contracts (minimal versions to keep file self-contained)

    /// <summary>
    /// A pipeline step that can take a DataFrame, mutate/augment it, and emit events.
    /// </summary>
    public interface IFeatureEngineeringPalette : IDisposable
    {
        /// <summary>Train the palette on the provided data.</summary>
        void Fit(DataFrame dataFrame);

        /// <summary>Transform the provided data and return a new <see cref="DataFrame"/> instance.</summary>
        DataFrame Transform(DataFrame dataFrame);

        /// <summary>Fit and transform in one step for convenience.</summary>
        DataFrame FitTransform(DataFrame dataFrame);

        /// <summary>Raised when new features are created.</summary>
        event EventHandler<FeatureEngineeredEventArgs>? FeatureEngineered;
    }

    /// <summary>Event payload for feature-engineering events.</summary>
    public sealed class FeatureEngineeredEventArgs : EventArgs
    {
        public FeatureEngineeredEventArgs(IReadOnlyCollection<string> featuresCreated)
            => FeaturesCreated = featuresCreated ?? Array.Empty<string>();

        public IReadOnlyCollection<string> FeaturesCreated { get; }
    }

    #endregion

    /// <summary>
    /// Palette that applies one-hot encoding to categorical columns.
    /// • Learns a category-to-index mapping during <see cref="Fit" />.
    /// • Adds boolean columns per category suffixed with “_{category}”.
    /// • Maintains thread-safe, immutable lookup structures post-fit.
    /// </summary>
    public sealed class OneHotEncodingPalette : IFeatureEngineeringPalette
    {
        private readonly HashSet<string> _categoricalColumns;
        private readonly ConcurrentDictionary<string, IReadOnlyList<string>> _categoryLookup;
        private readonly ReaderWriterLockSlim _rwLock = new(LockRecursionPolicy.NoRecursion);
        private bool _isFitted;

        /// <summary>
        /// Ctor
        /// </summary>
        /// <param name="categoricalColumns">Columns that require one-hot encoding.</param>
        public OneHotEncodingPalette(IEnumerable<string> categoricalColumns)
        {
            if (categoricalColumns is null)
                throw new ArgumentNullException(nameof(categoricalColumns));

            _categoricalColumns = new HashSet<string>(categoricalColumns);
            if (_categoricalColumns.Count == 0)
                throw new ArgumentException("At least one categorical column must be specified.", nameof(categoricalColumns));

            _categoryLookup = new ConcurrentDictionary<string, IReadOnlyList<string>>();
        }

        public event EventHandler<FeatureEngineeredEventArgs>? FeatureEngineered;

        #region Public API

        public void Fit(DataFrame dataFrame)
        {
            ValidateDataFrame(dataFrame);

            _rwLock.EnterWriteLock();
            try
            {
                foreach (var columnName in _categoricalColumns)
                {
                    var column = dataFrame.Columns[columnName];
                    var distinct = column!.Cast<string?>()
                                          .Where(v => v is not null)
                                          .Select(v => v!)
                                          .Distinct()
                                          .OrderBy(v => v, StringComparer.Ordinal)
                                          .ToArray();

                    _categoryLookup[columnName] = distinct;
                }

                _isFitted = true;
            }
            finally
            {
                _rwLock.ExitWriteLock();
            }
        }

        public DataFrame Transform(DataFrame dataFrame)
        {
            ValidateDataFrame(dataFrame);

            _rwLock.EnterReadLock();
            try
            {
                EnsureIsFitted();

                // Clone the original dataframe to avoid side-effects on upstream steps.
                var transformed = dataFrame.Clone();

                var createdFeatures = new List<string>();

                foreach (var (columnName, categories) in _categoryLookup)
                {
                    var originalColumn = dataFrame.Columns[columnName];

                    foreach (var category in categories)
                    {
                        var newColumnName = $"{columnName}_{SanitizeCategory(category)}";
                        var buffer = new bool[dataFrame.Rows.Count];

                        for (var i = 0; i < originalColumn.Length; i++)
                        {
                            buffer[i] = string.Equals(originalColumn[i]?.ToString(), category, StringComparison.Ordinal);
                        }

                        var boolColumn = new PrimitiveDataFrameColumn<bool>(newColumnName, buffer);
                        transformed.Columns.Add(boolColumn);

                        createdFeatures.Add(newColumnName);
                    }

                    // Optional: Drop original column
                    transformed.Columns.Remove(columnName);
                }

                OnFeatureEngineered(createdFeatures);

                return transformed;
            }
            finally
            {
                _rwLock.ExitReadLock();
            }
        }

        public DataFrame FitTransform(DataFrame dataFrame)
        {
            Fit(dataFrame);
            return Transform(dataFrame);
        }

        #endregion

        #region Helpers / Validation

        private void OnFeatureEngineered(IReadOnlyCollection<string> createdFeatures) =>
            FeatureEngineered?.Invoke(this, new FeatureEngineeredEventArgs(createdFeatures));

        private static string SanitizeCategory(string category)
        {
            // Replace unsafe chars with underscores for column naming
            var chars = category.Select(c => char.IsLetterOrDigit(c) ? c : '_').ToArray();
            return new string(chars);
        }

        private static void ValidateDataFrame(DataFrame? dataFrame)
        {
            if (dataFrame is null)
                throw new ArgumentNullException(nameof(dataFrame), "DataFrame cannot be null.");

            if (dataFrame.Rows.Count == 0)
                throw new ArgumentException("DataFrame contains no rows.", nameof(dataFrame));
        }

        private void EnsureIsFitted()
        {
            if (!_isFitted)
                throw new InvalidOperationException(
                    "Palette has not been fitted. Call Fit(...) or FitTransform(...) first.");
        }

        #endregion

        #region IDisposable

        private bool _disposed;

        public void Dispose()
        {
            if (_disposed) return;

            _rwLock.Dispose();
            _disposed = true;
            GC.SuppressFinalize(this);
        }

        #endregion
    }
}
```