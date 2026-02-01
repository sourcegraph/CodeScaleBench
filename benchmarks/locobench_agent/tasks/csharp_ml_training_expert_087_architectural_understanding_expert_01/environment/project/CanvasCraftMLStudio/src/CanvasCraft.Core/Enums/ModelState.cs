using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Serialization;

namespace CanvasCraft.Core.Enums
{
    /// <summary>
    ///     Represents the canonical life-cycle states a model can occupy within
    ///     CanvasCraft ML Studio.  
    ///     Numeric values are intentionally spaced to preserve backward-compatibility
    ///     and permit future insertions without breaking serialized data contracts.
    /// </summary>
    [JsonConverter(typeof(JsonStringEnumConverter))]
    public enum ModelState : byte
    {
        /// <summary>
        /// The model is merely a concept: metadata exists, but no training has begun.
        /// </summary>
        Draft = 0,

        /// <summary>
        /// The model is actively training (including preprocessing &amp; feature engineering).
        /// </summary>
        Training = 10,

        /// <summary>
        /// The model finished training and produced at least one checkpoint.
        /// </summary>
        Trained = 20,

        /// <summary>
        /// The model is being validated/evaluated against a hold-out dataset.
        /// </summary>
        Validating = 30,

        /// <summary>
        /// The model passed validation criteria and is eligible for deployment.
        /// </summary>
        Validated = 40,

        /// <summary>
        /// The model is live and serving predictions to end-users.
        /// </summary>
        Deployed = 50,

        /// <summary>
        /// The model is no longer in active use but retained for audit or rollback.
        /// </summary>
        Retired = 60,

        /// <summary>
        /// The model encountered an unrecoverable error during its life-cycle.
        /// </summary>
        Failed = 250,

        /// <summary>
        /// The model and its artifacts are frozen; no further changes are allowed.
        /// </summary>
        Archived = 255
    }

    /// <summary>
    ///     Domain helpers for <see cref="ModelState"/> that embed 
    ///     life-cycle transition rules and utility methods.
    /// </summary>
    public static class ModelStateExtensions
    {
        // Internal state transition map (source → valid targets)
        private static readonly IReadOnlyDictionary<ModelState, ModelState[]> ValidTransitions =
            new Dictionary<ModelState, ModelState[]>
            {
                [ModelState.Draft]      = new[] { ModelState.Training, ModelState.Archived },
                [ModelState.Training]   = new[] { ModelState.Trained,  ModelState.Failed   },
                [ModelState.Trained]    = new[] { ModelState.Validating, ModelState.Retired },
                [ModelState.Validating] = new[] { ModelState.Validated, ModelState.Failed   },
                [ModelState.Validated]  = new[] { ModelState.Deployed,  ModelState.Retired  },
                [ModelState.Deployed]   = new[] { ModelState.Retired,   ModelState.Failed   },
                [ModelState.Retired]    = new[] { ModelState.Archived },
                [ModelState.Failed]     = new[] { ModelState.Draft,     ModelState.Archived },
                [ModelState.Archived]   = Array.Empty<ModelState>()
            };

        /// <summary>
        ///     Provides a human-readable string suitable for UI display.
        /// </summary>
        public static string ToDisplayString(this ModelState state) =>
            state switch
            {
                ModelState.Draft      => "Draft",
                ModelState.Training   => "Training",
                ModelState.Trained    => "Trained",
                ModelState.Validating => "Validating",
                ModelState.Validated  => "Validated",
                ModelState.Deployed   => "Deployed",
                ModelState.Retired    => "Retired",
                ModelState.Failed     => "Failed",
                ModelState.Archived   => "Archived",
                _                     => state.ToString()
            };

        /// <summary>
        ///     Indicates whether the state represents a blocking or long-running process.
        /// </summary>
        public static bool IsBusy(this ModelState state) =>
            state is ModelState.Training or ModelState.Validating;

        /// <summary>
        ///     Indicates whether the state is terminal (i.e., no further transitions allowed).
        /// </summary>
        public static bool IsTerminal(this ModelState state) =>
            state == ModelState.Archived;

        /// <summary>
        ///     Returns the set of states that can validly follow the provided state.
        /// </summary>
        public static IReadOnlyCollection<ModelState> GetNextCandidates(this ModelState state) =>
            ValidTransitions.TryGetValue(state, out var targets) ? targets : Array.Empty<ModelState>();

        /// <summary>
        ///     Ensures a transition from <paramref name="current"/> to <paramref name="requested"/> 
        ///     is allowed. Throws <see cref="InvalidOperationException"/> when illegal.
        /// </summary>
        /// <exception cref="InvalidOperationException">
        ///     Thrown if the transition violates the life-cycle rules.
        /// </exception>
        public static void EnsureCanTransitionTo(this ModelState current, ModelState requested)
        {
            if (current == requested) return; // idempotent; always allowed

            if (!ValidTransitions.TryGetValue(current, out var validTargets) ||
                !validTargets.Contains(requested))
            {
                throw new InvalidOperationException(
                    $"Illegal model state transition: {current.ToDisplayString()} → {requested.ToDisplayString()}.\n" +
                    "Refer to the CanvasCraft ML Studio documentation for permitted transitions.");
            }
        }
    }
}