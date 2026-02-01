#include "services/FileUploadService.h"

#include <algorithm>
#include <chrono>
#include <exception>
#include <filesystem>
#include <fstream>
#include <future>
#include <iomanip>
#include <memory>
#include <mutex>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>

#include "config/Config.h"
#include "core/EventBus.h"
#include "core/Logger.h"
#include "crypto/Hasher.h"
#include "repository/FileMetadataRepository.h"
#include "storage/IStorageAdapter.h"
#include "util/MimeUtils.h"

namespace mbs::services
{
using namespace std::chrono_literals;
namespace fs = std::filesystem;

/*
 * Internal helpers / constants
 * ------------------------------------------------------------------ */
namespace
{
constexpr std::size_t kDefaultBufferSize = 1_MiB;   // Chunk size for streaming copies
constexpr std::chrono::milliseconds kDefaultProgressTick = 500ms;  // Time between progress callbacks

// Random ID generator for temp files
std::string generateTempId()
{
    static thread_local std::mt19937_64 rng{ std::random_device{}() };
    static constexpr char alphabet[] =
        "0123456789"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz";
    std::uniform_int_distribution<std::size_t> dist(0, sizeof(alphabet) - 2);

    std::string id(16, '\0');
    std::generate(id.begin(), id.end(), [&] { return alphabet[dist(rng)]; });

    return id;
}

// RAII temp file remover
struct ScopedTempFile
{
    explicit ScopedTempFile(fs::path p) : path{ std::move(p) } {}
    ~ScopedTempFile() noexcept
    {
        try
        {
            if (!path.empty() && fs::exists(path))
            {
                fs::remove(path);
            }
        }
        catch (...) {} // NOLINT(readability-else-after-return)
    }
    fs::path path;
};

} // anonymous namespace

/*
 * Implementation: Pimpl to keep header clean
 * ------------------------------------------------------------------ */
class FileUploadService::Impl
{
public:
    Impl(std::shared_ptr<storage::IStorageAdapter> storageAdapter,
         std::shared_ptr<repository::FileMetadataRepository> metadataRepo,
         std::shared_ptr<core::EventBus> eventBus)
        : storageAdapter_(std::move(storageAdapter))
        , metadataRepo_(std::move(metadataRepo))
        , eventBus_(std::move(eventBus))
        , conf_(config::Config::instance())
    {
        if (!storageAdapter_ || !metadataRepo_ || !eventBus_)
            throw std::invalid_argument("FileUploadService dependencies must not be null");
    }

    std::future<FileDescriptor> uploadAsync(const UploadRequest& request,
                                            ProgressCallback progressCb);

private:
    // Non-copyable
    Impl(const Impl&) = delete;
    Impl& operator=(const Impl&) = delete;

    struct InternalProgressState
    {
        std::mutex mtx;
        std::size_t bytesTransferred{};
        std::chrono::steady_clock::time_point lastCb =
            std::chrono::steady_clock::now();
    };

    FileDescriptor processUpload(const UploadRequest& request,
                                 ProgressCallback& progressCb);

