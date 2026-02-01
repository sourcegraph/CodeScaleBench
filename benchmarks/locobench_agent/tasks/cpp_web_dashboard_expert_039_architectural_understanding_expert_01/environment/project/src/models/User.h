#pragma once
/**
 *  MosaicBoard Studio
 *  File: MosaicBoardStudio/src/models/User.h
 *
 *  Description:
 *      Data-model for an authenticated user account inside the MosaicBoard
 *      Studio web-dashboard.  The class is intentionally self-contained:
 *      it can be used with the ORM layer, JSON (de)serialization, and the
 *      in-memory cache subsystem without requiring an additional facade.
 *
 *  Responsibilities:
 *      • Persistable entity (primary-key, timestamps, soft-delete flag)
 *      • Secure password hashing / verification
 *      • Social-login linkage (OAuth provider + remote user identifier)
 *      • Role-based authorization helper utilities
 *      • Simple JSON (de)serialization helpers for REST API payloads
 *      • Helpers for coherency in the distributed cache layer (key builder)
 *
 *  NOTE:
 *      Implementation of crypto / persistence details is delegated to
 *      service-specific components (HashService, Repository, etc.).  The
 *      model keeps only what it needs to stay framework-agnostic.
 */

#include <chrono>
#include <cstdint>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>

#include <nlohmann/json.hpp>      // MIT-licensed single-header JSON lib
#include <openssl/evp.h>          // OpenSSL EVP for PBKDF2-HMAC-SHA256

namespace mbs::models
{
    using Clock = std::chrono::system_clock;
    using TimePoint = std::chrono::time_point<Clock>;

    class User final
    {
    public:
        /* Constructors & factory helpers
         * ------------------------------ */
        User() = default;

        /**
         * Factory for a brand-new local user (traditional signup).
         *
         * Throws std::runtime_error if password hashing fails or if any
         * of the supplied arguments are semantically invalid.
         */
        static User createLocal(
            const std::string& username,
            const std::string& email,
            const std::string& passwordPlainText);

        /**
         * Factory for a user authenticated via a social OAuth provider.
         */
        static User createSocial(
            const std::string& username,
            const std::string& email,
            std::string provider,
            std::string providerUserId);

        /* Rule-of-Five compliance  */
        ~User() = default;
        User(const User&) = default;
        User(User&&) noexcept = default;
        User& operator=(const User&) = default;
        User& operator=(User&&) noexcept = default;

        /* Basic getters
         * ------------- */
        [[nodiscard]] uint64_t           id()              const noexcept { return _id; }
        [[nodiscard]] const std::string& username()        const noexcept { return _username; }
        [[nodiscard]] const std::string& email()           const noexcept { return _email; }
        [[nodiscard]] const std::set<std::string>& roles() const noexcept { return _roles; }
        [[nodiscard]] const std::optional<std::string>& avatarUrl() const noexcept { return _avatarUrl; }
        [[nodiscard]] bool isActive()          const noexcept { return _isActive; }
        [[nodiscard]] bool isEmailVerified()   const noexcept { return _isEmailVerified; }
        [[nodiscard]] TimePoint createdAt()    const noexcept { return _createdAt; }
        [[nodiscard]] TimePoint updatedAt()    const noexcept { return _updatedAt; }

        /* Role management
         * --------------- */
        bool hasRole(const std::string& role) const noexcept { return _roles.contains(role); }
        void addRole(std::string role)              { _roles.insert(std::move(role)); touch(); }
        void removeRole(const std::string& role)    { _roles.erase(role); touch(); }

        /* Credential helpers
         * ------------------ */
        bool verifyPassword(const std::string& plainText) const;
        void updatePassword(const std::string& newPlainText);

        /* Social login linkage  */
        [[nodiscard]] bool isSocialAccount() const noexcept { return _socialProvider.has_value(); }
        [[nodiscard]] const std::optional<std::string>& socialProvider() const noexcept { return _socialProvider; }
        [[nodiscard]] const std::optional<std::string>& socialId() const noexcept { return _socialId; }

        /* Convenience: generate a unique cache key for this user object. */
        [[nodiscard]] std::string cacheKey() const;

        /* JSON (de)serialization (for REST responses / requests) -------- */
        friend void to_json(nlohmann::json& j, const User& u);
        friend void from_json(const nlohmann::json& j, User& u);

