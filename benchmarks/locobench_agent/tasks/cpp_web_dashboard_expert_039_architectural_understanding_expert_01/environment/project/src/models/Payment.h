/**
 *  MosaicBoard Studio
 *  File: src/models/Payment.h
 *
 *  Description:
 *      Immutable domain-level representation of a Payment as stored in the
 *      MosaicBoard Studio service layer.  A Payment can be serialized/
 *      deserialized to JSON (for the REST API) and can be mutated through a
 *      well-defined, thread-safe state-machine that enforces valid transitions
 *      (e.g. you cannot capture a payment that is not yet authorised).
 *
 *  NOTE:
 *      This header is intentionally fully self-contained (header-only) so it
 *      can easily be included in multiple components (service layer, plugins,
 *      unit-tests, etc.) without requiring a separate compilation unit.
 */

#pragma once

#include <chrono>
#include <cstdint>
#include <mutex>
#include <optional>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>

#include <nlohmann/json.hpp>

namespace mosaic::models
{
    /* ────────────────────────────────────────────────────────────────────────── *
     *  Enumerations / Simple Helpers
     * ────────────────────────────────────────────────────────────────────────── */

    enum class PaymentStatus
    {
        Pending,        // Initial state – waiting for provider authorisation
        Authorised,     // Provider authorised funds but has not captured them
        Captured,       // Funds captured
        Cancelled,      // Cancelled before capture
        Refunded,       // Captured and subsequently refunded
        Failed          // Provider reported failure
    };

    enum class PaymentMethod
    {
        Card,
        BankTransfer,
        Wallet,
        Crypto,
        Unknown
    };

    /* Helper functions to convert enum values to/from wire-protocol strings. */
    inline std::string to_string(PaymentStatus status)
    {
        switch (status)
        {
            case PaymentStatus::Pending:    return "pending";
            case PaymentStatus::Authorised: return "authorised";
            case PaymentStatus::Captured:   return "captured";
            case PaymentStatus::Cancelled:  return "cancelled";
            case PaymentStatus::Refunded:   return "refunded";
            case PaymentStatus::Failed:     return "failed";
        }
        throw std::logic_error{"Unhandled PaymentStatus value"};
    }

    inline std::string to_string(PaymentMethod method)
    {
        switch (method)
        {
            case PaymentMethod::Card:         return "card";
            case PaymentMethod::BankTransfer: return "bank_transfer";
            case PaymentMethod::Wallet:       return "wallet";
            case PaymentMethod::Crypto:       return "crypto";
            case PaymentMethod::Unknown:      return "unknown";
        }
        throw std::logic_error{"Unhandled PaymentMethod value"};
    }

    inline PaymentStatus status_from_string(const std::string& val)
    {
        if (val == "pending")      return PaymentStatus::Pending;
        if (val == "authorised")   return PaymentStatus::Authorised;
        if (val == "captured")     return PaymentStatus::Captured;
        if (val == "cancelled")    return PaymentStatus::Cancelled;
        if (val == "refunded")     return PaymentStatus::Refunded;
        if (val == "failed")       return PaymentStatus::Failed;
        throw std::invalid_argument{"Invalid PaymentStatus string: " + val};
    }

    inline PaymentMethod method_from_string(const std::string& val)
    {
        if (val == "card")          return PaymentMethod::Card;
        if (val == "bank_transfer") return PaymentMethod::BankTransfer;
        if (val == "wallet")        return PaymentMethod::Wallet;
        if (val == "crypto")        return PaymentMethod::Crypto;
        return PaymentMethod::Unknown;
    }

    /* ────────────────────────────────────────────────────────────────────────── *
     *  Exception hierarchy
     * ────────────────────────────────────────────────────────────────────────── */

    class PaymentError : public std::runtime_error
    {
        using std::runtime_error::runtime_error;
    };

    class InvalidTransitionError : public PaymentError
    {
        using PaymentError::PaymentError;
    };

    /* ────────────────────────────────────────────────────────────────────────── *
     *  Payment Aggregate
     * ────────────────────────────────────────────────────────────────────────── */

