```java
package com.sprintcart.domain.ports.out.payment;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Currency;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * Outbound port that abstracts interactions with any external payment gateway.
 * <p>
 * Implementations live in the infrastructure layer and map these
 * high-level domain concepts to concrete gateway SDK calls or HTTP APIs.
 *
 * All monetary values must be represented in the {@link Money} value object to
 * guarantee currency consistency throughout the domain.
 */
public interface PaymentGatewayPort {

    /**
     * Requests authorization of a payment.
     *
     * @param request high-level payment request
     * @return authorization handle containing gateway-specific reference
     * @throws PaymentGatewayException when the gateway is unreachable or rejects the request
     */
    PaymentAuthorization authorize(PaymentRequest request) throws PaymentGatewayException;

    /**
     * Captures (settles) a previously authorized payment.
     *
     * @param authorization previously obtained authorization
     * @param amount        capture amount (must be &lt;= authorized amount)
     * @return capture receipt
     * @throws PaymentGatewayException          gateway error
     * @throws IllegalArgumentException         when amount exceeds authorized amount
     * @throws PaymentNotAuthorizedException    when the authorization is no longer valid
     */
    PaymentCapture capture(PaymentAuthorization authorization,
                           Money amount)
            throws PaymentGatewayException, PaymentNotAuthorizedException;

    /**
     * Voids an existing authorization. No funds will be transferred.
     *
     * @param authorizationId gateway authorization reference
     * @return {@code true} if the gateway confirms the void operation
     * @throws PaymentGatewayException gateway error
     */
    boolean voidAuthorization(String authorizationId) throws PaymentGatewayException;

    /**
     * Issues a refund against a settled capture.
     *
     * @param captureId capture reference as returned by {@link #capture(PaymentAuthorization, Money)}
     * @param amount    refund amount
     * @return refund receipt
     * @throws PaymentGatewayException   gateway error
     * @throws PaymentRefundException    business-level error (e.g. exceeds captured amount)
     */
    PaymentRefund refund(String captureId, Money amount)
            throws PaymentGatewayException, PaymentRefundException;

    /**
     * Validates a gateway webhook callback for authenticity and returns the parsed event.
     *
     * @param rawPayload      original webhook payload
     * @param signatureHeader gateway-specific signature header
     * @return validated event or empty if the signature is invalid
     * @throws PaymentGatewayException communication or parsing error
     */
    Optional<PaymentEvent> verifyAndParseWebhook(String rawPayload,
                                                 String signatureHeader) throws PaymentGatewayException;

    /**
     * Quick health probe that allows the application to know whether the gateway is operational.
     *
     * @return {@code true} if a trivial ping/pong request succeeds
     */
    boolean ping();
}

/* ---------------------------------------------------------------------------
 * Domain value objects & exceptions (package-private to keep file self-contained)
 * In a real project these would likely live in their own files.
 * ---------------------------------------------------------------------------
 */

/**
 * Immutable monetary value object that enforces currency consistency.
 */
record Money(BigDecimal amount, Currency currency) {

    public Money {
        Objects.requireNonNull(amount, "amount");
        Objects.requireNonNull(currency, "currency");

        if (amount.scale() > currency.getDefaultFractionDigits()) {
            throw new IllegalArgumentException(
                    "Scale of amount exceeds currency precision: " + currency);
        }
    }

    public Money add(Money other) {
        verifySameCurrency(other);
        return new Money(amount.add(other.amount), currency);
    }

    public Money subtract(Money other) {
        verifySameCurrency(other);
        return new Money(amount.subtract(other.amount), currency);
    }

    private void verifySameCurrency(Money other) {
        if (!currency.equals(other.currency)) {
            throw new IllegalArgumentException("Currency mismatch: " + currency + " vs " + other.currency);
        }
    }
}

/**
 * High-level request created by the checkout flow.
 */
record PaymentRequest(
        String orderId,
        Money amount,
        String customerEmail,
        String customerIp,
        String returnUrl,
        Map<String, String> metadata
) {
    public PaymentRequest {
        Objects.requireNonNull(orderId, "orderId");
        Objects.requireNonNull(amount, "amount");
        Objects.requireNonNull(customerEmail, "customerEmail");
        Objects.requireNonNull(returnUrl, "returnUrl");
    }
}

/**
 * Represents a successful authorization.
 */
record PaymentAuthorization(
        String authorizationId,
        String orderId,
        Money authorizedAmount,
        PaymentStatus status,
        Instant authorizedAt,
        Map<String, Object> rawGatewayResponse
) {
}

/**
 * Represents a capture/settlement of an authorization.
 */
record PaymentCapture(
        String captureId,
        String authorizationId,
        Money capturedAmount,
        PaymentStatus status,
        Instant capturedAt,
        Map<String, Object> rawGatewayResponse
) {
}

/**
 * Represents a refund of a previous capture.
 */
record PaymentRefund(
        String refundId,
        String captureId,
        Money refundedAmount,
        PaymentStatus status,
        Instant refundedAt,
        Map<String, Object> rawGatewayResponse
) {
}

/**
 * Generic gateway event delivered through webhooks.
 */
record PaymentEvent(
        String eventId,
        PaymentEventType type,
        Instant occurredAt,
        Map<String, Object> payload
) {
}

enum PaymentEventType {
    AUTHORIZED,
    CAPTURED,
    VOIDED,
    REFUNDED,
    CHARGEBACK,
    UNKNOWN
}

enum PaymentStatus {
    PENDING,
    AUTHORIZED,
    CAPTURED,
    VOIDED,
    REFUNDED,
    FAILED
}

/* ---------------------------------------------------------------------------
 * Exceptions
 * ---------------------------------------------------------------------------
 */

/**
 * Top-level technical exception for gateway communication problems.
 */
class PaymentGatewayException extends Exception {
    public PaymentGatewayException(String message) {
        super(message);
    }

    public PaymentGatewayException(String message, Throwable cause) {
        super(message, cause);
    }
}

/**
 * Business exception indicating that an authorization cannot be found or is expired.
 */
class PaymentNotAuthorizedException extends Exception {
    public PaymentNotAuthorizedException(String authorizationId) {
        super("Authorization not found or expired: " + authorizationId);
    }
}

/**
 * Thrown when a refund cannot be processed (e.g. exceeds captured amount).
 */
class PaymentRefundException extends Exception {
    public PaymentRefundException(String message) {
        super(message);
    }

    public PaymentRefundException(String message, Throwable cause) {
        super(message, cause);
    }
}

/* ---------------------------------------------------------------------------
 * Utility
 * ---------------------------------------------------------------------------
 */

/**
 * Generates idempotency keys to guarantee unique operations across retries.
 */
final class IdempotencyKey {

    private IdempotencyKey() {
    }

    public static String generate() {
        return UUID.randomUUID().toString();
    }
}
```