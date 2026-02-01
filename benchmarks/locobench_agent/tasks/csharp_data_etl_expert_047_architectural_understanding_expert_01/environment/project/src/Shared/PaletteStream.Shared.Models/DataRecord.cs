using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace PaletteStream.Shared.Models;

/// <summary>
/// Immutable, value-object representation of a single row flowing through the PaletteStream ETL pipeline.
/// Holds the raw payload alongside mandatory metadata used for lineage tracking, validation, and auditing.
/// </summary>
public sealed record DataRecord : IValidatableObject
{
    /// <summary>
    /// Unique, deterministic identifier for this record.
    /// This value is either supplied by the source system or computed from <see cref="Payload"/> using SHA-256.
    /// </summary>
    [JsonPropertyName("recordId")]
    public string RecordId { get; init; } = string.Empty;

    /// <summary>
    /// Arbitrary payload carried by the record. Always a JSON fragment.
    /// </summary>
    [JsonPropertyName("payload")]
    public JsonElement Payload { get; init; }

    /// <summary>
    /// Name of the system, topic, or file where the record originated from.
    /// </summary>
    [MaxLength(256)]
    [JsonPropertyName("source")]
    public string Source { get; init; } = "unknown";

    /// <summary>
    /// UTC instant when the record left the source system.
    /// </summary>
    [JsonPropertyName("sourceTimestampUtc")]
    public DateTimeOffset SourceTimestampUtc { get; init; }

    /// <summary>
    /// UTC instant when the record entered the PaletteStream platform.
    /// </summary>
    [JsonPropertyName("ingestionTimestampUtc")]
    public DateTimeOffset IngestionTimestampUtc { get; init; }

    /// <summary>
    /// Optional tag that groups correlated records together (e.g. Kafka partition key, TraceId).
    /// </summary>
    [MaxLength(128)]
    [JsonPropertyName("correlationId")]
    public string? CorrelationId { get; init; }

    /// <summary>
    /// Optional quality score added by validators. Range: 0 (bad) – 1 (excellent).
    /// </summary>
    [Range(0, 1)]
    [JsonPropertyName("qualityScore")]
    public decimal? QualityScore { get; init; }

    /// <summary>
    /// Free-form dictionary that may hold additional metadata added by transformers.
    /// </summary>
    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; init; }

    /// <summary>
    /// Version number for optimistic concurrency. Incremented whenever the record is mutated by a transformer.
    /// </summary>
    [JsonPropertyName("version")]
    public uint Version { get; init; } = 1;

    /// <summary>
    /// Flag indicating if the record has been logically deleted by a compensating transaction.
    /// </summary>
    [JsonPropertyName("isDeleted")]
    public bool IsDeleted { get; init; }

    #region Factory helpers

    /// <summary>
    /// Creates a new <see cref="DataRecord"/> from a raw JSON payload. A deterministic <see cref="RecordId"/> is generated using SHA-256.
    /// </summary>
    public static DataRecord Create(
        JsonElement payload,
        string? source = null,
        DateTimeOffset? sourceTimestampUtc = null,
        string? correlationId = null)
    {
        var now = DateTimeOffset.UtcNow;

        return new DataRecord
        {
            Payload = payload,
            RecordId = ComputeHash(payload),
            Source = source ?? "unknown",
            SourceTimestampUtc = sourceTimestampUtc ?? now,
            IngestionTimestampUtc = now,
            CorrelationId = correlationId
        };
    }

    /// <summary>
    /// Deserializes a record from JSON string.
    /// </summary>
    public static DataRecord FromJson(string json, JsonSerializerOptions? options = null) =>
        JsonSerializer.Deserialize<DataRecord>(json, options ?? JsonOptions) ??
        throw new InvalidOperationException("Failed to deserialize DataRecord.");

    /// <summary>
    /// Serializes this record to a JSON string.
    /// </summary>
    public string ToJson(JsonSerializerOptions? options = null) =>
        JsonSerializer.Serialize(this, options ?? JsonOptions);

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = false,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
    };

    #endregion

    #region Validation

    public IEnumerable<ValidationResult> Validate(ValidationContext validationContext)
    {
        if (string.IsNullOrWhiteSpace(RecordId))
            yield return new ValidationResult("RecordId cannot be null or whitespace.", new[] { nameof(RecordId) });

        if (SourceTimestampUtc > IngestionTimestampUtc)
            yield return new ValidationResult("SourceTimestampUtc cannot be greater than IngestionTimestampUtc.",
                new[] { nameof(SourceTimestampUtc), nameof(IngestionTimestampUtc) });

        if (QualityScore is < 0 or > 1)
            yield return new ValidationResult("QualityScore must be between 0 and 1.", new[] { nameof(QualityScore) });
    }

    #endregion

    #region Overrides

    /// <summary>
    /// Provides a concise debugging string.
    /// </summary>
    public override string ToString() =>
        $"[{SourceTimestampUtc:u}] {Source} | {RecordId} (v{Version})";

    #endregion

    #region Private helpers

    private static string ComputeHash(JsonElement payload)
    {
        var json = payload.GetRawText();
        using var sha = SHA256.Create();
        var bytes = sha.ComputeHash(Encoding.UTF8.GetBytes(json));
        return Convert.ToHexString(bytes);
    }

    #endregion
}