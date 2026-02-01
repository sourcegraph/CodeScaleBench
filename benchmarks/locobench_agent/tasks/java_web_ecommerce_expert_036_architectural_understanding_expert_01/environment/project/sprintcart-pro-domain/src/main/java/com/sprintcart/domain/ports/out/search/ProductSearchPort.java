package com.sprintcart.domain.ports.out.search;

import com.sprintcart.domain.model.Product;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Outbound port that encapsulates all catalog search capabilities.
 * <p>
 * Domain services depend on this abstraction; adapters implement it against a
 * concrete search engine (e.g., Elasticsearch, OpenSearch, Solr, or a SQL
 * full-text index).  Keeping the contract small and intention-revealing enables
 * the platform to swap search back-ends without touching core business logic.
 */
public interface ProductSearchPort {

    /**
     * Executes a pageable, faceted search across the product catalog.
     *
     * @param criteria non-{@code null} criteria describing query, filters,
     *                 pagination, and sorting
     * @return never-{@code null} {@link SearchResult} that wraps the matching
     *         products and pagination metadata (an empty result is allowed)
     * @throws SearchException if the underlying search engine fails or is
     *                         unreachable
     */
    SearchResult<Product> search(ProductSearchCriteria criteria) throws SearchException;

    /**
     * Returns type-ahead suggestions for the given partial user input.
     *
     * @param partialQuery non-blank, user-provided text
     * @param limit        maximum number of suggestions (must be {@code > 0})
     * @return ordered list of suggestion terms (may be empty, never {@code null})
     * @throws IllegalArgumentException if {@code limit <= 0}
     * @throws SearchException          if the underlying search engine fails
     */
    List<Suggestion> suggest(String partialQuery, int limit) throws SearchException;

    /**
     * Refreshes the underlying search index so that subsequent queries reflect
     * the latest catalog state.
     *
     * <p>Depending on the back-end, this operation may be synchronous
     * (blocking) or schedule a refresh task asynchronously.</p>
     *
     * @throws SearchException if the index cannot be refreshed
     */
    void refreshIndex() throws SearchException;

    /**
     * Domain-specific exception indicating that the search subsystem is
     * temporarily unavailable or malfunctioning.
     */
    final class SearchException extends RuntimeException {
        public SearchException(String message, Throwable cause) {
            super(message, cause);
        }

        public SearchException(String message) {
            super(message);
        }
    }
}

/* ======================================================================= */
/* == Below are lightweight DTOs that belong to the domain search port. == */
/* == Move them to separate files if your code-style rules require it.  == */
/* ======================================================================= */

/**
 * Immutable value object that describes how the caller wants to search products.
 * <p>
 * Use the {@link Builder} to construct instances in a readable manner:
 *
 * <pre>{@code
 * ProductSearchCriteria criteria = ProductSearchCriteria.builder()
 *     .query("running shoes")
 *     .page(0)
 *     .size(25)
 *     .filters(Map.of("brand", List.of("acme"), "color", List.of("blue")))
 *     .sorts(List.of(new ProductSearchCriteria.Sort("price", Direction.ASC)))
 *     .build();
 * }</pre>
 */
final class ProductSearchCriteria {

    private final String query;
    private final Map<String, List<String>> filters;
    private final List<Sort> sorts;
    private final int page;
    private final int size;

    private ProductSearchCriteria(Builder builder) {
        this.query = builder.query;
        this.filters = Collections.unmodifiableMap(new LinkedHashMap<>(builder.filters));
        this.sorts = Collections.unmodifiableList(builder.sorts);
        this.page = builder.page;
        this.size = builder.size;
    }

    public String query() {
        return query;
    }

    public Map<String, List<String>> filters() {
        return filters;
    }

    public List<Sort> sorts() {
        return sorts;
    }

    public int page() {
        return page;
    }

    public int size() {
        return size;
    }

    /* -------------------------------------------------------------- */
    /*                    Builder & Supporting Types                  */
    /* -------------------------------------------------------------- */

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private String query = "";
        private Map<String, List<String>> filters = new LinkedHashMap<>();
        private List<Sort> sorts = List.of();
        private int page = 0;
        private int size = 20;

