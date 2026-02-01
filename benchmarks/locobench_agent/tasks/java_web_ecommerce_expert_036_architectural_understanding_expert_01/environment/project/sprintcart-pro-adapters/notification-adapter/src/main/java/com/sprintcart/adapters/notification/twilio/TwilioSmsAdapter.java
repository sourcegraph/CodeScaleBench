package com.sprintcart.adapters.notification.twilio;

import com.sprintcart.domain.notification.model.SmsPayload;
import com.sprintcart.domain.notification.model.SmsResult;
import com.sprintcart.domain.notification.model.SmsResult.Status;
import com.sprintcart.domain.notification.port.outgoing.SmsNotificationPort;
import com.twilio.Twilio;
import com.twilio.exception.ApiException;
import com.twilio.rest.api.v2010.account.Message;
import com.twilio.type.PhoneNumber;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Clock;
import java.time.Instant;
import java.util.Objects;

/**
 * Outbound adapter that sends SMS messages through Twilio.
 * <p>
 *     This class lives in the infrastructure layer and fulfils the {@link SmsNotificationPort}
 *     contract required by the domain.  It is deliberately thin—concerned only with translating
 *     domain models into Twilio SDK calls, handling transient failures gracefully, and mapping
 *     Twilio specific exceptions into domain-friendly result objects.
 * </p>
 *
 * <pre>
 * ┌────────────────────────────┐
 * │Domain Layer (pure logic)   │
 * │  └─ SmsNotificationPort    │
 * └────────────────────────────┘
 *                ▲
 *                │ implements
 *                ▼
 * ┌────────────────────────────┐
 * │TwilioSmsAdapter            │  Outbound adapter
 * └────────────────────────────┘
 * </pre>
 *
 * Thread-safety: the adapter is stateless after construction; it can therefore be registered as a
 * singleton bean in Spring/Kotlin/Guice without additional synchronisation.
 */
public class TwilioSmsAdapter implements SmsNotificationPort {

    private static final Logger LOG = LoggerFactory.getLogger(TwilioSmsAdapter.class);

    private final TwilioConfig config;
    private final Clock clock;

    /**
     * Convenience constructor that initialises Twilio with the provided credentials
     * and uses {@link Clock#systemUTC()} as the time source.
     *
     * @param config configuration wrapper containing SID, auth-token and default "from" number.
     */
    public TwilioSmsAdapter(final TwilioConfig config) {
        this(config, Clock.systemUTC());
    }

    /**
     * Full constructor mainly used for testing, where the clock can be stubbed.
     */
    public TwilioSmsAdapter(final TwilioConfig config, final Clock clock) {
        this.config = Objects.requireNonNull(config, "config must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");

        /*
         * Twilio initialisation is idempotent; subsequent calls merely overwrite
         * the static singleton with the same values which is harmless.
         */
        Twilio.init(config.accountSid(), config.authToken());

        LOG.info("TwilioSmsAdapter initialised.  Account SID: {}", mask(config.accountSid()));
    }

    /**
     * Send an SMS using Twilio.
     *
     * @param payload domain-level description of the SMS to send.
     * @return a {@link SmsResult} describing the outcome, never {@code null}.
     */
    @Override
    public SmsResult send(final SmsPayload payload) {
        Objects.requireNonNull(payload, "payload must not be null");

        final Instant start = clock.instant();
        try {
            final Message message = Message.creator(
                    new PhoneNumber(payload.to()),
                    new PhoneNumber(payload.from().orElse(config.defaultFromNumber())),
                    payload.message())
                    .setStatusCallback(payload.statusCallbackUrl().orElse(null))
                    .create();

            final Instant end = clock.instant();
            LOG.debug("Sent SMS to {} in {} ms. Twilio SID={}",
                      payload.to(),
                      end.toEpochMilli() - start.toEpochMilli(),
                      message.getSid());

            return SmsResult.builder()
                            .status(Status.SENT)
                            .providerMessageId(message.getSid())
                            .timestamp(end)
                            .build();
        } catch (final ApiException apiEx) {
            // Typical Twilio error: 21211 (invalid 'To' phone number), 21610 (blacklisted), etc.
            LOG.warn("Twilio API error while sending SMS to {} (code={}): {}",
                     payload.to(), apiEx.getCode(), apiEx.getMessage());

            return SmsResult.builder()
                            .status(Status.REJECTED)
                            .providerErrorCode(String.valueOf(apiEx.getCode()))
                            .providerErrorMessage(apiEx.getMessage())
                            .timestamp(clock.instant())
                            .build();
        } catch (final Exception ex) {
            // Network error, credentials revoked, unknown runtime exceptions
            LOG.error("Unexpected error when sending SMS through Twilio", ex);
            return SmsResult.builder()
                            .status(Status.FAILED)
                            .providerErrorMessage(ex.getMessage())
                            .timestamp(clock.instant())
                            .build();
        }
    }

    /* --------------------------------------------------- *
     * Helper methods
     * --------------------------------------------------- */

    /**
     * Masks a sensitive token, showing only the last 4 characters.
     */
    private static String mask(final String token) {
        if (token == null || token.length() < 4) {
            return "****";
        }
        return "****" + token.substring(token.length() - 4);
    }

    /* --------------------------------------------------- *
     *  Config Record
     * --------------------------------------------------- */

    /**
     * Tiny immutable configuration record.
     * <p>
     *     In a Spring Boot environment this can be populated from
     *     <code>sprintcart.notification.twilio.*</code> properties
     *     via {@code @ConfigurationProperties} in a dedicated class.
     * </p>
     */
    public record TwilioConfig(String accountSid,
                               String authToken,
                               String defaultFromNumber) {

        public TwilioConfig {
            Objects.requireNonNull(accountSid, "accountSid must not be null");
            Objects.requireNonNull(authToken, "authToken must not be null");
            Objects.requireNonNull(defaultFromNumber, "defaultFromNumber must not be null");
        }
    }
}