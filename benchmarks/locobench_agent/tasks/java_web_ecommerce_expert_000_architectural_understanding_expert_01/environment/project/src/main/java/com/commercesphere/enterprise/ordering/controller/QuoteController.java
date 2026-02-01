package com.commercesphere.enterprise.ordering.controller;

import com.commercesphere.enterprise.ordering.dto.ApproveQuoteRequest;
import com.commercesphere.enterprise.ordering.dto.QuoteRequest;
import com.commercesphere.enterprise.ordering.dto.QuoteResponse;
import com.commercesphere.enterprise.ordering.exception.QuoteNotFoundException;
import com.commercesphere.enterprise.ordering.exception.QuoteStateException;
import com.commercesphere.enterprise.ordering.service.QuoteService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import java.net.URI;
import java.util.List;
import java.util.UUID;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.util.MimeTypeUtils;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

/**
 * REST controller that exposes endpoints related to Quote life-cycle operations such as creation,
 * approval, and conversion to order.
 *
 * <p>Every request entering this controller requires the caller to have at least the
 * ROLE_CUSTOMER_USER authority. Mutating operations (create / approve / convert) further require
 * additional privileges.</p>
 *
 * <p>The controller delegates business logic to {@link QuoteService}, ensuring a thin,
 * stateless interface layer that is easy to test and maintain.</p>
 *
 * @author CommerceSphere
 */
@Slf4j
@Validated
@RequiredArgsConstructor
@RestController
@RequestMapping(
        value = "/api/v1/quotes",
        produces = MimeTypeUtils.APPLICATION_JSON_VALUE)
public class QuoteController {

    private final QuoteService quoteService;

    /**
     * Creates a new quote. The quote will be persisted in DRAFT state until explicitly approved.
     *
     * @param request The incoming quote definition
     * @return 201-Created with the newly generated quote payload
     */
    @PostMapping(consumes = MimeTypeUtils.APPLICATION_JSON_VALUE)
    @PreAuthorize("hasAuthority('ROLE_CUSTOMER_USER')")
    public ResponseEntity<QuoteResponse> createQuote(@Valid @RequestBody QuoteRequest request) {
        long start = System.currentTimeMillis();
        String correlationId = UUID.randomUUID().toString();

        log.info("[{}] Creating quote for accountId={} submittedBy={}", correlationId,
                request.getAccountId(), request.getRequestedBy());

        QuoteResponse response = quoteService.createQuote(request, correlationId);

        log.info("[{}] Quote created: id={} (elapsed={} ms)", correlationId,
                response.getQuoteId(), System.currentTimeMillis() - start);

        return ResponseEntity
                .created(URI.create("/api/v1/quotes/" + response.getQuoteId()))
                .body(response);
    }

    /**
     * Retrieves a single quote.
     *
     * @param id Quote identifier
     * @return 200-OK with the Quote payload
     */
    @GetMapping("/{id}")
    @PreAuthorize("hasAuthority('ROLE_CUSTOMER_USER')")
    public ResponseEntity<QuoteResponse> getQuote(
            @PathVariable @Min(1) Long id) {

        QuoteResponse response =
                quoteService.getQuoteById(id).orElseThrow(() -> new QuoteNotFoundException(id));

        return ResponseEntity.ok(response);
    }

    /**
     * Paginated list of quotes visible to the current principal. Optional filters can be provided
     * through query parameters.
     */
    @GetMapping
    @PreAuthorize("hasAuthority('ROLE_CUSTOMER_USER')")
    public ResponseEntity<List<QuoteResponse>> listQuotes(
            @RequestParam(required = false) Long accountId,
            @RequestParam(required = false, defaultValue = "0") int page,
            @RequestParam(required = false, defaultValue = "20") int size) {

        List<QuoteResponse> quotes = quoteService.listQuotes(accountId, page, size);
        return ResponseEntity.ok(quotes);
    }

    /**
     * Approves a quote. Validation ensures the quote is in DRAFT state before approval.
     *
     * @param id      Quote identifier
     * @param request request wrapper for additional approval metadata
     * @return 200-OK with updated Quote payload
     */
    @PutMapping(
            path = "/{id}/approve",
            consumes = MimeTypeUtils.APPLICATION_JSON_VALUE)
    @PreAuthorize("hasAuthority('ROLE_ACCOUNT_MANAGER')")
    public ResponseEntity<QuoteResponse> approveQuote(
            @PathVariable @Min(1) Long id,
            @Valid @RequestBody ApproveQuoteRequest request) {

        try {
            QuoteResponse response = quoteService.approveQuote(id, request);
            return ResponseEntity.ok(response);
        } catch (QuoteStateException ex) {
            log.warn("Attempted to approve quote={} but state invalid: {}", id, ex.getMessage());
            throw ex;
        }
    }

    /**
     * Converts an approved quote into an order.
     *
     * @param id Quote identifier
     * @return 201-Created with the generated order identifier embedded in the payload
     */
    @PostMapping("/{id}/convert")
    @PreAuthorize("hasAuthority('ROLE_CUSTOMER_USER')")
    public ResponseEntity<QuoteResponse> convertQuoteToOrder(@PathVariable @Min(1) Long id) {

        QuoteResponse response = quoteService.convertQuoteToOrder(id);

        return ResponseEntity
                .status(HttpStatus.CREATED)
                .body(response);
    }

    // ---------------------------------------------------------------------
    // Exception Handlers
    // ---------------------------------------------------------------------

    @ExceptionHandler(QuoteNotFoundException.class)
    public ResponseEntity<String> handleNotFound(QuoteNotFoundException ex) {
        log.debug("QuoteNotFoundException: {}", ex.getMessage());
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(ex.getMessage());
    }

    @ExceptionHandler(QuoteStateException.class)
    public ResponseEntity<String> handleInvalidState(QuoteStateException ex) {
        log.debug("QuoteStateException: {}", ex.getMessage());
        return ResponseEntity.status(HttpStatus.CONFLICT).body(ex.getMessage());
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<String> handleGeneric(Exception ex) {
        log.error("Unhandled exception in QuoteController", ex);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body("Unexpected error processing quote request.");
    }
}