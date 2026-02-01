#pragma once
/***************************************************************************************************
 *  FileUploadController.h
 *  MosaicBoard Studio – Web Dashboard
 *
 *  Description:
 *      REST-style controller responsible for secure file uploads & downloads.  The controller
 *      handles multipart-form payloads, validates size / MIME type against an upload policy,
 *      persists the file via an injected storage service, and returns a canonical JSON resource
 *      descriptor that tiles can reference at runtime.
 *
 *      This header provides a self-contained implementation so that plugin developers can
 *      #include it without linking against an additional translation unit.  The controller uses
 *      Pistache for the HTTP layer, nlohmann::json for JSON rendering, and spdlog for structured
 *      logging.  All heavy-weight services are injected through light weight interfaces to keep the
 *      module testable and to honour the MVC service-layer boundaries.
 *
 *  Copyright:
 *      (c) 2023-2024 MosaicBoard Studio – All Rights Reserved.
 **************************************************************************************************/

#include <pistache/router.h>
#include <pistache/http.h>
#include <pistache/mime.h>
#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include <chrono>
#include <filesystem>
#include <memory>
#include <regex>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>
#include <vector>

namespace mb     {  // MosaicBoard root namespace
namespace core   { class IAuthService; }
namespace fs     { class IFileStorageService; }
namespace ctrl   {

/**************************************************************************************************
 *  UploadPolicy
 *
 *  Runtime policy struct describing the limitations for the upload endpoint.
 *************************************************************************************************/
struct UploadPolicy
{
    std::size_t             maxFileSizeBytes     = 25_MiB;     // Hard-limit for a single file.
    std::unordered_set<std::string> allowedMime;                // Allowed content-types.
    std::chrono::seconds    signedUrlTTL         = std::chrono::minutes(10);

    constexpr bool isMimeAllowed(const std::string& mime) const noexcept
    {
        return allowedMime.empty() || allowedMime.find(mime) != allowedMime.end();
    }

    constexpr bool isSizeAllowed(std::size_t bytes) const noexcept
    {
        return bytes <= maxFileSizeBytes;
    }
};

/**************************************************************************************************
 *  FileUploadController
 *
 *  REST controller responsible for:
 *      POST   /v1/files          – Upload a file (multipart/form-data)
 *      GET    /v1/files/{id}     – Download a file (pre-signed URL)
 *      DELETE /v1/files/{id}     – Remove a file
 *
 *  Thread-safe: yes
 *************************************************************************************************/
class FileUploadController : public std::enable_shared_from_this<FileUploadController>
{
public:
    FileUploadController(Pistache::Rest::Router&                 router,
                         std::shared_ptr<mb::fs::IFileStorageService> storageService,
                         std::shared_ptr<mb::core::IAuthService>      authService,
                         UploadPolicy                                 policy = {})
        : router_{router}
        , storage_{std::move(storageService)}
        , auth_   {std::move(authService)}
        , policy_ {std::move(policy)}
    {
        if (!storage_ || !auth_) {
            throw std::invalid_argument("FileUploadController – invalid service dependency (nullptr).");
        }
    }

    /**********************************************************************************************
     *  registerRoutes
     *      Must be called once during server startup to mount all HTTP handlers on the router that
     *      was passed through the constructor.
     *********************************************************************************************/
    void registerRoutes()
    {
        using namespace Pistache::Rest;
        Routes::Post   (router_, "/v1/files", Routes::bind(&FileUploadController::postUpload,  shared_from_this()));
        Routes::Get    (router_, "/v1/files/:id", Routes::bind(&FileUploadController::getDownload, shared_from_this()));
        Routes::Delete (router_, "/v1/files/:id", Routes::bind(&FileUploadController::deleteFile,  shared_from_this()));
        spdlog::info("FileUploadController – routes registered");
    }

private:
    /* ————————————————————————  Route Handlers  ————————————————————————— */
    void postUpload(const Pistache::Rest::Request& req, Pistache::Http::ResponseWriter resp)
    {
        const auto userId = authenticate(req, resp);
        if (userId.empty()) return;  // auth failure already responded.

        if (!req.headers().tryGetRaw("Content-Type")) {
            return respondError(resp, Pistache::Http::Code::Bad_Request, "Missing Content-Type header");
        }

        if (req.mime() != Pistache::Http::Mime::MediaType::fromString("multipart/form-data")) {
            return respondError(resp, Pistache::Http::Code::Unsupported_Media_Type, "Endpoint expects multipart/form-data");
        }

        // Pistache sadly does not parse multipart payloads natively, so we rely on storage_->persist()
        // taking the raw body and doing the heavy work.  Production deployments typically offload this
        // to nginx + an S3 presigned flow for efficiency.
        const auto contentSize = req.body().size();
        if (!policy_.isSizeAllowed(contentSize)) {
            return respondError(resp, Pistache::Http::Code::Request_Entity_Too_Large, "File exceeds size limit.");
        }

        const std::string mime = detectMime(req);
        if (!policy_.isMimeAllowed(mime)) {
            return respondError(resp, Pistache::Http::Code::Unsupported_Media_Type, "MIME type not allowed.");
        }

        try {
            auto fileId  = storage_->persist(req.body(), mime, userId);
            auto fileUrl = storage_->generateSignedDownloadUrl(fileId, policy_.signedUrlTTL);

            nlohmann::json payload{
                {"id",   fileId},
                {"url",  fileUrl},
                {"ttl",  policy_.signedUrlTTL.count()},
                {"size", contentSize},
                {"mime", mime}
            };

            resp.headers().add<Pistache::Http::Header::ContentType>(MIME(Application, Json));
            resp.send(Pistache::Http::Code::Created, payload.dump());
        }
        catch (const std::exception& e) {
            spdlog::error("FileUploadController – persist failed: {}", e.what());
            respondError(resp, Pistache::Http::Code::Internal_Server_Error, "Unable to persist file.");
        }
    }

