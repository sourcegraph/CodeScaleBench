package com.commercesphere.enterprise.payment.service;

import com.commercesphere.enterprise.common.audit.AuditLogger;
import com.commercesphere.enterprise.common.exceptions.BusinessException;
import com.commercesphere.enterprise.common.exceptions.ErrorCode;
import com.commercesphere.enterprise.payment.domain.enums.PaymentIntent;
import com.commercesphere.enterprise.payment.domain.enums.PaymentProvider;
import com.commercesphere.enterprise.payment.domain.model.PaymentRequest;
import com.commercesphere.enterprise.payment.domain.model.PaymentResponse;
import com.commercesphere.enterprise.payment.gateway.PaymentGateway;
import com.commercesphere.enterprise.payment.gateway.PaymentGatewayRouter;
import com.commercesphere.enterprise.payment.persistence.PaymentTransaction;
import com.commercesphere.enterprise.payment.persistence.PaymentTransactionRepository;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.ConstraintViolationException;
import jakarta.validation.Validator;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.ReentrantLock;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.ConcurrencyFailureException;
import org.springframework.retry.RetryCallback;
import org.springframework.retry.RetryContext;
import org.springframework.retry.RetryListener;
import org.springframework.retry.support.RetryTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * PaymentOrchestrationService acts as the single entry-point for any component that needs
 * to execute a monetary operation (authorize, capture, refund, void) in the CommerceSphere
 * monolith.  It is intentionally agnostic of the underlying payment providers/gateways,
 * delegating provider-specific behavior to {@link PaymentGateway} implementations that are
 * resolved via {@link PaymentGatewayRouter}.
 *
 * <p>This class is designed to be thread-safe and re-entrant.  A lightweight
 * {@link ReentrantLock} is used to guard against double-spends on the same
 * transaction identifier when the DB isolation level alone is insufficient
 * (e.g., during async webhook callbacks).</p>
 */
@Service
public class PaymentOrchestrationService {

    private static final Logger LOG = LoggerFactory.getLogger(PaymentOrchestrationService.class);
    private static final String LOCK_UNAVAILABLE_ERR_MSG =
            "Unable to acquire lock for payment transaction [%s] after %d seconds";

    private final PaymentGatewayRouter gatewayRouter;
    private final PaymentTransactionRepository transactionRepository;
    private final AuditLogger auditLogger;
    private final Validator validator;
    private final RetryTemplate retryTemplate;

    // Simple JVM-level lock to guard against intra-process race conditions.
    private final ReentrantLock orchestrationLock = new ReentrantLock();

    public PaymentOrchestrationService(
            PaymentGatewayRouter gatewayRouter,
            PaymentTransactionRepository transactionRepository,
            AuditLogger auditLogger,
            Validator validator,
            RetryTemplate retryTemplate) {

        this.gatewayRouter = gatewayRouter;
        this.transactionRepository = transactionRepository;
        this.auditLogger = auditLogger;
        this.validator = validator;
        this.retryTemplate = customizeRetryTemplate(retryTemplate);
    }

    @Transactional
    public PaymentResponse authorize(PaymentRequest request) {
        validate(request);

        return retryTemplate.execute(context -> {
            acquireLock(request.getExternalOrderId());

            try {
                PaymentGateway gateway = gatewayRouter.route(request.getPaymentMethod());
                PaymentResponse response = gateway.authorize(request);

                persistTransaction(request, response, PaymentIntent.AUTHORIZE);

                return response;
            } finally {
                releaseLock();
            }
        });
    }

    @Transactional
    public PaymentResponse capture(UUID authorizationId, BigDecimal amount) {
        PaymentTransaction authTxn = transactionRepository
                .findByPublicIdAndIntent(authorizationId, PaymentIntent.AUTHORIZE)
                .orElseThrow(() -> new BusinessException(ErrorCode.PAYMENT_TRANSACTION_NOT_FOUND,
                        "Authorization not found: " + authorizationId));

        return retryTemplate.execute(context -> {
            acquireLock(authTxn.getExternalOrderId());

            try {
                PaymentGateway gateway = gatewayRouter.route(authTxn.getPaymentMethod());
                PaymentResponse response = gateway.capture(authTxn.getGatewayTransactionId(), amount);

                persistTransaction(authTxn, response, PaymentIntent.CAPTURE);

                return response;
            } finally {
                releaseLock();
            }
        });
    }

    @Transactional
    public PaymentResponse refund(UUID captureId, BigDecimal amount) {
        PaymentTransaction captureTxn = transactionRepository
                .findByPublicIdAndIntent(captureId, PaymentIntent.CAPTURE)
                .orElseThrow(() -> new BusinessException(ErrorCode.PAYMENT_TRANSACTION_NOT_FOUND,
                        "Capture not found: " + captureId));

        return retryTemplate.execute(context -> {
            acquireLock(captureTxn.getExternalOrderId());

            try {
                PaymentGateway gateway = gatewayRouter.route(captureTxn.getPaymentMethod());
                PaymentResponse response = gateway.refund(captureTxn.getGatewayTransactionId(), amount);

                persistTransaction(captureTxn, response, PaymentIntent.REFUND);

                return response;
            } finally {
                releaseLock();
            }
        });
    }

