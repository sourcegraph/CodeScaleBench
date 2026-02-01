package com.commercesphere.enterprise.notification.service;

import com.commercesphere.enterprise.audit.AuditTrailService;
import com.commercesphere.enterprise.audit.domain.AuditEntry;
import com.commercesphere.enterprise.common.i18n.LocaleResolver;
import com.commercesphere.enterprise.notification.domain.NotificationTemplate;
import com.commercesphere.enterprise.notification.gateway.NotificationGateway;
import com.commercesphere.enterprise.notification.repository.NotificationTemplateRepository;
import lombok.Builder;
import lombok.Data;
import lombok.NonNull;
import lombok.Value;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.i18n.LocaleContextHolder;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.thymeleaf.context.Context;
import org.thymeleaf.spring5.SpringTemplateEngine;

import java.time.Instant;
import java.util.*;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.stream.Collectors;

/**
 * NotificationService is responsible for rendering templates and dispatching
 * notifications across multiple channels (EMAIL, SMS, PUSH).
 *
 * <p>The service is intentionally stateless; any per-notification state is
 * contained in the NotificationRequest value object passed to each public
 * method.</p>
 */
@Service
@Slf4j
public class NotificationService {

    private final NotificationTemplateRepository templateRepository;
    private final NotificationGateway gateway;
    private final SpringTemplateEngine templateEngine;
    private final AuditTrailService auditTrail;
    private final Executor notificationExecutor;
    private final LocaleResolver localeResolver;

    @Autowired
    public NotificationService(
            NotificationTemplateRepository templateRepository,
            NotificationGateway gateway,
            SpringTemplateEngine templateEngine,
            AuditTrailService auditTrail,
            LocaleResolver localeResolver,
            @Qualifier("notificationExecutor") Executor notificationExecutor) {
        this.templateRepository = Objects.requireNonNull(templateRepository);
        this.gateway = Objects.requireNonNull(gateway);
        this.templateEngine = Objects.requireNonNull(templateEngine);
        this.auditTrail = Objects.requireNonNull(auditTrail);
        this.localeResolver = Objects.requireNonNull(localeResolver);
        this.notificationExecutor = Objects.requireNonNull(notificationExecutor);
    }

    /**
     * Synchronously dispatches a notification.
     *
     * @param request Notification details.
     * @return NotificationReceipt containing dispatch metadata.
     * @throws NotificationDispatchException if one or more channels fail.
     */
    public NotificationReceipt sendNotification(@NonNull NotificationRequest request)
            throws NotificationDispatchException {
        Objects.requireNonNull(request, "request must not be null");

        Locale locale = resolveLocale(request);
        NotificationTemplate template = resolveTemplate(request, locale);

        Map<NotificationChannel, DispatchStatus> statusByChannel = new EnumMap<>(NotificationChannel.class);
        for (NotificationChannel channel : request.getChannels()) {
            try {
                switch (channel) {
                    case EMAIL:
                        gateway.dispatchEmail(
                                request.getRecipients(),
                                renderTemplate(template.getSubjectTemplate(), request.getVariables(), locale),
                                renderTemplate(template.getBodyTemplate(), request.getVariables(), locale));
                        break;
                    case SMS:
                        gateway.dispatchSms(
                                request.getRecipients(),
                                renderTemplate(template.getBodyTemplate(), request.getVariables(), locale));
                        break;
                    case PUSH:
                        gateway.dispatchPush(
                                request.getRecipients(),
                                renderTemplate(template.getSubjectTemplate(), request.getVariables(), locale),
                                renderTemplate(template.getBodyTemplate(), request.getVariables(), locale));
                        break;
                    default:
                        throw new IllegalStateException("Unsupported channel " + channel);
                }
                statusByChannel.put(channel, DispatchStatus.SUCCESS);
            } catch (Exception ex) {
                log.warn("Dispatch failed on channel {} for template {}: {}",
                        channel, request.getTemplateType(), ex.getMessage(), ex);
                statusByChannel.put(channel, DispatchStatus.FAILURE);
            }
        }

        NotificationReceipt receipt = NotificationReceipt.builder()
                .templateType(request.getTemplateType())
                .timestamp(Instant.now())
                .statusByChannel(Collections.unmodifiableMap(statusByChannel))
                .build();

        persistAuditTrail(request, receipt);

        if (statusByChannel.containsValue(DispatchStatus.FAILURE)) {
            throw new NotificationDispatchException(
                    "One or more channels failed while dispatching notification: " + statusByChannel);
        }
        return receipt;
    }

