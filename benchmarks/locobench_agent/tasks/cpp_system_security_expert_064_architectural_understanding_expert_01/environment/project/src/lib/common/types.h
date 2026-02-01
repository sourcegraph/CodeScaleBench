#pragma once
//======================================================================================================================
//  FortiLedger360 Enterprise Security Suite
//  File        : src/lib/common/types.h
//  Description : Common strongly-typed primitives, enumerations and utility helpers shared across layers.
//                This header purposefully contains ZERO implementation-specific business logic.  It merely provides
//                the “grammar” that the remainder of the code base relies on—identifiers, timestamps, results, etc.
//                Any modification MUST remain ABI-compatible; breaking changes ripple through the entire platform.
//======================================================================================================================

#include <array>
#include <chrono>
#include <cstdint>
#include <iomanip>
#include <optional>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <system_error>
#include <utility>
#include <variant>

// ---------------------------------------------------------------------------------------------------------------------
//  Namespace hierarchy
//      fortiledger360::common
//          |_ Types, helper structs and aliases used by all layers.
// ---------------------------------------------------------------------------------------------------------------------
namespace fortiledger360::common {

// =====================================================================================================================
//  1. Chronological utilities
// =====================================================================================================================
using Clock          = std::chrono::system_clock;
using TimePointMs    = std::chrono::time_point<Clock, std::chrono::milliseconds>;
using DurationMs     = std::chrono::milliseconds;

/**
 * @brief Obtain the current wall-clock timestamp in millisecond precision.
 */
inline TimePointMs now_ms()
{
    return std::chrono::time_point_cast<DurationMs>(Clock::now());
}

// =====================================================================================================================
//  2. Strongly-typed identifiers
// =====================================================================================================================

/**
 * @brief A helper that generates RFC-4122 compliant, pseudo-random UUID v4 strings.
 *        The implementation is header-only, dependency-free and *thread-local* RNG backed.
 * @return A canonical textual form: 8-4-4-4-12 lower-case hexadecimal characters.
 */
inline std::string generate_uuid_v4()
{
    static thread_local std::mt19937_64 rng{std::random_device{}()};
    std::uniform_int_distribution<uint32_t> d32(0, 0xffffffff);

    auto hex = [](uint64_t value, std::size_t width) {
        std::ostringstream oss;
        oss << std::hex << std::nouppercase << std::setfill('0') << std::setw(static_cast<int>(width)) << value;
        return oss.str();
    };

    const uint32_t part1 = d32(rng);
    const uint16_t part2 = static_cast<uint16_t>(d32(rng) & 0xffff);
    const uint16_t part3 = static_cast<uint16_t>((d32(rng) & 0x0fff) | 0x4000);   // version 4
    const uint16_t part4 = static_cast<uint16_t>((d32(rng) & 0x3fff) | 0x8000);   // variant 1
    const uint64_t part5 = (static_cast<uint64_t>(d32(rng)) << 16) | (d32(rng) & 0xffff);

    std::ostringstream oss;
    oss << hex(part1, 8)  << '-'
        << hex(part2, 4)  << '-'
        << hex(part3, 4)  << '-'
        << hex(part4, 4)  << '-'
        << hex(part5, 12);

    return oss.str();
}

/**
 * @tparam Tag  Empty struct acting as a *phantom type*—making otherwise identical IDs non-interchangeable.
 */
template <typename Tag>
class StrongID
{
public:
    using underlying_type = std::string;

    // -------------------------------------------------------------------------
    //  Construction
    // -------------------------------------------------------------------------
    StrongID() = default;

    explicit StrongID(std::string id)
        : id_(std::move(id))
    {
        if (id_.empty())
            throw std::invalid_argument("StrongID: identifier string must not be empty");
    }

    static StrongID generate() { return StrongID{generate_uuid_v4()}; }

    // -------------------------------------------------------------------------
    //  Observers
    // -------------------------------------------------------------------------
    const std::string& str() const noexcept { return id_; }
    bool empty() const noexcept             { return id_.empty(); }

