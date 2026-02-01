```java
package com.commercesphere.enterprisesuite;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.util.Assert;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestClientException;

import javax.validation.Valid;
import javax.validation.constraints.DecimalMin;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Currency;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Entry point for the CommerceSphere Enterprise Suite monolith.
 *
 * <p>This single deployable artifact hosts the MVC layer, REST API, service layer, and repository
 * components—running in the same JVM for reduced latency and simpler operational maintenance.</p>
 *
 * <p>For brevity, this file includes multiple package-private classes to demonstrate a cohesive,
 * production-ready subset of the payment-processing domain slice.</p>
 */
@SpringBootApplication
public class CommerceSphereEnterpriseSuiteApplication {

    private static final Logger log = LoggerFactory.getLogger(CommerceSphereEnterpriseSuiteApplication.class);

    public static void main(String[] args) {
        SpringApplication.run(CommerceSphereEnterpriseSuiteApplication.class, args);
        log.info("CommerceSphere Enterprise Suite started at {}", Instant.now());
    }

    /* ====================================================================== */
    /* ========================   BEAN DEFINITIONS   ======================== */
    /* ====================================================================== */

    @Bean
    public PaymentOrchestratorService paymentOrchestratorService(Map<String, PaymentGatewayClient> gatewayClients) {
        return new PaymentOrchestratorService(gatewayClients);
    }

    @Bean("stripeGatewayClient")
    public PaymentGatewayClient stripeGatewayClient() {
        // In real life we would inject Stripe configuration (API keys, timeouts) from an external vault.
        return new StripeGatewayClient("https://api.stripe.com/v1/charges", System.getenv("STRIPE_API_KEY"));
    }

    @Bean("paypalGatewayClient")
    public PaymentGatewayClient paypalGatewayClient() {
        return new PaypalGatewayClient("https://api.paypal.com/v2/payments", System.getenv("PAYPAL_BEARER_TOKEN"));
    }
}

/* ====================================================================== */
/* ==========================   CONTROLLER   ============================ */
/* ====================================================================== */

/**
 * REST adapter responsible for payment-related endpoints.
 */
@RestController
@RequestMapping("/api/v1/payments")
@Validated
class PaymentController {

    private final PaymentOrchestratorService orchestrator;

    PaymentController(PaymentOrchestratorService orchestrator) {
        this.orchestrator = orchestrator;
    }

    @PostMapping
    public ResponseEntity<PaymentResponse> charge(@Valid @RequestBody PaymentRequest request) throws PaymentException {
        PaymentReceipt receipt = orchestrator.processPayment(request);
        return ResponseEntity.status(HttpStatus.CREATED)
                             .body(new PaymentResponse(receipt));
    }

    /**
     * Graceful degradation & translation of internal exceptions to JSON payloads understood by the client.
     */
    @ExceptionHandler(PaymentException.class)
    public ResponseEntity<ErrorEnvelope> handlePaymentException(PaymentException ex) {
        ErrorEnvelope envelope = new ErrorEnvelope(
                "PAYMENT_PROCESSING_FAILURE",
                ex.getMessage(),
                Instant.now());
        return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(envelope);
    }
}

/* ====================================================================== */
/* ======================   SERVICE IMPLEMENTATION   ==================== */
/* ====================================================================== */

/**
 * Orchestrates multi-gateway payments while delegating gateway-specific details to
 * {@link PaymentGatewayClient} implementations.
 */
class PaymentOrchestratorService {

    private static final Logger log = LoggerFactory.getLogger(PaymentOrchestratorService.class);

    private final Map<String, PaymentGatewayClient> gatewayClients;

    PaymentOrchestratorService(Map<String, PaymentGatewayClient> gatewayClients) {
        // Defensive copy to avoid accidental modification from external code.
        this.gatewayClients = new ConcurrentHashMap<>(gatewayClients);
    }

    /**
     * Processes a {@link PaymentRequest} through the preferred gateway, providing robust exception handling.
     */
    public PaymentReceipt processPayment(PaymentRequest request) throws PaymentException {
        Assert.notNull(request, "PaymentRequest must not be null");

        String gatewayKey = resolveGatewayKey(request.getCurrency());
        PaymentGatewayClient client = Optional.ofNullable(gatewayClients.get(gatewayKey))
                                              .orElseThrow(() -> new PaymentException(
                                                      "No payment gateway configured for key: " + gatewayKey));

        log.info("Routing payment of {} {} to gateway [{}]", request.getAmount(), request.getCurrency(), gatewayKey);

        return client.charge(request);
    }

    /**
     * Very naive strategy: Stripe for USD/EUR, PayPal for everything else. Replace with a dynamic strategy pattern.
     */
    private String resolveGatewayKey(Currency currency) {
        return ("USD".equals(currency.getCurrencyCode()) || "EUR".equals(currency.getCurrencyCode()))
                ? "stripeGatewayClient"
                : "paypalGatewayClient";
    }
}

/* ====================================================================== */
/* ========================   GATEWAY CLIENTS   ========================= */
/* ====================================================================== */

/**
 * Common contract for payment gateway integration.
 */
interface PaymentGatewayClient {

    /**
     * Executes a charge operation on the upstream payment provider.
     *
     * @return an immutable business-layer receipt
     * @throws PaymentException if the provider rejected the payment or communication failed
     */
    PaymentReceipt charge(PaymentRequest request) throws PaymentException;
}

/**
 * Stripe-backed implementation. Demonstrates a robust retry & error-mapping skeleton.
 */
class StripeGatewayClient implements PaymentGatewayClient {

    private static final Logger log = LoggerFactory.getLogger(StripeGatewayClient.class);

    private final String endpoint;
    private final String apiKey;

    StripeGatewayClient(String endpoint, String apiKey) {
        this.endpoint = endpoint;
        this.apiKey = apiKey;
    }

    @Override
    public PaymentReceipt charge(PaymentRequest request) throws PaymentException {
        try {
            // In lieu of an actual HTTP call, we mimic a successful response.
            log.debug("Calling Stripe [{}] with request: {}", endpoint, request);
            // TODO: Use WebClient/RestTemplate inside a RetryTemplate with circuit-breaker.
            return PaymentReceipt.successful(request.getExternalOrderId(),
                                             "STRIPE-" + System.nanoTime(),
                                             request.getAmount(),
                                             request.getCurrency());
        } catch (RestClientException ex) {
            throw new PaymentException("Stripe communication failure", ex);
        }
    }
}

/**
 * PayPal-backed implementation. Showcases independent configuration.
 */
class PaypalGatewayClient implements PaymentGatewayClient {

    private static final Logger log = LoggerFactory.getLogger(PaypalGatewayClient.class);

    private final String endpoint;
    private final String bearerToken;

    PaypalGatewayClient(String endpoint, String bearerToken) {
        this.endpoint = endpoint;
        this.bearerToken = bearerToken;
    }

    @Override
    public PaymentReceipt charge(PaymentRequest request) throws PaymentException {
        try {
            log.debug("Calling PayPal [{}] with request: {}", endpoint, request);
            // TODO: Real HTTP interaction using OAuth2 token injection.
            return PaymentReceipt.successful(request.getExternalOrderId(),
                                             "PAYPAL-" + System.nanoTime(),
                                             request.getAmount(),
                                             request.getCurrency());
        } catch (RestClientException ex) {
            throw new PaymentException("PayPal communication failure", ex);
        }
    }
}

/* ====================================================================== */
/* ============================   DTOs   ================================ */
/* ====================================================================== */

class PaymentRequest {

    @NotBlank
    private String externalOrderId;

    @NotNull
    @DecimalMin("0.01")
    private BigDecimal amount;

    @NotNull
    private Currency currency;

    @NotBlank
    private String accountId; // Could be a B2B contract sub-account

    /* Default constructor for JSON binding */
    PaymentRequest() {
    }

    public PaymentRequest(String externalOrderId,
                          BigDecimal amount,
                          Currency currency,
                          String accountId) {
        this.externalOrderId = externalOrderId;
        this.amount = amount;
        this.currency = currency;
        this.accountId = accountId;
    }

    public String getExternalOrderId() {
        return externalOrderId;
    }

    public BigDecimal getAmount() {
        return amount;
    }

    public Currency getCurrency() {
        return currency;
    }

    public String getAccountId() {
        return accountId;
    }

    @Override
    public String toString() {
        return "PaymentRequest{" +
               "externalOrderId='" + externalOrderId + '\'' +
               ", amount=" + amount +
               ", currency=" + currency +
               ", accountId='" + accountId + '\'' +
               '}';
    }
}

class PaymentResponse {

    private final PaymentReceipt receipt;

    PaymentResponse(PaymentReceipt receipt) {
        this.receipt = receipt;
    }

    public PaymentReceipt getReceipt() {
        return receipt;
    }
}

/**
 * Immutable result returned back to clients after successful processing.
 */
class PaymentReceipt {

    private final String externalOrderId;
    private final String transactionId;
    private final BigDecimal amount;
    private final Currency currency;
    private final Instant processedAt;

    private PaymentReceipt(String externalOrderId,
                           String transactionId,
                           BigDecimal amount,
                           Currency currency,
                           Instant processedAt) {
        this.externalOrderId = externalOrderId;
        this.transactionId = transactionId;
        this.amount = amount;
        this.currency = currency;
        this.processedAt = processedAt;
    }

    static PaymentReceipt successful(String externalOrderId,
                                     String transactionId,
                                     BigDecimal amount,
                                     Currency currency) {
        return new PaymentReceipt(externalOrderId, transactionId, amount, currency, Instant.now());
    }

    public String getExternalOrderId() {
        return externalOrderId;
    }

    public String getTransactionId() {
        return transactionId;
    }

    public BigDecimal getAmount() {
        return amount;
    }

    public Currency getCurrency() {
        return currency;
    }

    public Instant getProcessedAt() {
        return processedAt;
    }
}

/**
 * Standardized error envelope that front-end applications can reliably parse.
 */
class ErrorEnvelope {

    private final String code;
    private final String message;
    private final Instant timestamp;

    ErrorEnvelope(String code, String message, Instant timestamp) {
        this.code = code;
        this.message = message;
        this.timestamp = timestamp;
    }

    public String getCode() {
        return code;
    }

    public String getMessage() {
        return message;
    }

    public Instant getTimestamp() {
        return timestamp;
    }
}

/* ====================================================================== */
/* ========================   EXCEPTIONS   ============================== */
/* ====================================================================== */

/**
 * Domain-specific wrapper for any abnormal payment condition, preserving cause chains for observability.
 */
class PaymentException extends Exception {

    PaymentException(String message) {
        super(message);
    }

    PaymentException(String message, Throwable cause) {
        super(message, cause);
    }
}
```