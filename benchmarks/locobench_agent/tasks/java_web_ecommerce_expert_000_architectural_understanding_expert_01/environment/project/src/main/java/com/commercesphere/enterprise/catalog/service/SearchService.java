package com.commercesphere.enterprise.catalog.service;

import com.commercesphere.enterprise.catalog.exception.SearchException;
import com.commercesphere.enterprise.catalog.gateway.CatalogSearchGateway;
import com.commercesphere.enterprise.catalog.model.ProductEntity;
import com.commercesphere.enterprise.catalog.model.dto.ProductSearchCriteria;
import com.commercesphere.enterprise.catalog.model.dto.ProductSummary;
import com.commercesphere.enterprise.catalog.repository.CategoryRepository;
import com.commercesphere.enterprise.catalog.repository.ProductRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cache.Cache;
import org.springframework.cache.CacheManager;
import org.springframework.dao.DataAccessException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.Pageable;
import org.springframework.scheduling.annotation.Async;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.Instant;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.stream.Collectors;

/**
 * High-level façade for catalog search operations.
 *
 * <p>
 * The service delegates full-text parsing and scoring to an underlying search
 * provider (e.g. Elasticsearch, Solr) through {@link CatalogSearchGateway}.
 * If the provider is unavailable, it transparently falls back to a relational
 * query executed through {@link ProductRepository}.
 * </p>
 *
 * <p>
 * All operations run read-only transactions to guarantee no accidental data
 * modifications while still participating in Spring’s transactional context
 * for connection reuse and consistent read semantics.
 * </p>
 */
@Service
@Transactional(readOnly = true)
public class SearchService {

    private static final Logger LOGGER = LoggerFactory.getLogger(SearchService.class);
    private static final String CACHE_SUGGEST = "keywordSuggestions";

    private final ProductRepository productRepository;
    private final CategoryRepository categoryRepository;
    private final CatalogSearchGateway searchGateway;
    private final Cache keywordSuggestionCache;

    public SearchService(ProductRepository productRepository,
                         CategoryRepository categoryRepository,
                         CatalogSearchGateway searchGateway,
                         CacheManager cacheManager) {
        this.productRepository = Objects.requireNonNull(productRepository);
        this.categoryRepository = Objects.requireNonNull(categoryRepository);
        this.searchGateway = Objects.requireNonNull(searchGateway);
        this.keywordSuggestionCache = cacheManager.getCache(CACHE_SUGGEST);
    }

    /**
     * Performs a product search using the supplied criteria.
     *
     * <p>
     * The method will:
     * <ol>
     *     <li>Validate incoming parameters.</li>
     *     <li>Attempt a full-text search through the search gateway.</li>
     *     <li>Fall back to a LIKE-based SQL query if the search engine
     *     is unreachable or returns no hits.</li>
     *     <li>Return an immutable page of {@link ProductSummary} DTOs.</li>
     * </ol>
     * </p>
     *
     * @param criteria  domain search criteria; must not be {@code null}
     * @param pageable  page descriptor; must not be {@code null}
     * @return non-null page of product summaries
     * @throws SearchException if validation fails or both search strategies fail
     */
    @PreAuthorize("hasAuthority('CATALOG_READ')")
    public Page<ProductSummary> searchProducts(ProductSearchCriteria criteria,
                                               Pageable pageable) {

        validateCriteria(criteria);

        Instant start = Instant.now();
        try {
            Page<Long> idPage = searchGateway.searchProductIds(criteria, pageable);
            if (!idPage.hasContent()) {
                LOGGER.debug("Search gateway returned no results for criteria {}", criteria);
                // fall through to relational search
                return relationalFallback(criteria, pageable, start);
            }

            List<ProductEntity> entities =
                    productRepository.findAllById(idPage.getContent());

            List<ProductSummary> summaries = entities.stream()
                                                     .map(ProductSummary::from)
                                                     .collect(Collectors.toList());

            LOGGER.info("Search completed through gateway in {} ms (hits={})",
                        Duration.between(start, Instant.now()).toMillis(),
                        summaries.size());

            return new PageImpl<>(summaries, pageable, idPage.getTotalElements());

        } catch (RuntimeException ex) {
            // Any unexpected runtime exception is handled as gateway failure
            LOGGER.warn("Gateway search failed, attempting relational fallback", ex);
            return relationalFallback(criteria, pageable, start);
        }
    }

    /**
     * Returns keyword suggestions for an autocomplete box.
     * Results are cached for short periods to reduce latency during typing.
     *
     * @param partial search text fragment
     * @param limit   maximum number of suggestions
     * @return ordered list of suggestions; never {@code null}
     */
    public List<String> suggestKeywords(String partial, int limit) {
        if (partial == null || partial.length() < 2) {
            return Collections.emptyList();
        }

        String cacheKey = partial.toLowerCase() + ":" + limit;
        List<String> cached = keywordSuggestionCache.get(cacheKey, List.class);
        if (cached != null) {
            return cached;
        }

        List<String> suggestions =
                searchGateway.suggestKeywords(partial, limit)
                             .stream()
                             .map(String::trim)
                             .collect(Collectors.toList());

        keywordSuggestionCache.put(cacheKey, suggestions);
        return suggestions;
    }

    /**
     * Rebuilds the entire search index asynchronously.
     * The operation can be long-running, so triggering it outside the request
     * thread prevents HTTP timeouts.
     */
    @Async
    @PreAuthorize("hasAuthority('CATALOG_ADMIN')")
    public void rebuildIndexAsync() {
        LOGGER.info("Starting asynchronous full index rebuild");
        Instant start = Instant.now();
        try {
            List<ProductEntity> allProducts = productRepository.findAll();
            searchGateway.rebuildIndex(allProducts);
            LOGGER.info("Full index rebuild finished in {} ms (items={})",
                        Duration.between(start, Instant.now()).toMillis(),
                        allProducts.size());
        } catch (Exception ex) {
            LOGGER.error("Full index rebuild failed", ex);
            throw new SearchException("Full index rebuild failed", ex);
        }
    }

    // ----------------------------------------------------------------
    // Private helpers
    // ----------------------------------------------------------------

    private void validateCriteria(ProductSearchCriteria criteria) {
        if (criteria == null) {
            throw new SearchException("Search criteria must not be null");
        }
        if (criteria.getKeywords() != null && criteria.getKeywords().length() < 2) {
            throw new SearchException("Keywords must contain at least two characters");
        }
        // Additional validations can be added as business evolves
    }

    /**
     * Executes a SQL LIKE-based search as a safe fallback.
     */
    private Page<ProductSummary> relationalFallback(ProductSearchCriteria criteria,
                                                    Pageable pageable,
                                                    Instant start) {
        try {
            Page<ProductEntity> entityPage =
                    productRepository.searchRelational(criteria, pageable);

            List<ProductSummary> summaries = entityPage.getContent()
                                                       .stream()
                                                       .map(ProductSummary::from)
                                                       .collect(Collectors.toList());

            LOGGER.info("Relational fallback completed in {} ms (hits={})",
                        Duration.between(start, Instant.now()).toMillis(),
                        summaries.size());

            return new PageImpl<>(summaries, pageable, entityPage.getTotalElements());
        } catch (DataAccessException daoEx) {
            LOGGER.error("Relational fallback search failed", daoEx);
            throw new SearchException("Search operation failed on all backends", daoEx);
        }
    }
}