    private:
        /* Internal helpers */
        static std::string hashPassword(const std::string& plainText);
        [[nodiscard]] static bool isPasswordMatch(const std::string& plainText,
                                                  const std::string& hashed);

        void touch() noexcept { _updatedAt = Clock::now(); }

        /* Data members -------------------------------------------------- */
        uint64_t _id {0};                                  // Primary key (DB generated)
        std::string _username;
        std::string _email;
        std::string _passwordHash;                         // PBKDF2-HMAC-SHA256 result

        std::set<std::string> _roles;                      // e.g. {"USER", "ADMIN"}

        std::optional<std::string> _avatarUrl;
        std::optional<std::string> _socialProvider;        // e.g. "google", "github"
        std::optional<std::string> _socialId;              // remote user id from provider

        TimePoint _createdAt {Clock::now()};
        TimePoint _updatedAt {Clock::now()};

        bool _isActive        {true};
        bool _isEmailVerified {false};
    };

    /* ------------------------------------------------------------------ */
    /* Inline implementations                                             */
    /* ------------------------------------------------------------------ */

    inline User User::createLocal(const std::string& username,
                                  const std::string& email,
                                  const std::string& passwordPlainText)
    {
        if (username.empty() || email.empty() || passwordPlainText.empty())
            throw std::invalid_argument("Username, email and password must be non-empty.");

        User u;
        u._username      = username;
        u._email         = email;
        u._passwordHash  = hashPassword(passwordPlainText);
        u._roles.insert("USER");
        u._createdAt     = Clock::now();
        u._updatedAt     = u._createdAt;
        return u;
    }

    inline User User::createSocial(const std::string& username,
                                   const std::string& email,
                                   std::string provider,
                                   std::string providerUserId)
    {
        if (username.empty() || email.empty() || provider.empty() || providerUserId.empty())
            throw std::invalid_argument("Social account arguments must be non-empty.");

        User u;
        u._username       = username;
        u._email          = email;
        u._passwordHash   = "";              // No local credential
        u._socialProvider = std::move(provider);
        u._socialId       = std::move(providerUserId);
        u._roles.insert("USER");
        u._createdAt      = Clock::now();
        u._updatedAt      = u._createdAt;
        u._isEmailVerified = true;           // Assume provider has verified
        return u;
    }

    inline bool User::verifyPassword(const std::string& plainText) const
    {
        if (_passwordHash.empty())
            return false; // Social account without local password

        return isPasswordMatch(plainText, _passwordHash);
    }

    inline void User::updatePassword(const std::string& newPlainText)
    {
        if (newPlainText.empty())
            throw std::invalid_argument("Password cannot be empty.");

        _passwordHash = hashPassword(newPlainText);
        touch();
    }

    inline std::string User::cacheKey() const
    {
        return "user:" + std::to_string(_id);
    }

    /* Password hashing utilities --------------------------------------- */
    inline std::string User::hashPassword(const std::string& plainText)
    {
        constexpr size_t  HASH_LEN = 32;         // 256-bit
        constexpr size_t  SALT_LEN = 16;         // 128-bit
        constexpr uint32_t ITERATIONS = 150000;  // OWASP recommendation (2023)

        // Generate a cryptographically strong salt
        unsigned char salt[SALT_LEN];
        if (!RAND_bytes(salt, SALT_LEN))
            throw std::runtime_error("RAND_bytes failed while generating password salt.");

        unsigned char hash[HASH_LEN];

        if (!PKCS5_PBKDF2_HMAC(
                plainText.c_str(),
                static_cast<int>(plainText.size()),
                salt,
                SALT_LEN,
                ITERATIONS,
                EVP_sha256(),
                HASH_LEN,
                hash))
        {
            throw std::runtime_error("PBKDF2 hashing failed.");
        }

        // Encode: <iterations>$<salt_hex>$<hash_hex>
        auto toHex = [](const unsigned char* data, size_t len) -> std::string {
            static constexpr char* const lut = (char*)"0123456789abcdef";
            std::string out;
            out.reserve(2 * len);
            for (size_t i = 0; i < len; ++i)
            {
                const unsigned char c = data[i];
                out.push_back(lut[c >> 4]);
                out.push_back(lut[c & 15]);
            }
            return out;
        };

        std::string saltHex = toHex(salt, SALT_LEN);
        std::string hashHex = toHex(hash, HASH_LEN);

        return std::to_string(ITERATIONS) + "$" + saltHex + "$" + hashHex;
    }