        private Builder() {
        }

        public Builder query(String query) {
            this.query = Objects.requireNonNullElse(query, "");
            return this;
        }

        public Builder filters(Map<String, List<String>> filters) {
            if (filters != null) {
                this.filters = new LinkedHashMap<>(filters);
            }
            return this;
        }

        public Builder sorts(List<Sort> sorts) {
            if (sorts != null) {
                this.sorts = List.copyOf(sorts);
            }
            return this;
        }

        public Builder page(int page) {
            if (page < 0) {
                throw new IllegalArgumentException("page must be >= 0");
            }
            this.page = page;
            return this;
        }

        public Builder size(int size) {
            if (size <= 0) {
                throw new IllegalArgumentException("size must be > 0");
            }
            this.size = size;
            return this;
        }

        public ProductSearchCriteria build() {
            return new ProductSearchCriteria(this);
        }
    }

    /**
     * Enumeration describing the direction of the sort.
     */
    public enum Direction {
        ASC, DESC
    }

    /**
     * Immutable value object representing a single sort directive.
     *
     * @param field     catalog attribute to sort by (e.g., {@code "price"})
     * @param direction sort direction
     */
    public record Sort(String field, Direction direction) {
        public Sort {
            Objects.requireNonNull(field, "field must not be null");
            Objects.requireNonNull(direction, "direction must not be null");
        }
    }
}

/**
 * Generic, pageable search result wrapper.
 *
 * @param <T> type of entities contained in the result list
 */
final class SearchResult<T> {

    private final List<T> items;
    private final long totalElements;
    private final int totalPages;
    private final int page;
    private final int size;

    private SearchResult(Builder<T> builder) {
        this.items = List.copyOf(builder.items);
        this.totalElements = builder.totalElements;
        this.totalPages = builder.totalPages;
        this.page = builder.page;
        this.size = builder.size;
    }

    public List<T> items() {
        return items;
    }

    public long totalElements() {
        return totalElements;
    }

    public int totalPages() {
        return totalPages;
    }

    public int page() {
        return page;
    }

    public int size() {
        return size;
    }

    /* -------------------------------------------------------------- */
    /*                             Builder                            */
    /* -------------------------------------------------------------- */

    public static <T> Builder<T> builder() {
        return new Builder<>();
    }

    public static final class Builder<T> {
        private List<T> items = new ArrayList<>();
        private long totalElements;
        private int totalPages;
        private int page;
        private int size;

        private Builder() {
        }

        public Builder<T> items(List<T> items) {
            if (items != null) {
                this.items = new ArrayList<>(items);
            }
            return this;
        }

        public Builder<T> totalElements(long totalElements) {
            if (totalElements < 0) {
                throw new IllegalArgumentException("totalElements must be >= 0");
            }
            this.totalElements = totalElements;
            return this;
        }

        public Builder<T> totalPages(int totalPages) {
            if (totalPages < 0) {
                throw new IllegalArgumentException("totalPages must be >= 0");
            }
            this.totalPages = totalPages;
            return this;
        }

        public Builder<T> page(int page) {
            if (page < 0) {
                throw new IllegalArgumentException("page must be >= 0");
            }
            this.page = page;
            return this;
        }

        public Builder<T> size(int size) {
            if (size <= 0) {
                throw new IllegalArgumentException("size must be > 0");
            }
            this.size = size;
            return this;
        }

        public SearchResult<T> build() {
            return new SearchResult<>(this);
        }
    }
}

/**
 * Simple record used for type-ahead suggestions in the catalog search.
 *
 * @param term  suggested term
 * @param score relevance score (between {@code 0.0f} and {@code 1.0f})
 */
record Suggestion(String term, float score) {
    Suggestion {
        Objects.requireNonNull(term, "term must not be null");
        if (score < 0f || score > 1f) {
            throw new IllegalArgumentException("score must be within [0,1]");
        }
    }
}