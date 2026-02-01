using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using PaletteStream.Quality.Abstractions;  // Presumed location of IDataQualityCheck & CheckResult contracts

namespace PaletteStream.Quality.Checks.Implementations;

/// <summary>
/// Quality-check that verifies the configured fields are neither <c>null</c> nor, in the case of strings, empty/whitespace.
/// </summary>
/// <remarks>
/// • Works with any POCO/DTO type by using reflection (cached per validation run).<br/>
/// • Executes in parallel to keep large dataset validations fast.<br/>
/// • Completely cancels and re-throws on <see cref="OperationCanceledException"/> to respect pipeline back-pressure.
/// </remarks>
public sealed class NotNullCheck : IDataQualityCheck
{
    private readonly IReadOnlyCollection<string> _fieldNames;
    private readonly ILogger<NotNullCheck> _logger;

    public NotNullCheck(IEnumerable<string> fieldNames, ILogger<NotNullCheck> logger)
    {
        if (fieldNames == null) throw new ArgumentNullException(nameof(fieldNames));

        _fieldNames = fieldNames.Select(f => f?.Trim())
                                .Where(f => !string.IsNullOrWhiteSpace(f))
                                .Distinct(StringComparer.OrdinalIgnoreCase)
                                .ToArray();

        if (_fieldNames.Count == 0)
            throw new ArgumentException("At least one non-empty field name must be supplied.", nameof(fieldNames));

        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    /// <inheritdoc />
    public string Name => $"NOT_NULL[{string.Join(",", _fieldNames)}]";

    /// <inheritdoc />
    public async Task<CheckResult> ValidateAsync<T>(IEnumerable<T> data, CancellationToken cancellationToken = default)
        where T : class
    {
        if (data == null) throw new ArgumentNullException(nameof(data));

        var materialized = data as IList<T> ?? data.ToList();
        if (materialized.Count == 0)
        {
            _logger.LogDebug("Data set passed to {CheckName} is empty — nothing to validate.", Name);
            return CheckResult.Pass(Name, "Data set empty.");
        }

        // Cache the properties once per run to avoid repeated reflection calls.
        Dictionary<string, PropertyInfo> propertyCache = BuildPropertyCache<T>();

        // Concurrent collection to store failures.
        var failedRows = new List<(int Index, T Row)>();

        try
        {
            await Task.Run(() =>
            {
                ParallelOptions options = new()
                {
                    CancellationToken = cancellationToken,
                    MaxDegreeOfParallelism = Environment.ProcessorCount
                };

                int rowIndex = -1;

                Parallel.ForEach(materialized, options, (row, _, _) =>
                {
                    int currentIndex = Interlocked.Increment(ref rowIndex);

                    foreach (string field in _fieldNames)
                    {
                        if (!propertyCache.TryGetValue(field, out PropertyInfo? prop))
                        {
                            // Configuration error: field does not exist on the object.
                            lock (failedRows)
                            {
                                failedRows.Add((currentIndex, row));
                            }

                            _logger.LogError("Configuration error: Field '{Field}' not found on type '{Type}'.",
                                             field, typeof(T).FullName);
                            break;
                        }

                        object? value = prop.GetValue(row);

                        if (value is null ||
                            (value is string str && string.IsNullOrWhiteSpace(str)))
                        {
                            lock (failedRows)
                            {
                                failedRows.Add((currentIndex, row));
                            }
                            break; // No need to check the remaining fields for this row.
                        }
                    }
                });
            }, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            _logger.LogWarning("Validation for {CheckName} canceled.", Name);
            throw;
        }

        if (failedRows.Count == 0)
        {
            _logger.LogInformation("{CheckName} passed: all {RowCount} rows valid.", Name, materialized.Count);
            return CheckResult.Pass(Name, $"{materialized.Count} rows validated successfully.");
        }

        _logger.LogWarning("{CheckName} failed: {Failed} of {Total} rows contain null/empty values.",
                           Name, failedRows.Count, materialized.Count);

        // If the consumer wants just the data, not the indices, project accordingly.
        return CheckResult.Fail(Name,
                                $"{failedRows.Count} rows failed NOT NULL validation.",
                                failedRows.Select(f => (object)f.Row).ToList());
    }

    // ---------------------------------------------------------------------
    // Private helpers
    // ---------------------------------------------------------------------

    private Dictionary<string, PropertyInfo> BuildPropertyCache<T>() where T : class
    {
        BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.IgnoreCase;
        PropertyInfo[] props = typeof(T).GetProperties(flags);

        return props
              .Where(p => _fieldNames.Contains(p.Name, StringComparer.OrdinalIgnoreCase))
              .ToDictionary(p => p.Name, p => p, StringComparer.OrdinalIgnoreCase);
    }
}