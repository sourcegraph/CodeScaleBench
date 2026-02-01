package com.sprintcart.domain.ports.out.notification;

import java.io.Serial;
import java.io.Serializable;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.regex.Pattern;

/**
 * Outbound port that allows the domain layer to request email notifications
 * without depending on any particular e-mail gateway or vendor SDK.
 *
 * Implementations live in the infrastructure layer (e.g. SendGridAdapter,
 * SESAdapter) and are wired into the application via dependency injection.
 *
 * The port purposefully exposes rich value objects (EmailMessage, Attachment,
 * EmailAddress) so that the domain layer can fully describe the intent of the
 * notification while remaining technology-agnostic.
 */
public interface EmailNotificationPort {

    /**
     * Synchronously sends an email message.  The method SHALL block until the
     * message has been either accepted by the provider or rejected with a
     * definitive reason.
     *
     * @param message domain representation of the e-mail
     * @throws EmailSendingException when the provider rejects or a technical
     *                               issue (network, authentication, etc.) occurs
     */
    void send(EmailMessage message) throws EmailSendingException;

    /**
     * Same as {@link #send(EmailMessage)} but returns immediately.  The
     * implementation decides whether to delegate to a message queue, thread
     * pool or a reactive pipeline.
     *
     * @param message  domain representation of the e-mail
     * @param callback callback invoked on success or failure
     */
    void sendAsync(EmailMessage message, EmailDeliveryCallback callback);

    /**
     * Lightweight liveness probe.  This may perform a HEAD request, token
     * refresh, SMTP NOOP or anything cheap that provides confidence that the
     * provider is reachable.
     *
     * @return {@code true} when the provider appears healthy
     */
    boolean health();

    /* -------------------------------------------------------------------- */
    /*                               VALUE OBJECTS                          */
    /* -------------------------------------------------------------------- */

    /**
     * Immutable value object that models an email to be sent.
     */
    final class EmailMessage implements Serializable {

        @Serial
        private static final long serialVersionUID = -8419846593503782503L;

        private static final Pattern SUBJECT_SANITIZER = Pattern.compile("\\s+");

        private final EmailAddress from;
        private final List<EmailAddress> to;
        private final List<EmailAddress> cc;
        private final List<EmailAddress> bcc;
        private final String subject;
        private final String body;
        private final BodyFormat bodyFormat;
        private final List<Attachment> attachments;
        private final Map<String, String> customHeaders;
        private final Instant createdAt;

        private EmailMessage(Builder builder) {
            this.from          = builder.from;
            this.to            = Collections.unmodifiableList(builder.to);
            this.cc            = Collections.unmodifiableList(builder.cc);
            this.bcc           = Collections.unmodifiableList(builder.bcc);
            this.subject       = sanitizeSubject(builder.subject);
            this.body          = builder.body;
            this.bodyFormat    = builder.bodyFormat;
            this.attachments   = Collections.unmodifiableList(builder.attachments);
            this.customHeaders = Map.copyOf(builder.customHeaders);
            this.createdAt     = Instant.now();
        }

        /* --------------- Factory / Builder ------------------------------- */

        public static Builder builder() {
            return new Builder();
        }

        public static final class Builder {
            private EmailAddress from;
            private final List<EmailAddress> to   = new ArrayList<>();
            private final List<EmailAddress> cc   = new ArrayList<>();
            private final List<EmailAddress> bcc  = new ArrayList<>();
            private String subject;
            private String body;
            private BodyFormat bodyFormat = BodyFormat.HTML;
            private final List<Attachment> attachments = new ArrayList<>();
            private Map<String, String> customHeaders = Map.of();

            private Builder() {
            }

            public Builder from(String email) {
                this.from = new EmailAddress(email);
                return this;
            }

            public Builder to(String email) {
                this.to.add(new EmailAddress(email));
                return this;
            }

            public Builder cc(String email) {
                this.cc.add(new EmailAddress(email));
                return this;
            }

            public Builder bcc(String email) {
                this.bcc.add(new EmailAddress(email));
                return this;
            }

            public Builder subject(String subject) {
                this.subject = subject;
                return this;
            }

            public Builder body(String body, BodyFormat format) {
                this.body       = body;
                this.bodyFormat = Objects.requireNonNull(format);
                return this;
            }

            public Builder attachment(Attachment attachment) {
                this.attachments.add(Objects.requireNonNull(attachment));
                return this;
            }

            public Builder headers(Map<String, String> headers) {
                this.customHeaders = Map.copyOf(headers);
                return this;
            }

            public EmailMessage build() {
                if (from == null) {
                    throw new IllegalStateException("'from' address must be provided");
                }
                if (to.isEmpty() && cc.isEmpty() && bcc.isEmpty()) {
                    throw new IllegalStateException("At least one recipient must be provided");
                }
                if (subject == null || subject.isBlank()) {
                    throw new IllegalStateException("Subject must not be blank");
                }
                if (body == null) {
                    throw new IllegalStateException("Body must be provided");
                }
                return new EmailMessage(this);
            }
        }

        /* --------------- Getters & helpers ------------------------------- */

        public EmailAddress getFrom() {
            return from;
        }

        public List<EmailAddress> getTo() {
            return to;
        }

        public List<EmailAddress> getCc() {
            return cc;
        }

