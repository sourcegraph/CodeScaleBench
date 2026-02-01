```java
package com.commercesphere.enterprise.payment.service;

import com.commercesphere.enterprise.common.exception.BusinessException;
import com.commercesphere.enterprise.common.exception.TechnicalException;
import com.commercesphere.enterprise.logging.AuditTrail;
import com.commercesphere.enterprise.payment.api.PaymentGateway;
import com.commercesphere.enterprise.payment.api.dto.PaymentRequest;
import com.commercesphere.enterprise.payment.api.dto.PaymentResponse;
import com.commercesphere.enterprise.payment.api.enums.PaymentStatus;
import com.commercesphere.enterprise.payment.config.PaymentProperties;
import com.stripe.Stripe;
import com.stripe.exception.CardException;
import com.stripe.exception.InvalidRequestException;
import com.stripe.exception.StripeException;
import com.stripe.model.PaymentIntent;
import com.stripe.model.Refund;
import com.stripe.param.PaymentIntentCaptureParams;
import com.stripe.param.PaymentIntentCreateParams;
import com.stripe.param.RefundCreateParams;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.retry.RetryCallback;
import org.springframework.retry.RetryContext;
import org.springframework.retry.backoff.FixedBackOffPolicy;
import org.springframework.retry.policy.SimpleRetryPolicy;
import org.springframework.retry.support.RetryTemplate;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Currency;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Stripe implementation of {@link PaymentGateway}. Responsibilities:
 *  - Authorizing and capturing payments (two-step)
 *  - Processing refunds
 *  - Converting Stripe errors to platform-specific exceptions
 *  - Centralized audit and PCI-compliant logging (never log raw PAN / CVV)
 *
 * The class is designed to be Spring managed and stateless; all mutable state
 * lives inside Stripe SDK domain objects or is transient inside method calls.
 */
@Service("stripePaymentGateway")
public class StripePaymentGateway implements PaymentGateway, InitializingBean {

    private static final Logger LOGGER = LoggerFactory.getLogger(StripePaymentGateway.class);

    private final PaymentProperties paymentProperties;
    private final AuditTrail auditTrail;

    private final RetryTemplate retryTemplate;

    public StripePaymentGateway(PaymentProperties paymentProperties,
                                AuditTrail auditTrail) {
        this.paymentProperties = paymentProperties;
        this.auditTrail = auditTrail;
        this.retryTemplate = buildRetryTemplate();
    }

    /**
     * Initializes the Stripe SDK with the secret key configured in application-
     * level properties. Spring calls this hook after property injection.
     */
    @Override
    public void afterPropertiesSet() {
        Stripe.apiKey = paymentProperties.getStripe().getSecretKey();
        Stripe.setAppInfo("CommerceSphereEnterpriseSuite", "1.0.0", "https://www.commercesphere.com");
    }

    // ------------------------------------------------------------------------
    // PaymentGateway API implementation
    // ------------------------------------------------------------------------

    /**
     * Creates a PaymentIntent in Stripe with manual capture. The intent id is
     * returned to callers so that it can be captured later during shipment.
     */
    @Override
    public PaymentResponse authorize(PaymentRequest request) {
        return retryTemplate.execute((RetryCallback<PaymentResponse, TechnicalException>) context ->
                doAuthorize(request)
        );
    }

    /**
     * Captures a previously authorized PaymentIntent from Stripe. The Stripe
     * idempotency layer automatically protects from double charges.
     */
    @Override
    public PaymentResponse capture(String authorizationId,
                                   BigDecimal amount,
                                   Currency currency) {
        return retryTemplate.execute((RetryCallback<PaymentResponse, TechnicalException>) context ->
                doCapture(authorizationId, amount, currency)
        );
    }

    /**
     * Refunds a charge (full or partial).
     */
    @Override
    public PaymentResponse refund(String transactionId,
                                  BigDecimal amount,
                                  Currency currency) {
        return retryTemplate.execute((RetryCallback<PaymentResponse, TechnicalException>) context ->
                doRefund(transactionId, amount, currency)
        );
    }

    // ------------------------------------------------------------------------
    // Core implementation
    // ------------------------------------------------------------------------

    private PaymentResponse doAuthorize(PaymentRequest request) {
        try {
            PaymentIntentCreateParams params = buildAuthorizationParams(request);
            PaymentIntent intent = PaymentIntent.create(params);
            auditSuccess("AUTHORIZE", intent.getId(), request.getOrderId());
            return buildPaymentResponse(intent, PaymentStatus.AUTHORIZED);
        } catch (StripeException e) {
            auditFailure("AUTHORIZE", request.getOrderId(), e);
            throw translateStripeException("authorization", e);
        }
    }

    private PaymentResponse doCapture(String authorizationId,
                                      BigDecimal amount,
                                      Currency currency) {
        try {
            PaymentIntent intent = PaymentIntent.retrieve(authorizationId);
            PaymentIntentCaptureParams captureParams = PaymentIntentCaptureParams.builder()
                    .setAmount(toMinorUnit(amount, currency))
                    .putMetadata("captured_at", Instant.now().toString())
                    .build();

            intent = intent.capture(captureParams);
            auditSuccess("CAPTURE", intent.getId(), authorizationId);
            return buildPaymentResponse(intent, PaymentStatus.CAPTURED);
        } catch (StripeException e) {
            auditFailure("CAPTURE", authorizationId, e);
            throw translateStripeException("capture", e);
        }
    }

    private PaymentResponse doRefund(String transactionId,
                                     BigDecimal amount,
                                     Currency currency) {
        try {
            RefundCreateParams params = RefundCreateParams.builder()
                    .setAmount(toMinorUnit(amount, currency))
                    .setPaymentIntent(transactionId)
                    .setReason(RefundCreateParams.Reason.REQUESTED_BY_CUSTOMER)
                    .putMetadata("refunded_at", Instant.now().toString())
                    .build();

            Refund refund = Refund.create(params);
            auditSuccess("REFUND", refund.getId(), transactionId);
            return buildRefundResponse(refund, PaymentStatus.REFUNDED);
        } catch (StripeException e) {
            auditFailure("REFUND", transactionId, e);
            throw translateStripeException("refund", e);
        }
    }

    // ------------------------------------------------------------------------
    // Helper methods
    // ------------------------------------------------------------------------

    private PaymentIntentCreateParams buildAuthorizationParams(PaymentRequest request) {
        return PaymentIntentCreateParams.builder()
                .setCurrency(request.getCurrency().getCurrencyCode().toLowerCase())
                .setAmount(toMinorUnit(request.getAmount(), request.getCurrency()))
                .setCustomer(request.getCustomerReference())
                .setPaymentMethod(request.getPaymentMethodToken())
                .setConfirm(Boolean.TRUE)
                .setCaptureMethod(PaymentIntentCreateParams.CaptureMethod.MANUAL)
                .setIdempotencyKey(buildIdempotencyKey("auth", request.getOrderId()))
                .putMetadata("order_id", request.getOrderId())
                .putMetadata("created_at", Instant.now().toString())
                .build();
    }

    private String buildIdempotencyKey(String prefix, String orderId) {
        // Stripe idempotency keys must be unique for each logical operation.
        return String.format("%s_%s_%s",
                prefix,
                orderId,
                UUID.randomUUID().toString().replace("-", "").substring(0, 18));
    }

    private long toMinorUnit(BigDecimal amount, Currency currency) {
        int fraction = currency.getDefaultFractionDigits();
        return amount.movePointRight(fraction).longValueExact();
    }

    private PaymentResponse buildPaymentResponse(PaymentIntent intent, PaymentStatus status) {
        return PaymentResponse.builder()
                .gatewayTransactionId(intent.getId())
                .status(status)
                .amount(new BigDecimal(intent.getAmount()).movePointLeft(intent.getCurrency().equals("jpy") ? 0 : 2))
                .currency(Currency.getInstance(intent.getCurrency().toUpperCase()))
                .createdAt(Instant.ofEpochSecond(intent.getCreated()))
                .rawResponse(intent.toJson())
                .build();
    }

    private PaymentResponse buildRefundResponse(Refund refund, PaymentStatus status) {
        return PaymentResponse.builder()
                .gatewayTransactionId(refund.getId())
                .status(status)
                .amount(new BigDecimal(refund.getAmount()).movePointLeft(refund.getCurrency().equals("jpy") ? 0 : 2))
                .currency(Currency.getInstance(refund.getCurrency().toUpperCase()))
                .createdAt(Instant.ofEpochSecond(refund.getCreated()))
                .rawResponse(refund.toJson())
                .build();
    }

    private TechnicalException translateStripeException(String operation, StripeException e) {
        if (e instanceof CardException) {
            // Recoverable business error (declined, etc.)
            return new BusinessException(
                    String.format("Stripe card error during %s: %s", operation, e.getMessage()), e);
        } else if (e instanceof InvalidRequestException) {
            return new BusinessException(
                    String.format("Invalid Stripe request during %s: %s", operation, e.getMessage()), e);
        }

        // Default to technical unrecoverable error
        return new TechnicalException(
                String.format("Stripe API failure during %s: %s", operation, e.getMessage()), e);
    }

    private void auditSuccess(String action, String stripeId, String referenceId) {
        auditTrail.logPaymentSuccess(action, stripeId, referenceId);
        LOGGER.info("Stripe {} successful. stripeId={}, reference={}", action, stripeId, referenceId);
    }

    private void auditFailure(String action, String referenceId, Exception e) {
        auditTrail.logPaymentFailure(action, referenceId, e.getMessage());
        LOGGER.error("Stripe {} failed for referenceId={}: {}", action, referenceId, e.getMessage());
    }

    private RetryTemplate buildRetryTemplate() {
        SimpleRetryPolicy policy = new SimpleRetryPolicy(
                paymentProperties.getStripe().getMaxRetries(),
                buildRetryableExceptionsMap(),
                true);

        FixedBackOffPolicy backOff = new FixedBackOffPolicy();
        backOff.setBackOffPeriod(paymentProperties.getStripe().getBackoff());
        RetryTemplate template = new RetryTemplate();
        template.setRetryPolicy(policy);
        template.setBackOffPolicy(backOff);
        return template;
    }

    private Map<Class<? extends Throwable>, Boolean> buildRetryableExceptionsMap() {
        Map<Class<? extends Throwable>, Boolean> map = new HashMap<>();
        map.put(com.stripe.exception.ApiConnectionException.class, true);
        map.put(com.stripe.exception.ApiException.class, true);
        map.put(com.stripe.exception.RateLimitException.class, true);
        map.put(com.stripe.exception.IdempotencyException.class, false);
        map.put(com.stripe.exception.InvalidRequestException.class, false);
        map.put(com.stripe.exception.CardException.class, false);
        return map;
    }
}
```