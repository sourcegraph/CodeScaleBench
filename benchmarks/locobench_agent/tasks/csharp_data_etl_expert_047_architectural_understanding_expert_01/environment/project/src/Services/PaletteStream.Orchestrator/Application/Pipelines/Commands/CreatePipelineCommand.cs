```csharp
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using FluentValidation;
using MediatR;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Orchestrator.Application.Pipelines.Commands
{
    /// <summary>
    /// Command used to create a new ETL pipeline inside the PaletteStream Orchestrator.
    /// </summary>
    /// <remarks>
    /// The command follows the CQRS + Mediator pattern.  Validation is performed via
    /// <see cref="CreatePipelineCommandValidator"/> before the handler executes.
    /// </remarks>
    public sealed class CreatePipelineCommand : IRequest<Guid>
    {
        public CreatePipelineCommand(
            string name,
            string? description,
            IReadOnlyCollection<PipelineStageDefinition> stages,
            PipelineRuntimeOptions runtimeOptions,
            string createdBy)
        {
            Name           = name;
            Description    = description;
            Stages         = stages;
            RuntimeOptions = runtimeOptions;
            CreatedBy      = createdBy;
        }

        /// <summary>Human-readable, unique name of the pipeline.</summary>
        public string Name { get; }

        /// <summary>Optional description shown in the PaletteStream UI.</summary>
        public string? Description { get; }

        /// <summary>Ordered collection of stage definitions describing the pipeline.</summary>
        public IReadOnlyCollection<PipelineStageDefinition> Stages { get; }

        /// <summary>Fine-grained runtime options (parallelism, monitoring toggles, etc.).</summary>
        public PipelineRuntimeOptions RuntimeOptions { get; }

        /// <summary>Audit information – the user/service that initiated creation.</summary>
        public string CreatedBy { get; }
    }

    /// <summary>
    /// Validator for <see cref="CreatePipelineCommand"/>.
    /// Performs lightweight, synchronous checks prior to the handler executing.
    /// Heavy or expensive validations should be moved to the handler itself.
    /// </summary>
    internal sealed class CreatePipelineCommandValidator : AbstractValidator<CreatePipelineCommand>
    {
        private const int MaxPipelineNameLength = 128;

        public CreatePipelineCommandValidator()
        {
            RuleFor(c => c.Name)
                .NotEmpty()
                .MaximumLength(MaxPipelineNameLength);

            RuleFor(c => c.Stages)
                .NotEmpty()
                .Must(stages => stages.Select(s => s.Order).Distinct().Count() == stages.Count)
                .WithMessage("Stage order indexes must be unique.");

            RuleFor(c => c.CreatedBy)
                .NotEmpty();
        }
    }

    /// <summary>
    /// Handler implementation responsible for persisting the pipeline to the backing store
    /// and emitting relevant domain events.
    /// </summary>
    internal sealed class CreatePipelineCommandHandler : IRequestHandler<CreatePipelineCommand, Guid>
    {
        private readonly IPipelineRepository     _repository;
        private readonly IUnitOfWork             _uow;
        private readonly ILogger                 _logger;
        private readonly IValidator<CreatePipelineCommand> _validator;

        public CreatePipelineCommandHandler(
            IPipelineRepository                 repository,
            IUnitOfWork                         uow,
            ILogger<CreatePipelineCommandHandler> logger,
            IValidator<CreatePipelineCommand>   validator)
        {
            _repository = repository  ?? throw new ArgumentNullException(nameof(repository));
            _uow        = uow         ?? throw new ArgumentNullException(nameof(uow));
            _logger     = logger      ?? throw new ArgumentNullException(nameof(logger));
            _validator  = validator   ?? throw new ArgumentNullException(nameof(validator));
        }

        public async Task<Guid> Handle(CreatePipelineCommand request, CancellationToken ct)
        {
            // 1.  Validate request (sync). Flows through FluentValidation.
            var validationResult = _validator.Validate(request);
            if (!validationResult.IsValid)
            {
                throw new ValidationException(validationResult.Errors);
            }

            // 2.  Guard: ensure a pipeline with the same name doesn't already exist.
            if (await _repository.ExistsAsync(request.Name, ct))
            {
                throw new DuplicatePipelineException(request.Name);
            }

            // 3.  Build domain aggregate using factory method.
            var pipeline = Pipeline.Create(
                name:            request.Name,
                description:     request.Description,
                createdBy:       request.CreatedBy,
                stageDefinitions: request.Stages,
                runtimeOptions:  request.RuntimeOptions);

            // 4.  Persist aggregate & commit UoW.
            await _repository.AddAsync(pipeline, ct);
            await _uow.CommitAsync(ct);

            _logger.LogInformation(
                "Created new pipeline '{PipelineName}' (ID: {PipelineId}) with {StageCount} stages.",
                pipeline.Name,
                pipeline.Id,
                pipeline.Stages.Count);

            // 5.  Return generated pipeline ID.
            return pipeline.Id;
        }
    }

    #region Domain-Specific Value Objects / Entities (simplified)

    /// <summary>
    /// Definition used when creating / updating pipeline stages from the API/UI layer.
    /// </summary>
    public sealed record PipelineStageDefinition(
        int Order,
        StageType Type,
        string ProcessorName,
        IDictionary<string, string> Parameters);

    /// <summary>
    /// Runtime options that influence how the orchestrator schedules and monitors the pipeline run.
    /// </summary>
    public sealed record PipelineRuntimeOptions(
        bool RunInParallel,
        int DegreeOfParallelism,
        bool EnableMonitoring,
        bool EnableDataQualityChecks);

    /// <summary>
    /// ETL stage semantic (Extract, Transform, Load).  Can be expanded for intra-step decoration.
    /// </summary>
    public enum StageType
    {
        Extract = 1,
        Transform,
        Load
    }

    /// <summary>
    /// Domain aggregate representing an ETL pipeline.
    /// Simplified for brevity; in production this would live in the Domain project.
    /// </summary>
    public sealed class Pipeline
    {
        private readonly List<PipelineStage> _stages = new();

        private Pipeline() { } // EF Core / serialization ctor

        public Guid   Id          { get; private set; }
        public string Name        { get; private set; } = null!;
        public string? Description{ get; private set; }
        public string CreatedBy   { get; private set; } = null!;
        public DateTime CreatedUtc{ get; private set; }
        public IReadOnlyCollection<PipelineStage> Stages => _stages.AsReadOnly();
        public PipelineRuntimeOptions RuntimeOptions { get; private set; } = null!;

        public static Pipeline Create(
            string name,
            string? description,
            string createdBy,
            IReadOnlyCollection<PipelineStageDefinition> stageDefinitions,
            PipelineRuntimeOptions runtimeOptions)
        {
            var pipeline = new Pipeline
            {
                Id          = Guid.NewGuid(),
                Name        = name,
                Description = description,
                CreatedBy   = createdBy,
                CreatedUtc  = DateTime.UtcNow,
                RuntimeOptions = runtimeOptions
            };

            foreach (var def in stageDefinitions.OrderBy(s => s.Order))
            {
                pipeline._stages.Add(new PipelineStage(
                    def.Order,
                    def.Type,
                    def.ProcessorName,
                    def.Parameters));
            }

            // Domain event example (omitted in this condensed sample)
            // pipeline.AddDomainEvent(new PipelineCreatedDomainEvent(pipeline));

            return pipeline;
        }
    }

    /// <summary>
    /// Child entity representing an individual stage in a pipeline.
    /// </summary>
    public sealed class PipelineStage
    {
        public PipelineStage(
            int order,
            StageType type,
            string processorName,
            IDictionary<string, string> parameters)
        {
            Order         = order;
            Type          = type;
            ProcessorName = processorName;
            Parameters    = parameters;
        }

        public int Order      { get; }
        public StageType Type { get; }
        public string ProcessorName { get; }
        public IDictionary<string, string> Parameters { get; }
    }

    #endregion

    #region Infrastructure Contracts (interfaces only; real impls live elsewhere)

    /// <summary>
    /// Repository abstraction for read/write operations on <see cref="Pipeline"/> aggregates.
    /// </summary>
    public interface IPipelineRepository
    {
        Task<bool> ExistsAsync(string uniqueName, CancellationToken ct);
        Task AddAsync(Pipeline pipeline, CancellationToken ct);
    }

    /// <summary>
    /// Unit-of-Work abstraction for committing multiple repository changes in a single transaction.
    /// </summary>
    public interface IUnitOfWork
    {
        Task CommitAsync(CancellationToken ct);
    }

    #endregion

    #region Custom Exceptions

    /// <summary>
    /// Thrown when attempting to create a pipeline that already exists.
    /// </summary>
    public sealed class DuplicatePipelineException : Exception
    {
        public DuplicatePipelineException(string name)
            : base($"A pipeline with the name '{name}' already exists.")
        { }
    }

    #endregion
}
```