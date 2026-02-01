#include "AuthService.h"

#include <chrono>
#include <random>
#include <stdexcept>
#include <utility>

#include <bcrypt/BCrypt.hpp>   // https://github.com/xen0n/BCrypt-for-Modern-Cpp
#include <jwt-cpp/jwt.h>       // https://github.com/Thalhammer/jwt-cpp
#include <spdlog/spdlog.h>     // Logging

#include "core/crypto/Uuid.h"
#include "core/exception/HttpException.h"
#include "core/http/HttpRequest.h"
#include "core/http/HttpStatus.h"
#include "persistence/TxGuard.h"
#include "repositories/RefreshTokenRepository.h"
#include "repositories/UserRepository.h"

using namespace MosaicBoard::Core;
using namespace MosaicBoard::Persistence;
using namespace MosaicBoard::Repositories;
using namespace std::chrono_literals;

/* =============================================== *
 *         Constants & internal helpers            *
 * =============================================== */

namespace {

constexpr std::chrono::minutes ACCESS_TOKEN_TTL   = std::chrono::minutes{15};
constexpr std::chrono::hours   REFRESH_TOKEN_TTL  = std::chrono::hours{24 * 7};  // one week

jwt::algorithm::hs256 makeJwtAlgorithm(const std::string& secret)
{
    return jwt::algorithm::hs256{secret};
}

std::string generateSecureRandom(size_t bytes)
{
    std::random_device rd;
    std::vector<uint8_t> data(bytes);
    std::generate(data.begin(), data.end(), std::ref(rd));

    static constexpr char hexmap[] = "0123456789abcdef";
    std::string result(data.size() * 2, '\0');

    for (size_t i = 0; i < data.size(); ++i) {
        result[2 * i]     = hexmap[(data[i] & 0xF0) >> 4];
        result[2 * i + 1] = hexmap[data[i] & 0x0F];
    }
    return result;
}

} // namespace

/* =============================================== *
 *               AuthService Impl                  *
 * =============================================== */

AuthService::AuthService(std::shared_ptr<UserRepository>           userRepo,
                         std::shared_ptr<RefreshTokenRepository>   refreshRepo,
                         std::string                               jwtSecret)
    : m_userRepo{std::move(userRepo)}
    , m_refreshTokenRepo{std::move(refreshRepo)}
    , m_jwtAlg{makeJwtAlgorithm(jwtSecret)}
    , m_jwtSecret{std::move(jwtSecret)}
{
    if (!m_userRepo || !m_refreshTokenRepo || m_jwtSecret.empty()) {
        throw std::invalid_argument{"AuthService: invalid construction parameters"};
    }
    spdlog::info("AuthService initialized");
}

/* ---------- Registration --------------------------------------------------- */

bool AuthService::registerUser(const std::string& userName,
                               const std::string& password,
                               const std::string& email)
{
    spdlog::debug("Registering user '{}'", userName);

    if (m_userRepo->existsByUserName(userName)) {
        throw HttpException{HttpStatus::Conflict, "Username already exists."};
    }

    const auto salt     = BCrypt::generateSalt();  // generates 29-char salt
    const auto hash     = BCrypt::generateHash(password, salt);
    const auto userUuid = Uuid::NewV4().toString();

    TxGuard tx{m_userRepo->connection()};  // start DB transaction
    m_userRepo->insert(UserRecord{userUuid, userName, hash, email, false /* isOauth */});
    tx.commit();
    return true;
}

/* ---------- Local Sign-In --------------------------------------------------- */

AuthTokenPair AuthService::signInLocal(const std::string& userName,
                                       const std::string& password)
{
    spdlog::debug("Local sign-in attempt for '{}'", userName);

    auto userOpt = m_userRepo->findByUserName(userName);
    if (!userOpt.has_value()) {
        throw HttpException{HttpStatus::Unauthorized, "Invalid credentials."};
    }

    const UserRecord& user = userOpt.value();
    if (!BCrypt::validatePassword(password, user.passwordHash)) {
        spdlog::warn("Failed authentication for '{}'", userName);
        throw HttpException{HttpStatus::Unauthorized, "Invalid credentials."};
    }

    return issueTokensFor(user.uuid);
}

