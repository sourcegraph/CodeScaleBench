package com.commercesphere.enterprise.notification.template;

import java.time.format.DateTimeFormatter;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.thymeleaf.TemplateEngine;
import org.thymeleaf.context.Context;

import com.commercesphere.enterprise.common.i18n.MessageBundle;
import com.commercesphere.enterprise.domain.order.CustomerAccount;
import com.commercesphere.enterprise.domain.order.SalesOrder;
import com.commercesphere.enterprise.notification.MailMessage;
import com.commercesphere.enterprise.notification.TemplateRenderingException;

/**
 * Production–ready e-mail template for confirming customer orders.
 *
 * <p>This class delegates all rendering to a {@link TemplateEngine} implementation
 * (e.g. Thymeleaf). The template engine instance is injected through the constructor
 * to keep the class testable and to avoid hard references to a particular engine.</p>
 *
 * <p>The template supports both HTML and plain-text bodies. Internationalization
 * relies on {@link MessageBundle}, which resolves keys against UTF-8 properties
 * files stored on classpath under {@code /i18n}.</p>
 *
 * <p>Expected template resource paths:
 * <ul>
 *   <li>{@code /templates/email/order-confirmation.html}</li>
 *   <li>{@code /templates/email/order-confirmation.txt}</li>
 * </ul>
 *
 * The subject line is also localized.</p>
 */
public final class OrderConfirmationEmail {

    private static final Logger LOGGER = LoggerFactory.getLogger(OrderConfirmationEmail.class);

    private static final String HTML_TEMPLATE_PATH = "email/order-confirmation.html";
    private static final String TEXT_TEMPLATE_PATH = "email/order-confirmation.txt";

    private static final DateTimeFormatter DATE_FMT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm");

    private final TemplateEngine templateEngine;
    private final MessageBundle messageBundle;

    /**
     * Constructs the template with the required collaborators.
     *
     * @param templateEngine the template engine used for rendering
     * @param messageBundle  message bundle for i18n
     */
    public OrderConfirmationEmail(final TemplateEngine templateEngine,
                                  final MessageBundle messageBundle) {
        this.templateEngine = Objects.requireNonNull(templateEngine, "templateEngine must not be null");
        this.messageBundle = Objects.requireNonNull(messageBundle, "messageBundle must not be null");
    }

    /**
     * Renders the final {@link MailMessage} to be sent to the customer.
     *
     * @param ctx contextual model values
     * @return a fully rendered mail message
     * @throws TemplateRenderingException if rendering fails for any reason
     */
    public MailMessage render(final OrderConfirmationContext ctx) {
        Objects.requireNonNull(ctx, "ctx must not be null");

        try {
            final Locale locale = ctx.getPreferredLocale();
            final String subject = renderSubject(ctx, locale);
            final String htmlBody = renderBody(ctx, locale, HTML_TEMPLATE_PATH);
            final String txtBody = renderBody(ctx, locale, TEXT_TEMPLATE_PATH);

            return MailMessage.builder()
                    .to(ctx.getRecipientEmail())
                    .subject(subject)
                    .htmlBody(htmlBody)
                    .textBody(txtBody)
                    .build();

        } catch (Exception ex) {
            LOGGER.error("Failed to render order-confirmation e-mail for order {}",
                    ctx.getOrder().getOrderNumber(), ex);
            throw new TemplateRenderingException("Unable to render order confirmation email", ex);
        }
    }

    /* ----------------------------- Internal Helpers ----------------------------- */

    private String renderSubject(final OrderConfirmationContext ctx, final Locale locale) {
        return messageBundle.get(
                "email.order.confirmation.subject",
                locale,
                ctx.getOrder().getOrderNumber());
    }

    private String renderBody(final OrderConfirmationContext ctx,
                              final Locale locale,
                              final String templatePath) {

        final Context thymeleafCtx = new Context(locale);
        thymeleafCtx.setVariables(createTemplateModel(ctx));

        return templateEngine.process(templatePath, thymeleafCtx);
    }

    private Map<String, Object> createTemplateModel(final OrderConfirmationContext ctx) {
        final SalesOrder order = ctx.getOrder();
        final CustomerAccount customer = order.getCustomerAccount();

        return Map.of(
                "order", order,
                "customer", customer,
                "submittedAt", DATE_FMT.format(order.getSubmittedAt()),
                "billingAddress", customer.getBillingAddress(),
                "shippingAddress", order.getShippingAddress(),
                "orderLines", order.getOrderLines(),
                "invoiceTotal", order.getInvoiceTotalPrice(),
                "currency", order.getCurrency(),
                "supportEmail", ctx.getSupportEmail()
        );
    }

    /* ----------------------------- Public DTO ----------------------------- */

    /**
     * Aggregates all data required to generate an order-confirmation e-mail.
     */
    public static final class OrderConfirmationContext {

        private final SalesOrder order;
        private final Locale preferredLocale;
        private final String supportEmail;

        public OrderConfirmationContext(final SalesOrder order,
                                        final Locale preferredLocale,
                                        final String supportEmail) {
            this.order = Objects.requireNonNull(order, "order must not be null");
            this.preferredLocale = Objects.requireNonNullElse(preferredLocale, Locale.ENGLISH);
            this.supportEmail = Objects.requireNonNull(supportEmail, "supportEmail must not be null");
        }

        public SalesOrder getOrder() {
            return order;
        }

        public Locale getPreferredLocale() {
            return preferredLocale;
        }

        public String getRecipientEmail() {
            return order.getCustomerAccount().getPrimaryContact().getEmail();
        }

        public String getSupportEmail() {
            return supportEmail;
        }
    }
}