```csharp
// File: CanvasCraftMLStudio/src/CanvasCraft.Api/DTOs/PipelineRequest.cs

using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;
using System.Linq;
using System.Text.Json.Serialization;
using CanvasCraft.Domain.Commands; // Domain-layer command (CQRS) – referenced by mapper below.

namespace CanvasCraft.Api.DTOs
{
    /// <summary>
    ///     Transport object representing a request to execute an ML pipeline.
    ///     The DTO is intentionally expressive so creative practitioners can specify
    ///     everything from a quick exploratory run to a scheduled retraining job.
    /// </summary>
    public sealed class PipelineRequest : IValidatableObject
    {
        /// <summary>
        ///     Friendly name for the experiment.  Required.
        /// </summary>
        [Required, MaxLength(160), RegularExpression(@"^[a-zA-Z0-9\-\_\s]+$")]
        public string ExperimentName { get; init; } = string.Empty;

        /// <summary>
        ///     Version of the canvas/model this pipeline should start from.
        ///     When null a completely new model lineage is created.
        /// </summary>
        public Guid? BaseModelVersionId { get; init; }

        /// <summary>
        ///     The high-level intent of the run.
        /// </summary>
        [JsonConverter(typeof(JsonStringEnumConverter))]
        public PipelineAction Action { get; init; } = PipelineAction.Train;

        /// <summary>
        ///     Custom key/value parameters that are forwarded to the strategy factory
        ///     (e.g. learning-rate, augmentation-strength, brush = "impressionist").
        /// </summary>
        public IReadOnlyDictionary<string, string> Parameters { get; init; } =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        /// <summary>
        ///     Arbitrary tags for later filtering in the experiment gallery.
        /// </summary>
        public IReadOnlyCollection<string>? Tags { get; init; }

        /// <summary>
        ///     Schedules the run for a future time (UTC).  If null the job is executed immediately.
        /// </summary>
        public DateTimeOffset? ScheduledAtUtc { get; init; }

        /// <summary>
        ///     When set the pipeline will stop at the planning stage and return a full DAG preview
        ///     without allocating expensive compute resources.
        /// </summary>
        public bool DryRun { get; init; }

        /// <summary>
        ///     Converts this DTO into a domain-level command understood by the application layer.
        ///     Throws <see cref="ValidationException" /> when the DTO is invalid.
        /// </summary>
        public LaunchPipelineCommand ToCommand(Guid requestedBy)
        {
            // Perform validation before we translate.
            var validationResults = new List<ValidationResult>();
            if (!Validator.TryValidateObject(this, new ValidationContext(this), validationResults, true))
            {
                throw new ValidationException(
                    $"PipelineRequest is invalid: {string.Join("; ", validationResults.Select(r => r.ErrorMessage))}");
            }

            return new LaunchPipelineCommand(
                experimentName: ExperimentName.Trim(),
                action: Action,
                parameters: Parameters?.ToDictionary(kvp => kvp.Key, kvp => kvp.Value, StringComparer.OrdinalIgnoreCase)
                            ?? new Dictionary<string, string>(),
                baseModelVersionId: BaseModelVersionId,
                tags: Tags?.Where(t => !string.IsNullOrWhiteSpace(t))
                           .Select(t => t.Trim())
                           .Distinct(StringComparer.OrdinalIgnoreCase)
                           .ToArray(),
                scheduledAtUtc: ScheduledAtUtc,
                dryRun: DryRun,
                requestedBy: requestedBy);
        }

        /// <summary>
        ///     Custom, cross-field validation rules.
        /// </summary>
        public IEnumerable<ValidationResult> Validate(ValidationContext validationContext)
        {
            // Dry-run cannot be scheduled in the future (makes no semantic sense).
            if (DryRun && ScheduledAtUtc.HasValue)
            {
                yield return new ValidationResult(
                    $"A dry-run cannot be scheduled. Remove {nameof(ScheduledAtUtc)} or set {nameof(DryRun)} to false.",
                    new[] { nameof(DryRun), nameof(ScheduledAtUtc) });
            }

            // Scheduled time must be in the future & not "now".
            if (ScheduledAtUtc.HasValue && ScheduledAtUtc.Value <= DateTimeOffset.UtcNow.AddSeconds(5))
            {
                yield return new ValidationResult(
                    $"Scheduled time must be at least 5 seconds in the future.",
                    new[] { nameof(ScheduledAtUtc) });
            }

            // Parameter keys must be unique (case-insensitive) – enforced at construction as IReadOnlyDictionary
            // but re-validate for defensive programming.
            if (Parameters != null && Parameters.Keys.Count != Parameters.Keys.Distinct(StringComparer.OrdinalIgnoreCase).Count())
            {
                yield return new ValidationResult(
                    $"Duplicate parameter keys detected.",
                    new[] { nameof(Parameters) });
            }
        }
    }

    /// <summary>
    ///     Permissible high-level actions when launching a pipeline.
    /// </summary>
    public enum PipelineAction
    {
        Train,
        Retrain,
        Evaluate,
        Serve
    }
}
```