    class Payment final
    {
    public:
        using Timestamp = std::chrono::system_clock::time_point;

        /* Factory: create a brand-new payment with a freshly generated UUID. */
        static Payment createNew(std::string  userId,
                                 std::string  orderId,
                                 int64_t      amountCents,
                                 std::string  currency,
                                 PaymentMethod method = PaymentMethod::Unknown)
        {
            return Payment(generate_uuid(),
                           std::move(userId),
                           std::move(orderId),
                           amountCents,
                           std::move(currency),
                           method,
                           PaymentStatus::Pending,
                           std::chrono::system_clock::now(),
                           std::chrono::system_clock::now());
        }

        /* Factory: hydrate payment from persistent storage / JSON. */
        static Payment fromJson(const nlohmann::json& j)
        {
            return Payment(
                j.at("id").get<std::string>(),
                j.at("user_id").get<std::string>(),
                j.at("order_id").get<std::string>(),
                j.at("amount_cents").get<int64_t>(),
                j.at("currency").get<std::string>(),
                method_from_string(j.at("method").get<std::string>()),
                status_from_string(j.at("status").get<std::string>()),
                Timestamp{std::chrono::milliseconds{
                    j.at("created_at_ms").get<int64_t>()}},
                Timestamp{std::chrono::milliseconds{
                    j.at("updated_at_ms").get<int64_t>()}},
                j.value("provider_charge_id", ""),
                j.contains("failure_message")
                    ? std::make_optional(j.at("failure_message").get<std::string>())
                    : std::nullopt);
        }

        /* Serialize to JSON. Sensitive providerChargeId can be redacted. */
        nlohmann::json toJson(bool redactSensitive = false) const
        {
            std::lock_guard lk{mutex_};
            nlohmann::json j;
            j["id"]              = id_;
            j["user_id"]         = userId_;
            j["order_id"]        = orderId_;
            j["amount_cents"]    = amountCents_;
            j["currency"]        = currency_;
            j["method"]          = to_string(method_);
            j["status"]          = to_string(status_);
            j["created_at_ms"]   = as_epoch_ms(createdAt_);
            j["updated_at_ms"]   = as_epoch_ms(updatedAt_);

            if (!providerChargeId_.empty() && !redactSensitive)
                j["provider_charge_id"] = providerChargeId_;

            if (failureMessage_)
                j["failure_message"] = *failureMessage_;

            return j;
        }

        /* ── Business state-machine operations ───────────────────────────── */

        void markAuthorised(std::string providerChargeId)
        {
            std::lock_guard lk{mutex_};
            if (status_ != PaymentStatus::Pending)
                throw InvalidTransitionError{"Can only authorise from Pending"};

            status_            = PaymentStatus::Authorised;
            providerChargeId_  = std::move(providerChargeId);
            touch_();
        }

        void markCaptured()
        {
            std::lock_guard lk{mutex_};
            if (status_ != PaymentStatus::Authorised)
                throw InvalidTransitionError{"Can only capture from Authorised"};

            status_ = PaymentStatus::Captured;
            touch_();
        }

        void markCancelled()
        {
            std::lock_guard lk{mutex_};
            if (status_ != PaymentStatus::Pending &&
                status_ != PaymentStatus::Authorised)
                throw InvalidTransitionError{"Can only cancel from Pending/Authorised"};

            status_ = PaymentStatus::Cancelled;
            touch_();
        }

        void markRefunded()
        {
            std::lock_guard lk{mutex_};
            if (status_ != PaymentStatus::Captured)
                throw InvalidTransitionError{"Can only refund a Captured payment"};

            status_ = PaymentStatus::Refunded;
            touch_();
        }

        void markFailed(std::string reason)
        {
            std::lock_guard lk{mutex_};
            if (status_ == PaymentStatus::Captured || status_ == PaymentStatus::Refunded)
                throw InvalidTransitionError{"Cannot fail an already captured/refunded payment"};

            status_         = PaymentStatus::Failed;
            failureMessage_ = std::move(reason);
            touch_();
        }

        /* ── Accessors ───────────────────────────────────────────────────── */

