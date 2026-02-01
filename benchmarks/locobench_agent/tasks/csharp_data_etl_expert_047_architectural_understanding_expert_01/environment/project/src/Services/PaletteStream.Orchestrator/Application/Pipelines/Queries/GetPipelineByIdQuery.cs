```csharp
using System;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using MediatR;
using Microsoft.Extensions.Caching.Distributed;
using Microsoft.Extensions.Logging;

namespace PaletteStream.Orchestrator.Application.Pipelines.Queries
{
    /// <summary>
    /// Query object that requests a single Pipeline by its identifier.
    /// </summary>
    /// <param name="PipelineId">Unique identifier of the pipeline.</param>
    /// <param name="IncludeLatestStatus">
    /// Optional flag indicating whether the latest runtime status (e.g., last run state,
    /// error details) should be attached to the response.
    /// </param>
    public sealed record GetPipelineByIdQuery(Guid PipelineId, bool IncludeLatestStatus = false)
        : IRequest<OperationResult<PipelineDto>>;

    /// <summary>
    /// Handler that executes <see cref="GetPipelineByIdQuery"/>.
    /// </summary>
    public sealed class GetPipelineByIdQueryHandler
        : IRequestHandler<GetPipelineByIdQuery, OperationResult<PipelineDto>>
    {
        private const string CacheKeyTemplate = "pipelines:{0}:v2"; // v2 => bump when schema changes
        private readonly IPipelineRepository _repository;
        private readonly IRuntimeStatusProvider _statusProvider;
        private readonly IDistributedCache _cache;
        private readonly ILogger<GetPipelineByIdQueryHandler> _logger;

        public GetPipelineByIdQueryHandler(
            IPipelineRepository repository,
            IRuntimeStatusProvider statusProvider,
            IDistributedCache cache,
            ILogger<GetPipelineByIdQueryHandler> logger)
        {
            _repository = repository ?? throw new ArgumentNullException(nameof(repository));
            _statusProvider = statusProvider ?? throw new ArgumentNullException(nameof(statusProvider));
            _cache = cache ?? throw new ArgumentNullException(nameof(cache));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        public async Task<OperationResult<PipelineDto>> Handle(
            GetPipelineByIdQuery request,
            CancellationToken cancellationToken)
        {
            if (request.PipelineId == Guid.Empty)
            {
                return OperationResult<PipelineDto>.BadRequest("PipelineId must be a non-empty GUID.");
            }

            var cacheKey = string.Format(CacheKeyTemplate, request.PipelineId);
            var pipelineDto = await GetFromCacheAsync(cacheKey, cancellationToken);

            if (pipelineDto is null)
            {
                _logger.LogDebug("Cache miss for pipeline {PipelineId}. Fetching from repository.", request.PipelineId);
                var pipeline = await _repository.GetAsync(request.PipelineId, cancellationToken);

                if (pipeline is null)
                {
                    _logger.LogInformation("Pipeline {PipelineId} not found.", request.PipelineId);
                    return OperationResult<PipelineDto>.NotFound($"Pipeline '{request.PipelineId}' was not found.");
                }

                pipelineDto = PipelineDto.FromDomain(pipeline);

                // hydrate cache (fire & forget)
                _ = CacheAsync(cacheKey, pipelineDto, cancellationToken);
            }

            if (request.IncludeLatestStatus)
            {
                var status = await _statusProvider.GetLatestStatusAsync(
                    request.PipelineId,
                    cancellationToken);

                pipelineDto = pipelineDto with { LatestStatus = status };
            }

            return OperationResult<PipelineDto>.Ok(pipelineDto);
        }

        #region Private Helpers

        private async Task<PipelineDto?> GetFromCacheAsync(
            string cacheKey,
            CancellationToken cancellationToken)
        {
            try
            {
                var cachedBytes = await _cache.GetAsync(cacheKey, cancellationToken);
                return cachedBytes is null
                    ? null
                    : JsonSerializer.Deserialize<PipelineDto>(cachedBytes);
            }
            catch (Exception ex)
            {
                // Cache failures should never break the request flow
                _logger.LogWarning(ex, "Failed to retrieve pipeline from cache (key: {CacheKey}).", cacheKey);
                return null;
            }
        }

        private async Task CacheAsync(
            string cacheKey,
            PipelineDto dto,
            CancellationToken cancellationToken)
        {
            try
            {
                var options = new DistributedCacheEntryOptions
                {
                    SlidingExpiration = TimeSpan.FromMinutes(15),
                    AbsoluteExpirationRelativeToNow = TimeSpan.FromHours(6)
                };

                var bytes = JsonSerializer.SerializeToUtf8Bytes(dto);
                await _cache.SetAsync(cacheKey, bytes, options, cancellationToken);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to save pipeline to cache (key: {CacheKey}).", cacheKey);
            }
        }

        #endregion
    }

    #region Supporting Types

    /// <summary>
    /// Simplistic OperationResult implementation tailored for the orchestrator.
    /// In a real code base this would either live in a shared kernel or be replaced
    /// by a NuGet package such as CSharpFunctionalExtensions.Result.
    /// </summary>
    public readonly struct OperationResult<T>
    {
        private OperationResult(T? data, bool isSuccess, int statusCode, string? errorMessage)
        {
            Data = data;
            IsSuccess = isSuccess;
            StatusCode = statusCode;
            ErrorMessage = errorMessage;
        }

        public T? Data { get; }
        public bool IsSuccess { get; }
        public int StatusCode { get; }
        public string? ErrorMessage { get; }

        public static OperationResult<T> Ok(T data)
            => new(data, true, 200, null);

        public static OperationResult<T> NotFound(string message)
            => new(default, false, 404, message);

        public static OperationResult<T> BadRequest(string message)
            => new(default, false, 400, message);
    }

    /// <summary>
    /// Data-transfer object for returning pipelines via API / queries.
    /// </summary>
    public sealed record PipelineDto
    {
        public Guid Id { get; init; }
        public string Name { get; init; } = default!;
        public string? Description { get; init; }
        public DateTimeOffset CreatedOn { get; init; }
        public PipelineStatusDto? LatestStatus { get; init; }

        public static PipelineDto FromDomain(Pipeline pipeline)
            => new()
            {
                Id          = pipeline.Id,
                Name        = pipeline.Name,
                Description = pipeline.Description,
                CreatedOn   = pipeline.CreatedOn
            };
    }

    /// <summary>
    /// DTO describing the latest runtime status for a pipeline.
    /// </summary>
    public sealed record PipelineStatusDto
    {
        public string State { get; init; } = default!;
        public DateTimeOffset? StartedOn { get; init; }
        public DateTimeOffset? CompletedOn { get; init; }
        public string? Error { get; init; }
    }

    #endregion
}
```