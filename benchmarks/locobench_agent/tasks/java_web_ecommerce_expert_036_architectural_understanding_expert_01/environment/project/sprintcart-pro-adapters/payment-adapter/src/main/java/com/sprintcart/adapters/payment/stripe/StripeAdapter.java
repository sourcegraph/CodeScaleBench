```java
package com.sprintcart.adapters.payment.stripe;

import com.stripe.Stripe;
import com.stripe.exception.SignatureVerificationException;
import com.stripe.exception.StripeException;
import com.stripe.model.Charge;
import com.stripe.model.Customer;
import com.stripe.model.Event;
import com.stripe.model.PaymentIntent;
import com.stripe.model.Refund;
import com.stripe.net.RequestOptions;
import com.stripe.net.Webhook;
import com.stripe.param.CustomerCreateParams;
import com.stripe.param.PaymentIntentCaptureParams;
import com.stripe.param.PaymentIntentCreateParams;
import com.stripe.param.RefundCreateParams;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.lang.Nullable;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.Clock;
import java.util.HashMap;
import java.util.Map;

/**
 * StripeAdapter implements the {@link PaymentGatewayPort} outbound port and encapsulates
 * Stripe–specific API calls such that the domain layer does not depend on any SDK.
 *
 * The adapter is responsible for:
 *  – Authorizing, capturing and refunding payments
 *  – Translating domain primitives to Stripe parameters and back
 *  – Verifying and dispatching webhook events
 *  – Propagating errors as domain‐specific exceptions
 *
 * NOTE: All amounts in Stripe are expressed in the smallest currency unit
 *       (e.g., cents for USD, no decimals for JPY). Conversion helpers are
 *       provided to ensure correct rounding.
 */
@Slf4j
@Component
@RequiredArgsConstructor
@SuppressWarnings({"java:S1192"}) // Ignore "string literal duplicates" for log messages
public class StripeAdapter implements PaymentGatewayPort, InitializingBean {

    /**
     * Secret key used for server-side Stripe API calls.
     * Injected via Spring’s property resolution to avoid hard coding secrets.
     */
    @Value("${integrations.stripe.secret-key}")
    private final String secretKey;

    /**
     * Webhook secret provided by Stripe Dashboard to validate event signatures.
     */
    @Value("${integrations.stripe.webhook-secret}")
    private final String webhookSecret;

    /**
     * Logical clock used throughout the platform. Centralising Clock usage
     * guarantees deterministic tests and makes time-based decisions traceable.
     */
    private final Clock clock;

    // ---------------------------------------------------------------------
    // Initialisation
    // ---------------------------------------------------------------------

    /**
     * Configure Stripe SDK once the Spring context has been initialised.
     */
    @Override
    public void afterPropertiesSet() {
        Stripe.apiKey = secretKey;
        Stripe.setAppInfo("SprintCart Pro", "1.0.0", "https://sprintcart.com");
    }

    // ---------------------------------------------------------------------
    // Public API — PaymentGatewayPort implementation
    // ---------------------------------------------------------------------

    @Override
    public PaymentIntentResult authorize(PaymentIntentRequest request) {
        try {
            PaymentIntentCreateParams params = buildAuthorizeParams(request);
            // Idempotency key derived from orderId + attempt allows safe retries
            RequestOptions options = RequestOptions.builder()
                                                   .setIdempotencyKey(request.orderId().value()
                                                                         + ":" + request.attempt())
                                                   .build();
            PaymentIntent intent = PaymentIntent.create(params, options);

            return mapToResult(intent);
        } catch (StripeException ex) {
            log.error("Failed to authorise payment for order {} – {}",
                      request.orderId().value(), ex.getMessage(), ex);
            throw new PaymentGatewayException("Unable to authorise payment with Stripe", ex);
        }
    }

    @Override
    public PaymentIntentResult capture(String paymentIntentId,
                                       BigDecimal amount,
                                       @Nullable String idempotencyKey) {
        try {
            PaymentIntent intent = PaymentIntent.retrieve(paymentIntentId);
            PaymentIntentCaptureParams capture = PaymentIntentCaptureParams.builder()
                                                                           .setAmount(amountToMinorUnit(
                                                                                   amount,
                                                                                   intent.getCurrency()))
                                                                           .build();

            RequestOptions opts = RequestOptions.builder()
                                                .setIdempotencyKey(idempotencyKey)
                                                .build();

            PaymentIntent captured = intent.capture(capture, opts);
            return mapToResult(captured);
        } catch (StripeException ex) {
            log.error("Failed to capture paymentIntent {} – {}",
                      paymentIntentId, ex.getMessage(), ex);
            throw new PaymentGatewayException("Unable to capture payment with Stripe", ex);
        }
    }

    @Override
    public RefundResult refund(String chargeId,
                               BigDecimal amount,
                               RefundReason reason,
                               @Nullable String idempotencyKey) {
        try {
            RefundCreateParams params = RefundCreateParams.builder()
                                                          .setCharge(chargeId)
                                                          .setAmount(amountToMinorUnit(amount, null))
                                                          .setReason(RefundCreateParams.Reason.valueOf(reason.name()))
                                                          .build();

            RequestOptions opts = RequestOptions.builder()
                                                .setIdempotencyKey(idempotencyKey)
                                                .build();

            Refund refund = Refund.create(params, opts);
            return mapToRefund(refund);
        } catch (StripeException ex) {
            log.error("Failed to refund charge {} – {}", chargeId, ex.getMessage(), ex);
            throw new PaymentGatewayException("Unable to refund payment with Stripe", ex);
        }
    }

    @Override
    public void handleWebhook(String rawPayload, String signatureHeader) {
        final Event event;
        try {
            event = Webhook.constructEvent(rawPayload, signatureHeader, webhookSecret);
        } catch (SignatureVerificationException ex) {
            log.warn("Rejected Stripe webhook – invalid signature: {}", ex.getMessage());
            throw new PaymentGatewayException("Invalid Stripe webhook signature", ex);
        }

        // Dispatch supported events
        switch (event.getType()) {
            case "payment_intent.succeeded" -> onPaymentSucceeded(toObject(event, PaymentIntent.class));
            case "payment_intent.payment_failed" -> onPaymentFailed(toObject(event, PaymentIntent.class));
            case "charge.refunded" -> onChargeRefunded(toObject(event, Charge.class));
            default -> log.debug("Ignored unsupported Stripe event type: {}", event.getType());
        }
    }

    // ---------------------------------------------------------------------
    // Stripe → Domain mappers & helpers
    // ---------------------------------------------------------------------

    private PaymentIntentCreateParams buildAuthorizeParams(PaymentIntentRequest request) throws StripeException {
        PaymentIntentCreateParams.Builder builder = PaymentIntentCreateParams.builder()
                                                                             .setCurrency(request.currency())
                                                                             .setAmount(amountToMinorUnit(
                                                                                     request.amount(),
                                                                                     request.currency()))
                                                                             .setCaptureMethod(PaymentIntentCreateParams.CaptureMethod.MANUAL)
                                                                             .setDescription("SprintCart Pro order "
                                                                                             + request.orderId().value())
                                                                             .putMetadata("orderId", request.orderId().value());

        // -----------------------------------------------------------------
        // Re-use existing Stripe customer or create a lightweight one
        // -----------------------------------------------------------------
        String stripeCustomerId = request.customerStripeId();
        if (stripeCustomerId == null) {
            stripeCustomerId = createOrUpdateCustomer(request);
        }
        builder.setCustomer(stripeCustomerId);

        if (request.paymentMethodId() != null) {
            builder.setPaymentMethod(request.paymentMethodId())
                   .setConfirm(true)                // immediate confirmation
                   .setOffSession(true);            // Card not present
        }

        return builder.build();
    }

    /**
     * Convert major currency unit (e.g., dollars) to Stripe minor unit (cents).
     * Handles zero-decimal currencies such as JPY, KRW.
     */
    private long amountToMinorUnit(BigDecimal amount, @Nullable String currency) {
        int scale = switch (currency == null ? "" : currency.toLowerCase()) {
            case "jpy", "krw" -> 0;
            default -> 2;
        };
        return amount.movePointRight(scale).longValueExact();
    }

    private String createOrUpdateCustomer(PaymentIntentRequest request) throws StripeException {
        Map<String, String> meta = new HashMap<>();
        meta.put("customerId", request.customerId().value());

        CustomerCreateParams params = CustomerCreateParams.builder()
                                                          .setEmail(request.customerEmail())
                                                          .setName(request.customerName())
                                                          .putAllMetadata(meta)
                                                          .build();
        Customer customer = Customer.create(params);
        return customer.getId();
    }

    private void onPaymentSucceeded(PaymentIntent intent) {
        log.info("Stripe paymentIntent {} succeeded – order={}", intent.getId(),
                 intent.getMetadata().get("orderId"));
        // TODO: Publish domain event to message bus
    }

    private void onPaymentFailed(PaymentIntent intent) {
        log.warn("Stripe paymentIntent {} failed – order={} – reason={}",
                 intent.getId(), intent.getMetadata().get("orderId"), intent.getLastPaymentError());
        // TODO: Publish domain event to message bus
    }

    private void onChargeRefunded(Charge charge) {
        log.info("Stripe charge {} refunded – order={}", charge.getId(),
                 charge.getMetadata().get("orderId"));
        // TODO: Publish domain event to message bus
    }

    /**
     * Safely casts the generic {@link Event} data object to the desired type.
     */
    @SuppressWarnings("unchecked")
    private <T> T toObject(Event event, Class<T> clazz) {
        return (T) event.getDataObjectDeserializer()
                        .getObject()
                        .orElseThrow(() -> new IllegalStateException("Unable to deserialize Stripe event"));
    }

    private PaymentIntentResult mapToResult(PaymentIntent intent) {
        return new PaymentIntentResult(
                intent.getId(),
                intent.getClientSecret(),
                PaymentStatus.fromStripe(intent.getStatus()),
                clock.instant());
    }

    private RefundResult mapToRefund(Refund refund) {
        return new RefundResult(
                refund.getId(),
                refund.getCharge(),
                RefundStatus.fromStripe(refund.getStatus()),
                clock.instant());
    }

    // ---------------------------------------------------------------------
    // Domain Port & DTOs — kept minimal to make this file self-contained.
    // In the actual codebase these belong in dedicated modules.
    // ---------------------------------------------------------------------

    public interface PaymentGatewayPort {

        PaymentIntentResult authorize(PaymentIntentRequest request);

        PaymentIntentResult capture(String paymentIntentId,
                                    BigDecimal amount,
                                    @Nullable String idempotencyKey);

        RefundResult refund(String chargeId,
                            BigDecimal amount,
                            RefundReason reason,
                            @Nullable String idempotencyKey);

        /**
         * Verify and dispatch a Stripe webhook.
         *
         * @param rawPayload      the request body
         * @param signatureHeader value of the Stripe-Signature header
         */
        void handleWebhook(String rawPayload, String signatureHeader);
    }

    // -----------------------------------------------------------------
    // Value Objects – implemented as Java records for brevity.
    // -----------------------------------------------------------------

    public record OrderId(String value) {}

    public record CustomerId(String value) {}

    public enum PaymentStatus {
        REQUIRES_PAYMENT_METHOD,
        REQUIRES_CONFIRMATION,
        REQUIRES_ACTION,
        PROCESSING,
        SUCCEEDED,
        CANCELED;

        static PaymentStatus fromStripe(String stripeStatus) {
            return switch (stripeStatus) {
                case "requires_payment_method" -> REQUIRES_PAYMENT_METHOD;
                case "requires_confirmation" -> REQUIRES_CONFIRMATION;
                case "requires_action" -> REQUIRES_ACTION;
                case "processing" -> PROCESSING;
                case "succeeded" -> SUCCEEDED;
                default -> CANCELED;
            };
        }
    }

    public enum RefundStatus {
        PENDING, SUCCEEDED, FAILED, CANCELED;

        static RefundStatus fromStripe(String stripeStatus) {
            return switch (stripeStatus) {
                case "pending" -> PENDING;
                case "succeeded" -> SUCCEEDED;
                case "failed" -> FAILED;
                default -> CANCELED;
            };
        }
    }

    public enum RefundReason { DUPLICATE, FRAUD, REQUESTED_BY_CUSTOMER }

    public record PaymentIntentRequest(
            OrderId orderId,
            CustomerId customerId,
            String customerName,
            String customerEmail,
            BigDecimal amount,
            String currency,
            int attempt,
            @Nullable String paymentMethodId,
            @Nullable String customerStripeId) { }

    public record PaymentIntentResult(
            String paymentIntentId,
            String clientSecret,
            PaymentStatus status,
            java.time.Instant time) { }

    public record RefundResult(
            String refundId,
            String chargeId,
            RefundStatus status,
            java.time.Instant time) { }

    // ---------------------------------------------------------------------
    // Exceptions
    // ---------------------------------------------------------------------

    public static class PaymentGatewayException extends RuntimeException {
        public PaymentGatewayException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
```