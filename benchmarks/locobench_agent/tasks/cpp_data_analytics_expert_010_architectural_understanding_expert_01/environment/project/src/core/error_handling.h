//===----------------------------------------------------------------------===//
// CardioInsight360 – Unified Healthcare Analytics Engine
// File: cardio_insight_360/src/core/error_handling.h
//
// Description:
//   Centralised error‐handling utilities shared across the CardioInsight360
//   code-base.  The facilities provided here deliver a lightweight alternative
//   to std::expected / std::source_location for C++17 while still preserving
//   rich contextual information (file, line, function) that is propagated up
//   the call stack, logged, and—optionally—shown in the UI.
//
//   Design goals:
//     • Keep error-handling uniform across ETL, streaming, UI, etc.
//     • Minimise boiler-plate with RETURN_IF_ERROR / THROW_IF_ERROR macros.
//     • Support structured logging via spdlog when available; gracefully
//       degrade to std::cerr when it is not.
//     • Be header-only so that all components see the same definitions.
//
//   Usage example:
//
//     ci360::core::Status ReadEcg(const std::string& path, EcgSignal* out) {
//         if (path.empty()) {
//             return CI360_MAKE_STATUS(
//                 ci360::core::ErrorCode::kInvalidArgument,
//                 "Path must not be empty");
//         }
//         // …
//         return ci360::core::Status::Ok();
//     }
//
//     void ApiHandler() {
//         CI360_THROW_IF_ERROR(ReadEcg(request.path(), &signal));
//         // …
//     }
//===----------------------------------------------------------------------===//
#pragma once

#include <cassert>
#include <cstdint>
#include <exception>
#include <iostream>
#include <mutex>
#include <ostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>

#if __has_include(<spdlog/spdlog.h>)
#  define CI360_USE_SPDLOG 1
#  include <spdlog/spdlog.h>
#endif

namespace ci360::core {

//----------------------------------------------------------------------------//
// ErrorCode – canonical, transport-agnostic error identifiers.
//----------------------------------------------------------------------------//
enum class ErrorCode : std::int32_t {
    kOk = 0,

    kInvalidArgument,   // 1  – Input does not meet pre-conditions.
    kNotFound,          // 2  – Requested entity not present.
    kAlreadyExists,     // 3  – Cannot create because one already exists.
    kOutOfRange,        // 4  – Parameter out of legal range.
    kDataIntegrity,     // 5  – Data corruption or validation failure.
    kIOError,           // 6  – Local or remote I/O error.
    kTimeout,           // 7  – Operation timed out.
    kPermissionDenied,  // 8  – Caller lacks sufficient privileges.
    kUnavailable,       // 9  – Service temporarily unavailable.
    kCancelled,         // 10 – Operation cancelled by caller or system.
    kInternal,          // 11 – Internal invariant broken.
    kUnknown            // 12 – Everything else.
};

// Human-readable conversion.
inline const char* ToString(ErrorCode code) noexcept {
    switch (code) {
        case ErrorCode::kOk:               return "Ok";
        case ErrorCode::kInvalidArgument:  return "InvalidArgument";
        case ErrorCode::kNotFound:         return "NotFound";
        case ErrorCode::kAlreadyExists:    return "AlreadyExists";
        case ErrorCode::kOutOfRange:       return "OutOfRange";
        case ErrorCode::kDataIntegrity:    return "DataIntegrity";
        case ErrorCode::kIOError:          return "IOError";
        case ErrorCode::kTimeout:          return "Timeout";
        case ErrorCode::kPermissionDenied: return "PermissionDenied";
        case ErrorCode::kUnavailable:      return "Unavailable";
        case ErrorCode::kCancelled:        return "Cancelled";
        case ErrorCode::kInternal:         return "Internal";
        case ErrorCode::kUnknown:          return "Unknown";
    }
    return "Unknown";
}

//----------------------------------------------------------------------------//
// Error – Rich exception type used when the throw-path is preferred.
//----------------------------------------------------------------------------//
class Error : public std::runtime_error {
public:
    Error(ErrorCode code,
          std::string  msg,
          const char*  file,
          std::int32_t line,
          const char*  function)
        : std::runtime_error(BuildWhat(code, msg, file, line, function)),
          code_(code),
          file_(file),
          line_(line),
          function_(function) {}

    // Accessors ----------------------------------------------------------------
    ErrorCode    code()     const noexcept { return code_; }
    const char*  file()     const noexcept { return file_; }
    std::int32_t line()     const noexcept { return line_; }
    const char*  function() const noexcept { return function_; }

private:
    static std::string BuildWhat(ErrorCode   code,
                                 const std::string& msg,
                                 const char*        file,
                                 std::int32_t       line,
                                 const char*        function) {
        std::ostringstream oss;
        oss << "[" << ToString(code) << "] " << msg
            << " (" << file << ":" << line << " @" << function << ")";
        return oss.str();
    }

