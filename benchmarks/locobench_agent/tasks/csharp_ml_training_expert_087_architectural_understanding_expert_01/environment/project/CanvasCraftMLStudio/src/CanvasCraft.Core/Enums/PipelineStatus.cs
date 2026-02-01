using System;
using System.Collections.Generic;

namespace CanvasCraft.Core.Enums
{
    /// <summary>
    /// Enumerates the discrete runtime states of a CanvasCraft end-to-end MLOps pipeline execution.
    /// </summary>
    /// <remarks>
    /// The values are intentionally spaced to leave room for intermediary states
    /// should the pipeline evolve (e.g., support for additional lifecycle hooks).
    /// </remarks>
    public enum PipelineStatus
    {
        /// <summary>The pipeline instance has been defined but not yet persisted.</summary>
        NotCreated = 0,

        /// <summary>The run has been enqueued and is awaiting compute resources.</summary>
        Queued = 10,

        // ───── Data Lifecycle ──────────────────────────────────────────────────────
        DataIngesting    = 20,
        DataIngested     = 30,
        Preprocessing    = 40,
        Preprocessed     = 50,
        FeatureEngineering = 60,
        FeatureEngineered  = 70,

        // ───── Model Lifecycle ─────────────────────────────────────────────────────
        Training         = 80,
        Trained          = 90,

        Validating       = 100,
        Validated        = 110,

        Registering      = 120,
        Registered       = 130,

        Deploying        = 140,
        Deployed         = 150,

        // ───── Post-Deployment ─────────────────────────────────────────────────────
        Monitoring       = 160,

        // ───── Terminal States ─────────────────────────────────────────────────────
        Completed        = 1000,
        Failed           = 2000,
        Cancelled        = 3000
    }

    /// <summary>
    /// Extension helpers for <see cref="PipelineStatus"/> to simplify business logic
    /// and UI rendering across the solution.
    /// </summary>
    public static class PipelineStatusExtensions
    {
        private static readonly HashSet<PipelineStatus> TerminalStates = new()
        {
            PipelineStatus.Completed,
            PipelineStatus.Failed,
            PipelineStatus.Cancelled
        };

        private static readonly HashSet<PipelineStatus> DefinedStatuses =
            new((PipelineStatus[])Enum.GetValues(typeof(PipelineStatus)));

        /// <summary>
        /// Indicates whether the supplied status is a terminal state
        /// in which the pipeline will no longer progress.
        /// </summary>
        public static bool IsTerminal(this PipelineStatus status) =>
            TerminalStates.Contains(status);

        /// <summary>
        /// Indicates whether the pipeline is currently executing or queued.
        /// </summary>
        /// <exception cref="ArgumentOutOfRangeException">
        /// Thrown when <paramref name="status"/> is not a valid enum value.
        /// </exception>
        public static bool IsInProgress(this PipelineStatus status)
        {
            ValidateDefined(status);
            return status >= PipelineStatus.Queued && !TerminalStates.Contains(status);
        }

        /// <summary>
        /// Converts the enum value into a user-friendly display string
        /// suitable for dashboards and logs.
        /// </summary>
        public static string ToDisplayName(this PipelineStatus status)
        {
            return status switch
            {
                PipelineStatus.NotCreated        => "Not Created",
                PipelineStatus.Queued            => "Queued",
                PipelineStatus.DataIngesting     => "Data Ingesting",
                PipelineStatus.DataIngested      => "Data Ingested",
                PipelineStatus.Preprocessing     => "Preprocessing",
                PipelineStatus.Preprocessed      => "Preprocessed",
                PipelineStatus.FeatureEngineering=> "Feature Engineering",
                PipelineStatus.FeatureEngineered => "Feature Engineered",
                PipelineStatus.Training          => "Training",
                PipelineStatus.Trained           => "Trained",
                PipelineStatus.Validating        => "Validating",
                PipelineStatus.Validated         => "Validated",
                PipelineStatus.Registering       => "Registering",
                PipelineStatus.Registered        => "Registered",
                PipelineStatus.Deploying         => "Deploying",
                PipelineStatus.Deployed          => "Deployed",
                PipelineStatus.Monitoring        => "Monitoring",
                PipelineStatus.Completed         => "Completed",
                PipelineStatus.Failed            => "Failed",
                PipelineStatus.Cancelled         => "Cancelled",
                _                                => "Unknown"
            };
        }

        /// <summary>
        /// Parses a display name produced by <see cref="ToDisplayName"/> back into
        /// its corresponding <see cref="PipelineStatus"/> value.
        /// </summary>
        /// <exception cref="ArgumentException">
        /// Thrown when the display name cannot be mapped to a known <see cref="PipelineStatus"/>.
        /// </exception>
        public static PipelineStatus FromDisplayName(string displayName)
        {
            if (string.IsNullOrWhiteSpace(displayName))
            {
                throw new ArgumentException("Display name cannot be null or whitespace.", nameof(displayName));
            }

            foreach (var status in DefinedStatuses)
            {
                if (string.Equals(displayName, status.ToDisplayName(), StringComparison.OrdinalIgnoreCase))
                {
                    return status;
                }
            }

            throw new ArgumentException(
                $"'{displayName}' is not a valid display name for {nameof(PipelineStatus)}.",
                nameof(displayName));
        }

        /// <summary>
        /// Validates that the provided status is defined in the <see cref="PipelineStatus"/> enumeration.
        /// </summary>
        /// <exception cref="ArgumentOutOfRangeException">
        /// Thrown when <paramref name="status"/> is not a defined enum value.
        /// </exception>
        private static void ValidateDefined(PipelineStatus status)
        {
            if (!DefinedStatuses.Contains(status))
            {
                throw new ArgumentOutOfRangeException(
                    nameof(status),
                    status,
                    $"{status} is not a defined {nameof(PipelineStatus)} value.");
            }
        }
    }
}