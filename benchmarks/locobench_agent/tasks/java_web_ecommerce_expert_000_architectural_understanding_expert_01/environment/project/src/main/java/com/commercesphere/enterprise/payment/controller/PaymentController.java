package com.commercesphere.enterprise.payment.controller;

import com.commercesphere.enterprise.common.logging.CorrelationIdHolder;
import com.commercesphere.enterprise.payment.dto.PaymentConfirmationRequest;
import com.commercesphere.enterprise.payment.dto.PaymentRequest;
import com.commercesphere.enterprise.payment.dto.PaymentResponse;
import com.commercesphere.enterprise.payment.dto.RefundRequest;
import com.commercesphere.enterprise.payment.exception.PaymentNotFoundException;
import com.commercesphere.enterprise.payment.service.PaymentService;
import jakarta.validation.Valid;
import java.net.URI;
import java.security.Principal;
import java.time.OffsetDateTime;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * REST controller responsible for exposing payment–related endpoints.
 *
 * <p>Endpoints are secured via Spring Security and expect an authenticated
 * {@code Principal}.  Each incoming request is tagged with a correlation-ID
 * enabling distributed tracing throughout the monolith as well as in external
 * systems such as the PSP (Payment Service Provider).</p>
 *
 * <p>Any business exceptions thrown from the service layer are converted into
 * meaningful HTTP responses.</p>
 */
@Slf4j
@Validated
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/v1/payments")
public class PaymentController {

    private static final String CORRELATION_ID_HEADER = "X-Correlation-Id";

    private final PaymentService paymentService;

    /* -------------------------------------------------------------------- */
    /*                                CREATE                                */
    /* -------------------------------------------------------------------- */

    /**
     * Initiates a new payment transaction.
     *
     * @param principal  the authenticated user
     * @param request    payment metadata such as amount, currency, and order-id
     * @param headerCorr optional correlation-ID supplied by the caller
     * @return a {@link ResponseEntity} holding a {@link PaymentResponse}
     */
    @PostMapping
    public ResponseEntity<PaymentResponse> createPayment(
            Principal principal,
            @Valid PaymentRequest request,
            @RequestHeader(value = CORRELATION_ID_HEADER, required = false)
            String headerCorr) {

        String correlationId = obtainCorrelationId(headerCorr);
        log.info("Creating payment for user={} correlationId={}", principal.getName(), correlationId);

        PaymentResponse response = paymentService.createPayment(principal.getName(), request, correlationId);

        return ResponseEntity
                .created(URI.create("/api/v1/payments/" + response.id()))
                .header(CORRELATION_ID_HEADER, correlationId)
                .body(response);
    }

    /* -------------------------------------------------------------------- */
    /*                                 READ                                 */
    /* -------------------------------------------------------------------- */

    /**
     * Retrieves the payment resource for the given identifier.
     *
     * @param principal the authenticated user
     * @param paymentId the payment identifier
     * @return the payment resource
     */
    @GetMapping("/{paymentId}")
    public ResponseEntity<PaymentResponse> getPayment(
            Principal principal,
            @PathVariable UUID paymentId,
            @RequestHeader(value = CORRELATION_ID_HEADER, required = false)
            String headerCorr) {

        String correlationId = obtainCorrelationId(headerCorr);
        log.debug("Fetching payment={} for user={} correlationId={}",
                  paymentId, principal.getName(), correlationId);

        PaymentResponse response = paymentService.getPayment(principal.getName(), paymentId, correlationId);

        return ResponseEntity.ok()
                .header(CORRELATION_ID_HEADER, correlationId)
                .body(response);
    }

    /* -------------------------------------------------------------------- */
    /*                               CONFIRM                                */
    /* -------------------------------------------------------------------- */

