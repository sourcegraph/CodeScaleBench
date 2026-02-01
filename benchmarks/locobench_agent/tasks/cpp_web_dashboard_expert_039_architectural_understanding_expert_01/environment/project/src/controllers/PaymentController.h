```cpp
#pragma once
/**
 * MosaicBoard Studio – Payment Controller
 *
 * Copyright
 * ----------
 * Copyright (c) MosaicBoard Studio
 *
 * Licensed under the MIT License. See LICENSE file in the project root for full
 * license information.
 *
 * Description
 * -----------
 * Handles all HTTP endpoints that deal with payment– and billing–related
 * workflows such as:
 *
 *   • Creating / managing checkout sessions
 *   • Processing asynchronous payment-provider web-hooks
 *   • Validating discount / coupon codes
 *   • Returning billing-history and subscription metadata
 *
 * The controller translates raw HTTP requests coming from the REST gateway
 * into strongly-typed domain operations executed by `PaymentService`.
 *
 * Architecture notes
 * ------------------
 * – Follows MVC (this is a Controller)
 * – All heavy-lifting is delegated to the Service layer
 * – Runs behind an Authentication / IAM middleware but performs secondary
 *   verifications (e.g. signature / HMAC checks for provider web-hooks)
 */

#include <memory>
#include <string>
#include <stdexcept>
#include <utility>

#include <nlohmann/json.hpp>

// -----------------------------------------------------------------------------
// Forward declarations (keep compile-time dependencies minimal)
// -----------------------------------------------------------------------------
namespace Mosaic::Http
{
    struct Request;
    class  Response;
    class  Router;
} // namespace Mosaic::Http

namespace Mosaic::Security
{
    class IAManager;
} // namespace Mosaic::Security

namespace Mosaic::Services
{
    struct PaymentSession;
    class  PaymentService;
} // namespace Mosaic::Services

namespace Mosaic::Utils
{
    class Logger;
} // namespace Mosaic::Utils

// -----------------------------------------------------------------------------
// Controller
// -----------------------------------------------------------------------------
namespace Mosaic::Controllers
{
    /**
     * PaymentController
     *
     * Provides REST endpoints under `/api/payments/*`.
     *
     *   POST   /api/payments/checkout        – Create a new checkout session
     *   POST   /api/payments/webhook         – Provider web-hook receiver
     *   GET    /api/payments/coupon/:code    – Validate / price a coupon
     *
     * Thread safety:
     *   The controller itself is stateless and therefore thread-safe as long as
     *   its collaborators are either stateless or internally synchronized.
     */
    class PaymentController final
    {
        using json = nlohmann::json;

    public:
        /**
         * Constructs a new PaymentController instance.
         *
         * @param paymentService  Strong reference to the service layer
         * @param iam             Reference to currently installed IAM / RBAC
         *                        manager (may be nullptr if IAM is disabled)
         * @param logger          Optional logger instance
         */
        PaymentController(std::shared_ptr<Mosaic::Services::PaymentService> paymentService,
                          std::shared_ptr<Mosaic::Security::IAManager>      iam,
                          std::shared_ptr<Mosaic::Utils::Logger>            logger);

        /**
         * Binds the controller’s handlers to the application’s router.
         *
         * Typically called during application bootstrap. Each call is idempotent.
         *
         * @param router Router implementation provided by web framework
         */
        void bindRoutes(Mosaic::Http::Router& router);

    private:
        // ---------------------------------------------------------------------
        // REST handler prototypes
        // ---------------------------------------------------------------------
        [[nodiscard]] Mosaic::Http::Response handleCreateCheckout(const Mosaic::Http::Request& req);
        [[nodiscard]] Mosaic::Http::Response handleWebhook         (const Mosaic::Http::Request& req);
        [[nodiscard]] Mosaic::Http::Response handleValidateCoupon  (const Mosaic::Http::Request& req);

        // ---------------------------------------------------------------------
        // Helper utilities
        // ---------------------------------------------------------------------
        [[nodiscard]] json  parseBody(const Mosaic::Http::Request& req) const;
        [[nodiscard]] bool  isAuthenticated(const Mosaic::Http::Request& req) const;
        [[nodiscard]] Mosaic::Http::Response
                            makeErrorResponse(int status, std::string_view message) const;

        // ---------------------------------------------------------------------
        // Data members
        // ---------------------------------------------------------------------
        std::shared_ptr<Mosaic::Services::PaymentService> m_paymentService;
        std::shared_ptr<Mosaic::Security::IAManager>      m_iam;
        std::shared_ptr<Mosaic::Utils::Logger>            m_logger;
    };

    //==========================================================================
    //  Implementation  (inline to keep single translation unit for headers-only
    //==========================================================================
    inline PaymentController::PaymentController(
        std::shared_ptr<Mosaic::Services::PaymentService> paymentService,
        std::shared_ptr<Mosaic::Security::IAManager>      iam,
        std::shared_ptr<Mosaic::Utils::Logger>            logger)
        : m_paymentService(std::move(paymentService))
        , m_iam           (std::move(iam))
        , m_logger        (std::move(logger))
    {
        if (!m_paymentService)
        {
            throw std::invalid_argument("PaymentController: 'paymentService' must not be null");
        }
    }

    // -------------------------------------------------------------------------
    inline void PaymentController::bindRoutes(Mosaic::Http::Router& router)
    {
        // NOTE: Exact binding APIs depend on the underlying HTTP framework.
        // The following lambda signatures assume a *request -> response* style.

        router.post("/api/payments/checkout",
                    [this](const Mosaic::Http::Request& req)
                    { return handleCreateCheckout(req); });

        router.post("/api/payments/webhook",
                    [this](const Mosaic::Http::Request& req)
                    { return handleWebhook(req); });

        router.get ("/api/payments/coupon/:code",
                    [this](const Mosaic::Http::Request& req)
                    { return handleValidateCoupon(req); });
    }

    // -------------------------------------------------------------------------
    //  Endpoint: Create Checkout Session
    // -------------------------------------------------------------------------
    inline Mosaic::Http::Response
    PaymentController::handleCreateCheckout(const Mosaic::Http::Request& req)
    {
        using namespace Mosaic;

        try
        {
            if (!isAuthenticated(req))
            {
                return makeErrorResponse(401, "Unauthorized");
            }

            const json body = parseBody(req);

            const std::string priceId     = body.at("priceId").get<std::string>();
            const std::string successUrl  = body.at("successUrl").get<std::string>();
            const std::string cancelUrl   = body.at("cancelUrl").get<std::string>();
            const std::string couponCode  = body.value("coupon", "");

            // Domain logic – delegated to service layer
            const auto session = m_paymentService->createCheckoutSession(
                priceId, successUrl, cancelUrl, couponCode, /* userId = */ req.userId());

            json responseJson {
                { "sessionId",  session.sessionId          },
                { "publicKey",  session.publicKey          },
                { "expiresAt",  session.expiresAt          },
                { "checkoutUrl", session.checkoutUrl       }
            };

            return Http::Response::json(201, std::move(responseJson));
        }
        catch (const std::exception& ex)
        {
            if (m_logger) { m_logger->error(ex.what()); }
            return makeErrorResponse(400, ex.what());
        }
    }

    // -------------------------------------------------------------------------
    //  Endpoint: Payment Provider Web-hook
    // -------------------------------------------------------------------------
    inline Mosaic::Http::Response
    PaymentController::handleWebhook(const Mosaic::Http::Request& req)
    {
        using namespace Mosaic;

        try
        {
            const std::string signatureHeader =
                req.header("X-Payment-Signature").value_or("");

            const auto rawPayload = req.raw_body(); // provider depends on raw, untouched payload

            bool verified = m_paymentService->verifyWebhookSignature(
                                rawPayload, signatureHeader);

            if (!verified)
            {
                return makeErrorResponse(400, "Invalid signature");
            }

            m_paymentService->processWebhookPayload(rawPayload);

            return Http::Response::json(200, { { "status", "ok" } });
        }
        catch (const std::exception& ex)
        {
            if (m_logger) { m_logger->error(ex.what()); }
            return makeErrorResponse(500, ex.what());
        }
    }

    // -------------------------------------------------------------------------
    //  Endpoint: Validate Coupon / Discount Code
    // -------------------------------------------------------------------------
    inline Mosaic::Http::Response
    PaymentController::handleValidateCoupon(const Mosaic::Http::Request& req)
    {
        using namespace Mosaic;

        try
        {
            const std::string code = req.param("code").value_or("");

            if (code.empty())
            {
                return makeErrorResponse(400, "Coupon code must not be empty");
            }

            const auto coupon = m_paymentService->validateCoupon(code);

            json out {
                { "code",         coupon.code        },
                { "percentage",   coupon.percentage  },
                { "valid",        coupon.valid       },
                { "expiresAt",    coupon.expiresAt   }
            };

            return Http::Response::json(200, std::move(out));
        }
        catch (const std::exception& ex)
        {
            if (m_logger) { m_logger->warn(ex.what()); }
            return makeErrorResponse(404, ex.what());
        }
    }

    // -------------------------------------------------------------------------
    //  Helpers
    // -------------------------------------------------------------------------
    inline PaymentController::json
    PaymentController::parseBody(const Mosaic::Http::Request& req) const
    {
        try
        {
            return json::parse(req.body());
        }
        catch (const json::parse_error& ex)
        {
            throw std::invalid_argument(
                std::string("Malformed JSON payload: ") + ex.what());
        }
    }

    inline bool
    PaymentController::isAuthenticated(const Mosaic::Http::Request& req) const
    {
        // IAM is optional (e.g., when running in „offline / kiosk“ mode).
        if (!m_iam) { return true; }

        return m_iam->isAuthenticated(req);
    }

    inline Mosaic::Http::Response
    PaymentController::makeErrorResponse(int status, std::string_view message) const
    {
        return Mosaic::Http::Response::json(
            status, { { "error", message } });
    }

} // namespace Mosaic::Controllers
```