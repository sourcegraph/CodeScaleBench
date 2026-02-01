```csharp
using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using CanvasCraft.Core.Events;
using CanvasCraft.Core.Exceptions;
using CanvasCraft.Core.Models;
using FluentAssertions;
using Moq;
using Xunit;

namespace CanvasCraft.Core.Tests.Models
{
    /// <summary>
    /// Unit tests that assert correct behavior of the ModelVersion aggregate root.
    /// </summary>
    public sealed class ModelVersionTests
    {
        private readonly Mock<IEventDispatcher> _eventDispatcher;
        private readonly Mock<IDateTimeProvider> _dateTime;
        private readonly ModelId _modelId;

        public ModelVersionTests()
        {
            _eventDispatcher = new Mock<IEventDispatcher>(MockBehavior.Strict);
            _dateTime       = new Mock<IDateTimeProvider>(MockBehavior.Strict);
            _dateTime.Setup(d => d.UtcNow)
                     .Returns(new DateTime(2023, 01, 01, 0, 0, 0, DateTimeKind.Utc));

            _modelId = ModelId.New();
        }

        [Fact]
        public void When_first_version_is_created_VersionNumber_is_set_to_one_and_event_is_published()
        {
            // Arrange
            var metadata = new ModelMetadata(
                description : "Stable-Diffusion base checkpoint",
                modality    : "txt2img",
                hyperParams : new Dictionary<string, string> { ["optimizer"] = "Adam" });

            // Act
            var version = ModelVersion.CreateInitial(
                modelId        : _modelId,
                metadata       : metadata,
                dateTime       : _dateTime.Object,
                eventDispatcher: _eventDispatcher.Object);

            // Assert
            version.VersionNumber.Should().Be(1);
            version.Metadata.Should().BeEquivalentTo(metadata);
            version.CreatedAtUtc.Should().Be(_dateTime.Object.UtcNow);

            _eventDispatcher.Verify(d => d.Dispatch(
                It.Is<ModelVersionCreatedEvent>(e =>
                    e.ModelId      == _modelId &&
                    e.VersionId    == version.VersionId &&
                    e.VersionNumber == 1)),
                Times.Once);
        }

        [Fact]
        public void Creating_next_version_increments_version_and_clones_previous_state()
        {
            // Arrange
            var v1 = ModelVersion.CreateInitial(
                _modelId,
                new ModelMetadata("v1", "txt2img"),
                _dateTime.Object,
                _eventDispatcher.Object);

            var updatedMetadata = new ModelMetadata("Fine-tuned on neon palette", "txt2img");

            // Act
            var v2 = v1.CreateNext(
                updatedMetadata,
                _dateTime.Object,
                _eventDispatcher.Object);

            // Assert
            v2.VersionNumber.Should().Be(v1.VersionNumber + 1);
            v2.ParentVersionId.Should().Be(v1.VersionId);
            v2.Metadata.Should().BeEquivalentTo(updatedMetadata);

            // Make sure the parent is unchanged (immutability)
            v1.Metadata.Should().BeEquivalentTo(new ModelMetadata("v1", "txt2img"));
        }

        [Fact]
        public void Activating_a_version_marks_only_one_active_and_raises_event()
        {
            // Arrange
            var v1 = ModelVersion.CreateInitial(
                _modelId,
                new ModelMetadata("v1", "txt2img"),
                _dateTime.Object,
                _eventDispatcher.Object);

            var v2 = v1.CreateNext(
                new ModelMetadata("v2", "txt2img"),
                _dateTime.Object,
                _eventDispatcher.Object);

            // Act
            v2.Activate(_eventDispatcher.Object);

            // Assert
            v2.IsActive.Should().BeTrue();
            v1.IsActive.Should().BeFalse();

            _eventDispatcher.Verify(d => d.Dispatch(
                It.Is<ModelVersionActivatedEvent>(e =>
                    e.ActivatedVersionId       == v2.VersionId &&
                    e.PreviousActiveVersionId  == v1.VersionId)),
                Times.Once);
        }

        [Fact]
        public void Concurrent_updates_on_same_version_should_throw_OptimisticConcurrencyException()
        {
            // Arrange
            var version = ModelVersion.CreateInitial(
                _modelId,
                new ModelMetadata("base", "txt2img"),
                _dateTime.Object,
                _eventDispatcher.Object);

            var updatedMetadata1 = new ModelMetadata("update-1", "txt2img");
            var updatedMetadata2 = new ModelMetadata("update-2", "txt2img");

            // Act
            var task1 = Task.Run(() =>
                version.ApplyMetadataPatch(updatedMetadata1, expectedETag: version.ETag));

            var task2 = Task.Run(() =>
            {
                // Small delay to increase the likelihood of race condition
                Thread.Sleep(40);
                version.ApplyMetadataPatch(updatedMetadata2, expectedETag: version.ETag);
            });

            Func<Task> combined = async () => await Task.WhenAll(task1, task2);

            // Assert
            combined.Should()
                    .ThrowAsync<OptimisticConcurrencyException>()
                    .WithMessage("*ETag*");
        }

        [Fact]
        public void Rolling_back_creates_new_version_with_original_metadata()
        {
            // Arrange
            var v1 = ModelVersion.CreateInitial(
                _modelId,
                new ModelMetadata("base", "txt2img"),
                _dateTime.Object,
                _eventDispatcher.Object);

            var v2 = v1.CreateNext(
                new ModelMetadata("over-fitted-colors", "txt2img"),
                _dateTime.Object,
                _eventDispatcher.Object);

            // Act
            var rollback = v2.RollbackTo(
                targetVersionId : v1.VersionId,
                dateTime        : _dateTime.Object,
                eventDispatcher : _eventDispatcher.Object);

            // Assert
            rollback.VersionNumber.Should().Be(3);
            rollback.Metadata.Description.Should().Be("base");
            rollback.ParentVersionId.Should().Be(v2.VersionId);

            _eventDispatcher.Verify(d => d.Dispatch(
                It.Is<ModelVersionRollbackEvent>(e =>
                    e.TargetVersionId == v1.VersionId &&
                    e.NewVersionId    == rollback.VersionId)),
                Times.Once);
        }
    }
}
```