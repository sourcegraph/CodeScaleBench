```csharp
// File: src/Services/PaletteStream.Loader/DataLake/DataLakeClient.cs

using System;
using System.IO;
using System.Net;
using System.Threading;
using System.Threading.Tasks;
using Azure;
using Azure.Storage;
using Azure.Storage.Files.DataLake;
using Azure.Storage.Files.DataLake.Models;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Polly;
using Polly.Retry;

namespace PaletteStream.Loader.DataLake
{
    /// <summary>
    ///     A thin wrapper around <see cref="DataLakeServiceClient"/> that provides
    ///     high-level helper functions for the ETL “canvas” to interact with Azure
    ///     Data Lake Storage Gen2.  All public members are resilient to transient
    ///     faults via Polly retry policies and emit telemetry through <see cref="ILogger"/>.
    /// </summary>
    public sealed class DataLakeClient : IDataLakeClient, IAsyncDisposable
    {
        private readonly DataLakeServiceClient _serviceClient;
        private readonly DataLakeSettings      _settings;
        private readonly ILogger<DataLakeClient> _logger;

        // Re-use a singleton retry policy instance for all operations.
        private readonly AsyncRetryPolicy _retryPolicy;

        public DataLakeClient(
            DataLakeServiceClient serviceClient,
            IOptions<DataLakeSettings> options,
            ILogger<DataLakeClient> logger)
        {
            _serviceClient = serviceClient ?? throw new ArgumentNullException(nameof(serviceClient));
            _settings      = options?.Value ?? throw new ArgumentNullException(nameof(options));
            _logger        = logger   ?? throw new ArgumentNullException(nameof(logger));

            _retryPolicy = Policy
                .Handle<RequestFailedException>(ex => IsTransient(ex))
                .Or<IOException>()
                .WaitAndRetryAsync(
                    retryCount: _settings.RetryCount,
                    sleepDurationProvider: attempt => TimeSpan.FromSeconds(Math.Pow(2, attempt)), // Exponential back-off
                    onRetry: (ex, ts, i, ctx) =>
                    {
                        _logger.LogWarning(ex,
                            "Transient failure talking to Data Lake (attempt {Attempt}/{Max}). Retrying in {Delay}.",
                            i, _settings.RetryCount, ts);
                    });
        }

        #region Public API

        /// <inheritdoc />
        public async Task UploadAsync(
            string zone,
            string blobPath,
            Stream content,
            bool overwrite            = false,
            CancellationToken cancel  = default)
        {
            ArgumentNullException.ThrowIfNull(zone);
            ArgumentNullException.ThrowIfNull(blobPath);
            ArgumentNullException.ThrowIfNull(content);

            await _retryPolicy.ExecuteAsync(async ct =>
            {
                var fileClient = await GetFileClientAsync(zone, blobPath, ct).ConfigureAwait(false);

                content.Position = 0;
                await fileClient.UploadAsync(content, overwrite, cancellationToken: ct).ConfigureAwait(false);

                _logger.LogInformation(
                    "Uploaded file to Data Lake. Zone: {Zone}, Path: {Path}, Overwrite: {Overwrite}",
                    zone, blobPath, overwrite);
            }, cancel).ConfigureAwait(false);
        }

        /// <inheritdoc />
        public async Task<Stream> DownloadAsync(
            string zone,
            string blobPath,
            CancellationToken cancel = default)
        {
            ArgumentNullException.ThrowIfNull(zone);
            ArgumentNullException.ThrowIfNull(blobPath);

            return await _retryPolicy.ExecuteAsync(async ct =>
            {
                var fileClient = await GetFileClientAsync(zone, blobPath, ct).ConfigureAwait(false);

                Response<FileDownloadInfo> response = await fileClient.ReadAsync(ct).ConfigureAwait(false);
                _logger.LogInformation(
                    "Downloaded file from Data Lake. Zone: {Zone}, Path: {Path}, Size: {Size} B",
                    zone, blobPath, response.Value.ContentLength);

                // Caller is responsible for disposing the stream.
                return response.Value.Content;
            }, cancel).ConfigureAwait(false);
        }

        /// <inheritdoc />
        public async Task<bool> ExistsAsync(
            string zone,
            string blobPath,
            CancellationToken cancel = default)
        {
            ArgumentNullException.ThrowIfNull(zone);
            ArgumentNullException.ThrowIfNull(blobPath);

            return await _retryPolicy.ExecuteAsync(async ct =>
            {
                var fileClient = await GetFileClientAsync(zone, blobPath, ct).ConfigureAwait(false);
                bool exists = await fileClient.ExistsAsync(ct).ConfigureAwait(false);
                _logger.LogDebug("File {Path} in zone {Zone} exists: {Exists}", blobPath, zone, exists);
                return exists;
            }, cancel).ConfigureAwait(false);
        }

        /// <inheritdoc />
        public async Task MoveAsync(
            string zone,
            string sourcePath,
            string destPath,
            bool overwrite           = false,
            CancellationToken cancel = default)
        {
            ArgumentNullException.ThrowIfNull(zone);
            ArgumentNullException.ThrowIfNull(sourcePath);
            ArgumentNullException.ThrowIfNull(destPath);

            await _retryPolicy.ExecuteAsync(async ct =>
            {
                var fileSystem   = await GetFileSystemAsync(zone, ct).ConfigureAwait(false);
                var sourceClient = fileSystem.GetFileClient(sourcePath);
                var destClient   = fileSystem.GetFileClient(destPath);

                if (overwrite && await destClient.ExistsAsync(ct).ConfigureAwait(false))
                {
                    await destClient.DeleteAsync(cancellationToken: ct).ConfigureAwait(false);
                }

                await sourceClient.RenameAsync(destPath, cancellationToken: ct).ConfigureAwait(false);

                _logger.LogInformation(
                    "Moved file inside Data Lake. Zone: {Zone}, From: {Source}, To: {Destination}",
                    zone, sourcePath, destPath);
            }, cancel).ConfigureAwait(false);
        }

        /// <inheritdoc />
        public async Task<string> GenerateSasAsync(
            string zone,
            string blobPath,
            DateTimeOffset expiresOn,
            CancellationToken cancel = default)
        {
            ArgumentNullException.ThrowIfNull(zone);
            ArgumentNullException.ThrowIfNull(blobPath);

            var fileClient = await GetFileClientAsync(zone, blobPath, cancel).ConfigureAwait(false);

            DataLakeSasBuilder sas = new(
                fileSystemName: fileClient.FileSystemName,
                path:           fileClient.Path)
            {
                ExpiresOn = expiresOn,
            };

            sas.SetPermissions(DataLakeSasPermissions.Read | DataLakeSasPermissions.List);

            string uri = fileClient.GenerateSasUri(sas).ToString();
            _logger.LogDebug("Generated SAS URI for {Path} in zone {Zone}", blobPath, zone);

            return uri;
        }

        #endregion

        #region Private helpers

        private async Task<DataLakeFileClient> GetFileClientAsync(
            string zone,
            string blobPath,
            CancellationToken cancel)
        {
            var fileSystem = await GetFileSystemAsync(zone, cancel).ConfigureAwait(false);
            return fileSystem.GetFileClient(blobPath);
        }

        private async Task<DataLakeFileSystemClient> GetFileSystemAsync(
            string zone,
            CancellationToken cancel)
        {
            var fileSystem = _serviceClient.GetFileSystemClient(zone.ToLowerInvariant());

            // Lazily create if not exists. This allows dynamic onboarding of new zones.
            await fileSystem.CreateIfNotExistsAsync(
                publicAccessType: PublicAccessType.None,
                cancellationToken: cancel).ConfigureAwait(false);

            return fileSystem;
        }

        /// <summary>
        /// Determines whether a given <see cref="RequestFailedException"/> is transient.
        /// </summary>
        private static bool IsTransient(RequestFailedException ex)
        {
            // Consider common transient error codes.
            return
                ex.Status == (int)HttpStatusCode.TooManyRequests ||  // 429
                ex.Status == (int)HttpStatusCode.RequestTimeout  ||  // 408
                ex.Status == (int)HttpStatusCode.ServiceUnavailable || // 503
                ex.Status == (int)HttpStatusCode.GatewayTimeout;       // 504
        }

        #endregion

        #region IDisposable Support

        private bool _disposed;

        public async ValueTask DisposeAsync()
        {
            if (_disposed) return;

            try
            {
                // Flush any connection pools, if necessary.
                if (_serviceClient?.Diagnostics != null)
                {
                    await _serviceClient.ClientDiagnostics.DisposeAsync().ConfigureAwait(false);
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Exception when disposing DataLakeClient diagnostics.");
            }

            _disposed = true;
        }

        #endregion
    }

    /// <summary>
    ///     Configuration options for <see cref="DataLakeClient"/>.
    ///     Added via <c>services.Configure&lt;DataLakeSettings&gt;(…)</c>.
    /// </summary>
    public sealed class DataLakeSettings
    {
        /// <summary>
        ///     Number of retry attempts for transient faults.
        /// </summary>
        public int RetryCount { get; set; } = 5;
    }

    /// <summary>
    ///     Abstraction to aid unit-testing and future storage back-ends.
    /// </summary>
    public interface IDataLakeClient
    {
        Task UploadAsync(string zone, string blobPath, Stream content, bool overwrite = false, CancellationToken cancel = default);

        Task<Stream> DownloadAsync(string zone, string blobPath, CancellationToken cancel = default);

        Task<bool> ExistsAsync(string zone, string blobPath, CancellationToken cancel = default);

        Task MoveAsync(string zone, string sourcePath, string destPath, bool overwrite = false, CancellationToken cancel = default);

        Task<string> GenerateSasAsync(string zone, string blobPath, DateTimeOffset expiresOn, CancellationToken cancel = default);
    }
}
```