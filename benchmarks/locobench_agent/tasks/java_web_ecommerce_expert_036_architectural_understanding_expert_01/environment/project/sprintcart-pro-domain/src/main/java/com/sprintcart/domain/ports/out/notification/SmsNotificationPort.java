package com.sprintcart.domain.ports.out.notification;

import java.time.Instant;
import java.time.ZonedDateTime;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * Outbound port that abstracts interaction with any SMS gateway/provider.
 * <p>
 * Implementations live in the infrastructure layer and are responsible for
 * marshalling {@link SmsNotificationPort.SmsMessage} instances to the
 * provider-specific API, as well as mapping provider responses to a generic
 * {@link SmsNotificationPort.DeliveryResult}.<br>
 * <br>
 * By depending on this interface, the domain layer can trigger SMS
 * notifications without creating a compile-time dependency on any particular
 * vendor (Twilio, AWS SNS, MessageBird, etc.), keeping the core pure and
 * testable.
 */
public interface SmsNotificationPort {

    /**
     * Immediately sends an SMS message.
     *
     * @param message fully-validated SMS payload
     * @return delivery result that contains the provider reference and current status
     * @throws SmsGatewayException when the gateway rejects or fails to accept the message
     */
    DeliveryResult send(SmsMessage message) throws SmsGatewayException;

    /**
     * Schedules an SMS for future delivery.
     *
     * @param message      message payload
     * @param deliveryTime absolute instant when the message should be delivered
     * @return delivery result containing the provider reference and current status (e.g. QUEUED)
     * @throws IllegalArgumentException when {@code deliveryTime} is in the past
     * @throws SmsGatewayException      when the provider fails to schedule the message
     */
    DeliveryResult schedule(SmsMessage message, Instant deliveryTime) throws SmsGatewayException;

    /**
     * Attempts to cancel a previously scheduled SMS.
     *
     * @param externalReference the provider-specific identifier obtained from {@link #schedule}
     * @return {@code true} if the cancellation was acknowledged by the provider, {@code false} otherwise
     * @throws SmsGatewayException when the provider returns an error or the operation is unsupported
     */
    boolean cancelScheduled(String externalReference) throws SmsGatewayException;

    /**
     * Lightweight health check used by observability probes.
     *
     * @return {@code true} when the provider is reachable and credentials are valid
     */
    default boolean healthCheck() {
        try {
            ping();
            return true;
        } catch (SmsGatewayException ignored) {
            return false;
        }
    }

    /**
     * Implementation-specific ping that validates connectivity and credentials.
     *
     * @throws SmsGatewayException when the check fails
     */
    void ping() throws SmsGatewayException;

    /* ---------- Value Objects & Errors (package-private) ------------------------------------ */

    /**
     * Domain value object representing an SMS message.
     */
    record SmsMessage(
            String from,
            String to,
            String body,
            boolean transactional,
            Map<String, String> metadata
    ) {
        private static final int MAX_MESSAGE_LENGTH = 1600;
        private static final Pattern E164_PATTERN = Pattern.compile("^\\+[1-9]\\d{1,14}$");

        public SmsMessage {
            Objects.requireNonNull(to, "Recipient phone number (to) must not be null");
            Objects.requireNonNull(body, "SMS body must not be null");

            if (!E164_PATTERN.matcher(to).matches()) {
                throw new IllegalArgumentException(
                        "Recipient phone number must be in E.164 format, e.g. +15551234567"
                );
            }

            if (from != null && !E164_PATTERN.matcher(from).matches()) {
                throw new IllegalArgumentException(
                        "Sender phone number (from) must be in E.164 format, e.g. +15559876543"
                );
            }

            if (body.isBlank()) {
                throw new IllegalArgumentException("SMS body must not be blank");
            }

            if (body.length() > MAX_MESSAGE_LENGTH) {
                throw new IllegalArgumentException(
                        "SMS body exceeds maximum length of " + MAX_MESSAGE_LENGTH + " characters"
                );
            }
        }

        /**
         * @return {@code true} when the SMS exceeds a single-part 160-character limit.
         */
        public boolean isLongMessage() {
            return body.length() > 160;
        }
    }

    /**
     * Generic delivery result decoupled from provider-specific response models.
     */
    record DeliveryResult(
            String externalReference,
            DeliveryStatus status,
            ZonedDateTime submittedAt,
            Optional<ZonedDateTime> deliveredAt,
            Optional<String> details
    ) {
        public DeliveryResult {
            Objects.requireNonNull(externalReference, "externalReference");
            Objects.requireNonNull(status, "status");
            Objects.requireNonNull(submittedAt, "submittedAt");
            Objects.requireNonNull(deliveredAt, "deliveredAt");
            Objects.requireNonNull(details, "details");
        }
    }

    /**
     * Enumerates the life-cycle states of an SMS inside the provider.
     */
    enum DeliveryStatus {
        /**
         * Accepted by provider and waiting for dispatch.
         */
        QUEUED,
        /**
         * Dispatched to telecom network.
         */
        SENT,
        /**
         * Delivery confirmed by network.
         */
        DELIVERED,
        /**
         * Permanently failed (e.g. unreachable number).
         */
        FAILED,
        /**
         * Successfully cancelled before dispatch.
         */
        CANCELLED
    }

    /**
     * Exception raised when the underlying SMS gateway rejects an operation.
     */
    class SmsGatewayException extends Exception {
        private final ErrorCategory category;

        public SmsGatewayException(String message, ErrorCategory category) {
            super(message);
            this.category = category;
        }

        public SmsGatewayException(String message, Throwable cause, ErrorCategory category) {
            super(message, cause);
            this.category = category;
        }

        public ErrorCategory getCategory() {
            return category;
        }

        /**
         * Categorizes gateway errors for downstream handling (e.g., retries vs. hard faults).
         */
        public enum ErrorCategory {
            TEMPORARY_NETWORK_FAILURE,
            AUTHENTICATION_FAILURE,
            VALIDATION_ERROR,
            PROVIDER_RATE_LIMIT,
            UNKNOWN
        }
    }
}