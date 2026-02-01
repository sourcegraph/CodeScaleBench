#include "controllers/PaymentController.hpp"

#include "middleware/JWTAuthMiddleware.hpp"
#include "services/PaymentService.hpp"

#include <nlohmann/json.hpp>
#include <spdlog/spdlog.h>

using json = nlohmann::json;

namespace Mosaic::Controllers
{

// ────────────────────────────────────────────────────────────────────────────────
// Construction & Wiring
// ────────────────────────────────────────────────────────────────────────────────
PaymentController::PaymentController(Http::IRouter&                                   router,
                                     std::shared_ptr<Services::PaymentService>      paymentService,
                                     std::shared_ptr<Middleware::JWTAuthMiddleware> authMiddleware)
    : _router(router)
    , _paymentService(std::move(paymentService))
    , _authMiddleware(std::move(authMiddleware))
{
    registerRoutes();
}

// ────────────────────────────────────────────────────────────────────────────────
// Route Registration
// ────────────────────────────────────────────────────────────────────────────────
void PaymentController::registerRoutes()
{
    //
    // Clients creating payment intents (JWT protected)
    //
    _router.post(
        "/api/v1/payments/intent",
        _authMiddleware->wrap([this](const Http::Request& req, Http::Response& res) {
            this->createPaymentIntent(req, res);
        }));

    //
    // Authenticated payment history endpoint
    //
    _router.get(
        "/api/v1/payments/history",
        _authMiddleware->wrap([this](const Http::Request& req, Http::Response& res) {
            this->getPaymentHistory(req, res);
        }));

    //
    // Stripe (or other PSP) webhook (MUST NOT be JWT protected!)
    //
    _router.post("/api/v1/payments/webhook",
                 [this](const Http::Request& req, Http::Response& res) {
                     this->handleWebhook(req, res);
                 });
}

// ────────────────────────────────────────────────────────────────────────────────
// Controller Methods
// ────────────────────────────────────────────────────────────────────────────────
void PaymentController::createPaymentIntent(const Http::Request& req, Http::Response& res)
{
    try
    {
        // Parse JSON body
        const auto bodyStr = req.body();
        auto       body    = json::parse(bodyStr);

        const auto amount   = body.at("amount").get<int64_t>();          // required
        const auto currency = body.value("currency", "usd");             // default USD
        const auto metadata = body.value("metadata", json::object());    // optional

        const auto userId = req.context().userId; // Populated by JWTAuthMiddleware

        Services::PaymentIntentDescriptor descriptor;
        descriptor.amount     = amount;
        descriptor.currency   = currency;
        descriptor.metadata   = metadata;
        descriptor.customerId = userId;

        std::string clientSecret = _paymentService->createPaymentIntent(descriptor);

        res.status(Http::Status::Created);
        res.json({{"clientSecret", clientSecret}});
    }
    catch (const json::exception& ex)
    {
        spdlog::warn("PaymentController::createPaymentIntent - Invalid JSON: {}", ex.what());
        res.status(Http::Status::BadRequest);
        res.json({{"error", "Invalid request body"}});
    }
    catch (const Services::PaymentException& ex)
    {
        spdlog::error("PaymentController::createPaymentIntent - Service error: {}", ex.what());
        res.status(Http::Status::InternalServerError);
        res.json({{"error", ex.what()}});
    }
    catch (const std::exception& ex)
    {
        spdlog::critical("PaymentController::createPaymentIntent - Unexpected error: {}", ex.what());
        res.status(Http::Status::InternalServerError);
        res.json({{"error", "Internal server error"}});
    }
}

// ────────────────────────────────────────────────────────────────────────────────
void PaymentController::getPaymentHistory(const Http::Request& req, Http::Response& res)
{
    try
    {
        const auto userId  = req.context().userId;
        auto       history = _paymentService->fetchPaymentHistory(userId);

        json historyJson = json::array();
        for (const auto& record : history)
        {
            historyJson.push_back({{"id", record.id},
                                   {"amount", record.amount},
                                   {"currency", record.currency},
                                   {"status", record.status},
                                   {"createdAt", record.createdAt}});
        }

        res.status(Http::Status::Ok);
        res.json({{"history", std::move(historyJson)}});
    }
    catch (const Services::PaymentException& ex)
    {
        spdlog::error("PaymentController::getPaymentHistory - Service error: {}", ex.what());
        res.status(Http::Status::InternalServerError);
        res.json({{"error", ex.what()}});
    }
    catch (const std::exception& ex)
    {
        spdlog::critical("PaymentController::getPaymentHistory - Unexpected error: {}", ex.what());
        res.status(Http::Status::InternalServerError);
        res.json({{"error", "Internal server error"}});
    }
}

// ────────────────────────────────────────────────────────────────────────────────
void PaymentController::handleWebhook(const Http::Request& req, Http::Response& res)
{
    try
    {
        const auto signatureHeader = req.header("Stripe-Signature");
        if (signatureHeader.empty())
        {
            res.status(Http::Status::BadRequest);
            res.send("Missing Stripe-Signature header");
            return;
        }

        const std::string& rawPayload = req.body();

        _paymentService->processWebhook(rawPayload, signatureHeader);

        res.status(Http::Status::Ok);
        res.send("Webhook processed");
    }
    catch (const Services::InvalidSignatureException& ex)
    {
        spdlog::warn("PaymentController::handleWebhook - Invalid signature: {}", ex.what());
        res.status(Http::Status::BadRequest);
        res.send("Invalid signature");
    }
    catch (const Services::PaymentException& ex)
    {
        spdlog::error("PaymentController::handleWebhook - Service error: {}", ex.what());
        res.status(Http::Status::InternalServerError);
        res.send("Webhook handling failed");
    }
    catch (const std::exception& ex)
    {
        spdlog::critical("PaymentController::handleWebhook - Unexpected error: {}", ex.what());
        res.status(Http::Status::InternalServerError);
        res.send("Internal server error");
    }
}

} // namespace Mosaic::Controllers