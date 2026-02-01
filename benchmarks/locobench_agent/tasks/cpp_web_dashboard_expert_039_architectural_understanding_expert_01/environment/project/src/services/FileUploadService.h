#pragma once
/**
 *  MosaicBoard Studio
 *  File: FileUploadService.h
 *
 *  Description:
 *      Service-layer abstraction responsible for validating, storing and
 *      serving user-supplied files (datasets, static images, audio stems,
 *      plug-in binaries, etc.).  
 *
 *      The service is intentionally backend-agnostic – concrete storage
 *      strategies (e.g. local disk, Amazon S3, Azure Blob, in-memory cache)
 *      can be registered at runtime via dependency-injection.  All
 *      heavy-lifting (chunked uploads, MIME sniffing, deduplication,
 *      checksum validation, virus scanning, CDN invalidations) is delegated
 *      to strategy objects that implement `IStorageStrategy`.
 *
 *      Thread-safety: public entry points are re-entrant; internal state is
 *      guarded by a shared mutex allowing parallel reads while writes are
 *      exclusive.
 *
 *  Author: MosaicBoard Studio Team
 *  License: MIT
 */

#include <cstdint>
#include <filesystem>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <string>
#include <system_error>
#include <unordered_map>
#include <utility>
#include <vector>

namespace mbs {       // MosaicBoard Studio namespace
namespace services {  // Service-layer namespace

// ---------------------------------------------------------------------------
// Helper aliases & forward declarations
// ---------------------------------------------------------------------------
using ByteBuffer       = std::vector<std::uint8_t>;
using ProgressCallback = std::function<void(std::uint64_t bytesSent,
                                            std::uint64_t totalBytes)>;

/**
 *  StorageLocation:
 *      Represents the final canonical URI where an uploaded artifact resides.
 */
struct StorageLocation
{
    std::string scheme;   // "file", "s3", "gs", ...
    std::string bucket;   // disk path, S3 bucket name, etc.
    std::string object;   // relative object key
    std::string toString() const;
};

/**
 *  FileUploadRequest:
 *      Data holder describing what is going to be uploaded.
 */
struct FileUploadRequest
{
    std::string        originalFilename;   // Client-side filename, UTF-8.
    std::string        contentType;        // MIME type.
    std::uint64_t      contentLength = 0;  // In bytes; 0 if unknown (streaming).
    std::optional<ByteBuffer> payload;     // In-memory uploads; mutually
                                           // exclusive with inputPath.
    std::optional<std::filesystem::path> inputPath; // For zero-copy disk move.
    bool               computeChecksum = true;      // SHA-256 by default.
};

/**
 *  FileUploadResponse:
 *      Returned once a file has been safely persisted.
 */
struct FileUploadResponse
{
    StorageLocation       location;
    std::optional<std::string> checksum;     // SHA-256 hex digest
    std::uint64_t         bytesStored = 0;
};

// ---------------------------------------------------------------------------
// Exception types
// ---------------------------------------------------------------------------
class FileUploadException : public std::runtime_error
{
public:
    explicit FileUploadException(const std::string& what)
        : std::runtime_error(what)
    {}
};

class StorageUnavailableException : public FileUploadException
{
public:
    using FileUploadException::FileUploadException;
};

class ValidationFailedException : public FileUploadException
{
public:
    using FileUploadException::FileUploadException;
};

// ---------------------------------------------------------------------------
// Strategy interface
// ---------------------------------------------------------------------------
class IStorageStrategy
{
public:
    virtual ~IStorageStrategy() = default;

    /**
     * Persist `request` into the backend.  This method should be non-blocking
     * and return a future that resolves when the upload is durable.
     */
    virtual std::future<FileUploadResponse>
    upload(const FileUploadRequest& request,
           ProgressCallback         onProgress) = 0;

    /**
     * Remove an object identified by a canonical URI previously returned by
     * `upload`. Returns `false` if the object did not exist.
     */
    virtual bool remove(const StorageLocation& uri, std::error_code& ec) = 0;