    inline bool User::isPasswordMatch(const std::string& plainText,
                                      const std::string& stored) 
    {
        // Split stored hash
        const auto firstDelim = stored.find('$');
        const auto secondDelim = stored.find('$', firstDelim + 1);
        if (firstDelim == std::string::npos || secondDelim == std::string::npos)
            throw std::invalid_argument("Malformed password hash.");

        uint32_t iterations = std::stoul(stored.substr(0, firstDelim));
        std::string saltHex = stored.substr(firstDelim + 1, secondDelim - firstDelim - 1);
        std::string hashHex = stored.substr(secondDelim + 1);

        auto hexToBytes = [](const std::string& hex) {
            if (hex.size() % 2 != 0)
                throw std::invalid_argument("Hex string has odd length.");
            std::vector<unsigned char> out(hex.size() / 2);
            for (size_t i = 0; i < out.size(); ++i)
            {
                unsigned int byte;
                std::sscanf(hex.substr(2 * i, 2).c_str(), "%02x", &byte);
                out[i] = static_cast<unsigned char>(byte);
            }
            return out;
        };

        auto salt = hexToBytes(saltHex);
        std::vector<unsigned char> computed(hashHex.size() / 2);

        if (!PKCS5_PBKDF2_HMAC(
                plainText.c_str(),
                static_cast<int>(plainText.size()),
                salt.data(),
                static_cast<int>(salt.size()),
                iterations,
                EVP_sha256(),
                static_cast<int>(computed.size()),
                computed.data()))
        {
            throw std::runtime_error("PBKDF2 hashing failed during password check.");
        }

        // Constant-time comparison
        std::string computedHex;
        computedHex.reserve(hashHex.size());
        static constexpr char* const lut = (char*)"0123456789abcdef";
        for (unsigned char byte : computed)
        {
            computedHex.push_back(lut[byte >> 4]);
            computedHex.push_back(lut[byte & 15]);
        }

        return CRYPTO_memcmp(computedHex.data(), hashHex.data(), hashHex.size()) == 0;
    }

    /* JSON (de)serialization ------------------------------------------- */
    inline void to_json(nlohmann::json& j, const User& u)
    {
        j = nlohmann::json{
            {"id", u._id},
            {"username", u._username},
            {"email", u._email},
            {"roles", u._roles},
            {"avatarUrl", u._avatarUrl},
            {"socialProvider", u._socialProvider},
            {"socialId", u._socialId},
            {"createdAt", std::chrono::duration_cast<std::chrono::milliseconds>(
                              u._createdAt.time_since_epoch()).count()},
            {"updatedAt", std::chrono::duration_cast<std::chrono::milliseconds>(
                              u._updatedAt.time_since_epoch()).count()},
            {"isActive", u._isActive},
            {"isEmailVerified", u._isEmailVerified}
        };
    }

    inline void from_json(const nlohmann::json& j, User& u)
    {
        // ID may be absent for new (not-yet-persisted) entities.
        j.at("username").get_to(u._username);
        j.at("email").get_to(u._email);
        j.at("roles").get_to(u._roles);

        if (j.contains("id"))                j.at("id").get_to(u._id);
        if (j.contains("avatarUrl"))         j.at("avatarUrl").get_to(u._avatarUrl);
        if (j.contains("socialProvider"))    j.at("socialProvider").get_to(u._socialProvider);
        if (j.contains("socialId"))          j.at("socialId").get_to(u._socialId);
        if (j.contains("isActive"))          j.at("isActive").get_to(u._isActive);
        if (j.contains("isEmailVerified"))   j.at("isEmailVerified").get_to(u._isEmailVerified);

        // Timestamps: milliseconds since epoch
        if (j.contains("createdAt"))
        {
            auto ms = std::chrono::milliseconds(j.at("createdAt").get<int64_t>());
            u._createdAt = TimePoint(ms);
        }

        if (j.contains("updatedAt"))
        {
            auto ms = std::chrono::milliseconds(j.at("updatedAt").get<int64_t>());
            u._updatedAt = TimePoint(ms);
        }
    }

} // namespace mbs::models