    ErrorCode    code_;
    const char*  file_;
    std::int32_t line_;
    const char*  function_;
};

//----------------------------------------------------------------------------//
// Status – non-throwable error carrier resembling absl::Status or std::expected
//----------------------------------------------------------------------------//
class Status {
public:
    // Factory: success.
    static Status Ok() noexcept { return Status(); }

    // Factory: error.
    static Status MakeError(ErrorCode code,
                            std::string  msg,
                            const char*  file,
                            std::int32_t line,
                            const char*  function) noexcept {
        return Status(code, std::move(msg), file, line, function);
    }

    // Query --------------------------------------------------------------------
    bool ok() const noexcept { return code_ == ErrorCode::kOk; }
    explicit operator bool() const noexcept { return ok(); }

    ErrorCode           code()     const noexcept { return code_;     }
    const std::string&  message()  const noexcept { return message_;  }
    const char*         file()     const noexcept { return file_;     }
    std::int32_t        line()     const noexcept { return line_;     }
    const char*         function() const noexcept { return function_; }

    std::string ToString() const {
        std::ostringstream oss;
        oss << "[" << ToString(code_) << "] " << message_;
        if (file_) {
            oss << " (" << file_ << ":" << line_ << " @" << function_ << ")";
        }
        return oss.str();
    }

private:
    // Success constructor.
    Status() noexcept
        : code_(ErrorCode::kOk),
          file_(nullptr),
          line_(0),
          function_(nullptr) {}

    // Error constructor.
    Status(ErrorCode code,
           std::string  msg,
           const char*  file,
           std::int32_t line,
           const char*  function) noexcept
        : code_(code),
          message_(std::move(msg)),
          file_(file),
          line_(line),
          function_(function) {}

    ErrorCode    code_;
    std::string  message_;
    const char*  file_;
    std::int32_t line_;
    const char*  function_;
};

// Helper for inline macro use.
inline Status MakeStatus(ErrorCode   code,
                         std::string message,
                         const char* file,
                         std::int32_t line,
                         const char* function) {
    return Status::MakeError(code, std::move(message), file, line, function);
}

//----------------------------------------------------------------------------//
// Logging utility – spdlog preferred, else std::cerr.
//----------------------------------------------------------------------------//
inline void LogError(const Status& status) noexcept {
    if (status.ok()) return;  // Nothing to log.

#if defined(CI360_USE_SPDLOG)
    spdlog::error("CI360 Error: {}", status.ToString());
#else
    static std::mutex cerr_mu;
    std::lock_guard<std::mutex> lk(cerr_mu);
    std::cerr << "CI360 Error: " << status.ToString() << std::endl;
#endif
}

//----------------------------------------------------------------------------//
// Convenience macros – reduce boiler-plate in call sites.
//----------------------------------------------------------------------------//
#define CI360_MAKE_STATUS(code, msg) \
    ::ci360::core::MakeStatus((code), (msg), __FILE__, __LINE__, __func__)

// Propagate error without logging.
#define CI360_RETURN_IF_ERROR(expr)                    \
    do {                                               \
        const ::ci360::core::Status _s = (expr);       \
        if (!_s.ok()) {                                \
            return _s;                                 \
        }                                              \
    } while (false)

// Propagate error, but log first (useful for background threads).
#define CI360_RETURN_IF_ERROR_LOG(expr)               \
    do {                                              \
        const ::ci360::core::Status _s = (expr);      \
        if (!_s.ok()) {                               \
            ::ci360::core::LogError(_s);              \
            return _s;                                \
        }                                             \
    } while (false)

// Evaluate expression returning Status; throw if error.
#define CI360_THROW_IF_ERROR(expr)                     \
    do {                                               \
        const ::ci360::core::Status _s = (expr);       \
        if (!_s.ok()) {                                \
            throw ::ci360::core::Error(                \
                _s.code(), _s.message(),               \
                _s.file(), _s.line(), _s.function());  \
        }                                              \
    } while (false)

// Assertion that maps to Error when false; active even in Release builds.
#define CI360_ASSERT(cond, code, msg)                        \
    do {                                                     \
        if (!(cond)) {                                       \
            throw ::ci360::core::Error(                      \
                (code), (msg), __FILE__, __LINE__, __func__);\
        }                                                    \
    } while (false)

// Internal invariants enabled only for Debug builds.
#ifndef NDEBUG
#  define CI360_DCHECK(cond) assert(cond)
#else
#  define CI360_DCHECK(cond) ((void)0)
#endif

}  // namespace ci360::core
