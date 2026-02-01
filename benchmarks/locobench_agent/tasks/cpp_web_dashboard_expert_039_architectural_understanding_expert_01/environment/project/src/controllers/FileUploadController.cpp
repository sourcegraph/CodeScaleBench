```cpp
/****************************************************************************************
 *  FileUploadController.cpp
 *
 *  MosaicBoard Studio – Web Dashboard
 *  ----------------------------------------------------------------------------
 *  Copyright (c) MosaicBoard
 *
 *  Description:
 *      REST-controller responsible for handling user file uploads.  The controller
 *      authenticates the caller, streams the incoming multipart/form-data to the
 *      configured StorageService, persists meta-data through FileRepository, and
 *      publishes an UploadCompletedEvent on the global EventBus once the upload
 *      succeeds.  Errors are translated into structured JSON responses.
 *
 *  NOTE:
 *      This compilation unit purposefully depends on the internal HTTP / Service
 *      abstractions provided by MosaicBoard Studio.  Those headers are assumed to
 *      be present elsewhere in the code-base.
 ****************************************************************************************/

#include "FileUploadController.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <filesystem>
#include <future>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>

#include "core/http/HttpCodes.hpp"
#include "core/http/HttpRequest.hpp"
#include "core/http/HttpResponse.hpp"
#include "core/security/AuthContext.hpp"
#include "core/security/AuthService.hpp"
#include "models/FileUpload.hpp"
#include "repositories/FileRepository.hpp"
#include "services/events/EventBus.hpp"
#include "services/storage/StorageService.hpp"
#include "utils/Clock.hpp"
#include "utils/Json.hpp"
#include "utils/Logger.hpp"
#include "utils/UUID.hpp"

namespace fs = std::filesystem;

namespace MosaicBoard::Controllers
{

using namespace std::string_literals;

static constexpr std::size_t MAX_UPLOAD_SIZE       = 500_MiB;   // <- compile-time suffix via utils header
static constexpr std::size_t MAX_FILENAME_LENGTH   = 255;
static constexpr std::array<std::string_view, 6> BLOCKED_EXTENSIONS{
    ".exe", ".bat", ".cmd", ".com", ".scr", ".jar"
};

/* ========================================================================================
 *  Helpers
 * ===================================================================================== */

/**
 * Returns true if the file extension of `name` is black-listed.
 */
static bool isBlockedExtension(std::string_view name)
{
    const auto ext = fs::path{ name }.extension().string();
    return std::any_of(BLOCKED_EXTENSIONS.begin(), BLOCKED_EXTENSIONS.end(),
                       [&ext](std::string_view blocked) { return utils::str::iequals(ext, blocked); });
}

/* ========================================================================================
 *  Ctor / Dtor
 * ===================================================================================== */

FileUploadController::FileUploadController(std::shared_ptr<core::security::AuthService> authSvc,
                                           std::shared_ptr<services::storage::StorageService> storageSvc,
                                           std::shared_ptr<repositories::FileRepository> fileRepo,
                                           std::shared_ptr<services::events::EventBus> evtBus) :
    m_authService{ std::move(authSvc) },
    m_storageService{ std::move(storageSvc) },
    m_fileRepository{ std::move(fileRepo) },
    m_eventBus{ std::move(evtBus) }
{
    if (!m_authService || !m_storageService || !m_fileRepository || !m_eventBus)
    {
        throw std::invalid_argument("FileUploadController – missing required service");
    }
}

/* ========================================================================================
 *  Public API
 * ===================================================================================== */

void FileUploadController::registerRoutes(core::http::IRouter& router)
{
    router.addRoute(core::http::Method::POST,  "/api/v1/uploads",        this, &FileUploadController::postUpload);
    router.addRoute(core::http::Method::GET,   "/api/v1/uploads/{uuid}", this, &FileUploadController::getStatus);
}

/* ------------------------------------------------------------------------------------- *
 |  POST /api/v1/uploads
 * ------------------------------------------------------------------------------------- */

core::http::HttpResponse FileUploadController::postUpload(const core::http::HttpRequest& req)
{
    try
    {
        // --------------------------------------------------------------------
        // Step 1. Authenticate caller
        // --------------------------------------------------------------------
        auto ctx = m_authService->requireAuthentication(req);
        if (!ctx)
        {
            return core::http::HttpResponse::unauthorized("Authentication required");
        }

        // --------------------------------------------------------------------
        // Step 2. Validate incoming multipart / streaming body
        // --------------------------------------------------------------------
        const auto maybeFilePart = req.file("file"); // ← HTTP framework abstraction
        if (!maybeFilePart)
        {
            return core::http::HttpResponse::badRequest("No file part named 'file' in form-data");
        }

        const auto& filePart = *maybeFilePart;
        if (filePart.size > MAX_UPLOAD_SIZE)
        {
            return core::http::HttpResponse::payloadTooLarge(
                fmt::format("File exceeds maximum allowed size ({} MiB)", MAX_UPLOAD_SIZE / (1024 * 1024)));
        }

        if (filePart.filename.empty() || filePart.filename.size() > MAX_FILENAME_LENGTH)
        {
            return core::http::HttpResponse::badRequest("Invalid filename");
        }

        if (isBlockedExtension(filePart.filename))
        {
            return core::http::HttpResponse::badRequest("File type not allowed");
        }

        // --------------------------------------------------------------------
        // Step 3. Generate meta-data record
        // --------------------------------------------------------------------
        models::FileUpload meta;
        meta.id              = utils::UUID::v4();
        meta.originalName    = filePart.filename;
        meta.mimeType        = filePart.contentType;
        meta.sizeBytes       = filePart.size;
        meta.storagePath     = "";           // resolved below
        meta.uploaderId      = ctx->user().id();
        meta.createdAt       = utils::Clock::nowUtc();
        meta.status          = models::FileUpload::Status::PROCESSING;

        // Optimistically create DB record (status = PROCESSING)
        m_fileRepository->create(meta);

        // --------------------------------------------------------------------
        // Step 4. Asynchronously stream to StorageService
        // --------------------------------------------------------------------
        const auto uploadTask = std::async(std::launch::async, [this, meta, &filePart]() mutable {
            try
            {
                const fs::path storagePath = m_storageService->generateObjectPath(meta.id, filePart.filename);
                m_storageService->storeStream(storagePath, filePart.stream);
                meta.storagePath = storagePath.string();
                meta.status      = models::FileUpload::Status::READY;

                m_fileRepository->update(meta);
                m_eventBus->publish(services::events::UploadCompletedEvent{ meta });
            }
            catch (const std::exception& ex)
            {
                // Handle failure – mark as errored, propagate for logging
                meta.status = models::FileUpload::Status::FAILED;
                m_fileRepository->update(meta);
                m_eventBus->publish(services::events::UploadFailedEvent{ meta.id, ex.what() });

                throw; // ensures outer catch logs the message
            }
        });

        // --------------------------------------------------------------------
        // Step 5. Immediately respond with 202 Accepted
        // --------------------------------------------------------------------
        nlohmann::json body{
            { "upload_id", meta.id },
            { "status",    "PROCESSING" }
        };
        return core::http::HttpResponse::accepted(body.dump(), "application/json");
    }
    catch (const std::exception& ex)
    {
        utils::Logger::error("FileUploadController::postUpload – {}", ex.what());
        return core::http::HttpResponse::internalServerError("Unexpected server error");
    }
}

/* ------------------------------------------------------------------------------------- *
 |  GET /api/v1/uploads/{uuid}
 * ------------------------------------------------------------------------------------- */

core::http::HttpResponse FileUploadController::getStatus(const core::http::HttpRequest& req)
{
    try
    {
        // Require auth (but allow the file owner or admin to query)
        auto ctx = m_authService->requireAuthentication(req);
        if (!ctx)
        {
            return core::http::HttpResponse::unauthorized("Authentication required");
        }

        const auto uploadId = req.pathParameter("uuid");
        if (!utils::UUID::isValid(uploadId))
        {
            return core::http::HttpResponse::badRequest("Invalid upload id");
        }

        const auto maybeUpload = m_fileRepository->findById(uploadId);
        if (!maybeUpload)
        {
            return core::http::HttpResponse::notFound("Upload not found");
        }

        const auto& upload = *maybeUpload;
        if (upload.uploaderId != ctx->user().id() && !ctx->user().isAdmin())
        {
            return core::http::HttpResponse::forbidden("Not allowed to access this upload");
        }

        nlohmann::json body{
            { "upload_id",   upload.id },
            { "filename",    upload.originalName },
            { "size_bytes",  upload.sizeBytes },
            { "mime_type",   upload.mimeType },
            { "status",      models::FileUpload::statusToString(upload.status) },
            { "created_at",  utils::Clock::toIso8601(upload.createdAt) }
        };
        return core::http::HttpResponse::ok(body.dump(), "application/json");
    }
    catch (const std::exception& ex)
    {
        utils::Logger::error("FileUploadController::getStatus – {}", ex.what());
        return core::http::HttpResponse::internalServerError("Unexpected server error");
    }
}

} // namespace MosaicBoard::Controllers
```