        std::string                         id()              const { std::lock_guard lk{mutex_}; return id_; }
        std::string                         userId()          const { std::lock_guard lk{mutex_}; return userId_; }
        std::string                         orderId()         const { std::lock_guard lk{mutex_}; return orderId_; }
        int64_t                             amountCents()     const { std::lock_guard lk{mutex_}; return amountCents_; }
        std::string                         currency()        const { std::lock_guard lk{mutex_}; return currency_; }
        PaymentMethod                       method()          const { std::lock_guard lk{mutex_}; return method_; }
        PaymentStatus                       status()          const { std::lock_guard lk{mutex_}; return status_; }
        std::optional<std::string>          failureMessage()  const { std::lock_guard lk{mutex_}; return failureMessage_; }
        std::optional<std::string>          providerChargeId()const { std::lock_guard lk{mutex_};
                                                                      return providerChargeId_.empty() ?
                                                                             std::nullopt :
                                                                             std::make_optional(providerChargeId_); }
        Timestamp                           createdAt()       const { std::lock_guard lk{mutex_}; return createdAt_; }
        Timestamp                           updatedAt()       const { std::lock_guard lk{mutex_}; return updatedAt_; }

    private:
        /* Hidden constructor used by factories. */
        Payment(std::string  id,
                std::string  userId,
                std::string  orderId,
                int64_t      amountCents,
                std::string  currency,
                PaymentMethod method,
                PaymentStatus status,
                Timestamp    createdAt,
                Timestamp    updatedAt,
                std::string  providerChargeId = {},
                std::optional<std::string> failureMessage = std::nullopt)
        : id_(std::move(id)),
          userId_(std::move(userId)),
          orderId_(std::move(orderId)),
          amountCents_(amountCents),
          currency_(std::move(currency)),
          method_(method),
          status_(status),
          createdAt_(createdAt),
          updatedAt_(updatedAt),
          providerChargeId_(std::move(providerChargeId)),
          failureMessage_(std::move(failureMessage))
        {}

        /* Generate cryptographically secure-ish UUID4. */
        static std::string generate_uuid()
        {
            std::random_device rd;
            std::mt19937_64    gen(rd());
            std::uniform_int_distribution<uint64_t> dis;

            auto to_hex = [](uint64_t value, int width) {
                std::stringstream ss;
                ss << std::hex << std::nouppercase;
                ss.width(width);
                ss.fill('0');
                ss << value;
                return ss.str();
            };

            uint64_t part1 = dis(gen);
            uint64_t part2 = dis(gen);

            /* UUID format: 8-4-4-4-12 */
            return to_hex(part1 >> 32, 8) + "-" +
                   to_hex(part1 >> 16, 4) + "-" +
                   to_hex((part1 & 0x0fff) | 0x4000, 4) + "-" +           // Version 4
                   to_hex((part2 & 0x3fff) | 0x8000, 4) + "-" +           // Variant 1
                   to_hex(part2 & 0xFFFFFFFFFFFFULL, 12);
        }

        /* Convert time_point to epoch milliseconds. */
        static int64_t as_epoch_ms(const Timestamp& ts)
        {
            using namespace std::chrono;
            return duration_cast<milliseconds>(ts.time_since_epoch()).count();
        }

        /* Update `updatedAt_` */
        void touch_() noexcept { updatedAt_ = std::chrono::system_clock::now(); }

        /* ── Members ─────────────────────────────────────────────────────── */
        mutable std::mutex   mutex_;

        std::string          id_;
        std::string          userId_;
        std::string          orderId_;
        int64_t              amountCents_;
        std::string          currency_;

        PaymentMethod        method_;
        PaymentStatus        status_;

        Timestamp            createdAt_;
        Timestamp            updatedAt_;

        std::string          providerChargeId_;            // PSP (Stripe, Paypal, etc.)
        std::optional<std::string> failureMessage_;        // human-readable error
    };

    /* Extend nlohmann::json to understand Payment automatically. */
    inline void to_json(nlohmann::json& j, const Payment& p) { j = p.toJson(); }
    inline void from_json(const nlohmann::json& j, Payment& p) { p = Payment::fromJson(j); }

} // namespace mosaic::models