/* ---------- OAuth sign-in --------------------------------------------------- */

AuthTokenPair AuthService::signInOAuth(const std::string& provider,
                                       const std::string& providerAccessToken)
{
    spdlog::debug("OAuth sign-in attempt via {} ", provider);
    // NOTE: In production, we'd call the provider's API to validate access token
    // For brevity, we treat providerAccessToken as validated and containing email.

    const std::string mockedEmail = providerAccessToken + "@mock.oauth";

    auto userOpt = m_userRepo->findByEmail(mockedEmail);

    // Create user if not exists
    if (!userOpt.has_value()) {
        const auto userUuid = Uuid::NewV4().toString();
        UserRecord rec;
        rec.uuid         = userUuid;
        rec.userName     = provider + "-" + Uuid::NewV4().toString().substr(0, 8);
        rec.passwordHash = "";  // OAuth users have no local password
        rec.email        = mockedEmail;
        rec.isOauth      = true;
        m_userRepo->insert(rec);
        userOpt = rec;
    }

    return issueTokensFor(userOpt->uuid);
}

/* ---------- Token Refresh --------------------------------------------------- */

AuthTokenPair AuthService::refreshToken(const std::string& refreshToken)
{
    spdlog::debug("Refreshing token");

    auto stored = m_refreshTokenRepo->findValid(refreshToken);
    if (!stored.has_value()) {
        throw HttpException{HttpStatus::Unauthorized, "Refresh token invalid or expired."};
    }

    // invalidate old refresh token
    m_refreshTokenRepo->invalidate(refreshToken);
    return issueTokensFor(stored->userUuid);
}

/* ---------- Sign-out -------------------------------------------------------- */

void AuthService::signOut(const std::string& refreshToken)
{
    spdlog::debug("Signing out via refresh token");

    // Even if token not found, we do not leak information.
    m_refreshTokenRepo->invalidate(refreshToken);
}

/* ---------- Request Verification ------------------------------------------- */

bool AuthService::verifyRequest(const HttpRequest& request,
                                std::string&        userUuidOut)
{
    auto authHeader = request.header("Authorization");
    if (!authHeader.starts_with("Bearer ")) {
        return false;
    }
    const std::string token = authHeader.substr(7);

    try {
        auto decoded = jwt::decode(token);

        jwt::verify()
            .allow_algorithm(m_jwtAlg)
            .with_issuer("mosaicboard")
            .verify(decoded);

        // token is valid
        userUuidOut = decoded.get_payload_claim("uid").as_string();
    } catch (const std::exception& ex) {
        spdlog::warn("JWT verification failed: {}", ex.what());
        return false;
    }
    return true;
}

/* ---------- Internal helpers ---------------------------------------------- */

AuthTokenPair AuthService::issueTokensFor(const std::string& userUuid)
{
    const auto now       = std::chrono::system_clock::now();
    const auto expires   = now + ACCESS_TOKEN_TTL;
    const auto refreshId = generateSecureRandom(32);

    // 1. Issue access token (JWT)
    std::string accessToken = jwt::create()
                                  .set_issued_at(now)
                                  .set_expires_at(expires)
                                  .set_issuer("mosaicboard")
                                  .set_type("JWS")
                                  .set_payload_claim("uid", jwt::claim(userUuid))
                                  .sign(m_jwtAlg);

    // 2. Persist refresh token
    RefreshTokenRecord rt;
    rt.token        = refreshId;
    rt.userUuid     = userUuid;
    rt.expiresAt    = now + REFRESH_TOKEN_TTL;

    m_refreshTokenRepo->insert(rt);

    return AuthTokenPair{std::move(accessToken), refreshId};
}