    /**
     * Confirms (captures) a previously authorized payment.
     *
     * @param principal the authenticated user
     * @param paymentId the payment identifier
     * @param request   confirmation payload (e.g., 3-D Secure result)
     * @return updated payment resource
     */
    @PostMapping("/{paymentId}/confirm")
    public ResponseEntity<PaymentResponse> confirmPayment(
            Principal principal,
            @PathVariable UUID paymentId,
            @Valid PaymentConfirmationRequest request,
            @RequestHeader(value = CORRELATION_ID_HEADER, required = false)
            String headerCorr) {

        String correlationId = obtainCorrelationId(headerCorr);
        log.info("Confirming payment={} user={} correlationId={}",
                 paymentId, principal.getName(), correlationId);

        PaymentResponse response = paymentService.confirmPayment(principal.getName(),
                                                                 paymentId,
                                                                 request,
                                                                 correlationId);
        return ResponseEntity.ok()
                .header(CORRELATION_ID_HEADER, correlationId)
                .body(response);
    }

    /* -------------------------------------------------------------------- */
    /*                                REFUND                                */
    /* -------------------------------------------------------------------- */

    /**
     * Issues a refund for a settled payment.
     *
     * @param principal the authenticated user
     * @param paymentId the payment identifier
     * @param request   refund details such as amount and reason
     * @return updated payment resource
     */
    @DeleteMapping("/{paymentId}/refund")
    public ResponseEntity<PaymentResponse> refundPayment(
            Principal principal,
            @PathVariable UUID paymentId,
            @Valid RefundRequest request,
            @RequestHeader(value = CORRELATION_ID_HEADER, required = false)
            String headerCorr) {

        String correlationId = obtainCorrelationId(headerCorr);
        log.warn("Refund requested payment={} user={} correlationId={} reason={}",
                 paymentId, principal.getName(), correlationId, request.reason());

        PaymentResponse response = paymentService.refundPayment(principal.getName(),
                                                                paymentId,
                                                                request,
                                                                correlationId);

        return ResponseEntity.status(HttpStatus.ACCEPTED)
                .header(CORRELATION_ID_HEADER, correlationId)
                .body(response);
    }

    /* -------------------------------------------------------------------- */
    /*                           GLOBAL HANDLERS                            */
    /* -------------------------------------------------------------------- */

    @ExceptionHandler(PaymentNotFoundException.class)
    public ResponseEntity<String> handlePaymentNotFound(
            PaymentNotFoundException ex,
            @RequestHeader(value = CORRELATION_ID_HEADER, required = false)
            String headerCorr) {

        String correlationId = obtainCorrelationId(headerCorr);
        log.error("Payment not found: {} correlationId={}", ex.getMessage(), correlationId);

        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .header(CORRELATION_ID_HEADER, correlationId)
                .body("Payment not found: " + ex.getMessage());
    }

    /* -------------------------------------------------------------------- */
    /*                              Utilities                               */
    /* -------------------------------------------------------------------- */

    /**
     * Returns an existing correlation-ID or generates a fresh UUID.
     */
    private String obtainCorrelationId(String headerCorr) {
        String corrId = headerCorr != null && !headerCorr.isBlank()
                ? headerCorr
                : UUID.randomUUID().toString();

        // Store in thread-local so that lower layers (repositories, HTTP clients)
        // can automatically enrich their log statements.
        CorrelationIdHolder.setCurrentId(corrId);
        return corrId;
    }

    /**
     * Ensures the correlation-ID is cleared once the request is completed.
     */
    @SuppressWarnings("unused") // invoked by Spring via reflection
    private void finalize() {
        // This acts as a safety-net in case the servlet container does not
        // invoke the registered filter’s after-completion hook.
        CorrelationIdHolder.clear();
    }

    /* -------------------------------------------------------------------- */
    /*                          Health Probe Only                           */
    /* -------------------------------------------------------------------- */

    /**
     * Lightweight liveness probe that does NOT hit the database.
     */
    @GetMapping("/health/live")
    public ResponseEntity<String> live() {
        return ResponseEntity.ok("OK " + OffsetDateTime.now());
    }
}