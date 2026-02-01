#pragma once
/*******************************************************************************
 *  MosaicBoard Studio - Payment Service Interface
 *
 *  File: PaymentService.h
 *  Project: MosaicBoard Studio (web_dashboard)
 *  Description:
 *      Provides an abstraction layer between controllers (REST endpoints) and
 *      low-level payment providers (Stripe, PayPal, etc.).  Encapsulates all
 *      business rules, caching, idempotency guarantees and exception handling
 *      required for reliable payment processing inside the dashboard runtime.
 *
 *  Author: MosaicBoard Core Team
 *  License: Apache-2.0
 ******************************************************************************/

#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>

#include <nlohmann/json.hpp>       // For structured metadata

//------------------------------------------------------------------------------
// Forward declarations of other MosaicBoard components
//------------------------------------------------------------------------------
namespace mbs
{
class ILogger;                     // Logging facade
class ICache;                      // Generic cache interface (e.g., Redis/Memcached)
class IDatabaseSession;            // ORM/Repository abstraction
} // namespace mbs

//------------------------------------------------------------------------------
// Public API
//------------------------------------------------------------------------------
namespace mbs::payments
{

//------------------------------------------------------------------------------
// Enumerations / Constants
//------------------------------------------------------------------------------
enum class PaymentMethod
{
    Card,
    PayPal,
    ApplePay,
    GooglePay,
    BankTransfer
};

enum class PaymentStatus
{
    Pending,
    Succeeded,
    Failed,
    Refunded
};

//------------------------------------------------------------------------------
// Exception Hierarchy
//------------------------------------------------------------------------------
class PaymentException : public std::runtime_error
{
public:
    explicit PaymentException(const std::string& what)
        : std::runtime_error{ what }
    {}
};

class PaymentGatewayException : public PaymentException
{
public:
    using PaymentException::PaymentException;
};

class DuplicateRequestException : public PaymentException
{
public:
    using PaymentException::PaymentException;
};

//------------------------------------------------------------------------------
// Data Transfer Objects
//------------------------------------------------------------------------------
struct PaymentRequest
{
    std::string         idempotencyKey;    // Unique key across retries
    std::string         userId;            // Dashboard user making the payment
    std::uint64_t       amountCents;       // Minor currency unit
    std::string         currency;          // ISO-4217 (e.g., "USD")
    PaymentMethod       method;            // Selected payment method
    nlohmann::json      metadata;          // Arbitrary JSON (order info, etc.)
};

struct PaymentReceipt
{
    std::string                     receiptId;
    std::string                     transactionId;  // Provider-specific
    PaymentStatus                   status;
    std::uint64_t                   amountCents;
    std::string                     currency;
    std::chrono::system_clock::time_point timestamp;
    nlohmann::json                  metadata;
};

//------------------------------------------------------------------------------
// Payment Gateway Abstraction
//------------------------------------------------------------------------------
class IPaymentGateway
{
public:
    virtual ~IPaymentGateway() = default;

    // Process a charge; throws PaymentGatewayException on failures
    virtual PaymentReceipt charge(const PaymentRequest& request) = 0;

    // Refund an existing charge; partial refunds supported
    virtual PaymentReceipt refund(const std::string& transactionId,
                                  std::optional<std::uint64_t> amountCents,
                                  const nlohmann::json& metadata) = 0;
};

//------------------------------------------------------------------------------
// Payment Repository Abstraction
//------------------------------------------------------------------------------
class IPaymentRepository
{
public:
    virtual ~IPaymentRepository() = default;

    virtual void saveReceipt(const PaymentReceipt& receipt) = 0;
    virtual std::optional<PaymentReceipt> findById(const std::string& receiptId) = 0;
    virtual std::optional<PaymentReceipt> findByIdempotencyKey(const std::string& idemKey) = 0;
    virtual void updateStatus(const std::string& receiptId, PaymentStatus) = 0;
};

//------------------------------------------------------------------------------
// PaymentService
//------------------------------------------------------------------------------
class PaymentService
{
public:
    struct Config
    {
        std::chrono::minutes idemKeyTtl        = std::chrono::minutes{ 30 };   // Duplicate window
        std::chrono::seconds gatewayTimeout    = std::chrono::seconds{ 15 };   // External call
    };

public:
    PaymentService(std::shared_ptr<IPaymentGateway> gateway,
                   std::shared_ptr<IPaymentRepository> repository,
                   std::shared_ptr<ICache> cache,
                   std::shared_ptr<ILogger> logger,
                   Config cfg = {})
        : _gateway{ std::move(gateway) }
        , _repository{ std::move(repository) }
        , _cache{ std::move(cache) }
        , _logger{ std::move(logger) }
        , _cfg{ cfg }
    {}

