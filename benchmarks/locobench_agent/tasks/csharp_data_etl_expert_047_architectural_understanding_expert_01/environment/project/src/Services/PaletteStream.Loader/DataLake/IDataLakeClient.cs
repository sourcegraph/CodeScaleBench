```csharp
using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

namespace PaletteStream.Loader.DataLake
{
    /// <summary>
    ///     Describes the contract for interacting with the logical Data Lake “canvas”.
    ///     This abstraction shields the rest of the ETL pipeline from the concrete
    ///     storage implementation (Azure Data Lake Gen2, AWS S3, GCP GCS, on-prem HDFS, etc.).
    ///     
    ///     All operations are asynchronous, cancellable, and designed to work in
    ///     high-throughput / high-concurrency scenarios typical for stream-enhanced ETL.
    ///     
    ///     Thread-safety:
    ///         • Implementations MUST be safe for concurrent usage across threads.
    ///     
    ///     Error handling:
    ///         • Implementations SHOULD throw <see cref="DataLakeException"/> for
    ///           domain-specific failures (authorization, path not found, etc.) in order
    ///           to allow consistent error recovery across micro-services.
    /// </summary>
    public interface IDataLakeClient : IAsyncDisposable
    {
        #region Ingestion / Upload

        /// <summary>
        ///     Uploads a data stream to the Data Lake.
        /// </summary>
        /// <param name="destinationPath">
        ///     Logical destination path (e.g., "/raw/events/2023/10/19/part-0001.json.gz").
        ///     MUST be fully qualified inside the lake namespace.
        /// </param>
        /// <param name="content">Readable data stream. The stream WILL be disposed by the caller.</param>
        /// <param name="overwrite">
        ///     When <c>true</c>, an existing file at <paramref name="destinationPath"/> will be replaced.
        ///     When <c>false</c>, and the file exists, <see cref="DataLakeException"/>
        ///     with <see cref="DataLakeErrorCode.AlreadyExists"/> MUST be thrown.
        /// </param>
        /// <param name="cancellationToken">Operation cancellation token.</param>
        Task UploadAsync(
            string destinationPath,
            Stream content,
            bool overwrite = false,
            CancellationToken cancellationToken = default);

        #endregion

        #region Extraction / Download

        /// <summary>
        ///     Downloads data from the lake as a stream.
        /// </summary>
        /// <param name="sourcePath">Fully-qualified lake path.</param>
        /// <param name="cancellationToken">Operation cancellation token.</param>
        /// <returns>
        ///     A readable <see cref="Stream"/> positioned at offset 0. The caller is responsible for disposing it.
        /// </returns>
        Task<Stream> DownloadAsync(
            string sourcePath,
            CancellationToken cancellationToken = default);

        #endregion

        #region Discovery

        /// <summary>
        ///     Lists immediate children (files and folders) of a given lake directory path.
        /// </summary>
        /// <param name="directoryPath">Lake folder path (must end with a forward slash).</param>
        /// <param name="cancellationToken">Operation cancellation token.</param>
        /// <returns>
        ///     A collection of <see cref="DataLakeEntry"/> containing metadata for each child.
        /// </returns>
        Task<IReadOnlyCollection<DataLakeEntry>> ListAsync(
            string directoryPath,
            CancellationToken cancellationToken = default);

        /// <summary>
        ///     Gets metadata for a single file or folder.
        /// </summary>
        Task<DataLakeEntry> GetMetadataAsync(
            string path,
            CancellationToken cancellationToken = default);

        /// <summary>
        ///     Checks whether the specified path exists.
        /// </summary>
        Task<bool> ExistsAsync(
            string path,
            CancellationToken cancellationToken = default);

        #endregion

        #region Partition Utilities

        /// <summary>
        ///     Generates a date-partitioned lake path for the provided base folder:
        ///         e.g. base="/raw/events/" → "/raw/events/2023/10/19/"
        /// </summary>
        /// <param name="baseFolder">The logical base folder (trailing slash optional).</param>
        /// <param name="utcTimestamp">DateTime in UTC used to build the partition.</param>
        /// <returns>The generated folder path ending with a forward slash.</returns>
        string BuildDatePartition(string baseFolder, DateTime utcTimestamp);

        #endregion

        #region Concurrency & Locks

        /// <summary>
        ///     Attempts to acquire a distributed “lease” on a path. Useful for
        ///     preventing concurrent writers in multi-instance microservice deployments.
        /// </summary>
        /// <param name="path">Target file or folder path.</param>
        /// <param name="ttl">Lease time-to-live. After expiration, the lock is released automatically.</param>
        /// <param name="cancellationToken">Operation cancellation token.</param>
        /// <returns>
        ///     An <see cref="IDataLakeLease"/> representing the acquired lease,
        ///     or <c>null</c> if the lease could not be obtained.
        /// </returns>
        Task<IDataLakeLease?> AcquireLeaseAsync(
            string path,
            TimeSpan ttl,
            CancellationToken cancellationToken = default);

        #endregion

        #region Deletion

        /// <summary>
        ///     Deletes a single file or folder. If deleting a folder, the behavior
        ///     is implementation-specific (recursive vs non-recursive). Clients SHOULD
        ///     consult <see cref="Capabilities"/> to understand supported behaviors.
        /// </summary>
        /// <param name="path">File or folder path.</param>
        /// <param name="recursive">
        ///     When <c>true</c>, delete entire subtree. Unsupported mode SHOULD throw
        ///     <see cref="NotSupportedException"/>.
        /// </param>
        /// <param name="cancellationToken">Operation cancellation token.</param>
        Task DeleteAsync(
            string path,
            bool recursive = false,
            CancellationToken cancellationToken = default);

        #endregion

        #region Capabilities & Health

        /// <summary>
        ///     Describes what operations / behaviors the underlying lake implementation supports.
        /// </summary>
        DataLakeCapabilities Capabilities { get; }

        /// <summary>
        ///     Performs service health check (e.g., ping the storage endpoint).
        /// </summary>
        /// <exception cref="DataLakeException">When the service is unhealthy.</exception>
        Task CheckHealthAsync(CancellationToken cancellationToken = default);

        #endregion
    }

    /// <summary>
    ///     Information returned by <see cref="IDataLakeClient.ListAsync"/> and
    ///     <see cref="IDataLakeClient.GetMetadataAsync"/>.
    /// </summary>
    public sealed record DataLakeEntry(
        string Path,
        bool IsDirectory,
        long? SizeInBytes,
        DateTimeOffset CreatedUtc,
        DateTimeOffset? LastModifiedUtc);

    /// <summary>
    ///     Represents a distributed lease acquired via <see cref="IDataLakeClient.AcquireLeaseAsync"/>.
    /// </summary>
    public interface IDataLakeLease : IAsyncDisposable
    {
        /// <summary>
        ///     Path that the lease is associated with.
        /// </summary>
        string Path { get; }

        /// <summary>
        ///     Unique lease identifier (GUID, eTag, etc.).
        /// </summary>
        string LeaseId { get; }

        /// <summary>
        ///     Renews the lease for the same <see cref="TimeSpan"/> used during acquisition.
        /// </summary>
        Task RenewAsync(CancellationToken cancellationToken = default);
    }

    /// <summary>
    ///     Describes the feature set supported by an <see cref="IDataLakeClient"/> implementation.
    ///     Bit-flags allow composing capabilities.
    /// </summary>
    [Flags]
    public enum DataLakeCapabilities
    {
        None = 0,

        /// <summary>
        ///     Supports recursive folder deletion.
        /// </summary>
        RecursiveDelete = 1 << 0,

        /// <summary>
        ///     Supports distributed locking / leasing.
        /// </summary>
        Leasing = 1 << 1,

        /// <summary>
        ///     Supports server-side append (streaming uploads).
        /// </summary>
        Append = 1 << 2,

        /// <summary>
        ///     Supports re-hydrating archived data (cold → hot tiers).
        /// </summary>
        Rehydrate = 1 << 3
    }

    /// <summary>
    ///     Data-lake-specific exception. Provides an error code in addition to the message.
    /// </summary>
    public sealed class DataLakeException : Exception
    {
        public DataLakeException(
            DataLakeErrorCode errorCode,
            string message,
            Exception? innerException = null)
            : base(message, innerException) =>
            ErrorCode = errorCode;

        public DataLakeErrorCode ErrorCode { get; }
    }

    /// <summary>
    ///     Enumerates canonical error codes exposed by <see cref="DataLakeException"/>.
    /// </summary>
    public enum DataLakeErrorCode
    {
        Unknown = 0,
        NotFound,
        AlreadyExists,
        Unauthorized,
        QuotaExceeded,
        LeaseConflict,
        InvalidPath,
        ServiceUnavailable
    }
}
```