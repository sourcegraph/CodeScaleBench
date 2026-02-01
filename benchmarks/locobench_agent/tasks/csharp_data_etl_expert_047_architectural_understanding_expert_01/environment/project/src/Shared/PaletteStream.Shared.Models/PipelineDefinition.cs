```csharp
using System;
using System.Collections.Generic;
using System.Collections.Immutable;
using System.ComponentModel.DataAnnotations;
using System.Diagnostics.CodeAnalysis;
using System.Linq;
using System.Text.Json.Serialization;

namespace PaletteStream.Shared.Models
{
    /// <summary>
    /// A serialisable, self-contained definition of an ETL pipeline.
    /// Instances of this type are stored in configuration stores (e.g. Cosmos DB, Consul, Git),
    /// distributed to worker nodes, and interpreted by the execution engine.
    /// </summary>
    public sealed class PipelineDefinition
    {
        private const int MaxNameLength = 250;

        #region Ctor

        /// <summary>
        /// Creates a new, empty <see cref="PipelineDefinition"/>.
        /// </summary>
        [JsonConstructor]
        public PipelineDefinition(
            Guid id,
            string name,
            string? description,
            IEnumerable<PipelineStep> steps,
            string? schedule,
            bool enabled,
            DateTimeOffset createdOn,
            DateTimeOffset? updatedOn,
            int version,
            IEnumerable<string>? tags = null)
        {
            Id          = id == Guid.Empty ? Guid.NewGuid() : id;
            Name        = name.Trim();
            Description = description?.Trim();
            Steps       = steps.ToImmutableArray();
            Schedule    = schedule;
            Enabled     = enabled;
            CreatedOn   = createdOn == default ? DateTimeOffset.UtcNow : createdOn;
            UpdatedOn   = updatedOn;
            Version     = version < 1 ? 1 : version;
            Tags        = tags?.Select(t => t.Trim())
                               .Where(t => t.Length > 0)
                               .ToImmutableSortedSet(StringComparer.OrdinalIgnoreCase)
                         ?? ImmutableSortedSet<string>.Empty;

            // Run lightweight validation on construction.
            var validationErrors = Validate().ToArray();
            if (validationErrors.Length != 0)
            {
                throw new ValidationException(
                    $"PipelineDefinition '{Name}' is invalid. " +
                    $"Errors: {string.Join("; ", validationErrors.Select(e => e.ErrorMessage))}");
            }
        }

        /// <summary>
        /// Creates a new <see cref="PipelineDefinition"/> with a generated Id.
        /// </summary>
        public PipelineDefinition(string name, IEnumerable<PipelineStep> steps)
            : this(Guid.NewGuid(), name, null, steps, schedule: null, enabled: true,
                   createdOn: DateTimeOffset.UtcNow, updatedOn: null, version: 1)
        { }

        #endregion

        #region Public Properties

        /// <summary>
        /// Technical identifier of the pipeline. Immutable.
        /// </summary>
        public Guid Id { get; }

        /// <summary>
        /// Human-readable pipeline name.
        /// </summary>
        [MaxLength(MaxNameLength)]
        public string Name { get; }

        /// <summary>
        /// Short, optional description that appears in the Studio UI.
        /// </summary>
        public string? Description { get; }

        /// <summary>
        /// Ordered collection of transformation steps that make up the pipeline.
        /// </summary>
        public ImmutableArray<PipelineStep> Steps { get; }

        /// <summary>
        /// Cron expression (in UTC) indicating when the pipeline should be executed.
        /// Null/empty means manual or event-driven execution.
        /// </summary>
        public string? Schedule { get; }

        /// <summary>
        /// Whether the pipeline is currently enabled for execution.
        /// </summary>
        public bool Enabled { get; }

        /// <summary>
        /// Tags allow users to search and filter pipelines in the UI.
        /// </summary>
        public ImmutableSortedSet<string> Tags { get; }

        /// <summary>
        /// Creation timestamp.
        /// </summary>
        public DateTimeOffset CreatedOn { get; }

        /// <summary>
        /// Last modification timestamp.
        /// </summary>
        public DateTimeOffset? UpdatedOn { get; }

        /// <summary>
        /// Semantic version. Major/minor/patch are not enforced—clients
        /// can adopt their own semantics. Default is 1.
        /// </summary>
        public int Version { get; }

        #endregion

        #region Public API

        /// <summary>
        /// Validates the pipeline definition producing a collection of <see cref="ValidationResult"/>.
        /// The definition is considered valid when the returned collection is empty.
        /// </summary>
        public IEnumerable<ValidationResult> Validate()
        {
            // 1. Name present & length.
            if (string.IsNullOrWhiteSpace(Name))
                yield return new ValidationResult("Pipeline name is required.", new[] { nameof(Name) });

            if (Name.Length > MaxNameLength)
                yield return new ValidationResult($"Pipeline name must not exceed {MaxNameLength} characters.",
                                                  new[] { nameof(Name) });

            // 2. Steps exist.
            if (Steps.Length == 0)
                yield return new ValidationResult("At least one pipeline step must be defined.", new[] { nameof(Steps) });

            // 3. Duplicate step ids.
            var dupes = Steps.GroupBy(s => s.Id, StringComparer.Ordinal)
                             .Where(g => g.Count() > 1)
                             .Select(g => g.Key)
                             .ToArray();
            if (dupes.Length > 0)
                yield return new ValidationResult($"Duplicate step identifiers detected: {string.Join(", ", dupes)}",
                                                  new[] { nameof(Steps) });

            // 4. Validate each step.
            foreach (var step in Steps)
            {
                foreach (var result in step.Validate())
                    yield return result;
            }

            // 5. Dependency graph validation (cycles & missing deps).
            foreach (var result in ValidateGraph())
                yield return result;
        }

        /// <summary>
        /// Returns the pipeline steps sorted in a topological order such that
        /// each step appears after all of its dependencies.
        /// </summary>
        /// <exception cref="InvalidOperationException">
        /// Thrown when the dependency graph is cyclic and cannot be sorted.
        /// </exception>
        public IReadOnlyList<PipelineStep> GetExecutionOrder()
        {
            var sorted = new List<PipelineStep>(Steps.Length);
            var visited = new Dictionary<string, VisitState>(Steps.Length, StringComparer.Ordinal);

            foreach (var step in Steps)
            {
                if (!visited.ContainsKey(step.Id))
                    TopologicalSort(step, visited, sorted);
            }

            return sorted;
        }

        /// <summary>
        /// Returns a copy of the current definition with <see cref="Version"/> incremented by one
        /// and <see cref="UpdatedOn"/> set to <see cref="DateTimeOffset.UtcNow"/>.
        /// </summary>
        public PipelineDefinition NextVersion([StringSyntax(StringSyntaxAttribute.DateTimeFormat)] string? reason = null)
        {
            // Shallow copy is sufficient—steps are immutable.
            return new PipelineDefinition(
                id: Id,
                name: Name,
                description: reason ?? Description,
                steps: Steps,
                schedule: Schedule,
                enabled: Enabled,
                createdOn: CreatedOn,
                updatedOn: DateTimeOffset.UtcNow,
                version: Version + 1,
                tags: Tags);
        }

        #endregion

        #region Private Helpers

        private IEnumerable<ValidationResult> ValidateGraph()
        {
            var map = Steps.ToDictionary(s => s.Id, StringComparer.Ordinal);

            // Check that all declared dependencies exist.
            var missingDeps = Steps
                .SelectMany(s => s.DependsOn, (s, dep) => (Step: s, Dep: dep))
                .Where(t => !map.ContainsKey(t.Dep))
                .ToArray();

            if (missingDeps.Length != 0)
            {
                foreach (var (step, dep) in missingDeps)
                {
                    yield return new ValidationResult(
                        $"Step '{step.Id}' depends on missing step '{dep}'.",
                        new[] { nameof(Steps) });
                }
                yield break; // No point in cycle detection with missing deps.
            }

            // Detect cycles.
            var visited = new Dictionary<string, VisitState>(Steps.Length, StringComparer.Ordinal);
            foreach (var step in Steps)
            {
                if (HasCycle(step))
                {
                    yield return new ValidationResult(
                        $"Cyclic dependency detected starting at step '{step.Id}'.",
                        new[] { nameof(Steps) });
                    break;
                }
            }

            bool HasCycle(PipelineStep node)
            {
                if (!visited.TryGetValue(node.Id, out var state))
                    state = VisitState.Unvisited;

                if (state == VisitState.Visiting) return true;
                if (state == VisitState.Visited)  return false;

                visited[node.Id] = VisitState.Visiting;
                foreach (var depId in node.DependsOn)
                {
                    if (HasCycle(map[depId])) return true;
                }
                visited[node.Id] = VisitState.Visited;
                return false;
            }
        }

        private static void TopologicalSort(
            PipelineStep current,
            IDictionary<string, VisitState> state,
            ICollection<PipelineStep> output)
        {
            if (state.TryGetValue(current.Id, out var visitState))
            {
                if (visitState == VisitState.Visiting)
                    throw new InvalidOperationException(
                        $"Cycle detected while sorting pipeline definition, step '{current.Id}'.");

                // Already processed.
                return;
            }

            state[current.Id] = VisitState.Visiting;

            foreach (var depId in current.DependsOn)
            {
                var depStep = output.FirstOrDefault(s => s.Id.Equals(depId, StringComparison.Ordinal))
                              ?? throw new InvalidOperationException(
                                  $"Dependency '{depId}' referenced by step '{current.Id}' was not found.");

                TopologicalSort(depStep, state, output);
            }

            state[current.Id] = VisitState.Visited;
            output.Add(current);
        }

        private enum VisitState
        {
            Unvisited,
            Visiting,
            Visited
        }

        #endregion
    }

    /// <summary>
    /// Describes an individual action within a <see cref="PipelineDefinition"/>.
    /// Steps are immutable value objects; any modification should create a new instance.
    /// </summary>
    public sealed record PipelineStep
    {
        /// <summary>
        /// Creates a new <see cref="PipelineStep"/>.
        /// </summary>
        /// <param name="id">
        /// Unique, deterministic identifier. Recommended: kebab-case without spaces.
        /// </param>
        /// <param name="operation">
        /// Canonical name of the transformation strategy (e.g. 'csv-to-parquet').
        /// Must be resolvable by the StrategyFactory at runtime.
        /// </param>
        /// <param name="dependsOn">
        /// Zero or more identifiers of steps that must complete successfully before
        /// this step can begin.
        /// </param>
        /// <param name="parameters">
        /// Arbitrary, serialisable configuration parameters passed to the transformer.
        /// Values are stored as strings to keep the model backend-agnostic.
        /// </param>
        /// <param name="retryPolicy">
        /// Optional, friendly name of a retry policy defined in the execution engine.
        /// </param>
        [JsonConstructor]
        public PipelineStep(
            string id,
            string operation,
            IEnumerable<string>? dependsOn     = null,
            IReadOnlyDictionary<string, string>? parameters = null,
            string? retryPolicy              = null,
            bool isIsolated                  = false)
        {
            if (string.IsNullOrWhiteSpace(id))
                throw new ArgumentException("Step Id is required.", nameof(id));

            if (string.IsNullOrWhiteSpace(operation))
                throw new ArgumentException("Operation is required.", nameof(operation));

            Id          = id.Trim();
            Operation   = operation.Trim();
            DependsOn   = dependsOn?.Select(d => d.Trim())
                                    .Where(d => d.Length > 0)
                                    .Distinct(StringComparer.Ordinal)
                                    .ToImmutableArray()
                          ?? ImmutableArray<string>.Empty;
            Parameters  = parameters != null
                            ? parameters.ToImmutableDictionary(StringComparer.OrdinalIgnoreCase)
                            : ImmutableDictionary<string, string>.Empty;
            RetryPolicy = retryPolicy;
            IsIsolated  = isIsolated;
        }

        /// <summary>
        /// Unique step identifier within the pipeline.
        /// </summary>
        public string Id { get; }

        /// <summary>
        /// Name of the transformer/strategy to invoke.
        /// </summary>
        public string Operation { get; }

        /// <summary>
        /// Optional collection of steps that must run before this step.
        /// Defines the edge set of the DAG.
        /// </summary>
        public ImmutableArray<string> DependsOn { get; }

        /// <summary>
        /// Key-value parameters forwarded to the transformer.
        /// </summary>
        public ImmutableDictionary<string, string> Parameters { get; }

        /// <summary>
        /// Name of the retry policy registered in the application container
        /// (e.g. 'exponential-backoff-3x'), or null to use the default policy.
        /// </summary>
        public string? RetryPolicy { get; }

        /// <summary>
        /// Indicates whether the step should run in a dedicated worker/process
        /// to avoid resource contention (e.g. GPU-bound stages).
        /// </summary>
        public bool IsIsolated { get; }

        /// <summary>
        /// Performs local validation of the step.
        /// </summary>
        internal IEnumerable<ValidationResult> Validate()
        {
            if (Id.IndexOf(' ') >= 0)
                yield return new ValidationResult($"Step Id '{Id}' must not contain spaces.", new[] { nameof(Id) });

            if (Operation.Length > 128)
                yield return new ValidationResult($"Operation name for step '{Id}' is too long.", new[] { nameof(Operation) });

            // Parameter keys must be non-empty.
            foreach (var (key, value) in Parameters)
            {
                if (string.IsNullOrWhiteSpace(key))
                    yield return new ValidationResult($"Parameter key in step '{Id}' cannot be empty.",
                                                      new[] { nameof(Parameters) });

                if (value is null)
                    yield return new ValidationResult($"Parameter '{key}' in step '{Id}' cannot be null.",
                                                      new[] { nameof(Parameters) });
            }
        }
    }
}
```