    std::shared_ptr<storage::IStorageAdapter> storageAdapter_;
    std::shared_ptr<repository::FileMetadataRepository> metadataRepo_;
    std::shared_ptr<core::EventBus> eventBus_;
    const config::Config& conf_;
};

/*
 * Public API
 * ------------------------------------------------------------------ */
FileUploadService::FileUploadService(std::shared_ptr<storage::IStorageAdapter> storageAdapter,
                                     std::shared_ptr<repository::FileMetadataRepository> metadataRepo,
                                     std::shared_ptr<core::EventBus> eventBus)
    : pImpl_(std::make_unique<Impl>(std::move(storageAdapter),
                                    std::move(metadataRepo),
                                    std::move(eventBus)))
{
}

FileUploadService::~FileUploadService() = default;

std::future<FileDescriptor> FileUploadService::uploadAsync(const UploadRequest& request,
                                                           ProgressCallback progressCb)
{
    return pImpl_->uploadAsync(request, std::move(progressCb));
}

/*
 * Impl details
 * ------------------------------------------------------------------ */
std::future<FileDescriptor> FileUploadService::Impl::uploadAsync(const UploadRequest& request,
                                                                 ProgressCallback progressCb)
{
    // Launch in thread pool
    return std::async(std::launch::async, [this, request, cb = std::move(progressCb)]() mutable {
        try
        {
            return processUpload(request, cb);
        }
        catch (...)
        {
            if (cb)
            {
                cb(ProgressEvent{ .phase = Phase::Failed,
                                  .bytesTransferred = 0,
                                  .totalBytes = request.contentLength,
                                  .message = "Upload failed" });
            }
            throw; // rethrow for caller
        }
    });
}

FileDescriptor FileUploadService::Impl::processUpload(const UploadRequest& request,
                                                      ProgressCallback& progressCb)
{
    // --- Validation ----------------------------------------------------------
    if (!request.dataStream)
        throw std::invalid_argument("UploadRequest must contain dataStream");

    if (request.contentLength == 0)
        throw std::invalid_argument("Cannot upload empty file");

    const auto allowed = conf_.getVector<std::string>("upload.allowed_mime_types");
    if (!allowed.empty() &&
        std::find(allowed.begin(), allowed.end(), request.contentType) == allowed.end())
    {
        throw std::runtime_error("MIME type not allowed: " + request.contentType);
    }

    const auto maxSize = conf_.get<std::size_t>("upload.max_size_bytes", 50_MiB);
    if (request.contentLength > maxSize)
    {
        std::ostringstream oss;
        oss << "File exceeds maximum allowed size (" << request.contentLength << " > "
            << maxSize << ")";
        throw std::runtime_error(oss.str());
    }

    // --- Prepare temp file ---------------------------------------------------
    fs::path tempDir = conf_.get<std::string>("upload.temp_dir", fs::temp_directory_path().string());
    fs::create_directories(tempDir);

    const fs::path tempPath = tempDir / (generateTempId() + ".upload.tmp");
    ScopedTempFile scopedTemp(tempPath);

    std::ofstream ofs(tempPath, std::ios::binary);
    if (!ofs)
        throw std::runtime_error("Unable to open temp file for writing");

    // --- Hash + copy ---------------------------------------------------------
    crypto::Hasher hasher(crypto::HashAlgorithm::SHA256);
    InternalProgressState pstate;

    std::vector<char> buffer(kDefaultBufferSize);
    std::size_t totalRead = 0;

    while (!request.dataStream->eof())
    {
        request.dataStream->read(buffer.data(), buffer.size());
        std::streamsize readBytes = request.dataStream->gcount();
        if (readBytes <= 0)
            break;

        ofs.write(buffer.data(), readBytes);
        hasher.update(buffer.data(), static_cast<std::size_t>(readBytes));

        totalRead += static_cast<std::size_t>(readBytes);

        // Progress tick
        {
            std::scoped_lock lock(pstate.mtx);
            pstate.bytesTransferred = totalRead;
            const auto now = std::chrono::steady_clock::now();
            if (progressCb && now - pstate.lastCb >= kDefaultProgressTick)
            {
                pstate.lastCb = now;
                progressCb(ProgressEvent{ .phase = Phase::Uploading,
                                          .bytesTransferred = totalRead,
                                          .totalBytes = request.contentLength });
            }
        }
    }

    ofs.flush();
    ofs.close();

    if (totalRead != request.contentLength)
    {
        std::ostringstream oss;
        oss << "Read mismatch: expected " << request.contentLength << ", got " << totalRead;
        throw std::runtime_error(oss.str());
    }

    // --- Persist via storage adapter ----------------------------------------
    const std::string checksum = hasher.finalizeHex();

    const std::string datePath = [] {
        const auto now = std::chrono::system_clock::now();
        std::time_t t = std::chrono::system_clock::to_time_t(now);
        std::tm tm{};
#ifdef _WIN32
        localtime_s(&tm, &t);
#else
        localtime_r(&t, &tm);
#endif
        std::ostringstream oss;
        oss << std::put_time(&tm, "%Y/%m/%d");
        return oss.str();
    }();

    fs::path targetPath =
        fs::path("uploads") / datePath / (checksum + fs::path(request.originalFilename).extension().string());

    // Provide delegate progress hooking into the same cb
    storage::IStorageAdapter::ProgressDelegate storageDelegate =
        [&, total = request.contentLength](std::size_t transferred) {
            if (progressCb)
            {
                progressCb(ProgressEvent{ .phase = Phase::Persisting,
                                          .bytesTransferred = transferred,
                                          .totalBytes = total });
            }
        };

    storageAdapter_->upload(tempPath, targetPath, storageDelegate);

    // --- Build descriptor & metadata ----------------------------------------
    const auto uri = storageAdapter_->uriForPath(targetPath);

    FileDescriptor desc;
    desc.id = checksum;
    desc.fileName = request.originalFilename;
    desc.mimeType = request.contentType;
    desc.sizeBytes = request.contentLength;
    desc.checksumSha256 = checksum;
    desc.uri = uri;
    desc.uploadedAt = std::chrono::system_clock::now();
    desc.uploaderUserId = request.uploaderId;

    metadataRepo_->insert(desc);

    // --- Publish event -------------------------------------------------------
    eventBus_->publish(FileUploadedEvent{ desc });

    if (progressCb)
    {
        progressCb(ProgressEvent{ .phase = Phase::Completed,
                                  .bytesTransferred = desc.sizeBytes,
                                  .totalBytes = desc.sizeBytes,
                                  .uri = desc.uri });
    }

    return desc;
}

} // namespace mbs::services