    /**
     * Small human-readable descriptor (e.g. "LocalDisk", "S3-eu-west-1").
     */
    [[nodiscard]] virtual std::string_view name() const noexcept = 0;
};

// ---------------------------------------------------------------------------
// FileUploadService
// ---------------------------------------------------------------------------
class FileUploadService
{
public:
    /**
     * Register a storage backend.  The first backend registered becomes the
     * default unless another is explicitly set.
     *
     * Thread-safe.
     */
    void registerStrategy(std::shared_ptr<IStorageStrategy> strategy);

    /**
     * Designate the default backend for subsequent uploads.
     */
    void setDefaultStrategy(std::string_view strategyName);

    /**
     * Asynchronously validate and store data according to `request`.
     *
     *  ‑ Sanitises filename and ensures allowed MIME types / size limits
     *  ‑ Streams or moves the payload into the storage backend
     *  ‑ Produces cryptographic checksum (optional)
     *
     * Throws: ValidationFailedException, StorageUnavailableException
     *
     * Thread-safe.
     */
    std::future<FileUploadResponse>
    uploadFile(const FileUploadRequest& request,
               ProgressCallback         onProgress = {});

    /**
     * Remove the object at `uri`. Returns false if the backing strategy could
     * not find the object.  Throws StorageUnavailableException on connectivity
     * or internal errors.
     *
     * Thread-safe.
     */
    bool deleteFile(const StorageLocation& uri);

private:
    // -----------------------------------------------------------------------
    // Validation helpers
    // -----------------------------------------------------------------------
    void validateRequest(const FileUploadRequest& req) const;

    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------
    mutable std::shared_mutex                              _mutex;
    std::unordered_map<std::string, std::shared_ptr<IStorageStrategy>> _strategies;
    std::string                                            _defaultStrategy;
};

// ---------------------------------------------------------------------------
// Inline implementations
// ---------------------------------------------------------------------------

inline std::string StorageLocation::toString() const
{
    return scheme + "://" + bucket + "/" + object;
}

inline void FileUploadService::registerStrategy(std::shared_ptr<IStorageStrategy> strategy)
{
    if (!strategy)
        throw std::invalid_argument("strategy must not be null");

    std::unique_lock lock(_mutex);
    const std::string key{strategy->name()};
    _strategies[key] = std::move(strategy);
    if (_defaultStrategy.empty())
        _defaultStrategy = key;
}

inline void FileUploadService::setDefaultStrategy(std::string_view strategyName)
{
    std::shared_lock readLock(_mutex);
    if (_strategies.find(std::string(strategyName)) == _strategies.end())
        throw std::invalid_argument("Unknown storage strategy: " + std::string(strategyName));
    readLock.unlock();

    std::unique_lock writeLock(_mutex);
    _defaultStrategy = std::string(strategyName);
}

inline void FileUploadService::validateRequest(const FileUploadRequest& req) const
{
    constexpr std::uint64_t kMaxUploadBytes = 250_MiB; // Macro defined elsewhere

    if (req.originalFilename.empty())
        throw ValidationFailedException("Filename must not be empty");

    if (req.contentLength > kMaxUploadBytes)
        throw ValidationFailedException("File exceeds maximum allowed size");

    if (!req.payload && !req.inputPath)
        throw ValidationFailedException("No payload or inputPath specified");
}

inline std::future<FileUploadResponse>
FileUploadService::uploadFile(const FileUploadRequest& request,
                              ProgressCallback         onProgress)
{
    validateRequest(request);

    std::shared_ptr<IStorageStrategy> strategy;
    {
        std::shared_lock lock(_mutex);
        if (_defaultStrategy.empty())
            throw StorageUnavailableException("No storage strategy registered");

        strategy = _strategies.at(_defaultStrategy);
    }
    return strategy->upload(request, std::move(onProgress));
}

inline bool FileUploadService::deleteFile(const StorageLocation& uri)
{
    // Parse scheme from URI to locate the correct backend
    const auto schemeSeparator = uri.scheme;
    std::shared_ptr<IStorageStrategy> strategy;
    {
        std::shared_lock lock(_mutex);
        auto it = _strategies.find(schemeSeparator);
        if (it == _strategies.end())
            throw StorageUnavailableException("No backend registered for scheme: " + schemeSeparator);
        strategy = it->second;
    }

    std::error_code ec;
    const bool ok = strategy->remove(uri, ec);
    if (ec)
        throw StorageUnavailableException("Deletion failed: " + ec.message());
    return ok;
}

} // namespace services
} // namespace mbs