    void getDownload(const Pistache::Rest::Request& req, Pistache::Http::ResponseWriter resp)
    {
        const auto userId = authenticate(req, resp);
        if (userId.empty()) return;

        const std::string fileId = req.param(":id").as<std::string>();
        try {
            if (!storage_->authorizeView(fileId, userId)) {
                return respondError(resp, Pistache::Http::Code::Forbidden, "Access denied.");
            }

            auto url = storage_->generateSignedDownloadUrl(fileId, policy_.signedUrlTTL);
            nlohmann::json payload{ {"url", url}, {"ttl", policy_.signedUrlTTL.count()} };
            resp.headers().add<Pistache::Http::Header::ContentType>(MIME(Application, Json));
            resp.send(Pistache::Http::Code::Ok, payload.dump());
        }
        catch (const std::exception& e) {
            spdlog::error("FileUploadController – getDownload failed: {}", e.what());
            respondError(resp, Pistache::Http::Code::Internal_Server_Error, "Unable to generate download URL.");
        }
    }

    void deleteFile(const Pistache::Rest::Request& req, Pistache::Http::ResponseWriter resp)
    {
        const auto userId = authenticate(req, resp);
        if (userId.empty()) return;

        const std::string fileId = req.param(":id").as<std::string>();
        try {
            if (!storage_->authorizeDelete(fileId, userId)) {
                return respondError(resp, Pistache::Http::Code::Forbidden, "Access denied.");
            }

            storage_->erase(fileId);
            resp.send(Pistache::Http::Code::No_Content);
        }
        catch (const std::exception& e) {
            spdlog::error("FileUploadController – delete failed: {}", e.what());
            respondError(resp, Pistache::Http::Code::Internal_Server_Error, "Unable to delete file.");
        }
    }

    /* ————————————————————————  Helper functions  ————————————————————————— */
    static void respondError(Pistache::Http::ResponseWriter& resp,
                             Pistache::Http::Code            code,
                             std::string_view                message)
    {
        nlohmann::json payload{ {"error", message} };
        resp.headers().add<Pistache::Http::Header::ContentType>(MIME(Application, Json));
        resp.send(code, payload.dump());
    }

    std::string authenticate(const Pistache::Rest::Request& req,
                             Pistache::Http::ResponseWriter& resp) const
    {
        auto hdr = req.headers().tryGetRaw("Authorization");
        if (!hdr) {
            respondError(resp, Pistache::Http::Code::Unauthorized, "Missing authorization header.");
            return {};
        }

        try {
            const auto userId = auth_->validateToken(hdr->value());
            if (userId.empty()) {
                respondError(resp, Pistache::Http::Code::Unauthorized, "Invalid token.");
            }
            return userId;
        }
        catch (const std::exception& e) {
            spdlog::warn("Authentication failed: {}", e.what());
            respondError(resp, Pistache::Http::Code::Unauthorized, "Invalid token.");
            return {};
        }
    }

    static std::string detectMime(const Pistache::Rest::Request& req)
    {
        // Basic MIME detection – in production we’d sniff the first bytes or delegate to libmagic.
        if (auto ct = req.headers().tryGetRaw("X-File-Mime"); ct) {
            return ct->value();
        }
        return "application/octet-stream";
    }

private:
    Pistache::Rest::Router&                router_;
    std::shared_ptr<mb::fs::IFileStorageService> storage_;
    std::shared_ptr<mb::core::IAuthService>      auth_;
    UploadPolicy                             policy_;
};

/* ————————————————————————  Inline constants ——————————————————————————— */
constexpr std::size_t operator"" _MiB(unsigned long long mib) { return mib * 1024ull * 1024ull; }

} // namespace ctrl
} // namespace mb


/***************************************************************************************************
 *  Minimal service interfaces
 *
 *  Provided here as forward-declared lightweight contracts so that the header can be consumed
 *  without pulling in the full service layer.  Real implementations live in the Service Layer and
 *  fulfil the interface.
 **************************************************************************************************/
namespace mb::fs {

class IFileStorageService
{
public:
    virtual ~IFileStorageService() = default;

    virtual std::string persist(std::string_view          fileData,
                                std::string_view          mime,
                                std::string_view          ownerId)                     = 0;

    virtual std::string generateSignedDownloadUrl(std::string_view fileId,
                                                  std::chrono::seconds ttl) const     = 0;

    virtual bool authorizeView(std::string_view fileId,
                               std::string_view userId) const                          = 0;

    virtual bool authorizeDelete(std::string_view fileId,
                                 std::string_view userId) const                        = 0;

    virtual void erase(std::string_view fileId)                                        = 0;
};

} // namespace mb::fs

namespace mb::core {

class IAuthService
{
public:
    virtual ~IAuthService() = default;

    // Returns a user-id if token is valid, else an empty string.
    virtual std::string validateToken(std::string_view bearerToken) const = 0;
};

} // namespace mb::core