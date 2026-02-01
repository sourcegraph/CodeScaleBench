```java
package com.commercesphere.enterprise.notification.service;

import jakarta.annotation.PreDestroy;
import jakarta.mail.MessagingException;
import jakarta.mail.internet.MimeMessage;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.env.Environment;
import org.springframework.lang.NonNull;
import org.springframework.lang.Nullable;
import org.springframework.mail.MailException;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.MimeMessageHelper;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.thymeleaf.TemplateEngine;
import org.thymeleaf.context.Context;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.*;

/**
 * Production–grade email service that supports synchronous and asynchronous
 * dispatch, template rendering (Thymeleaf), attachments, and audit-grade logging.
 * <p>
 * The implementation is stateless and thread-safe.
 */
@Service
public class EmailService {

    private static final Logger LOGGER = LoggerFactory.getLogger(EmailService.class);
    private static final Set<String> SUPPORTED_CONTENT_TYPES = Set.of("text/plain", "text/html");

    private final JavaMailSender mailSender;
    private final TemplateEngine templateEngine;
    private final ExecutorService executorService;
    private final Environment environment;

    @Value("${commerceSphere.mail.default-from:noreply@commerceSphere.com}")
    private String defaultFrom;

    public EmailService(JavaMailSender mailSender,
                        TemplateEngine templateEngine,
                        Environment environment) {
        this.mailSender = Objects.requireNonNull(mailSender, "mailSender must not be null");
        this.templateEngine = Objects.requireNonNull(templateEngine, "templateEngine must not be null");
        this.environment = Objects.requireNonNull(environment, "environment must not be null");
        this.executorService = new ThreadPoolExecutor(
                2,
                8,
                60L,
                TimeUnit.SECONDS,
                new LinkedBlockingQueue<>(256),
                r -> {
                    Thread t = new Thread(r, "email-dispatcher-" + Instant.now().toEpochMilli());
                    t.setDaemon(true);
                    return t;
                },
                new ThreadPoolExecutor.CallerRunsPolicy()
        );
    }

    /**
     * Sends an email synchronously. Blocks the calling thread until the email
     * is handed off to the SMTP gateway.
     *
     * @throws EmailSendingException if the email could not be sent
     */
    public void send(@NonNull EmailRequest request) throws EmailSendingException {
        validate(request);
        try {
            MimeMessage mimeMessage = toMimeMessage(request);
            mailSender.send(mimeMessage);
            LOGGER.info("Email successfully sent to {}", request.to);
        } catch (MessagingException | MailException ex) {
            LOGGER.error("Failed to send email to {}", request.to, ex);
            throw new EmailSendingException("Unable to send email", ex);
        }
    }

    /**
     * Sends an email asynchronously. The method returns immediately with a
     * {@link CompletableFuture} that is completed when the email is dispatched.
     */
    @Async
    public CompletableFuture<Void> sendAsync(@NonNull EmailRequest request) {
        return CompletableFuture
                .runAsync(() -> send(request), executorService)
                .exceptionally(ex -> {
                    LOGGER.error("Async email dispatch failed", ex);
                    return null;
                });
    }

    /**
     * Converts an {@link EmailRequest} into a fully-populated {@link MimeMessage}.
     */
    private MimeMessage toMimeMessage(EmailRequest request) throws MessagingException {
        MimeMessage message = mailSender.createMimeMessage();
        boolean multipart = !request.attachments.isEmpty();
        MimeMessageHelper helper = new MimeMessageHelper(message, multipart, StandardCharsets.UTF_8.name());

        helper.setSubject(request.subject);
        helper.setFrom(request.from != null ? request.from : defaultFrom);
        helper.setTo(request.to);

        if (!request.cc.isEmpty()) helper.setCc(request.cc.toArray(String[]::new));
        if (!request.bcc.isEmpty()) helper.setBcc(request.bcc.toArray(String[]::new));

        // Render template
        String body = renderTemplate(request.templateName, request.model);
        boolean isHtml = request.contentType.equalsIgnoreCase("text/html");
        helper.setText(body, isHtml);

        // Add attachments
        for (Attachment attachment : request.attachments) {
            helper.addAttachment(
                    attachment.fileName,
                    attachment.data,
                    attachment.mimeType
            );
        }
        return message;
    }

    private String renderTemplate(@NonNull String templateName, Map<String, Object> model) {
        Context ctx = new Context();
        if (model != null) {
            model.forEach(ctx::setVariable);
        }
        return templateEngine.process(templateName, ctx);
    }

    private void validate(EmailRequest request) {
        if (request.to == null || request.to.isBlank()) {
            throw new IllegalArgumentException("Recipient (to) address must be provided");
        }
        if (request.subject == null || request.subject.isBlank()) {
            throw new IllegalArgumentException("Email subject must not be empty");
        }
        if (!SUPPORTED_CONTENT_TYPES.contains(request.contentType)) {
            throw new IllegalArgumentException("Unsupported content type: " + request.contentType);
        }
    }

    @PreDestroy
    public void shutdown() {
        executorService.shutdown();
    }

    /**
     * Fluent builder for {@link EmailRequest}.
     */
    public static Builder builder() {
        return new Builder();
    }

    // -----------------------------------------------------------------------
    // DTOs & Builder
    // -----------------------------------------------------------------------

    /**
     * Immutable value object representing an email to be sent.
     */
    public static final class EmailRequest {

        private final String from;
        private final String to;
        private final List<String> cc;
        private final List<String> bcc;
        private final String subject;
        private final String templateName;
        private final Map<String, Object> model;
        private final String contentType;
        private final List<Attachment> attachments;

        private EmailRequest(String from,
                             String to,
                             List<String> cc,
                             List<String> bcc,
                             String subject,
                             String templateName,
                             Map<String, Object> model,
                             String contentType,
                             List<Attachment> attachments) {
            this.from = from;
            this.to = to;
            this.cc = cc;
            this.bcc = bcc;
            this.subject = subject;
            this.templateName = templateName;
            this.model = model;
            this.contentType = contentType;
            this.attachments = attachments;
        }
    }

    /**
     * Attachment descriptor used for multipart emails.
     */
    public record Attachment(
            @NonNull String fileName,
            @NonNull InputStream data,
            @NonNull String mimeType) {
    }

    /**
     * Builder for {@link EmailRequest}. Thread-unsafe; do not reuse.
     */
    public static final class Builder {

        private String from;
        private String to;
        private List<String> cc = Collections.emptyList();
        private List<String> bcc = Collections.emptyList();
        private String subject;
        private String templateName;
        private Map<String, Object> model = Collections.emptyMap();
        private String contentType = "text/html";
        private List<Attachment> attachments = Collections.emptyList();

        private Builder() {}

        public Builder from(@Nullable String from) {
            this.from = from;
            return this;
        }

        public Builder to(@NonNull String to) {
            this.to = to;
            return this;
        }

        public Builder cc(@NonNull List<String> cc) {
            this.cc = List.copyOf(cc);
            return this;
        }

        public Builder bcc(@NonNull List<String> bcc) {
            this.bcc = List.copyOf(bcc);
            return this;
        }

        public Builder subject(@NonNull String subject) {
            this.subject = subject;
            return this;
        }

        public Builder template(@NonNull String templateName, @Nullable Map<String, Object> model) {
            this.templateName = templateName;
            if (model != null) {
                this.model = Map.copyOf(model);
            }
            return this;
        }

        public Builder contentType(@NonNull String contentType) {
            this.contentType = contentType;
            return this;
        }

        public Builder attachments(@NonNull List<Attachment> attachments) {
            this.attachments = List.copyOf(attachments);
            return this;
        }

        public EmailRequest build() {
            return new EmailRequest(
                    from,
                    to,
                    cc,
                    bcc,
                    subject,
                    templateName,
                    model,
                    contentType,
                    attachments
            );
        }
    }

    // -----------------------------------------------------------------------
    // Exception
    // -----------------------------------------------------------------------

    /**
     * Domain-specific exception for email-related failures.
     */
    public static class EmailSendingException extends RuntimeException {
        public EmailSendingException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}
```