    @Transactional
    public void voidAuthorization(UUID authorizationId) {
        PaymentTransaction authTxn = transactionRepository
                .findByPublicIdAndIntent(authorizationId, PaymentIntent.AUTHORIZE)
                .orElseThrow(() -> new BusinessException(ErrorCode.PAYMENT_TRANSACTION_NOT_FOUND,
                        "Authorization not found: " + authorizationId));

        retryTemplate.execute(context -> {
            acquireLock(authTxn.getExternalOrderId());

            try {
                PaymentGateway gateway = gatewayRouter.route(authTxn.getPaymentMethod());
                gateway.voidAuthorization(authTxn.getGatewayTransactionId());

                persistTransaction(authTxn, null, PaymentIntent.VOID);
                return null;
            } finally {
                releaseLock();
            }
        });
    }

    /* ---------------------------------------------------------------------- */
    /* Internal helpers                                                       */
    /* ---------------------------------------------------------------------- */

    /**
     * Persists the result of a gateway call in the audit-grade transaction table.
     */
    private void persistTransaction(
            PaymentRequest originatingRequest,
            PaymentResponse response,
            PaymentIntent intent) {

        PaymentTransaction txn = PaymentTransaction.builder()
                .publicId(UUID.randomUUID())
                .externalOrderId(originatingRequest.getExternalOrderId())
                .intent(intent)
                .amount(originatingRequest.getAmount())
                .currency(originatingRequest.getCurrency())
                .paymentMethod(originatingRequest.getPaymentMethod())
                .paymentProvider(resolveProvider(originatingRequest.getPaymentMethod()))
                .status(response.getStatus())
                .gatewayTransactionId(response.getGatewayTransactionId())
                .processedAt(OffsetDateTime.now())
                .build();

        transactionRepository.save(txn);
        auditLogger.logPayment(txn);
    }

    /**
     * Persists a derivative transaction that is linked to a previous transaction
     * (e.g., capture -> authorization, refund -> capture).
     */
    private void persistTransaction(
            PaymentTransaction parent,
            PaymentResponse response,
            PaymentIntent intent) {

        PaymentTransaction txn = PaymentTransaction.builder()
                .publicId(UUID.randomUUID())
                .externalOrderId(parent.getExternalOrderId())
                .parent(parent)
                .intent(intent)
                .amount(response != null ? response.getAmount() : parent.getAmount())
                .currency(parent.getCurrency())
                .paymentMethod(parent.getPaymentMethod())
                .paymentProvider(parent.getPaymentProvider())
                .status(response != null ? response.getStatus() : "VOIDED")
                .gatewayTransactionId(response != null ? response.getGatewayTransactionId() : null)
                .processedAt(OffsetDateTime.now())
                .build();

        transactionRepository.save(txn);
        auditLogger.logPayment(txn);
    }

    private PaymentProvider resolveProvider(String paymentMethod) {
        return gatewayRouter.route(paymentMethod).getProvider();
    }

    private void validate(PaymentRequest request) {
        Set<ConstraintViolation<PaymentRequest>> violations = validator.validate(request);
        if (!violations.isEmpty()) {
            throw new ConstraintViolationException(violations);
        }
    }

    /* ---------------------------------------------------------------------- */
    /* Lock helpers                                                           */
    /* ---------------------------------------------------------------------- */

    private void acquireLock(String transactionKey) {
        try {
            boolean locked = orchestrationLock.tryLock(5, TimeUnit.SECONDS);
            if (!locked) {
                String msg = String.format(LOCK_UNAVAILABLE_ERR_MSG, transactionKey, 5);
                throw new ConcurrencyFailureException(msg);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ConcurrencyFailureException("Interrupted while waiting for lock", e);
        }
    }

    private void releaseLock() {
        if (orchestrationLock.isHeldByCurrentThread()) {
            orchestrationLock.unlock();
        }
    }

    /* ---------------------------------------------------------------------- */
    /* Retry helpers                                                          */
    /* ---------------------------------------------------------------------- */

    private RetryTemplate customizeRetryTemplate(RetryTemplate template) {
        template.registerListener(new RetryLoggingListener());
        return template;
    }

    private static class RetryLoggingListener implements RetryListener {

        @Override
        public <T, E extends Throwable> boolean open(RetryContext context, RetryCallback<T, E> callback) {
            // Do nothing
            return true;
        }

        @Override
        public <T, E extends Throwable> void close(RetryContext context, RetryCallback<T, E> callback, Throwable throwable) {
            // Do nothing
        }

        @Override
        public <T, E extends Throwable> void onError(RetryContext context,
                                                     RetryCallback<T, E> callback,
                                                     Throwable throwable) {

            LOG.warn("Attempt {}/{} failed for payment operation: {}",
                    context.getRetryCount(),
                    context.getRetryPolicy().getMaxAttempts(),
                    throwable.getMessage(), throwable);
        }
    }
}