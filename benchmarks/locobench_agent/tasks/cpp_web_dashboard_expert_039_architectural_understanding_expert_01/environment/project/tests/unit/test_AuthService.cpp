```cpp
// MosaicBoardStudio/tests/unit/test_AuthService.cpp
//
// Unit-tests for the authentication/service layer.
//
// These tests focus on the public contract exposed by
// services::auth::AuthService.  All external collaborators
// (repositories, crypto utilities, 3rd-party OAuth providers, …)
// are mocked with Trompeloeil so that we can validate AuthService’s
// behaviour in complete isolation.
//
// Build requirements (CMake example):
//
//     find_package(Catch2 CONFIG REQUIRED)
//     find_package(trompeloeil CONFIG REQUIRED)
//     add_executable(test_auth_service test_AuthService.cpp)
//     target_link_libraries(test_auth_service
//         PRIVATE Catch2::Catch2WithMain trompeloeil::trompeloeil)
//
// ────────────────────────────────────────────────────────────────────────────
#include <catch2/catch.hpp>
#include <trompeloeil.hpp>

#include <chrono>
#include <optional>
#include <string>
#include <stdexcept>

// ──────────────────────── Project headers (SUT) ────────────────────────────
#include "services/auth/AuthService.hpp"          //  interfaces::IAuthService
#include "services/auth/exceptions.hpp"          //  AuthenticationError, …
#include "domain/user/User.hpp"                  //  domain::User

using namespace std::chrono_literals;
using namespace mosaicboard::services;
using namespace mosaicboard::services::auth;
using mosaicboard::domain::User;

// ──────────────────────── Helper data builders ─────────────────────────────
namespace builders
{
    inline User makeDummyUser(std::string email,
                              std::string passwordHash,
                              bool isActive = true)
    {
        User user;
        user.id            = User::Id{42};
        user.email         = std::move(email);
        user.password_hash = std::move(passwordHash);
        user.is_active     = isActive;
        user.created_at    = std::chrono::system_clock::now() - 24h;
        user.updated_at    = std::chrono::system_clock::now() - 1h;
        return user;
    }
}

// ────────────────────────────── Mocks ──────────────────────────────────────
struct MockUserRepository : public interfaces::IUserRepository
{
    MAKE_MOCK1(findByEmail,
               std::optional<User>(const std::string& email),
               override);

    MAKE_MOCK1(save,
               void(const User&),
               override);
};

struct MockPasswordHasher : public interfaces::IPasswordHasher
{
    MAKE_CONST_MOCK1(verify,
                     bool(const std::string& raw, const std::string& hash),
                     override);

    MAKE_CONST_MOCK1(hash,
                     std::string(const std::string& raw),
                     override);
};

struct MockTokenService : public interfaces::ITokenService
{
    MAKE_MOCK2(issuePair,
               TokenPair(const User&, std::chrono::seconds),
               override);

    MAKE_CONST_MOCK1(validateAccess,
                     TokenValidationResult(const std::string& accessToken),
                     override);

    MAKE_MOCK1(invalidate,
               void(const std::string& accessToken),
               override);

    MAKE_MOCK1(refresh,
               TokenPair(const std::string& refreshToken),
               override);
};

struct MockOAuthProvider : public interfaces::IOAuthProvider
{
    MAKE_CONST_MOCK1(fetchUserEmail,
                     std::string(const std::string& authCode),
                     override);
};

struct MockProviderRegistry : public interfaces::IOAuthProviderRegistry
{
    MAKE_CONST_MOCK1(resolve,
                     std::shared_ptr<interfaces::IOAuthProvider>(const std::string& providerName),
                     override);
};

// ────────────────────────── Test-Fixture  ──────────────────────────────────
struct AuthServiceFixture
{
    std::unique_ptr<AuthService>            sut;
    std::shared_ptr<MockUserRepository>     repo  = std::make_shared<MockUserRepository>();
    std::shared_ptr<MockPasswordHasher>     hasher = std::make_shared<MockPasswordHasher>();
    std::shared_ptr<MockTokenService>       tokens = std::make_shared<MockTokenService>();
    std::shared_ptr<MockProviderRegistry>   oauth  = std::make_shared<MockProviderRegistry>();

    AuthServiceFixture()
    {
        sut = std::make_unique<AuthService>(repo, hasher, tokens, oauth);
    }
};

// ───────────────────────────── Test-Cases ──────────────────────────────────
TEST_CASE_METHOD(AuthServiceFixture,
                 "login() succeeds with valid credentials",
                 "[auth][login][positive]")
{
    const std::string email    = "alice@mosaic.tld";
    const std::string password = "P@ssw0rd!";

    // 1.  Repository returns the user
    const auto user = builders::makeDummyUser(email, "$hashed$pw");
    REQUIRE_CALL(*repo, findByEmail(email)).RETURN(user);

    // 2.  Password hasher confirms validity
    REQUIRE_CALL(*hasher, verify(password, user.password_hash)).RETURN(true);

    // 3.  Token service issues a fresh pair
    const TokenPair expectedPair{ "access-tok", "refresh-tok", 30min };
    REQUIRE_CALL(*tokens, issuePair(user, 30min)).RETURN(expectedPair);

    const auto actualPair = sut->login(email, password);

    REQUIRE(actualPair.accessToken  == expectedPair.accessToken);
    REQUIRE(actualPair.refreshToken == expectedPair.refreshToken);
}

TEST_CASE_METHOD(AuthServiceFixture,
                 "login() throws when user does not exist",
                 "[auth][login][negative]")
{
    const std::string email = "ghost@mosaic.tld";

    REQUIRE_CALL(*repo, findByEmail(email)).RETURN(std::nullopt);

    REQUIRE_THROWS_AS(sut->login(email, "irrelevant"),
                      AuthenticationError);
}

TEST_CASE_METHOD(AuthServiceFixture,
                 "login() throws with wrong password",
                 "[auth][login][negative]")
{
    const std::string email = "bob@mosaic.tld";
    const auto        user  = builders::makeDummyUser(email, "$hashed$pw");
    REQUIRE_CALL(*repo, findByEmail(email)).RETURN(user);

    REQUIRE_CALL(*hasher, verify("wrong-pw", user.password_hash))
        .RETURN(false);

    REQUIRE_THROWS_AS(sut->login(email, "wrong-pw"),
                      AuthenticationError);
}

TEST_CASE_METHOD(AuthServiceFixture,
                 "validate() returns true for a valid token",
                 "[auth][validate]")
{
    const std::string token = "valid-access-tok";
    REQUIRE_CALL(*tokens, validateAccess(token))
        .RETURN(TokenValidationResult{
            .isValid   = true,
            .userId    = User::Id{42},
            .expiresIn = 5min });

    const auto result = sut->validate(token);

    REQUIRE(result.isValid);
    REQUIRE(result.userId == User::Id{42});
}

TEST_CASE_METHOD(AuthServiceFixture,
                 "validate() returns false for an expired token",
                 "[auth][validate]")
{
    const std::string token = "expired-access-tok";
    REQUIRE_CALL(*tokens, validateAccess(token))
        .RETURN(TokenValidationResult{
            .isValid   = false,
            .userId    = {},
            .expiresIn = 0s });

    const auto result = sut->validate(token);

    REQUIRE_FALSE(result.isValid);
}

TEST_CASE_METHOD(AuthServiceFixture,
                 "refresh() returns a new token pair",
                 "[auth][refresh]")
{
    const std::string refresh = "refresh-tok-123";
    const TokenPair   pair    = { "a2", "r2", 30min };
    REQUIRE_CALL(*tokens, refresh(refresh)).RETURN(pair);

    const auto actual = sut->refresh(refresh);

    REQUIRE(actual.accessToken  == pair.accessToken);
    REQUIRE(actual.refreshToken == pair.refreshToken);
}

TEST_CASE_METHOD(AuthServiceFixture,
                 "logout() invalidates the supplied access token",
                 "[auth][logout]")
{
    const std::string access = "to-be-revoked";
    REQUIRE_CALL(*tokens, invalidate(access)).TIMES(1);

    sut->logout(access);
}

TEST_CASE_METHOD(AuthServiceFixture,
                 "socialLogin() provisions a new user when one does not yet exist",
                 "[auth][social][provision]")
{
    constexpr auto providerName = "github";
    const std::string authCode = "gh-oauth-code";
    const std::string fetchedEmail = "carol@github.dev";

    // 1.  Provider registry returns an OAuth provider
    auto provider = std::make_shared<MockOAuthProvider>();
    REQUIRE_CALL(*oauth, resolve(providerName)).RETURN(provider);

    // 2.  Provider extracts e-mail from OAuth code
    REQUIRE_CALL(*provider, fetchUserEmail(authCode)).RETURN(fetchedEmail);

    // 3.  User does *not* exist yet -> repo returns nullopt
    REQUIRE_CALL(*repo, findByEmail(fetchedEmail)).RETURN(std::nullopt);

    // 4.  Repo will be asked to *save* the provisioned user
    REQUIRE_CALL(*repo, save(trompeloeil::_)).TIMES(1);

    // 5.  Token service issues a pair for the newly created user
    const TokenPair pair{ "soc-access", "soc-refresh", 30min };
    REQUIRE_CALL(*tokens, issuePair(trompeloeil::_, 30min)).RETURN(pair);

    const auto actual = sut->socialLogin(providerName, authCode);

    REQUIRE(actual.accessToken == pair.accessToken);
}

TEST_CASE_METHOD(AuthServiceFixture,
                 "socialLogin() fails when provider is unknown",
                 "[auth][social][negative]")
{
    constexpr auto providerName = "nonexistent";
    constexpr auto authCode     = "dummy";

    REQUIRE_CALL(*oauth, resolve(providerName))
        .RETURN(nullptr);

    REQUIRE_THROWS_AS(sut->socialLogin(providerName, authCode),
                      ProviderNotFoundError);
}
```