        public List<EmailAddress> getBcc() {
            return bcc;
        }

        public String getSubject() {
            return subject;
        }

        public String getBody() {
            return body;
        }

        public BodyFormat getBodyFormat() {
            return bodyFormat;
        }

        public List<Attachment> getAttachments() {
            return attachments;
        }

        public Map<String, String> getCustomHeaders() {
            return customHeaders;
        }

        public Instant getCreatedAt() {
            return createdAt;
        }

        private String sanitizeSubject(String raw) {
            return SUBJECT_SANITIZER.matcher(raw.trim())
                                    .replaceAll(" ");
        }

        @Override
        public int hashCode() {
            return Objects.hash(from, to, cc, bcc, subject, body, bodyFormat,
                                attachments, customHeaders, createdAt);
        }

        @Override
        public boolean equals(Object obj) {
            if (this == obj) return true;
            if (!(obj instanceof EmailMessage other)) return false;
            return Objects.equals(from,          other.from) &&
                   Objects.equals(to,            other.to) &&
                   Objects.equals(cc,            other.cc) &&
                   Objects.equals(bcc,           other.bcc) &&
                   Objects.equals(subject,       other.subject) &&
                   Objects.equals(body,          other.body) &&
                   bodyFormat == other.bodyFormat &&
                   Objects.equals(attachments,   other.attachments) &&
                   Objects.equals(customHeaders, other.customHeaders) &&
                   Objects.equals(createdAt,     other.createdAt);
        }

        @Override
        public String toString() {
            return "EmailMessage{" +
                   "from=" + from +
                   ", to=" + to +
                   ", cc=" + cc +
                   ", bcc=" + bcc +
                   ", subject='" + subject + '\'' +
                   ", bodyFormat=" + bodyFormat +
                   ", attachments=" + attachments.size() +
                   ", createdAt=" + createdAt +
                   '}';
        }
    }

    /**
     * Simple immutable wrapper around an RFC-5322 compliant e-mail address.
     */
    final class EmailAddress implements Serializable {

        @Serial
        private static final long serialVersionUID = -651214013175570326L;

        // Very permissive pattern, delegates stricter validation to provider
        private static final Pattern RFC5322 = Pattern.compile("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$");

        private final String value;

        public EmailAddress(String raw) {
            Objects.requireNonNull(raw, "E-mail address cannot be null");
            String trimmed = raw.trim();
            if (!RFC5322.matcher(trimmed).matches()) {
                throw new IllegalArgumentException("Invalid e-mail address: " + raw);
            }
            this.value = trimmed.toLowerCase(StandardCharsets.US_ASCII);
        }

        public String getValue() {
            return value;
        }

        @Override
        public String toString() {
            return value;
        }

        @Override
        public int hashCode() {
            return value.hashCode();
        }

        @Override
        public boolean equals(Object obj) {
            return obj instanceof EmailAddress other && value.equals(other.value);
        }
    }

    /**
     * Attachment container.  Keep it minimal in the domain layer; let adapters
     * map it to Jakarta Mail, SendGrid’s API, etc.
     */
    final class Attachment implements Serializable {

        @Serial
        private static final long serialVersionUID = 918322345850190153L;

        private final String fileName;
        private final String mediaType;
        private final byte[] content;

        public Attachment(String fileName, String mediaType, byte[] content) {
            this.fileName  = Objects.requireNonNull(fileName,  "fileName must not be null");
            this.mediaType = Objects.requireNonNull(mediaType, "mediaType must not be null");
            this.content   = Objects.requireNonNull(content,   "content must not be null").clone();
        }

        public String getFileName() {
            return fileName;
        }

        public String getMediaType() {
            return mediaType;
        }

        public byte[] getContent() {
            return content.clone();
        }

        @Override
        public int hashCode() {
            return Objects.hash(fileName, mediaType, content.length);
        }

        @Override
        public boolean equals(Object obj) {
            if (this == obj) return true;
            if (!(obj instanceof Attachment other)) return false;
            return Objects.equals(fileName,  other.fileName) &&
                   Objects.equals(mediaType, other.mediaType) &&
                   Objects.deepEquals(content, other.content);
        }
    }

    /**
     * Enum describing the format of the email body.
     */
    enum BodyFormat {
        PLAIN_TEXT,
        HTML
    }

    /**
     * Callback used for asynchronous delivery attempts.
     */
    interface EmailDeliveryCallback {

        /**
         * Invoked when the email has been handed over to the provider for
         * delivery.  The provider-specific message identifier is supplied for
         * downstream tracking.
         */
        void onSuccess(String providerMessageId);

        /**
         * Invoked when the email could not be delivered.  The throwable MAY be
         * an {@link EmailSendingException} but could be any {@link Exception}
         * encountered during processing.
         */
        void onFailure(Throwable cause);
    }

    /**
     * Technical exception thrown when an email cannot be queued or sent.
     *
     * This is not a business exception (e.g. “Promotion expired”) but a
     * cross-cutting infrastructure failure.  Therefore it extends
     * {@link RuntimeException} so that transaction boundaries are marked for
     * rollback automatically by Spring or Jakarta EE.
     */
    class EmailSendingException extends RuntimeException {
        @Serial
        private static final long serialVersionUID = -3282339468058042062L;

        public EmailSendingException(String message) {
            super(message);
        }

        public EmailSendingException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}