```cpp
// ──────────────────────────────────────────────────────────────────────────────
//  File:        src/module_33.cpp
//  Project:     IntraLedger BlogSuite (web_blog)
//  Component:   Authentication Middleware / Rate-Limiting
//
//  Description:
//      Production-grade implementation of a login throttler that mitigates brute
//      force attacks by rate-limiting failed credential attempts on both a per-
//      user and per-IP basis.  The module persists counters through the
//      project-wide ORM so that limits survive process restarts and are
//      shareable across horizontally-scaled instances.
//
//  Author:      IntraLedger Engineering
//  SPDX-License-Identifier: MIT
// ──────────────────────────────────────────────────────────────────────────────

#include <chrono>
#include <cstdint>
#include <exception>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

// ── Project-local includes ────────────────────────────────────────────────────
#include "orm/EntityManager.hpp"     // In-house, (MariaDB/PostgreSQL) agnostic
#include "orm/QueryBuilder.hpp"
#include "util/Logger.hpp"
#include "util/ScopeGuard.hpp"

namespace web_blog::auth {

// ──────────────────────────────────────────────────────────────────────────────
//  Exception Types
// ──────────────────────────────────────────────────────────────────────────────
class ThrottlingException final : public std::runtime_error {
public:
    explicit ThrottlingException(const std::string& msg)
        : std::runtime_error(msg) {}
};

// ──────────────────────────────────────────────────────────────────────────────
//  Data Transfer Objects ‑ ORM representations
// ──────────────────────────────────────────────────────────────────────────────
struct LoginAttemptDTO {
    std::string key;               // user:<USER_ID> or ip:<ADDR>
    std::uint32_t counter{0};
    std::chrono::system_clock::time_point windowStart{};
    std::chrono::system_clock::time_point lockedUntil{};

    // For ORM hydration/serialization
    static constexpr const char* TableName = "login_attempts";
};

// clang-format off
ORM_BEGIN(LoginAttemptDTO, LoginAttemptDTO::TableName)
    ORM_FIELD(key)
    ORM_FIELD(counter)
    ORM_FIELD(windowStart)
    ORM_FIELD(lockedUntil)
ORM_END()
// clang-format on

// ──────────────────────────────────────────────────────────────────────────────
//  LoginAttemptThrottler
// ──────────────────────────────────────────────────────────────────────────────
class LoginAttemptThrottler {
public:
    struct Limits {
        std::uint32_t maxAttempts;                         // Number of attempts before lockout
        std::chrono::seconds window;                       // Rolling window duration
        std::chrono::seconds lockout;                      // How long the user is locked
    };

    explicit LoginAttemptThrottler(Limits userLimits,
                                   Limits ipLimits,
                                   orm::EntityManager& em);

    // Record a failed authentication attempt
    void registerFailure(const std::optional<std::uint64_t>& userId,
                         const std::string& ipAddress);

    // Record a successful login and clear counters
    void registerSuccess(const std::optional<std::uint64_t>& userId,
                         const std::string& ipAddress);

    // Throws ThrottlingException if user or IP is locked
    void assertNotLocked(const std::optional<std::uint64_t>& userId,
                         const std::string& ipAddress);

    // Periodic flush that persists in-memory stats to DB
    void flushToDatabase();

private:
    struct CounterState {
        std::uint32_t counter{0};
        std::chrono::system_clock::time_point windowStart{};
        std::chrono::system_clock::time_point lockedUntil{};
        bool dirty{false};     // Whether state changed (needs persistence)
    };

    // Key helpers
    static std::string makeUserKey(std::uint64_t userId);
    static std::string makeIpKey(const std::string& ip);

    // Shared implementation
    void touch(const std::string& key, Limits limits);

    void persistOne(const std::string& key, const CounterState& state, orm::EntityManager& em);

    Limits userLimits_;
    Limits ipLimits_;
    orm::EntityManager& em_;       // Not owned

    std::mutex mtx_;
    std::unordered_map<std::string, CounterState> cache_;
};

// ──────────────────────────────────────────────────────────────────────────────
//  Implementation
// ──────────────────────────────────────────────────────────────────────────────
LoginAttemptThrottler::LoginAttemptThrottler(Limits userLimits,
                                             Limits ipLimits,
                                             orm::EntityManager& em)
    : userLimits_{std::move(userLimits)}
    , ipLimits_{std::move(ipLimits)}
    , em_{em}
{
    // Pre-load existing counters (best-effort)
    try {
        auto rows = orm::QueryBuilder(em_)
                        .select<LoginAttemptDTO>()
                        .execute();

        std::lock_guard lk{mtx_};
        for (auto& row : rows) {
            cache_[row.key] = CounterState{row.counter, row.windowStart,
                                           row.lockedUntil, false};
        }
        util::Logger::info("LoginAttemptThrottler: Initialized with {} entries in cache",
                           cache_.size());
    } catch (const std::exception& ex) {
        util::Logger::warn("LoginAttemptThrottler: Unable to preload counters – {}",
                           ex.what());
    }
}

/*static*/ std::string LoginAttemptThrottler::makeUserKey(const std::uint64_t userId)
{
    return "user:" + std::to_string(userId);
}

/*static*/ std::string LoginAttemptThrottler::makeIpKey(const std::string& ip)
{
    return "ip:" + ip;
}

void LoginAttemptThrottler::assertNotLocked(const std::optional<std::uint64_t>& userId,
                                            const std::string& ipAddress)
{
    const auto now = std::chrono::system_clock::now();

    auto isLocked = [&](const std::string& key) {
        std::lock_guard lk{mtx_};
        const auto it = cache_.find(key);
        return it != cache_.end() && it->second.lockedUntil > now;
    };

    if (userId && isLocked(makeUserKey(*userId))) {
        throw ThrottlingException{"Too many failed log-in attempts (user locked)."};
    }
    if (isLocked(makeIpKey(ipAddress))) {
        throw ThrottlingException{"Too many failed log-in attempts (IP locked)."};
    }
}

void LoginAttemptThrottler::touch(const std::string& key, Limits limits)
{
    using namespace std::chrono;
    const auto now = system_clock::now();

    std::lock_guard lk{mtx_};
    auto& state = cache_[key];  // Creates if missing

    // Reset window if expired
    if (now - state.windowStart > limits.window) {
        state.counter = 0;
        state.windowStart = now;
    }

    // Increment and determine lockout
    ++state.counter;
    if (state.counter >= limits.maxAttempts) {
        state.lockedUntil = now + limits.lockout;
        // Reset counter so that after lockout new window starts clean
        state.counter = 0;
        state.windowStart = state.lockedUntil;  // Next window begins after lockout expires
    }

    state.dirty = true;
}

void LoginAttemptThrottler::registerFailure(const std::optional<std::uint64_t>& userId,
                                            const std::string& ipAddress)
{
    try {
        if (userId) {
            touch(makeUserKey(*userId), userLimits_);
        }
        touch(makeIpKey(ipAddress), ipLimits_);
    } catch (const std::exception& e) {
        util::Logger::error("LoginAttemptThrottler.registerFailure: {}", e.what());
    }
}

void LoginAttemptThrottler::registerSuccess(const std::optional<std::uint64_t>& userId,
                                            const std::string& ipAddress)
{
    std::lock_guard lk{mtx_};

    if (userId) {
        cache_.erase(makeUserKey(*userId));
    }
    cache_.erase(makeIpKey(ipAddress));
}

void LoginAttemptThrottler::persistOne(const std::string& key,
                                       const CounterState& state,
                                       orm::EntityManager& em)
{
    if (!state.dirty) { return; }

    LoginAttemptDTO dto;
    dto.key = key;
    dto.counter = state.counter;
    dto.windowStart = state.windowStart;
    dto.lockedUntil = state.lockedUntil;

    em.persistOrUpdate(dto);
}

void LoginAttemptThrottler::flushToDatabase()
{
    std::unordered_map<std::string, CounterState> snapshot;
    {
        std::lock_guard lk{mtx_};
        snapshot = cache_;  // Cheap with move (C++17 guaranteed)
        for (auto& [_, state] : cache_) { state.dirty = false; }
    }

    orm::Transaction txn{em_};
    util::ScopeGuard guard{[&]() noexcept {
        txn.rollback();
    }};

    try {
        for (const auto& [key, state] : snapshot) {
            persistOne(key, state, em_);
        }
        txn.commit();
        guard.dismiss();
    } catch (const std::exception& ex) {
        util::Logger::error("LoginAttemptThrottler.flushToDatabase: {}", ex.what());
    }
}

// ──────────────────────────────────────────────────────────────────────────────
//  Example of integration with background job scheduler
// ──────────────────────────────────────────────────────────────────────────────
namespace {

class ThrottlerFlushJob {
public:
    explicit ThrottlerFlushJob(LoginAttemptThrottler& throttler,
                               std::chrono::minutes interval)
        : throttler_{throttler}
        , interval_{interval}
        , worker_{&ThrottlerFlushJob::run, this}
    {
        worker_.detach();  // Fire-and-forget background thread
    }

private:
    void run()
    {
        util::Logger::info("ThrottlerFlushJob: Worker thread started.");

        while (true) {
            std::this_thread::sleep_for(interval_);
            throttler_.flushToDatabase();
        }
    }

    LoginAttemptThrottler& throttler_;
    std::chrono::minutes interval_;
    std::thread worker_;
};

} // namespace

// ──────────────────────────────────────────────────────────────────────────────
//  Unit-style self-test (only compiled in debug)
// ──────────────────────────────────────────────────────────────────────────────
#ifdef BLOGSUITE_DEBUG_LOGIN_THROTTLER

#include <cassert>

void debugSelfTest()
{
    orm::EntityManager em;  // Dummy
    LoginAttemptThrottler::Limits userL{5, std::chrono::seconds{30},
                                        std::chrono::seconds{60}};
    LoginAttemptThrottler::Limits ipL{10, std::chrono::seconds{30},
                                      std::chrono::seconds{60}};
    LoginAttemptThrottler throttler{userL, ipL, em};

    const std::string ip = "192.0.2.4";
    const std::uint64_t userId = 123;

    // 5 failures → lock
    for (int i = 0; i < 5; ++i) {
        throttler.registerFailure(userId, ip);
    }
    bool thrown = false;
    try {
        throttler.assertNotLocked(userId, ip);
    } catch (const ThrottlingException&) {
        thrown = true;
    }
    assert(thrown);
    util::Logger::info("LoginAttemptThrottler self-test passed.");
}

#endif // BLOGSUITE_DEBUG_LOGIN_THROTTLER

} // namespace web_blog::auth
```