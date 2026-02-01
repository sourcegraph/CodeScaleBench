#pragma once
/**
 *  FortiLedger360 Enterprise Security Suite
 *  ----------------------------------------
 *  File  : errors.h
 *  Module: lib/common
 *
 *  Copyright (c) 
 *
 *  Description:
 *      Unified, cross-cutting error-handling primitives shared by every layer
 *      of the FortiLedger360 platform.  The utilities in this header make it
 *      possible to:
 *
 *        • Express rich, strongly-typed error codes that plug seamlessly into
 *          <system_error>.
 *        • Attach contextual metadata—file, line, and optional component name.
 *        • Bubble errors through the stack either as std::error_code *or*
 *          full-blown exceptions, depending on the call-site policy.
 *
 *      The design complies with C++17 (with C++20 <source_location> support
 *      auto-enabled when the standard library is available).
 */

#include <system_error>
#include <string>
#include <string_view>
#include <stdexcept>
#include <utility>
#include <sstream>

#if __cpp_lib_source_location >= 201907L
    #include <source_location>
#endif

namespace fl360::common
{
/*--------------------------------------------------------------
 * 1. Strongly-typed error codes
 *------------------------------------------------------------*/

enum class ErrorCode
{
    Success                 = 0,   ///< No error.
    InvalidArgument         = 1,   ///< Parameter validation failed.
    NotFound                = 2,   ///< Entity/resource not found.
    AlreadyExists           = 3,   ///< Attempted to create a duplicate entity.
    PermissionDenied        = 4,   ///< Caller lacks sufficient privileges.
    Timeout                 = 5,   ///< Operation exceeded its deadline.
    ServiceUnavailable      = 6,   ///< Downstream service currently unavailable.
    InternalFailure         = 7,   ///< Unexpected internal failure.
    ConfigError             = 8,   ///< Configuration is incorrect or incomplete.
    ComplianceViolation     = 9,   ///< Request violates compliance policy.
    TransportFailure        = 10,  ///< Underlying transport (gRPC, MQ, TCP...) failed.
    SerializationError      = 11,  ///< Unable to serialize payload.
    DeserializationError    = 12,  ///< Unable to parse/deserialize payload.
    SSLHandshakeFailed      = 13,  ///< Mutual-TLS handshake failure.
    OperationCancelled      = 14,  ///< Operation was cancelled pre-emptively.
    Unknown                 = 255  ///< Fallback for unmapped/unspecified errors.
};

/* Tell <system_error> that ErrorCode is eligible for std::error_code. */
} // namespace fl360::common

namespace std
{
template <>
struct is_error_code_enum<fl360::common::ErrorCode> : std::true_type {};
} // namespace std

namespace fl360::common
{
/*--------------------------------------------------------------
 * 2. std::error_category implementation
 *------------------------------------------------------------*/

class ErrorCategory final : public std::error_category
{
public:
    const char* name() const noexcept override
    {
        return "FortiLedger360";
    }

    std::string message(int ev) const override
    {
        const auto code = static_cast<ErrorCode>(ev);
        switch (code)
        {
            case ErrorCode::Success:              return "Success";
            case ErrorCode::InvalidArgument:      return "Invalid argument";
            case ErrorCode::NotFound:             return "Entity not found";
            case ErrorCode::AlreadyExists:        return "Entity already exists";
            case ErrorCode::PermissionDenied:     return "Permission denied";
            case ErrorCode::Timeout:              return "Operation timed out";
            case ErrorCode::ServiceUnavailable:   return "Service unavailable";
            case ErrorCode::InternalFailure:      return "Internal failure";
            case ErrorCode::ConfigError:          return "Configuration error";
            case ErrorCode::ComplianceViolation:  return "Compliance violation";
            case ErrorCode::TransportFailure:     return "Transport failure";
            case ErrorCode::SerializationError:   return "Serialization failure";
            case ErrorCode::DeserializationError: return "Deserialization failure";
            case ErrorCode::SSLHandshakeFailed:   return "SSL/TLS handshake failed";
            case ErrorCode::OperationCancelled:   return "Operation cancelled";
            default:                              return "Unknown error";
        }
    }

    bool equivalent(const std::error_code& code,
                    int                    condition) const noexcept override
    {
        return code.value() == condition;
    }
};

/* Singleton accessor */
inline const std::error_category& error_category() noexcept
{
    static ErrorCategory instance;
    return instance;
}

/* Factory for std::error_code from ErrorCode. */
inline std::error_code make_error_code(ErrorCode e) noexcept
{
    return {static_cast<int>(e), error_category()};
}

/*--------------------------------------------------------------
 * 3. Utility: stringify ErrorCode
 *------------------------------------------------------------*/
inline std::string to_string(ErrorCode ec)
{
    return error_category().message(static_cast<int>(ec));
}

/*--------------------------------------------------------------
 * 4. Exception class that carries ErrorCode + context
 *------------------------------------------------------------*/

class Error final : public std::runtime_error
{
public:
#if __cpp_lib_source_location >= 201907L
    explicit Error(ErrorCode code,
                   std::string_view what,
                   std::source_location loc = std::source_location::current())
        : std::runtime_error(build_message(code, what, loc))
        , m_code(code)
    {
    }
#else
    explicit Error(ErrorCode code,
                   std::string_view what,
                   const char* file = __FILE__,
                   int line        = __LINE__)
        : std::runtime_error(build_message(code, what, file, line))
        , m_code(code)
    {
    }
#endif

    ErrorCode code() const noexcept
    {
        return m_code;
    }

    std::error_code as_error_code() const noexcept
    {
        return make_error_code(m_code);
    }

private:
#if __cpp_lib_source_location >= 201907L
    static std::string build_message(ErrorCode code,
                                     std::string_view what,
                                     std::source_location loc)
    {
        std::ostringstream oss;
        oss << "[" << to_string(code) << "] "
            << what
            << " (" << loc.file_name() << ':' << loc.line() << ')';
        return oss.str();
    }
#else
    static std::string build_message(ErrorCode code,
                                     std::string_view what,
                                     const char* file,
                                     int line)
    {
        std::ostringstream oss;
        oss << "[" << to_string(code) << "] "
            << what
            << " (" << file << ':' << line << ')';
        return oss.str();
    }
#endif

    ErrorCode m_code;
};

/*--------------------------------------------------------------
 * 5. Helper macro: throw with automatic context
 *------------------------------------------------------------*/

#if __cpp_lib_source_location >= 201907L
    #define FL360_THROW(code, msg) \
        throw ::fl360::common::Error((code), (msg))
#else
    #define FL360_THROW(code, msg) \
        throw ::fl360::common::Error((code), (msg), __FILE__, __LINE__)
#endif

/*--------------------------------------------------------------
 * 6. Convenience alias for std::expected-like pattern (C++17)
 *------------------------------------------------------------*/

template <typename T>
using Result = std::pair<T, std::error_code>;   // {value, ec}. ec == {} on success.

/*--------------------------------------------------------------
 * 7. Non-throwing helper: make failure Result<T>
 *------------------------------------------------------------*/
template <typename T>
inline Result<T> make_failure(ErrorCode code)
{
    return Result<T>{T{}, make_error_code(code)};
}

} // namespace fl360::common