    /**
     * Asynchronously dispatches a notification.
     *
     * @param request Notification details.
     * @return CompletableFuture that completes with the NotificationReceipt or exceptionally.
     */
    @Async("notificationExecutor")
    public CompletableFuture<NotificationReceipt> sendNotificationAsync(@NonNull NotificationRequest request) {
        return CompletableFuture.supplyAsync(() -> {
            try {
                return sendNotification(request);
            } catch (NotificationDispatchException ex) {
                throw new NotificationDispatchRuntimeException(ex);
            }
        }, notificationExecutor);
    }

    /* --------------------------------------------------------------------- */
    /* ------------------------  PRIVATE HELPERS  -------------------------- */
    /* --------------------------------------------------------------------- */

    private String renderTemplate(String templateBody, Map<String, Object> variables, Locale locale) {
        Context context = new Context(locale);
        if (variables != null) {
            context.setVariables(variables);
        }
        return templateEngine.process(templateBody, context);
    }

    private NotificationTemplate resolveTemplate(NotificationRequest request, Locale locale) {
        return templateRepository
                .findByTypeAndLocale(request.getTemplateType(), locale)
                .orElseThrow(() -> new UnknownTemplateException(
                        String.format("No template found for type=%s, locale=%s",
                                request.getTemplateType(), locale)));
    }

    private Locale resolveLocale(NotificationRequest request) {
        if (request.getPreferredLocale() != null) {
            return request.getPreferredLocale();
        }
        return localeResolver.resolveOrDefault(LocaleContextHolder.getLocale());
    }

    private void persistAuditTrail(NotificationRequest request, NotificationReceipt receipt) {
        AuditEntry entry = AuditEntry.builder()
                .action("NOTIFICATION_DISPATCH")
                .actor(request.getActor())
                .resourceId(request.getTemplateType().name())
                .details(Map.of(
                        "recipients", request.getRecipients(),
                        "channels", request.getChannels().stream()
                                .map(Enum::name)
                                .collect(Collectors.toList()),
                        "statusByChannel", receipt.getStatusByChannel()
                ))
                .timestamp(receipt.getTimestamp())
                .build();
        auditTrail.record(entry);
    }

    /* --------------------------------------------------------------------- */
    /* ----------------------  VALUE & ENUM  OBJECTS  ---------------------- */
    /* --------------------------------------------------------------------- */

    /**
     * A request to dispatch a notification.
     */
    @Data
    @Builder(toBuilder = true)
    public static class NotificationRequest {
        @NonNull
        private final TemplateType templateType;
        @Builder.Default
        private final Set<NotificationChannel> channels =
                EnumSet.noneOf(NotificationChannel.class);
        @Builder.Default
        private final Set<String> recipients = Collections.emptySet();
        @Builder.Default
        private final Map<String, Object> variables = Collections.emptyMap();
        private final Locale preferredLocale;
        @Builder.Default
        private final String actor = "SYSTEM"; // Service or user responsible for invocation
    }

    /**
     * Dispatch result wrapper.
     */
    @Value
    @Builder
    public static class NotificationReceipt {
        @NonNull
        private TemplateType templateType;
        @NonNull
        private Instant timestamp;
        @NonNull
        private Map<NotificationChannel, DispatchStatus> statusByChannel;
    }

    /**
     * Logical channel enumeration.
     */
    public enum NotificationChannel {
        EMAIL,
        SMS,
        PUSH
    }

    /**
     * Template enumeration—could also be persisted in DB for richer criteria.
     */
    public enum TemplateType {
        ORDER_CONFIRMATION,
        ORDER_SHIPPED,
        PASSWORD_RESET,
        INVOICE_AVAILABLE
    }

    /**
     * Execution status per channel.
     */
    public enum DispatchStatus {
        SUCCESS,
        FAILURE
    }

    /* --------------------------------------------------------------------- */
    /* -----------------------  CUSTOM EXCEPTIONS  ------------------------- */
    /* --------------------------------------------------------------------- */

    public static class NotificationDispatchException extends Exception {
        public NotificationDispatchException(String message) {
            super(message);
        }

        public NotificationDispatchException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    /**
     * Runtime wrapper for async dispatch.
     */
    public static class NotificationDispatchRuntimeException extends RuntimeException {
        public NotificationDispatchRuntimeException(Throwable cause) {
            super(cause);
        }
    }

    public static class UnknownTemplateException extends RuntimeException {
        public UnknownTemplateException(String message) {
            super(message);
        }
    }
}