    // Prevent slicing; explicit rule-of-5 management
    PaymentService(const PaymentService&)            = delete;
    PaymentService& operator=(const PaymentService&) = delete;
    PaymentService(PaymentService&&)                 = delete;
    PaymentService& operator=(PaymentService&&)      = delete;

    ~PaymentService() = default;

    //----------------------------------------------------------------------
    // Public API
    //----------------------------------------------------------------------
    // Executes a payment request while guaranteeing idempotency.
    PaymentReceipt processPayment(const PaymentRequest& request)
    {
        // 1. Deduplicate calls via cache (idempotencyKey -> receiptId)
        const auto cacheKey = makeCacheKey(request.idempotencyKey);
        if (const auto cachedId = _cache->getString(cacheKey); !cachedId.empty())
        {
            if (auto receiptOpt = _repository->findById(cachedId))
            {
                _logger->info("[PaymentService] Returning cached receipt {} for idemKey {}",
                               cachedId, request.idempotencyKey);
                return *receiptOpt; // Already processed
            }
        }

        // 2. Double-check in persistent storage (safety net)
        if (auto receiptOpt = _repository->findByIdempotencyKey(request.idempotencyKey))
        {
            _cache->putString(cacheKey, receiptOpt->receiptId,
                              std::chrono::duration_cast<std::chrono::seconds>(_cfg.idemKeyTtl));
            _logger->warn("[PaymentService] Found existing payment via repository for idemKey {}",
                          request.idempotencyKey);
            return *receiptOpt;
        }

        //----------------------------------------
        // 3. Perform charge against gateway
        //----------------------------------------
        PaymentReceipt receipt;
        try
        {
            receipt = _gateway->charge(request);
        }
        catch (const PaymentGatewayException& ex)
        {
            _logger->error("[PaymentService] Gateway error processing idemKey {}: {}",
                           request.idempotencyKey, ex.what());
            throw;  // Propagate to controller layer
        }

        //----------------------------------------
        // 4. Persist & Cache
        //----------------------------------------
        _repository->saveReceipt(receipt);
        _cache->putString(cacheKey, receipt.receiptId,
                          std::chrono::duration_cast<std::chrono::seconds>(_cfg.idemKeyTtl));

        _logger->info("[PaymentService] Payment succeeded. receiptId={} amount={} cents", 
                      receipt.receiptId, receipt.amountCents);

        return receipt;
    }

    // Refund can be called multiple times; ensures status tracking and idempotency
    PaymentReceipt refundPayment(const std::string& receiptId,
                                 std::optional<std::uint64_t> amountCents = {},
                                 const nlohmann::json& metadata = {})
    {
        // Fetch receipt to obtain provider transactionId
        auto receiptOpt = _repository->findById(receiptId);
        if (!receiptOpt.has_value())
        {
            throw PaymentException{ "Receipt not found: " + receiptId };
        }

        auto& original = *receiptOpt;
        if (original.status == PaymentStatus::Refunded)
        {
            _logger->warn("[PaymentService] Attempt to refund already refunded receipt {}",
                          receiptId);
            return original;
        }

        // Call gateway
        PaymentReceipt refundReceipt;
        try
        {
            refundReceipt = _gateway->refund(original.transactionId, amountCents, metadata);
        }
        catch (const PaymentGatewayException& ex)
        {
            _logger->error("[PaymentService] Gateway refund error for receipt {}: {}",
                           receiptId, ex.what());
            throw;
        }

        // Update DB
        _repository->updateStatus(receiptId, PaymentStatus::Refunded);

        // Cache invalidation
        _cache->erase(makeCacheKey(original.metadata.value("idempotencyKey", "")));

        _logger->info("[PaymentService] Refund succeeded. receiptId={} amount={} cents", 
                      refundReceipt.receiptId, refundReceipt.amountCents);

        return refundReceipt;
    }

private:
    //----------------------------------------------------------------------
    // Internal helpers
    //----------------------------------------------------------------------
    static std::string makeCacheKey(const std::string& idemKey)
    {
        return "PAYMENT:IDEM:" + idemKey;
    }

private:
    //----------------------------------------------------------------------
    // Data Members
    //----------------------------------------------------------------------
    std::shared_ptr<IPaymentGateway>    _gateway;
    std::shared_ptr<IPaymentRepository> _repository;
    std::shared_ptr<ICache>             _cache;
    std::shared_ptr<ILogger>            _logger;
    Config                              _cfg;

    // Thread-safety primitives (if required by gateway/repository)
    mutable std::mutex                  _mutex;
};

} // namespace mbs::payments