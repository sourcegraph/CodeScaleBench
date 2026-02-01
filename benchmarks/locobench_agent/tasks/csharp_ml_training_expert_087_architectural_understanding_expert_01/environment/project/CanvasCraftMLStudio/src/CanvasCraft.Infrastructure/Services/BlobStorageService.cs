```csharp
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Azure;
using Azure.Core;
using Azure.Storage;
using Azure.Storage.Blobs;
using Azure.Storage.Blobs.Models;
using Azure.Storage.Sas;
using CanvasCraft.Infrastructure.Exceptions;
using Microsoft.Extensions.Logging;

namespace CanvasCraft.Infrastructure.Services
{
    /// <summary>
    /// Contract for interacting with a blob-compatible object store (e.g., Azure Blob Storage, S3-compatible endpoints).
    /// All methods are asynchronous, cancellable, and safe for concurrent use.
    /// </summary>
    public interface IBlobStorageService
    {
        Task<Uri> UploadAsync(
            string container,
            string blobName,
            Stream content,
            string contentType,
            IDictionary<string, string>? metadata = null,
            CancellationToken cancellationToken = default);

        Task<Stream> DownloadAsync(
            string container,
            string blobName,
            CancellationToken cancellationToken = default);

        Task DeleteAsync(
            string container,
            string blobName,
            CancellationToken cancellationToken = default);

        Task<IReadOnlyCollection<BlobItem>> ListAsync(
            string container,
            string? prefix = null,
            CancellationToken cancellationToken = default);

        Task<Uri> GenerateReadSasAsync(
            string container,
            string blobName,
            DateTimeOffset expiresOn,
            CancellationToken cancellationToken = default);
    }

    /// <summary>
    /// Production-grade implementation of <see cref="IBlobStorageService"/> built on top of Azure Storage SDK (v12+).
    /// </summary>
    public sealed class BlobStorageService : IBlobStorageService
    {
        private readonly BlobServiceClient _blobServiceClient;
        private readonly ILogger<BlobStorageService> _logger;

        // Default permissions for generated SAS tokens (read-only).
        private static readonly BlobSasPermissions DefaultSasPermissions =
            BlobSasPermissions.Read | BlobSasPermissions.List;

        public BlobStorageService(
            BlobServiceClient blobServiceClient,
            ILogger<BlobStorageService> logger)
        {
            _blobServiceClient = blobServiceClient ?? throw new ArgumentNullException(nameof(blobServiceClient));
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
        }

        #region Public API

        public async Task<Uri> UploadAsync(
            string container,
            string blobName,
            Stream content,
            string contentType,
            IDictionary<string, string>? metadata = null,
            CancellationToken cancellationToken = default)
        {
            ValidateContainerAndBlobName(container, blobName);

            var containerClient = await GetOrCreateContainerAsync(container, cancellationToken).ConfigureAwait(false);
            var blobClient = containerClient.GetBlobClient(blobName);

            try
            {
                // UploadOptions to set HTTP headers & metadata atomically.
                var options = new BlobUploadOptions
                {
                    HttpHeaders = new BlobHttpHeaders
                    {
                        ContentType = contentType
                    },
                    Metadata = metadata
                };

                await blobClient.UploadAsync(content, options, cancellationToken).ConfigureAwait(false);
                _logger.LogInformation("Uploaded blob '{Blob}' to container '{Container}'.", blobName, container);
                return blobClient.Uri;
            }
            catch (RequestFailedException ex)
            {
                _logger.LogError(ex, "Failed to upload blob '{Blob}' to container '{Container}'.", blobName, container);
                throw new StorageOperationException("Upload failed.", ex);
            }
        }

        public async Task<Stream> DownloadAsync(
            string container,
            string blobName,
            CancellationToken cancellationToken = default)
        {
            ValidateContainerAndBlobName(container, blobName);

            var containerClient = _blobServiceClient.GetBlobContainerClient(container);
            var blobClient = containerClient.GetBlobClient(blobName);

            try
            {
                var response = await blobClient.DownloadStreamingAsync(cancellationToken: cancellationToken)
                                                .ConfigureAwait(false);

                _logger.LogDebug("Downloaded blob '{Blob}' from container '{Container}'.", blobName, container);
                return response.Value.Content;
            }
            catch (RequestFailedException ex) when (ex.Status == 404)
            {
                _logger.LogWarning("Blob '{Blob}' not found in container '{Container}'.", blobName, container);
                throw new BlobNotFoundException(container, blobName, ex);
            }
            catch (RequestFailedException ex)
            {
                _logger.LogError(ex, "Failed to download blob '{Blob}' from container '{Container}'.", blobName, container);
                throw new StorageOperationException("Download failed.", ex);
            }
        }

        public async Task DeleteAsync(
            string container,
            string blobName,
            CancellationToken cancellationToken = default)
        {
            ValidateContainerAndBlobName(container, blobName);

            var containerClient = _blobServiceClient.GetBlobContainerClient(container);
            var blobClient = containerClient.GetBlobClient(blobName);

            try
            {
                await blobClient.DeleteIfExistsAsync(
                    DeleteSnapshotsOption.IncludeSnapshots,
                    cancellationToken: cancellationToken).ConfigureAwait(false);

                _logger.LogInformation("Deleted blob '{Blob}' (if existed) from container '{Container}'.", blobName, container);
            }
            catch (RequestFailedException ex)
            {
                _logger.LogError(ex, "Failed to delete blob '{Blob}' from container '{Container}'.", blobName, container);
                throw new StorageOperationException("Delete failed.", ex);
            }
        }

        public async Task<IReadOnlyCollection<BlobItem>> ListAsync(
            string container,
            string? prefix = null,
            CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(container))
                throw new ArgumentException("Container name cannot be null or empty.", nameof(container));

            var containerClient = _blobServiceClient.GetBlobContainerClient(container);

            try
            {
                var results = new List<BlobItem>();
                await foreach (var item in containerClient
                                           .GetBlobsAsync(prefix: prefix, cancellationToken: cancellationToken)
                                           .ConfigureAwait(false))
                {
                    results.Add(item);
                }

                _logger.LogDebug("Listed {Count} blob(s) in container '{Container}' with prefix '{Prefix}'.",
                                 results.Count, container, prefix);

                return results;
            }
            catch (RequestFailedException ex)
            {
                _logger.LogError(ex, "Failed to list blobs in container '{Container}'.", container);
                throw new StorageOperationException("Listing failed.", ex);
            }
        }

        public async Task<Uri> GenerateReadSasAsync(
            string container,
            string blobName,
            DateTimeOffset expiresOn,
            CancellationToken cancellationToken = default)
        {
            ValidateContainerAndBlobName(container, blobName);

            var containerClient = _blobServiceClient.GetBlobContainerClient(container);
            var blobClient = containerClient.GetBlobClient(blobName);

            // Ensure the blob actually exists before generating a SAS.
            if (!await blobClient.ExistsAsync(cancellationToken).ConfigureAwait(false))
            {
                throw new BlobNotFoundException(container, blobName);
            }

            // If the client was created with StorageSharedKeyCredential we can build a SAS directly.
            if (_blobServiceClient.CanGenerateAccountSasUri)
            {
                var sasUri = blobClient.GenerateSasUri(
                    permissions: DefaultSasPermissions,
                    expiresOn: expiresOn);

                _logger.LogDebug("Generated SAS URI for blob '{Blob}' in container '{Container}'.", blobName, container);
                return sasUri;
            }

            throw new InvalidOperationException(
                "BlobServiceClient must be created with StorageSharedKeyCredential to generate SAS URIs.");
        }

        #endregion

        #region Private Helpers

        private async Task<BlobContainerClient> GetOrCreateContainerAsync(
            string container,
            CancellationToken cancellationToken)
        {
            var containerClient = _blobServiceClient.GetBlobContainerClient(container);

            try
            {
                await containerClient.CreateIfNotExistsAsync(
                    publicAccessType: PublicAccessType.None,
                    cancellationToken: cancellationToken).ConfigureAwait(false);
            }
            catch (RequestFailedException ex) when (ex.ErrorCode.Equals("ContainerAlreadyExists", StringComparison.OrdinalIgnoreCase))
            {
                // benign race condition when container already exists
            }

            return containerClient;
        }

        private static void ValidateContainerAndBlobName(string container, string blobName)
        {
            if (string.IsNullOrWhiteSpace(container))
                throw new ArgumentException("Container name cannot be null or empty.", nameof(container));

            if (string.IsNullOrWhiteSpace(blobName))
                throw new ArgumentException("Blob name cannot be null or empty.", nameof(blobName));
        }

        #endregion
    }

    #region Custom Exception Types

    /// <summary>
    /// Base class for domain-specific storage failures.
    /// </summary>
    public class StorageOperationException : Exception
    {
        public StorageOperationException(string? message, Exception? innerException = null)
            : base(message, innerException) { }
    }

    /// <summary>
    /// Exception thrown when a requested blob is not found.
    /// </summary>
    public sealed class BlobNotFoundException : StorageOperationException
    {
        public string Container { get; }
        public string Blob { get; }

        public BlobNotFoundException(string container, string blob, Exception? innerException = null)
            : base($"Blob '{blob}' not found in container '{container}'.", innerException)
        {
            Container = container;
            Blob = blob;
        }
    }

    #endregion
}
```