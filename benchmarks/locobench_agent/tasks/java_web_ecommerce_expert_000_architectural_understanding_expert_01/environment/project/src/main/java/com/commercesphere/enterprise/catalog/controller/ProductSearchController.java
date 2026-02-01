package com.commercesphere.enterprise.catalog.controller;

import com.commercesphere.enterprise.catalog.dto.ProductSearchCriteria;
import com.commercesphere.enterprise.catalog.dto.ProductSummaryDto;
import com.commercesphere.enterprise.catalog.service.ProductSearchService;
import com.commercesphere.enterprise.shared.api.PagedResponse;
import com.commercesphere.enterprise.shared.logging.MdcUtil;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.PositiveOrZero;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.time.Duration;
import java.util.Locale;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

/**
 * REST controller that exposes read-only search capabilities for catalog products.
 * <p>
 * The controller performs lightweight request validation, builds a type-safe criteria
 * object, and delegates the heavy lifting to {@link ProductSearchService}.  Results
 * are wrapped inside {@link PagedResponse} to provide consistent pagination metadata
 * for the SPA storefront and the legacy Thymeleaf views that consume the same endpoint.
 * <p>
 * Concrete responsibilities:
 * <ul>
 *     <li>Translate query parameters to {@link ProductSearchCriteria}</li>
 *     <li>Resolve {@link Pageable} and {@link Sort} in a safe, white-listed fashion</li>
 *     <li>Emit structured logs enriched with correlation IDs</li>
 *     <li>Return immutable cache headers for anonymous traffic when appropriate</li>
 * </ul>
 */
@RestController
@RequestMapping(path = "/api/v1/catalog/products", produces = MediaType.APPLICATION_JSON_VALUE)
@Validated
@RequiredArgsConstructor
public class ProductSearchController {

    private static final Logger LOG = LoggerFactory.getLogger(ProductSearchController.class);
    private static final int MAX_PAGE_SIZE = 200;
    private static final Sort DEFAULT_SORT = Sort.by(Sort.Order.desc("relevance"));
    private final ProductSearchService productSearchService;

    /**
     * Search endpoint.
     *
     * @param query       Free-text query term
     * @param categoryId  Optional category UUID
     * @param priceMin    Min unit price filter
     * @param priceMax    Max unit price filter
     * @param page        Page index (zero-based)
     * @param size        Page size
     * @param sortParam   Comma-separated <code>property,direction</code> pairs (e.g. {@code price,asc})
     * @param langHeader  Accept-Language header used for i18n projection
     * @return PagedResponse with {@link ProductSummaryDto}
     */
    @GetMapping
    public ResponseEntity<PagedResponse<ProductSummaryDto>> searchProducts(
            @RequestParam(value = "q", required = false) String query,
            @RequestParam(value = "category", required = false) UUID categoryId,
            @RequestParam(value = "priceMin", required = false) @PositiveOrZero BigDecimal priceMin,
            @RequestParam(value = "priceMax", required = false) @Positive BigDecimal priceMax,
            @RequestParam(value = "page", defaultValue = "0") @Min(0) int page,
            @RequestParam(value = "size", defaultValue = "20") @Min(1) @Max(MAX_PAGE_SIZE) int size,
            @RequestParam(value = "sort", required = false) String sortParam,
            @RequestHeader(value = HttpHeaders.ACCEPT_LANGUAGE, required = false) String langHeader) {

        // Safety check: ensure price bounds make sense
        if (priceMin != null && priceMax != null && priceMin.compareTo(priceMax) > 0) {
            throw new IllegalArgumentException("Parameter 'priceMin' must be less than or equal to 'priceMax'.");
        }

        Sort sort = parseSort(sortParam).orElse(DEFAULT_SORT);
        Pageable pageable = PageRequest.of(page, size, sort);
        Locale locale = resolveLocale(langHeader);

        ProductSearchCriteria criteria = ProductSearchCriteria.builder()
                .query(query)
                .categoryId(categoryId)
                .priceMin(priceMin)
                .priceMax(priceMax)
                .locale(locale)
                .build();

        String requestId = MdcUtil.getCorrelationId();
        LOG.info("SEARCH_PRODUCTS requestId={} criteria={} pageable={}", requestId, criteria, pageable);

        Page<ProductSummaryDto> resultPage = productSearchService.search(criteria, pageable);

        PagedResponse<ProductSummaryDto> response = PagedResponse.from(resultPage);

        /*
         * For anonymous users we can mark response as cacheable for a short window
         * because the underlying search index is near-real-time and business rules
         * tolerate slight staleness.  Authentication is handled by a servlet filter
         * that sets MDC key 'authSubject', so we peek at it to decide.
         */
        boolean anonymous = MdcUtil.isAnonymous();
        CacheControl cacheControl = anonymous
                ? CacheControl.maxAge(Duration.ofMinutes(5)).cachePublic()
                : CacheControl.noCache().mustRevalidate();

        return ResponseEntity.ok()
                .cacheControl(cacheControl)
                .body(response);
    }

    /**
     * Attempt to build a Spring {@link Sort} instance while safeguarding against
     * SQL injection and exposing only a white-listed subset of sortable fields.
     */
    private Optional<Sort> parseSort(String sortParam) {
        if (sortParam == null || sortParam.isBlank()) {
            return Optional.empty();
        }

        String[] tokens = sortParam.split(",");
        if (tokens.length != 2) {
            return Optional.empty();
        }

        String property = tokens[0].trim();
        String directionToken = tokens[1].trim().toLowerCase(Locale.ROOT);

        // Safelist to avoid exposing raw DB column names
        switch (property) {
            case "price":
            case "name":
            case "created":
            case "relevance":
                break;
            default:
                LOG.warn("Unknown sort property '{}', falling back to default.", property);
                return Optional.empty();
        }

        Sort.Direction direction = "asc".equals(directionToken)
                ? Sort.Direction.ASC
                : Sort.Direction.DESC;

        return Optional.of(Sort.by(direction, property));
    }

    private Locale resolveLocale(String langHeader) {
        if (langHeader == null || langHeader.isBlank()) {
            return Locale.US;
        }
        return Locale.forLanguageTag(langHeader);
    }

    // ----------------------------------------------------------
    // Exception Handling
    // ----------------------------------------------------------

    @ExceptionHandler({IllegalArgumentException.class, MissingServletRequestParameterException.class})
    public ResponseEntity<ErrorPayload> handleClientErrors(Exception ex) {
        LOG.debug("Client error: {}", ex.getMessage(), ex);
        ErrorPayload payload = new ErrorPayload("BAD_REQUEST", ex.getMessage());
        return ResponseEntity.badRequest().body(payload);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorPayload> handleServerErrors(Exception ex) {
        String requestId = MdcUtil.getCorrelationId();
        LOG.error("Unhandled exception on requestId={}", requestId, ex);
        ErrorPayload payload = new ErrorPayload("INTERNAL_ERROR",
                "Unexpected server exception. Reference id: " + requestId);
        return ResponseEntity.status(500).body(payload);
    }

    /**
     * Lightweight error representation to avoid leaking stack traces to clients.
     */
    public record ErrorPayload(String code, String message) {
    }
}