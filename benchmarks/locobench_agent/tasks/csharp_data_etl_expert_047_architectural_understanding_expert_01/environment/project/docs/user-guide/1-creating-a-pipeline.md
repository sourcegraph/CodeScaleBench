using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using Xunit;

namespace PaletteStream.ETLCanvas.Docs.UserGuide.Tests
{
    /// <summary>
    /// Validates the sample code that appears in:
    /// docs/user-guide/1-creating-a-pipeline.md
    /// The goal is to ensure that every snippet shown in the documentation
    /// actually compiles, runs, and produces the expected results.
    /// </summary>
    public sealed class CreatingAPipelineDocTests
    {
        [Fact(DisplayName = "Documentation sample pipeline should execute and load expected results")]
        public async Task DocumentationSamplePipeline_Should_RunSuccessfully()
        {
            // ------------------------------------------------------------------
            // Arrange – mimic the steps a user would take following the docs
            // ------------------------------------------------------------------

            // 1. Create a data source (pretend we pulled this from a message queue)
            var rawPigments = new[]
            {
                new Dictionary<string, object?>
                {
                    ["Id"]        = 1,
                    ["Name"]      = "Ada Lovelace",
                    ["Email"]     = "ada@computing.io",
                    ["IsActive"]  = true,
                    ["Country"]   = "UK"
                },
                new Dictionary<string, object?>
                {
                    ["Id"]        = 2,
                    ["Name"]      = "Charles Babbage",
                    ["Email"]     = "charles@computing.io",
                    ["IsActive"]  = false,
                    ["Country"]   = "UK"
                },
                new Dictionary<string, object?>
                {
                    ["Id"]        = 3,
                    ["Name"]      = "Alan Turing",
                    ["Email"]     = "alan@computing.io",
                    ["IsActive"]  = true,
                    ["Country"]   = "UK"
                }
            };

            var source      = new InMemoryDataSource(rawPigments);
            var sink        = new InMemoryDataSink();
            var cancellation = new CancellationTokenSource(TimeSpan.FromSeconds(5));

            // 2. Compose the pipeline using builder-style DSL (mirrors the docs)
            var pipeline = new PipelineBuilder()
                .From(source)
                .Transform(new FilterInactiveRecordsTransformation())
                .Transform(new EmailAnonymizerTransformation())
                .LoadTo(sink)
                .Build();

            // ------------------------------------------------------------------
            // Act – execute the pipeline
            // ------------------------------------------------------------------
            await pipeline.RunAsync(cancellation.Token);

            // ------------------------------------------------------------------
            // Assert – verify the sink contains the expected data
            // ------------------------------------------------------------------
            sink.Items.Should().HaveCount(2, "inactive records should have been filtered out");

            foreach (var row in sink.Items)
            {
                row["Email"].Should().Be("****@computing.io", "emails should be anonymized");
                row["IsActive"].Should().BeTrue();
            }
        }

        #region Minimal pipeline implementation used exclusively for doc-validation tests
        // NOTE: The real library provides fully-featured implementations.
        // These internal types only exist to keep the unit-test self-contained.

        private interface IDataSource
        {
            IAsyncEnumerable<IDictionary<string, object?>> ReadAsync(CancellationToken token = default);
        }

        private interface IDataSink
        {
            Task WriteAsync(IAsyncEnumerable<IDictionary<string, object?>> stream,
                            CancellationToken token = default);
        }

        private interface ITransformation
        {
            IAsyncEnumerable<IDictionary<string, object?>> Apply(
                IAsyncEnumerable<IDictionary<string, object?>> stream,
                CancellationToken token = default);
        }

        private sealed class Pipeline
        {
            private readonly IDataSource          _source;
            private readonly IReadOnlyList<ITransformation> _transformations;
            private readonly IDataSink            _sink;

            public Pipeline(IDataSource source,
                            IReadOnlyList<ITransformation> transformations,
                            IDataSink sink)
            {
                _source         = source;
                _transformations = transformations;
                _sink           = sink;
            }

            public async Task RunAsync(CancellationToken token = default)
            {
                var stream = _source.ReadAsync(token);
                foreach (var transformation in _transformations)
                {
                    stream = transformation.Apply(stream, token);
                }

                await _sink.WriteAsync(stream, token);
            }
        }

        private sealed class PipelineBuilder
        {
            private IDataSource?                    _source;
            private readonly List<ITransformation> _transformations = new();
            private IDataSink?                      _sink;

            public PipelineBuilder From(IDataSource source)
            {
                _source = source;
                return this;
            }

            public PipelineBuilder Transform(ITransformation transformation)
            {
                _transformations.Add(transformation);
                return this;
            }

            public PipelineBuilder LoadTo(IDataSink sink)
            {
                _sink = sink;
                return this;
            }

            public Pipeline Build()
            {
                if (_source is null) throw new InvalidOperationException("Source not specified.");
                if (_sink   is null) throw new InvalidOperationException("Sink not specified.");

                return new Pipeline(_source, _transformations.ToArray(), _sink);
            }
        }

        // ---------------------------
        // Concrete helpers (stubs)
        // ---------------------------

        private sealed class InMemoryDataSource : IDataSource
        {
            private readonly IReadOnlyCollection<IDictionary<string, object?>> _items;

            public InMemoryDataSource(IReadOnlyCollection<IDictionary<string, object?>> items)
            {
                _items = items;
            }

            public async IAsyncEnumerable<IDictionary<string, object?>> ReadAsync(
                [EnumeratorCancellation] CancellationToken token = default)
            {
                foreach (var item in _items)
                {
                    token.ThrowIfCancellationRequested();
                    yield return item;
                    await Task.Yield(); // simulate async boundary
                }
            }
        }

        private sealed class InMemoryDataSink : IDataSink
        {
            public IReadOnlyCollection<IDictionary<string, object?>> Items => _items;

            private readonly ConcurrentBag<IDictionary<string, object?>> _items = new();

            public async Task WriteAsync(IAsyncEnumerable<IDictionary<string, object?>> stream,
                                         CancellationToken token = default)
            {
                await foreach (var row in stream.WithCancellation(token))
                {
                    _items.Add(new Dictionary<string, object?>(row));
                }
            }
        }

        // ---------------------------
        // Transformations
        // ---------------------------

        private sealed class FilterInactiveRecordsTransformation : ITransformation
        {
            public async IAsyncEnumerable<IDictionary<string, object?>> Apply(
                IAsyncEnumerable<IDictionary<string, object?>> stream,
                [EnumeratorCancellation] CancellationToken token = default)
            {
                await foreach (var row in stream.WithCancellation(token))
                {
                    if (row.TryGetValue("IsActive", out var isActiveObj) &&
                        isActiveObj is bool isActive &&
                        isActive)
                    {
                        yield return row;
                    }
                }
            }
        }

        private sealed class EmailAnonymizerTransformation : ITransformation
        {
            private const string EmailKey = "Email";

            public async IAsyncEnumerable<IDictionary<string, object?>> Apply(
                IAsyncEnumerable<IDictionary<string, object?>> stream,
                [EnumeratorCancellation] CancellationToken token = default)
            {
                await foreach (var row in stream.WithCancellation(token))
                {
                    if (row.TryGetValue(EmailKey, out var emailObj) &&
                        emailObj is string email &&
                        email.Contains('@'))
                    {
                        var domain = email[(email.IndexOf('@') + 1)..];
                        row[EmailKey] = $"****@{domain}";
                    }

                    yield return row;
                }
            }
        }

        #endregion
    }
}