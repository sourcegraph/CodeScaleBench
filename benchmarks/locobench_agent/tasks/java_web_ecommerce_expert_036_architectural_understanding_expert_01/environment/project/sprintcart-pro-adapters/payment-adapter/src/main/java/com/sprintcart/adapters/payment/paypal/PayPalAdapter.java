```java
package com.sprintcart.adapters.payment.paypal;

import com.sprintcart.domain.common.Money;
import com.sprintcart.domain.payment.gateway.PaymentGatewayPort;
import com.sprintcart.domain.payment.model.PaymentRequest;
import com.sprintcart.domain.payment.model.PaymentResponse;
import com.sprintcart.domain.payment.model.PaymentStatus;
import com.sprintcart.domain.payment.model.RefundRequest;
import com.sprintcart.infrastructure.metrics.MetricsRegistry;
import com.sprintcart.infrastructure.tracing.Traceable;
import com.sprintcart.infrastructure.tracing.Tracing;
import com.paypal.core.PayPalEnvironment;
import com.paypal.core.PayPalHttpClient;
import com.paypal.http.HttpResponse;
import com.paypal.http.exceptions.HttpException;
import com.paypal.orders.*;
import org.apache.commons.lang3.StringUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Collections;
import java.util.Optional;
import java.util.UUID;

/**
 * PayPalAdapter is an outbound adapter that bridges SprintCart Pro's payment
 * port (PaymentGatewayPort) with PayPal's REST v2 API.
 *
 * Notes about architecture:
 *  - No PayPal SDK types ever leak outside the adapter boundary.
 *  - All PayPal-specific exceptions are mapped to domain-level failure codes.
 *  - The adapter is completely stateless and hence safe for Spring singleton scope.
 *
 * Dependencies:
 *  - <dependency>
 *      <groupId>com.paypal.sdk</groupId>
 *      <artifactId>paypalhttp</artifactId>
 *      <version>1.0.2</version>
 *    </dependency>
 *  - (omitted for brevity – see build.gradle / pom.xml in project root)
 */
@Traceable
public class PayPalAdapter implements PaymentGatewayPort {

    private static final Logger log = LoggerFactory.getLogger(PayPalAdapter.class);

    private final PayPalHttpClient client;
    private final MetricsRegistry metrics;

    /**
     * Creates a new PayPal adapter using client credentials pulled from the secure
     * configuration store (Vault, AWS Secrets Manager, etc.).
     *
     * @param clientId     PayPal client id
     * @param clientSecret PayPal client secret
     * @param sandbox      whether to use sandbox endpoints
     * @param metricsRegistry central metrics registry for instrumentation
     */
    public PayPalAdapter(final String clientId,
                         final String clientSecret,
                         final boolean sandbox,
                         final MetricsRegistry metricsRegistry) {

        PayPalEnvironment environment = sandbox
                ? new PayPalEnvironment.Sandbox(clientId, clientSecret)
                : new PayPalEnvironment.Live(clientId, clientSecret);

        this.client = new PayPalHttpClient(environment);
        this.metrics = metricsRegistry;
    }

    // -------------------------------------------------------------------------
    // Payment Gateway Port Implementation
    // -------------------------------------------------------------------------

    @Override
    public PaymentResponse authorize(final PaymentRequest request) {
        return Tracing.trace("paypal.authorize", span -> {
            OrderRequest orderRequest = buildOrderRequest(request);
            OrdersCreateRequest createRequest = new OrdersCreateRequest()
                    .prefer("return=representation")
                    .requestBody(orderRequest);

            try {
                HttpResponse<Order> response = client.execute(createRequest);

                String orderId = Optional.ofNullable(response.result())
                        .map(Order::id)
                        .orElseThrow(() -> new IllegalStateException("Missing order id from PayPal"));

                metrics.counter("payment.paypal.authorize.success").increment();
                return PaymentResponse.builder()
                        .providerId(orderId)
                        .status(PaymentStatus.AUTHORIZED)
                        .rawResponse(response.result().toString())
                        .build();
            } catch (IOException | HttpException ex) {
                metrics.counter("payment.paypal.authorize.failure").increment();
                log.error("PayPal authorization failed: {}", ex.getMessage(), ex);
                return PaymentResponse.failed("PAYPAL_AUTH_ERR", ex.getMessage());
            }
        });
    }

    @Override
    public PaymentResponse capture(final String authorizationId, final Money amount) {
        return Tracing.trace("paypal.capture", span -> {
            OrdersCaptureRequest captureReq = new OrdersCaptureRequest(authorizationId);
            captureReq.requestBody(new OrderRequest()); // empty body for capture

            try {
                HttpResponse<Order> response = client.execute(captureReq);
                String captureId = extractCaptureId(response.result());

                metrics.counter("payment.paypal.capture.success").increment();
                return PaymentResponse.builder()
                        .providerId(captureId)
                        .status(PaymentStatus.CAPTURED)
                        .rawResponse(response.result().toString())
                        .build();
            } catch (IOException | HttpException ex) {
                metrics.counter("payment.paypal.capture.failure").increment();
                log.error("PayPal capture failed: {}", ex.getMessage(), ex);
                return PaymentResponse.failed("PAYPAL_CAPTURE_ERR", ex.getMessage());
            }
        });
    }

    @Override
    public PaymentResponse refund(final RefundRequest request) {
        return Tracing.trace("paypal.refund", span -> {
            if (StringUtils.isBlank(request.getProviderCaptureId())) {
                return PaymentResponse.failed("MISSING_CAPTURE_ID", "Provider capture id is mandatory");
            }

            CapturesRefundRequest refundReq =
                    new CapturesRefundRequest(request.getProviderCaptureId())
                            .requestBody(buildRefundRequestBody(request));

            try {
                HttpResponse<Refund> response = client.execute(refundReq);

                metrics.counter("payment.paypal.refund.success").increment();
                return PaymentResponse.builder()
                        .providerId(response.result().id())
                        .status(PaymentStatus.REFUNDED)
                        .rawResponse(response.result().toString())
                        .build();
            } catch (IOException | HttpException ex) {
                metrics.counter("payment.paypal.refund.failure").increment();
                log.error("PayPal refund failed: {}", ex.getMessage(), ex);
                return PaymentResponse.failed("PAYPAL_REFUND_ERR", ex.getMessage());
            }
        });
    }

    /**
     * Verifies the authenticity of a PayPal webhook transmission.
     * This method is separated from the interface because most callers use
     * webhooks through a dedicated inbound adapter.
     *
     * @return true if the webhook signature is valid
     */
    public boolean verifyWebhookSignature(final String transmissionId,
                                          final String timeStamp,
                                          final String webhookId,
                                          final String transmissionSig,
                                          final String expectedBody) {

        // In a real implementation we would invoke:
        // com.paypal.subscriptions.WebhookEvent.verify(...)
        // For simplicity, we simulate verification only.

        try {
            // Pretend to verify using HMAC + secret
            boolean valid = SecureWebhookVerifier.verify(
                    transmissionId,
                    timeStamp,
                    webhookId,
                    transmissionSig,
                    expectedBody
            );

            if (!valid) {
                metrics.counter("payment.paypal.webhook.invalid_signature").increment();
            }

            return valid;
        } catch (Exception ex) {
            log.error("Webhook verification error", ex);
            return false;
        }
    }

    // -------------------------------------------------------------------------
    // Helper Methods
    // -------------------------------------------------------------------------

    private OrderRequest buildOrderRequest(PaymentRequest req) {
        OrderRequest request = new OrderRequest();
        request.checkoutPaymentIntent("AUTHORIZE");

        AmountWithBreakdown amount = new AmountWithBreakdown()
                .currencyCode(req.getMoney().getCurrency().getCurrencyCode())
                .value(formatAmount(req.getMoney().getAmount()));

        PurchaseUnitRequest purchaseUnit = new PurchaseUnitRequest()
                .referenceId(UUID.randomUUID().toString())
                .description(req.getDescription())
                .amountWithBreakdown(amount);

        request.purchaseUnits(Collections.singletonList(purchaseUnit));

        ApplicationContext context = new ApplicationContext()
                .returnUrl(req.getReturnUrl())
                .cancelUrl(req.getCancelUrl());

        request.applicationContext(context);

        return request;
    }

    private RefundRequestBody buildRefundRequestBody(final RefundRequest req) {
        return new RefundRequestBody()
                .amount(new Money()
                        .currencyCode(req.getMoney().getCurrency().getCurrencyCode())
                        .value(formatAmount(req.getMoney().getAmount())))
                .invoiceId(req.getOrderId())
                .noteToPayer(req.getReason())
                .softDescriptor("SPRINTCART");
    }

    private String formatAmount(BigDecimal amount) {
        return amount.setScale(2, BigDecimal.ROUND_HALF_UP).toPlainString();
    }

    /**
     * Extracts the capture id from a PayPal Order response.
     * PayPal nests captures inside purchase_units[] → payments → captures[].
     */
    private String extractCaptureId(Order order) {
        return Optional.ofNullable(order.purchaseUnits())
                .flatMap(units -> units.stream().findFirst())
                .flatMap(u -> Optional.ofNullable(u.payments()))
                .flatMap(p -> Optional.ofNullable(p.captures()).flatMap(caps -> caps.stream().findFirst()))
                .map(Capture::id)
                .orElse("UNKNOWN_CAPTURE_ID");
    }

    // -------------------------------------------------------------------------
    // Inner helper: secure webhook verifier
    // -------------------------------------------------------------------------

    /**
     * Minimal secure signature verification helper.
     * In production this would likely live in a shared security module.
     */
    private static final class SecureWebhookVerifier {

        /**
         * Verifies the PayPal webhook HMAC signature.
         *
         * @return true if valid
         */
        static boolean verify(String transmissionId,
                              String timeStamp,
                              String webhookId,
                              String transmissionSig,
                              String expectedBody) {

            // For illustration only.
            // Real implementation would fetch webhook secret and verify RSA-SHA256 signature.
            String generated = String.join("|", transmissionId, timeStamp, webhookId, expectedBody);
            String expectedSignature = Hashing.sha256Hex(generated); // Apache commons / Guava hash

            return expectedSignature.equals(transmissionSig);
        }
    }

    // -------------------------------------------------------------------------
    // Static hashing helper (placeholder)
    // -------------------------------------------------------------------------

    /**
     * Hashing utilities (placeholder).
     * In a real system we would pull in Guava or Apache Commons Codec.
     */
    private static final class Hashing {
        static String sha256Hex(String input) {
            try {
                java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-256");
                byte[] hash = md.digest(input.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                StringBuilder hex = new StringBuilder();
                for (byte b : hash) {
                    String h = Integer.toHexString(0xff & b);
                    if (h.length() == 1) hex.append('0');
                    hex.append(h);
                }
                return hex.toString();
            } catch (Exception e) {
                throw new IllegalStateException("Unable to compute SHA-256 hash", e);
            }
        }
    }

    // -------------------------------------------------------------------------
    // Builder (for dependency-injection-friendly construction)
    // -------------------------------------------------------------------------

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private String clientId;
        private String clientSecret;
        private boolean sandbox = false;
        private MetricsRegistry metricsRegistry = MetricsRegistry.noop();

        public Builder clientId(String clientId) {
            this.clientId = clientId;
            return this;
        }

        public Builder clientSecret(String clientSecret) {
            this.clientSecret = clientSecret;
            return this;
        }

        public Builder sandbox(boolean sandbox) {
            this.sandbox = sandbox;
            return this;
        }

        public Builder metrics(MetricsRegistry metricsRegistry) {
            this.metricsRegistry = metricsRegistry;
            return this;
        }

        public PayPalAdapter build() {
            return new PayPalAdapter(clientId, clientSecret, sandbox, metricsRegistry);
        }
    }

    // -------------------------------------------------------------------------
    // Tracing – executed when bean is destroyed (e.g., graceful shutdown)
    // -------------------------------------------------------------------------

    @Override
    public void close() throws Exception {
        // PayPalHttpClient currently has no close() but future versions might.
        // This method exists to satisfy AutoCloseable and for symmetry across adapters.
        log.info("PayPalAdapter closed at {}", Instant.now());
    }
}
```