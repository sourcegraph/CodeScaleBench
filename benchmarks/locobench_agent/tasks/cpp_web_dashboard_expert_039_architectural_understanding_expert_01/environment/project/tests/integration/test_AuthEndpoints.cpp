```cpp
/**
 *  File: MosaicBoardStudio/tests/integration/test_AuthEndpoints.cpp
 *  Description:
 *      Integration-level tests for the Authentication REST endpoints exposed by
 *      MosaicBoard Studio’s service layer.  Tests cover the whole request/response
 *      lifecycle against a running instance of the application (usually spawned
 *      via docker-compose or `bazel run //server:mosaicboard_server` prior to
 *      running the test-suite).
 *
 *  Requirements / Build:
 *      • GoogleTest              – unit / integration test framework
 *      • cpr (https://github.com/libcpr/cpr) – lightweight HTTP client
 *      • nlohmann/json           – JSON (de)serialization
 *
 *      All three libraries are already part of third_party/ and wired into the
 *      build via CMake / Bazel in the parent project.
 *
 *  Usage:
 *      $ ./bazel test //tests/integration:test_AuthEndpoints
 *
 *  Author: MosaicBoard Studio Core Team
 *  ----------------------------------------------------------------------------
 */

#include <gtest/gtest.h>
#include <cpr/cpr.h>
#include <nlohmann/json.hpp>

#include <chrono>
#include <cstdlib>
#include <future>
#include <random>
#include <regex>
#include <thread>

using json = nlohmann::json;

// -----------------------------------------------------------------------------
// Test configuration helpers
// -----------------------------------------------------------------------------

namespace {

constexpr std::chrono::seconds kDefaultTimeout = std::chrono::seconds{5};

/**
 * Utility to read environment variables with default fallback.
 */
std::string getenv_or_default(const char* key, std::string_view fallback) {
    const char* value = std::getenv(key);
    return value == nullptr ? std::string{fallback} : std::string{value};
}

/**
 * Scoped deletion of a test user at the end of a test-case that created it.
 * Allows the test-suite to remain idempotent across multiple executions.
 */
class ScopedUserDeleter final {
public:
    ScopedUserDeleter(std::string baseUrl,
                      std::string userId,
                      std::string jwt)
        : baseUrl_(std::move(baseUrl))
        , userId_(std::move(userId))
        , jwt_(std::move(jwt))
    {}

    ~ScopedUserDeleter() noexcept {
        if (userId_.empty() || jwt_.empty())
            return;

        const auto endpoint = baseUrl_ + "/api/v1/users/" + userId_;
        auto resp = cpr::Delete(
            cpr::Url{endpoint},
            cpr::Header{{"Authorization", "Bearer " + jwt_}},
            cpr::Timeout{kDefaultTimeout});

        // We don’t assert here because dtor must not throw; print to stderr.
        if (resp.status_code >= 400) {
            std::cerr << "[WARN] Could not delete test user (id=" << userId_
                      << "), HTTP " << resp.status_code << '\n';
        }
    }

private:
    std::string baseUrl_;
    std::string userId_;
    std::string jwt_;
};

struct AuthTestConfig {
    std::string baseUrl      = getenv_or_default("MOSBD_BASE_URL", "http://localhost:8080");
    std::string testEmail    = "integration_tester+" + std::to_string(std::time(nullptr))
                             + "@example.com";
    std::string testPassword = "Sup3r$ecretPassw0rd!";
};

bool is_server_reachable(const std::string& baseUrl) {
    auto resp = cpr::Get(cpr::Url{baseUrl + "/health"},
                         cpr::Timeout{kDefaultTimeout});
    return resp.status_code == 200;
}

/**
 * Validates that the JWT returned by the server has a plausible format:
 *      header.payload.signature  (all Base64URL)
 */
bool is_plausible_jwt(const std::string& token) {
    static const std::regex jwt_regex(R"(^[-_a-zA-Z0-9]+\.[-_a-zA-Z0-9]+\.[-_a-zA-Z0-9]+$)");
    return std::regex_match(token, jwt_regex);
}

} // namespace

// -----------------------------------------------------------------------------
// Test Fixture
// -----------------------------------------------------------------------------

class AuthEndpointsTest : public ::testing::Test {
protected:
    AuthEndpointsTest()
        : cfg_()
    {}

    void SetUp() override {
        if (!is_server_reachable(cfg_.baseUrl)) {
            GTEST_SKIP_("Server unreachable. Ensure MosaicBoard Studio backend "
                        "is running and MOSBD_BASE_URL is set correctly.");
        }
    }

    AuthTestConfig cfg_;
};

// -----------------------------------------------------------------------------
// Test-Cases
// -----------------------------------------------------------------------------

TEST_F(AuthEndpointsTest, Register_Login_Refresh_Logout_HappyPath) {
    // ------------------------
    // 1. REGISTER NEW ACCOUNT
    // ------------------------
    json payload = {
        {"email",    cfg_.testEmail     },
        {"password", cfg_.testPassword  },
        {"fullName", "Integration Bot" }
    };

    cpr::Response regResp = cpr::Post(
        cpr::Url{cfg_.baseUrl + "/api/v1/auth/register"},
        cpr::Header{{"Content-Type", "application/json"}},
        cpr::Body{payload.dump()},
        cpr::Timeout{kDefaultTimeout});

    ASSERT_EQ(regResp.status_code, 201) << regResp.text;
    auto regBody = json::parse(regResp.text);

    std::string userId = regBody.value("userId", "");
    std::string jwt    = regBody.value("token", "");

    ASSERT_FALSE(userId.empty());
    ASSERT_TRUE(is_plausible_jwt(jwt));

    ScopedUserDeleter cleanup(cfg_.baseUrl, userId, jwt);

    // ------------------------
    // 2. LOGIN WITH NEW ACCOUNT
    // ------------------------
    json loginPayload = {
        {"email",    cfg_.testEmail    },
        {"password", cfg_.testPassword }
    };

    auto loginResp = cpr::Post(
        cpr::Url{cfg_.baseUrl + "/api/v1/auth/login"},
        cpr::Header{{"Content-Type", "application/json"}},
        cpr::Body{loginPayload.dump()},
        cpr::Timeout{kDefaultTimeout});

    ASSERT_EQ(loginResp.status_code, 200);
    auto loginBody = json::parse(loginResp.text);
    std::string loginJwt = loginBody.value("token", "");

    ASSERT_TRUE(is_plausible_jwt(loginJwt));
    ASSERT_NE(loginJwt, jwt) << "Initial token from /register should differ from /login";

    // ------------------------
    // 3. REFRESH TOKEN
    // ------------------------
    auto refreshResp = cpr::Post(
        cpr::Url{cfg_.baseUrl + "/api/v1/auth/refresh"},
        cpr::Header{
            {"Authorization", "Bearer " + loginJwt},
            {"Content-Type",  "application/json"}
        },
        cpr::Timeout{kDefaultTimeout});

    ASSERT_EQ(refreshResp.status_code, 200);
    auto refreshBody = json::parse(refreshResp.text);
    std::string newJwt = refreshBody.value("token", "");

    ASSERT_TRUE(is_plausible_jwt(newJwt));
    ASSERT_NE(newJwt, loginJwt);

    // ------------------------
    // 4. LOGOUT
    // ------------------------
    auto logoutResp = cpr::Post(
        cpr::Url{cfg_.baseUrl + "/api/v1/auth/logout"},
        cpr::Header{{"Authorization", "Bearer " + newJwt}},
        cpr::Timeout{kDefaultTimeout});

    ASSERT_EQ(logoutResp.status_code, 204);

    // Token should now be invalid
    auto postLogoutResp = cpr::Post(
        cpr::Url{cfg_.baseUrl + "/api/v1/auth/refresh"},
        cpr::Header{{"Authorization", "Bearer " + newJwt}},
        cpr::Timeout{kDefaultTimeout});

    EXPECT_EQ(postLogoutResp.status_code, 401);
}

TEST_F(AuthEndpointsTest, Register_DuplicateEmail_ShouldConflict) {
    // First registration
    json payload = {
        {"email",    cfg_.testEmail     },
        {"password", cfg_.testPassword  },
        {"fullName", "Integration Bot" }
    };

    auto reg1 = cpr::Post(
        cpr::Url{cfg_.baseUrl + "/api/v1/auth/register"},
        cpr::Header{{"Content-Type", "application/json"}},
        cpr::Body{payload.dump()},
        cpr::Timeout{kDefaultTimeout});

    ASSERT_EQ(reg1.status_code, 201);
    auto body1 = json::parse(reg1.text);
    ScopedUserDeleter cleanup(cfg_.baseUrl, body1.value("userId", ""), body1.value("token", ""));

    // Duplicate registration
    auto reg2 = cpr::Post(
        cpr::Url{cfg_.baseUrl + "/api/v1/auth/register"},
        cpr::Header{{"Content-Type", "application/json"}},
        cpr::Body{payload.dump()},
        cpr::Timeout{kDefaultTimeout});

    EXPECT_EQ(reg2.status_code, 409) << reg2.text;
}

TEST_F(AuthEndpointsTest, Login_With_InvalidCredentials_ShouldFail) {
    json wrongPayload = {
        {"email",    "nonexistent_" + std::to_string(std::time(nullptr)) + "@example.com"},
        {"password", "wrongPassword123"}
    };

    auto resp = cpr::Post(
        cpr::Url{cfg_.baseUrl + "/api/v1/auth/login"},
        cpr::Header{{"Content-Type", "application/json"}},
        cpr::Body{wrongPayload.dump()},
        cpr::Timeout{kDefaultTimeout});

    EXPECT_EQ(resp.status_code, 401);
}

TEST_F(AuthEndpointsTest, ConcurrentLoginShouldSucceedAndReturnUniqueTokens) {
    const int kThreadCount = 5;
    std::vector<std::future<std::string>> futures;

    // Ensure the test user exists
    json payload = {
        {"email",    cfg_.testEmail     },
        {"password", cfg_.testPassword  },
        {"fullName", "Concurrent Bot" }
    };
    cpr::Post(
        cpr::Url{cfg_.baseUrl + "/api/v1/auth/register"},
        cpr::Header{{"Content-Type", "application/json"}},
        cpr::Body{payload.dump()},
        cpr::Timeout{kDefaultTimeout}); // ignore status; may already exist

    auto loginLambda = [this]() -> std::string {
        json loginPayload = {
            {"email",    cfg_.testEmail    },
            {"password", cfg_.testPassword }
        };
        auto resp = cpr::Post(
            cpr::Url{cfg_.baseUrl + "/api/v1/auth/login"},
            cpr::Header{{"Content-Type", "application/json"}},
            cpr::Body{loginPayload.dump()},
            cpr::Timeout{kDefaultTimeout});

        if (resp.status_code != 200)
            return {};

        return json::parse(resp.text).value("token", "");
    };

    for (int i = 0; i < kThreadCount; ++i) {
        futures.emplace_back(std::async(std::launch::async, loginLambda));
    }

    std::vector<std::string> tokens;
    for (auto& f : futures) {
        auto token = f.get();
        EXPECT_TRUE(is_plausible_jwt(token));
        tokens.push_back(std::move(token));
    }

    // Ensure all tokens are unique
    std::sort(tokens.begin(), tokens.end());
    auto it = std::unique(tokens.begin(), tokens.end());
    EXPECT_EQ(it, tokens.end()) << "Duplicate JWTs were returned for concurrent logins";
}

```