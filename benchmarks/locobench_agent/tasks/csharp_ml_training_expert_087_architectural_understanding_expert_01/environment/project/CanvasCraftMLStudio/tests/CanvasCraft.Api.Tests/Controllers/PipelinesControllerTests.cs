```csharp
using System;
using System.Collections.Generic;
using System.Net;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Api.Controllers;
using CanvasCraft.Api.Models.Pipelines;
using CanvasCraft.Api.Services;
using FluentAssertions;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using Moq;
using Xunit;

namespace CanvasCraft.Api.Tests.Controllers
{
    /// <summary>
    /// Unit-tests for <see cref="PipelinesController"/>
    /// covering the public contract and interaction with <see cref="IPipelineService"/>.
    /// </summary>
    public sealed class PipelinesControllerTests
    {
        private readonly Mock<IPipelineService> _pipelineServiceMock;
        private readonly Mock<ILogger<PipelinesController>> _loggerMock;
        private readonly PipelinesController _sut; // System Under Test

        public PipelinesControllerTests()
        {
            _pipelineServiceMock = new Mock<IPipelineService>(MockBehavior.Strict);
            _loggerMock          = new Mock<ILogger<PipelinesController>>();

            _sut = new PipelinesController(
                _pipelineServiceMock.Object,
                _loggerMock.Object)
            {
                // Required for CreatedAtAction URL generation in unit-test context.
                ControllerContext = new ControllerContext
                {
                    HttpContext = new DefaultHttpContext()
                }
            };
        }

        #region GET /pipelines/{id}

        [Fact]
        public async Task GetById_ShouldReturnOk_WhenPipelineExists()
        {
            // Arrange
            var pipelineId = Guid.NewGuid();
            var expected   = FakePipelineDto(pipelineId);

            _pipelineServiceMock
                .Setup(s => s.GetByIdAsync(pipelineId, It.IsAny<CancellationToken>()))
                .ReturnsAsync(expected);

            // Act
            var result = await _sut.GetByIdAsync(pipelineId);

            // Assert
            var okResult = result.Should().BeOfType<OkObjectResult>().Subject;
            okResult.Value.Should().BeEquivalentTo(expected);

            _pipelineServiceMock.Verify(
                s => s.GetByIdAsync(pipelineId, It.IsAny<CancellationToken>()),
                Times.Once);
        }

        [Fact]
        public async Task GetById_ShouldReturnNotFound_WhenPipelineDoesNotExist()
        {
            // Arrange
            var pipelineId = Guid.NewGuid();

            _pipelineServiceMock
                .Setup(s => s.GetByIdAsync(pipelineId, It.IsAny<CancellationToken>()))
                .ReturnsAsync((PipelineDto?)null);

            // Act
            var result = await _sut.GetByIdAsync(pipelineId);

            // Assert
            result.Should().BeOfType<NotFoundResult>();

            _pipelineServiceMock.Verify(
                s => s.GetByIdAsync(pipelineId, It.IsAny<CancellationToken>()),
                Times.Once);
        }

        #endregion

        #region POST /pipelines

        [Fact]
        public async Task Create_ShouldReturnCreatedAt_WhenRequestIsValid()
        {
            // Arrange
            var request  = new PipelineCreateRequest("stable-diffusion-repaint-v2", "description");
            var created  = FakePipelineDto(Guid.NewGuid());

            _pipelineServiceMock
                .Setup(s => s.CreateAsync(request, It.IsAny<CancellationToken>()))
                .ReturnsAsync(created);

            // Act
            var result = await _sut.CreateAsync(request);

            // Assert
            var createdResult = result.Should().BeOfType<CreatedAtActionResult>().Subject;
            createdResult.ActionName.Should().Be(nameof(PipelinesController.GetByIdAsync));
            createdResult.RouteValues!["id"].Should().Be(created.Id);
            createdResult.Value.Should().BeEquivalentTo(created, options => options.ComparingByMembers<PipelineDto>());

            _pipelineServiceMock.Verify(
                s => s.CreateAsync(request, It.IsAny<CancellationToken>()),
                Times.Once);
        }

        [Fact]
        public async Task Create_ShouldReturnBadRequest_WhenModelStateIsInvalid()
        {
            // Arrange
            _sut.ModelState.AddModelError("Name", "Required");

            // Act
            var result = await _sut.CreateAsync(new PipelineCreateRequest(null!, null));

            // Assert
            result.Should().BeOfType<BadRequestObjectResult>();
            _pipelineServiceMock.Verify(
                s => s.CreateAsync(It.IsAny<PipelineCreateRequest>(), It.IsAny<CancellationToken>()),
                Times.Never);
        }

        #endregion

        #region POST /pipelines/{id}/runs

        [Fact]
        public async Task TriggerRun_ShouldReturnAccepted_WhenTriggerSucceeds()
        {
            // Arrange
            var pipelineId = Guid.NewGuid();

            _pipelineServiceMock
                .Setup(s => s.TriggerRunAsync(pipelineId, It.IsAny<CancellationToken>()))
                .ReturnsAsync(true);

            // Act
            var result = await _sut.TriggerRunAsync(pipelineId);

            // Assert
            result.Should().BeOfType<AcceptedResult>()
                  .Which.Location.Should().Contain(pipelineId.ToString());

            _pipelineServiceMock.Verify(
                s => s.TriggerRunAsync(pipelineId, It.IsAny<CancellationToken>()),
                Times.Once);
        }

        [Fact]
        public async Task TriggerRun_ShouldReturnConflict_WhenPipelineIsAlreadyRunning()
        {
            // Arrange
            var pipelineId = Guid.NewGuid();

            _pipelineServiceMock
                .Setup(s => s.TriggerRunAsync(pipelineId, It.IsAny<CancellationToken>()))
                .ThrowsAsync(new InvalidOperationException("Pipeline is already running"));

            // Act
            var result = await _sut.TriggerRunAsync(pipelineId);

            // Assert
            var conflict = result.Should().BeOfType<ConflictObjectResult>().Subject;
            conflict.Value.Should().Be("Pipeline is already running");

            _pipelineServiceMock.Verify(
                s => s.TriggerRunAsync(pipelineId, It.IsAny<CancellationToken>()),
                Times.Once);
        }

        #endregion

        #region DELETE /pipelines/{id}

        [Fact]
        public async Task Delete_ShouldReturnNoContent_WhenDeleteSucceeds()
        {
            // Arrange
            var id = Guid.NewGuid();

            _pipelineServiceMock
                .Setup(s => s.DeleteAsync(id, It.IsAny<CancellationToken>()))
                .ReturnsAsync(true);

            // Act
            var result = await _sut.DeleteAsync(id);

            // Assert
            result.Should().BeOfType<NoContentResult>();

            _pipelineServiceMock.Verify(
                s => s.DeleteAsync(id, It.IsAny<CancellationToken>()),
                Times.Once);
        }

        [Fact]
        public async Task Delete_ShouldReturnNotFound_WhenPipelineDoesNotExist()
        {
            // Arrange
            var id = Guid.NewGuid();

            _pipelineServiceMock
                .Setup(s => s.DeleteAsync(id, It.IsAny<CancellationToken>()))
                .ReturnsAsync(false);

            // Act
            var result = await _sut.DeleteAsync(id);

            // Assert
            result.Should().BeOfType<NotFoundResult>();

            _pipelineServiceMock.Verify(
                s => s.DeleteAsync(id, It.IsAny<CancellationToken>()),
                Times.Once);
        }

        #endregion

        #region Test helpers

        private static PipelineDto FakePipelineDto(Guid id) =>
            new()
            {
                Id           = id,
                Name         = $"pipeline-{id:N}",
                Description  = "A test pipeline",
                CreatedUtc   = DateTime.UtcNow,
                LastUpdatedUtc = DateTime.UtcNow
            };

        #endregion
    }

    #region Stubs (only used for compiling tests when domain layer is not referenced)

    // These DTOs/requets should already exist in production code.
    // They are re-declared here only to allow the test project to compile in isolation.
    // When integrated into the full solution, remove these stubs.
    namespace CanvasCraft.Api.Models.Pipelines
    {
        public sealed record PipelineCreateRequest(string? Name, string? Description);

        public sealed class PipelineDto
        {
            public Guid       Id             { get; set; }
            public string     Name           { get; set; } = default!;
            public string?    Description    { get; set; }
            public DateTime   CreatedUtc     { get; set; }
            public DateTime   LastUpdatedUtc { get; set; }
        }
    }

    namespace CanvasCraft.Api.Services
    {
        public interface IPipelineService
        {
            Task<PipelineDto?>                        GetByIdAsync(Guid id, CancellationToken ct = default);
            Task<PipelineDto>                         CreateAsync(PipelineCreateRequest request, CancellationToken ct = default);
            Task<bool>                                TriggerRunAsync(Guid id, CancellationToken ct = default);
            Task<IReadOnlyCollection<PipelineRunDto>> GetRunsAsync(Guid id, CancellationToken ct = default);
            Task<bool>                                DeleteAsync(Guid id, CancellationToken ct = default);
        }

        public sealed class PipelineRunDto
        {
            public Guid       Id          { get; set; }
            public Guid       PipelineId  { get; set; }
            public DateTime   StartedUtc  { get; set; }
            public DateTime?  FinishedUtc { get; set; }
            public string     Status      { get; set; } = default!;
        }
    }
    #endregion
}
```