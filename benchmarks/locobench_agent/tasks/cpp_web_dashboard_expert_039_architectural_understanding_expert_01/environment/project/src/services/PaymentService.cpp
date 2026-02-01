#include "PaymentService.hpp"

#include <chrono>
#include <future>
#include <stdexcept>

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

#include "../config/Configuration.hpp"
#include "../core/EventBus.hpp"
#include "../middleware/AuthContext.hpp"
#include "../repositories/PaymentRepository.hpp"
#include "../utils/Retry.hpp"
#include "../utils/Uuid.hpp"

namespace mosaic::services
{

using json = nlohmann::json;

namespace
{
    constexpr std::chrono::milliseconds kDefaultGatewayTimeout{8'000};
}

// ────────────────────────────────────────────────────────────────────────────────
// ctor / dtor
// ────────────────────────────────────────────────────────────────────────────────
PaymentService::PaymentService(std::shared_ptr<gateways::PaymentGateway> gateway,
                               std::shared_ptr<repositories::PaymentRepository> repo,
                               std::shared_ptr<core::EventBus> eventBus,
                               std::shared_ptr<cache::CacheLayer> cache)
    : _gateway(std::move(gateway))
    , _repo(std::move(repo))
    , _eventBus(std::move(eventBus))
    , _cache(std::move(cache))
{
    if (!_gateway || !_repo || !_eventBus || !_cache)
    {
        throw std::invalid_argument("PaymentService: nullptr dependency injected");
    }
}

// ────────────────────────────────────────────────────────────────────────────────
// Public API
// ────────────────────────────────────────────────────────────────────────────────
PaymentResult PaymentService::processPayment(const PaymentRequest& request,
                                             const middleware::AuthContext& ctx)
{
    SPDLOG_INFO("PaymentService::processPayment | user_id={}, amount_cents={}, currency={}",
                ctx.userId(), request.amountCents, request.currency);

    if (!ctx.isAuthenticated())
    {
        SPDLOG_WARN("processPayment attempted without authentication");
        throw security::AuthenticationError("User not authenticated");
    }

    // Basic validation
    validateRequest(request);

    // Check cache to prevent double-spend (idempotency)
    if (_cache->contains(request.idempotencyKey))
    {
        const auto cached = _cache->get<PaymentResult>(request.idempotencyKey);
        SPDLOG_INFO("Idempotent payment request retrieved from cache: {}",
                    request.idempotencyKey);
        return cached;
    }

    // Persist "PENDING" record in DB (helps us recover unfinished payments)
    auto record = repositories::PaymentRecord::fromRequest(ctx.userId(), request);
    record.status = repositories::PaymentStatus::PENDING;
    _repo->insert(record);

    // Execute payment with gateway using retry strategy
    auto gatewayResponse = utils::retry<gateways::GatewayResponse>(
        [this, &request] {
            return _gateway->charge(request);
        },
        /*retries*/ 3,
        /*delay*/ std::chrono::milliseconds{500});

    // Map gateway response to internal record / domain object
    record.externalPaymentId = gatewayResponse.chargeId;
    record.status            = gatewayResponse.success
                                 ? repositories::PaymentStatus::SUCCEEDED
                                 : repositories::PaymentStatus::FAILED;
    record.failureReason     = gatewayResponse.errorMessage;

    _repo->update(record);

    PaymentResult result{
        .paymentId          = record.id,
        .externalPaymentId  = record.externalPaymentId,
        .status             = record.status,
        .amountCents        = record.amountCents,
        .currency           = record.currency,
        .createdAt          = record.createdAt,
        .failureReason      = record.failureReason};

    // Cache the result for idempotency window (10 min)
    _cache->put(request.idempotencyKey, result, std::chrono::minutes{10});

    // Broadcast event
    _eventBus->publish<events::PaymentEvent>(result);

    SPDLOG_INFO("Payment completed | id={}, status={}, user_id={}",
                result.paymentId,
                toString(result.status),
                ctx.userId());

    if (!gatewayResponse.success)
    {
        throw PaymentProcessingError(fmt::format("Payment failed: {}", record.failureReason));
    }

    return result;
}

void PaymentService::handleWebhook(std::string_view signature,
                                   std::string_view payload)
{
    SPDLOG_TRACE("PaymentService::handleWebhook | payload-size={}", payload.size());

    if (!_gateway->verifyWebhookSignature(signature, payload))
    {
        SPDLOG_WARN("Webhook verification failed");
        throw security::SignatureVerificationError("Invalid webhook signature");
    }

    const auto parsed = json::parse(payload);
    const auto eventType = parsed.at("type").get<std::string>();

    if (eventType == "charge.refunded")
    {
        const auto externalId = parsed.at("data").at("object").at("id").get<std::string>();
        auto record           = _repo->findByExternalId(externalId);

        if (!record)
        {
            SPDLOG_ERROR("handleWebhook | payment record not found for external_id={}", externalId);
            return;
        }

        record->status = repositories::PaymentStatus::REFUNDED;
        _repo->update(*record);

        // Broadcast event async to avoid blocking webhook thread
        std::async(std::launch::async, [bus = _eventBus, result = PaymentResult::fromRecord(*record)] {
            bus->publish<events::PaymentEvent>(result);
        });

        SPDLOG_INFO("Payment refunded | payment_id={}", record->id);
    }
}

PaymentResult PaymentService::refundPayment(std::string_view paymentId,
                                            const middleware::AuthContext& ctx)
{
    SPDLOG_INFO("PaymentService::refundPayment | payment_id={}, user={}", paymentId, ctx.userId());

    if (!ctx.hasRole("admin") && !ctx.hasRole("finance"))
    {
        throw security::AuthorizationError("User not authorized to perform refunds");
    }

    auto record = _repo->findById(paymentId);
    if (!record)
    {
        throw PaymentNotFoundError(fmt::format("Payment not found: {}", paymentId));
    }

    // Avoid double refund
    if (record->status == repositories::PaymentStatus::REFUNDED)
    {
        return PaymentResult::fromRecord(*record);
    }

    auto response = _gateway->refund(record->externalPaymentId);
    if (!response.success)
    {
        throw PaymentProcessingError(fmt::format("Refund failed: {}", response.errorMessage));
    }

    record->status = repositories::PaymentStatus::REFUNDED;
    _repo->update(*record);

    PaymentResult result = PaymentResult::fromRecord(*record);
    _eventBus->publish<events::PaymentEvent>(result);

    return result;
}

PaymentStatus PaymentService::getPaymentStatus(std::string_view paymentId) const
{
    if (auto cached = _cache->maybeGet<PaymentStatus>(paymentId))
    {
        return *cached;
    }

    auto record = _repo->findById(paymentId);
    if (!record)
    {
        throw PaymentNotFoundError(fmt::format("Payment not found: {}", paymentId));
    }

    _cache->put(paymentId, record->status, std::chrono::seconds{30});
    return record->status;
}

// ────────────────────────────────────────────────────────────────────────────────
// Private helpers
// ────────────────────────────────────────────────────────────────────────────────
void PaymentService::validateRequest(const PaymentRequest& req) const
{
    if (req.amountCents <= 0)
    {
        throw std::invalid_argument("Invalid amount");
    }

    static const std::unordered_set<std::string_view> kSupportedCurrencies{
        "USD", "EUR", "JPY"};
    if (kSupportedCurrencies.find(req.currency) == kSupportedCurrencies.end())
    {
        throw std::invalid_argument("Unsupported currency");
    }

    if (req.sourceToken.empty())
    {
        throw std::invalid_argument("Missing source token");
    }

    if (req.idempotencyKey.empty())
    {
        throw std::invalid_argument("Missing idempotency key");
    }
}

} // namespace mosaic::services