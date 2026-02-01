```csharp
// File: PaletteStream-ETL-Canvas/docs/user-guide/3-exploring-the-gallery.md
// NOTE: Although the path suggests a Markdown document, this file intentionally contains
//       executable test code that drives the “Exploring the Gallery” user-guide scenario.
//       The tests validate both API and UI (Blazor) behaviour associated with the Gallery
//       feature.  See project README for the rationale behind co-locating executable
//       examples with the documentation.

using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Bunit;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Moq;
using PaletteStream.ETL.Canvas.Abstractions;
using PaletteStream.ETL.Canvas.Components;
using PaletteStream.ETL.Canvas.DTOs;
using PaletteStream.ETL.Canvas.Eventing;
using PaletteStream.ETL.Canvas.Services;
using Shouldly;
using Xunit;

namespace PaletteStream.ETL.Canvas.Tests.Docs
{
    /// <summary>
    /// High-level, end-to-end tests that power the step-by-step instructions in
    /// docs/user-guide/3-exploring-the-gallery.md.  
    ///
    /// The tests purposely exercise both the HTTP API surface (used by JS-interop
    /// graphs in the docs) and the Blazor component model that renders the Gallery.
    /// </summary>
    public class ExploringTheGallerySpecs :
        IClassFixture<WebApplicationFactory<Program>>,           // API + Server-rendered Blazor
        IDisposable                                              // Disposes bUnit TestContext
    {
        private readonly WebApplicationFactory<Program> _factory;
        private readonly HttpClient _client;
        private readonly TestContext _bunit;                     // Client-side Blazor test harness
        private readonly Mock<IEventStreamer> _eventStreamerMock;

        public ExploringTheGallerySpecs(WebApplicationFactory<Program> factory)
        {
            _eventStreamerMock = new Mock<IEventStreamer>();

            // Spin up a real TestServer but swap IEventStreamer for a strict mock.
            _factory = factory.WithWebHostBuilder(builder =>
            {
                builder.UseEnvironment("Test");
                builder.ConfigureServices(services =>
                {
                    services.AddSingleton(_eventStreamerMock.Object);
                    // Optionally seed the in-memory database with curated assets.
                    var paletteSeeder = new CuratedPaletteSeeder();
                    services.AddSingleton<IPaletteSeeder>(paletteSeeder);
                });
            });

            _client = _factory.CreateClient();

            // Setup bUnit test context with same DI graph as the TestServer.
            _bunit = new TestContext();
            _bunit.Services = _factory.Services;
        }

        public void Dispose()
        {
            _client?.Dispose();
            _bunit?.Dispose();
        }

        // ---------------------------------------------------------------------
        //                          API-LEVEL TESTS
        // ---------------------------------------------------------------------

        [Fact(DisplayName = "GET /api/gallery returns HTTP 200 with at least one curated pigment")]
        public async Task GalleryApi_ShouldReturnCuratedAssetsAsync()
        {
            // Act
            var response = await _client.GetAsync("/api/gallery?zone=curated");

            // Assert
            response.StatusCode.ShouldBe(HttpStatusCode.OK);

            var json = await response.Content.ReadAsStringAsync();
            var payload = JsonSerializer.Deserialize<IReadOnlyList<PaletteAssetDto>>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            });

            payload.ShouldNotBeNull();
            payload!.Any().ShouldBeTrue("Expected at least one curated asset to be present.");
            payload!.All(a => a.Zone.Equals("curated", StringComparison.OrdinalIgnoreCase))
                  .ShouldBeTrue("Only curated assets should be returned.");
        }

        [Fact(DisplayName = "GET /api/gallery/preview/{id} yields a streamable content-type")]
        public async Task GalleryApi_ShouldReturnPreviewStreamAsync()
        {
            // Arrange
            var firstId = await GetFirstCuratedAssetIdAsync();

            // Act
            var response = await _client.GetAsync($"/api/gallery/preview/{firstId}");

            // Assert
            response.StatusCode.ShouldBe(HttpStatusCode.OK);
            response.Content.Headers.ContentType!.MediaType
                    .ShouldBe("image/webp", "Gallery previews are served as WEBP for better perf.");
        }

        // ---------------------------------------------------------------------
        //                        COMPONENT-LEVEL TESTS
        // ---------------------------------------------------------------------

        [Fact(DisplayName = "GalleryViewer renders correct tile count and reacts to selection")]
        public async Task GalleryViewer_ShouldRenderTiles_AndOpenDetailModalOnClick()
        {
            // Arrange
            var curated = await GetCuratedAssetsAsync();
            var component = _bunit.RenderComponent<GalleryViewer>(parameters => parameters
                .Add(p => p.InitialPalette, curated)
            );

            // Assert – basic render
            var tiles = component.FindAll(".ps-tile");
            tiles.Count.ShouldBe(curated.Count);

            // Act – simulate clicking first tile
            var firstTile = tiles.First();
            firstTile.Click();

            // Assert – modal appears with correct content
            component.FindAll(".ps-modal")
                     .Single()
                     .TextContent.ShouldContain(curated.First().Name);
        }

        [Fact(DisplayName = "GalleryViewer updates tiles in real-time when EventStreamer pushes new asset")]
        public void GalleryViewer_ShouldUpdateOnEventStream()
        {
            // Arrange
            var curated = new List<PaletteAssetDto>();
            var component = _bunit.RenderComponent<GalleryViewer>(parameters => parameters
                .Add(p => p.InitialPalette, curated)
            );

            // Assert – no tiles initially
            component.FindAll(".ps-tile").ShouldBeEmpty();

            // Act – fire an AddAsset event through the mocked IEventStreamer
            var newAsset = new PaletteAssetDto
            {
                AssetId = Guid.NewGuid().ToString(),
                Name = "🤖 AI-Generated Texture",
                Zone = "curated",
                PreviewUrl = "/fake/preview/ai"
            };

            _eventStreamerMock.Raise(es => es.AssetAdded += null,
                new AssetEventArgs(newAsset));

            // Allow the component to re-render
            _bunit.WaitForState(() => component.FindAll(".ps-tile").Any());

            // Assert – tile count incremented
            component.FindAll(".ps-tile").Count.ShouldBe(1);
            component.Markup.ShouldContain("AI-Generated Texture");
        }

        // ---------------------------------------------------------------------
        //                           HELPER UTILITIES
        // ---------------------------------------------------------------------

        private async Task<string> GetFirstCuratedAssetIdAsync(CancellationToken ct = default)
        {
            var assets = await GetCuratedAssetsAsync(ct);
            return assets.First().AssetId;
        }

        private async Task<IReadOnlyList<PaletteAssetDto>> GetCuratedAssetsAsync(CancellationToken ct = default)
        {
            var json = await _client.GetStringAsync("/api/gallery?zone=curated", ct);
            return JsonSerializer.Deserialize<IReadOnlyList<PaletteAssetDto>>(json,
                       new JsonSerializerOptions { PropertyNameCaseInsensitive = true })!;
        }
    }

    #region •— Test Utilities & Stubs —•

    /// <summary>
    /// Lightweight seeder used only in the test environment to hydrate the in-memory
    /// persistence layer with predictable demo data.
    /// </summary>
    internal sealed class CuratedPaletteSeeder : IPaletteSeeder
    {
        public IReadOnlyCollection<PaletteAssetDto> Seed()
        {
            return new[]
            {
                new PaletteAssetDto
                {
                    AssetId    = Guid.Parse("11111111-1111-1111-1111-111111111111").ToString(),
                    Name       = "Color-Swirl Galaxy",
                    Zone       = "curated",
                    PreviewUrl = "/gallery/preview/11111111-1111-1111-1111-111111111111"
                },
                new PaletteAssetDto
                {
                    AssetId    = Guid.Parse("22222222-2222-2222-2222-222222222222").ToString(),
                    Name       = "Monochrome Mountains",
                    Zone       = "curated",
                    PreviewUrl = "/gallery/preview/22222222-2222-2222-2222-222222222222"
                }
            };
        }
    }

    /// <summary>
    /// Contract responsible for seeding palettes during test startup.
    /// </summary>
    internal interface IPaletteSeeder
    {
        IReadOnlyCollection<PaletteAssetDto> Seed();
    }

    #endregion
}
```