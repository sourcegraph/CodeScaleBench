package com.sprintcart.adapters.notification.sendgrid;

import com.sendgrid.Attachments;
import com.sendgrid.Content;
import com.sendgrid.Email;
import com.sendgrid.Mail;
import com.sendgrid.Method;
import com.sendgrid.Personalization;
import com.sendgrid.Request;
import com.sendgrid.Response;
import com.sendgrid.SendGrid;
import com.sprintcart.domain.notification.EmailSenderPort;
import com.sprintcart.domain.notification.exception.NotificationException;
import com.sprintcart.domain.notification.model.EmailAttachment;
import com.sprintcart.domain.notification.model.EmailMessage;
import com.sprintcart.domain.notification.model.EmailRecipient;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.DisposableBean;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.util.Assert;
import org.springframework.util.CollectionUtils;

/**
 * Outbound adapter that sends e-mails through SendGrid.
 *
 * <p>The adapter is intentionally unaware of any web, persistence, or
 * framework specifics other than the SendGrid Java SDK. It translates the
 * domain‐level {@link EmailMessage} into a concrete SendGrid API call.
 *
 * <p>All blocking IO is executed on a dedicated thread pool to avoid pinning
 * Spring’s request processing threads while waiting for SendGrid’s response.
 */
@Slf4j
@Component
@RequiredArgsConstructor
@SuppressWarnings("Duplicates")
public class SendGridEmailAdapter implements EmailSenderPort, DisposableBean {

    private static final int HTTP_STATUS_ACCEPTED = 202;

    private final SendGrid sendGrid;

    /**
     * Default “from” address configured via Spring properties (application.yml/env).
     */
    private final String defaultSender;

    /**
     * Dedicated pool for outbound network calls. This prevents uncontrolled thread
     * creation if the application fires a high volume of e-mails concurrently.
     */
    private final ExecutorService ioPool = Executors.newFixedThreadPool(
            Math.max(Runtime.getRuntime().availableProcessors() / 2, 2),
            r -> {
                Thread t = new Thread(r, "sendgrid-io");
                t.setDaemon(true);
                return t;
            });

    public SendGridEmailAdapter(
            @Value("${sprintcart.notification.sendgrid.apikey}") final String apiKey,
            @Value("${sprintcart.notification.sendgrid.sender}") final String defaultSender) {
        this.sendGrid = new SendGrid(Objects.requireNonNull(apiKey, "SendGrid API Key must not be null"));
        this.defaultSender = Objects.requireNonNull(defaultSender, "Default sender must not be null");
    }

    /**
     * Sends an e-mail synchronously and returns only when SendGrid has
     * acknowledged the request. The operation is wrapped in an internal
     * {@link CompletableFuture} so that upstream code can call it without
     * blocking the calling thread.
     */
    @Override
    public CompletableFuture<Void> sendEmail(final EmailMessage message) {
        Assert.notNull(message, "EmailMessage must not be null");

        return CompletableFuture
                .supplyAsync(() -> buildRequest(message), ioPool)
                .thenComposeAsync(this::executeRequest, ioPool)
                .exceptionally(this::translateException);
    }

    /* ---------- Private helper methods ---------- */

    private Request buildRequest(final EmailMessage message) {
        if (CollectionUtils.isEmpty(message.getTo())) {
            throw new IllegalArgumentException("Email must have at least one recipient");
        }

        final Mail mail = new Mail();
        mail.setFrom(toSendGridEmail(
                message.getFrom() != null ? message.getFrom()
                        : new EmailRecipient(defaultSender, null)));
        mail.setSubject(message.getSubject());

        final Personalization personalization = new Personalization();
        addRecipients(personalization::addTo, message.getTo());
        addRecipients(personalization::addCc, message.getCc());
        addRecipients(personalization::addBcc, message.getBcc());
        mail.addPersonalization(personalization);

        final String mimeType = message.isHtml() ? "text/html" : "text/plain";
        mail.addContent(new Content(mimeType, message.getBody()));

        addAttachments(mail, message.getAttachments());

        final Request req = new Request();
        req.setMethod(Method.POST);
        req.setEndpoint("mail/send");
        try {
            req.setBody(mail.build());
        } catch (IOException e) {
            // Should never happen because Mail#build only throws IO on StringWriter
            throw new IllegalStateException("Unable to build SendGrid mail object", e);
        }

        return req;
    }

    private CompletableFuture<Void> executeRequest(final Request req) {
        return CompletableFuture.runAsync(() -> {
            try {
                final Response res = sendGrid.api(req);
                if (res.getStatusCode() != HTTP_STATUS_ACCEPTED) {
                    throw new NotificationException("Unexpected SendGrid response: "
                            + res.getStatusCode() + " – " + res.getBody());
                }
                log.debug("Email accepted by SendGrid: {}", res.getHeaders());
            } catch (IOException ex) {
                throw new NotificationException("I/O error while calling SendGrid", ex);
            }
        }, ioPool);
    }

    private Void translateException(final Throwable throwable) {
        if (throwable instanceof NotificationException) {
            throw (NotificationException) throwable;
        }
        throw new NotificationException("Unexpected error while sending email", throwable);
    }

    private void addRecipients(
            final java.util.function.Consumer<Email> consumer,
            final List<EmailRecipient> recipients) {
        if (CollectionUtils.isEmpty(recipients)) {
            return;
        }
        recipients.stream()
                .map(this::toSendGridEmail)
                .forEach(consumer);
    }

    private Email toSendGridEmail(final EmailRecipient recipient) {
        return new Email(recipient.getAddress(), recipient.getName());
    }

    private void addAttachments(final Mail mail, final List<EmailAttachment> attachments) {
        if (CollectionUtils.isEmpty(attachments)) {
            return;
        }
        for (EmailAttachment att : attachments) {
            try {
                final Attachments sgAtt = new Attachments();
                sgAtt.setFilename(att.getFilename());
                sgAtt.setType(att.getMimeType());
                sgAtt.setDisposition("attachment");
                sgAtt.setContent(Base64.getEncoder()
                        .encodeToString(att.getBytes()));
                mail.addAttachments(sgAtt);
            } catch (Exception ex) {
                log.warn("Skipping attachment [{}] due to error: {}", att.getFilename(), ex.getMessage());
            }
        }
    }

    /* ---------- Bean lifecycle ---------- */

    @Override
    public void destroy() {
        ioPool.shutdown();
    }
}