    // -------------------------------------------------------------------------
    //  Comparators
    // -------------------------------------------------------------------------
    friend bool operator==(const StrongID& a, const StrongID& b) noexcept { return a.id_ == b.id_; }
    friend bool operator!=(const StrongID& a, const StrongID& b) noexcept { return !(a == b); }
    friend bool operator< (const StrongID& a, const StrongID& b) noexcept { return a.id_ < b.id_; }

private:
    std::string id_;
};

// Forward-declared tags – extend freely as the domain evolves.
struct TenantTag       {};
struct SubscriptionTag {};
struct TraceTag        {};

using TenantID       = StrongID<TenantTag>;
using SubscriptionID = StrongID<SubscriptionTag>;
using TraceID        = StrongID<TraceTag>;

// Hash specializations so IDs can be keys in unordered containers.
} // namespace fortiledger360::common

namespace std {
template <typename Tag>
struct hash<fortiledger360::common::StrongID<Tag>>
{
    std::size_t operator()(const fortiledger360::common::StrongID<Tag>& id) const noexcept
    {
        return std::hash<std::string>{}(id.str());
    }
};
} // namespace std

namespace fortiledger360::common {

// =====================================================================================================================
//  3. Enumerations – canonical across the entire platform
// =====================================================================================================================

enum class ServiceTier : std::uint8_t
{
    Basic,
    Standard,
    Premium,
    Enterprise,
    Undefined
};

enum class CommandType : std::uint8_t
{
    InitiateSecurityScan,
    RollClusterBackup,
    LoadBalancerScaleUp,
    Undefined
};

enum class SeverityLevel : std::uint8_t
{
    Debug,
    Info,
    Warning,
    Error,
    Critical,
    Undefined
};

// =====================================================================================================================
//  4. Error & Result wrapper – lightweight substitute for std::expected (C++23)
// =====================================================================================================================

struct Error
{
    std::error_code code;
    std::string     message;

    explicit operator bool() const noexcept { return static_cast<bool>(code); }
};

template <typename T>
class Result
{
public:
    //------------------------------------------------------------------------
    //  Factory helpers
    //------------------------------------------------------------------------
    static Result ok(T value)                                  { return Result{std::move(value)}; }
    static Result fail(std::error_code ec, std::string message){ return Result{Error{ec, std::move(message)}}; }

    //------------------------------------------------------------------------
    //  Observers
    //------------------------------------------------------------------------
    bool has_value() const noexcept      { return std::holds_alternative<T>(data_); }
    explicit operator bool() const noexcept { return has_value(); }

    T&       value()       { return std::get<T>(data_); }
    const T& value() const { return std::get<T>(data_); }

    Error&       error()       { return std::get<Error>(data_); }
    const Error& error() const { return std::get<Error>(data_); }

    //------------------------------------------------------------------------
    //  Monadic helper – if value present executes callable and forwards result.
    //------------------------------------------------------------------------
    template <typename Fn>
    auto and_then(Fn&& fn) const -> Result<decltype(fn(std::declval<T>()))>
    {
        using U = decltype(fn(std::declval<T>()));
        if (has_value())
            return Result<U>::ok(fn(value()));
        return Result<U>::fail(error().code, error().message);
    }

private:
    explicit Result(T value)   : data_(std::move(value)) {}
    explicit Result(Error err) : data_(std::move(err))   {}

    std::variant<T, Error> data_;
};

// =====================================================================================================================
//  5. Utility constants & helpers
// =====================================================================================================================

constexpr std::string_view kUnknownTenant   = "00000000-0000-0000-0000-000000000000";
constexpr std::string_view kUnknownTrace    = "ffffffff-ffff-ffff-ffff-ffffffffffff";
constexpr DurationMs       kDefaultTimeout  { 30'000 };     // 30 seconds

//======================================================================================================================
} // namespace fortiledger360::common
