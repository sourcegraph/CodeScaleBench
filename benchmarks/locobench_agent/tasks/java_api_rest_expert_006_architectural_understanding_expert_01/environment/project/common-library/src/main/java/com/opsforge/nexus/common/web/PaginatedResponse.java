package com.opsforge.nexus.common.web;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.io.Serial;
import java.io.Serializable;
import java.net.URI;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.function.Function;

/**
 * A generic, immutable container that wraps a page of results together with pagination
 * metadata and optional HATEOAS-style navigation links.  The class is intentionally free of
 * Spring or Jakarta dependencies so it can be consumed from any adapter layer (REST, GraphQL, messaging, etc.).
 *
 * @param <T> the concrete payload type stored in {@link #content}
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public final class PaginatedResponse<T> implements Serializable {

    @Serial
    private static final long serialVersionUID = -7529449540402459255L;

    private final List<T> content;
    private final PageMetadata page;
    private final Map<String, URI> links;

    /**
     * Creates a new {@link PaginatedResponse}.
     *
     * @param content the content for the current page
     * @param page    metadata describing the page
     * @param links   optional HATEOAS links
     */
    @JsonCreator
    private PaginatedResponse(
            @JsonProperty("content") List<T> content,
            @JsonProperty("page") PageMetadata page,
            @JsonProperty("links") Map<String, URI> links) {

        this.content = Collections.unmodifiableList(
                Objects.requireNonNullElseGet(content, Collections::emptyList)
        );
        this.page = Objects.requireNonNull(page, "Page metadata must be provided");
        this.links = links == null ? Map.of() : Collections.unmodifiableMap(new LinkedHashMap<>(links));
    }

    /* =========================================================================
       Factory methods
       ========================================================================= */

    /**
     * Creates a {@link PaginatedResponse} without any HATEOAS links.
     */
    public static <T> PaginatedResponse<T> of(List<T> content,
                                              long pageNumber,
                                              long pageSize,
                                              long totalElements) {
        return of(content, pageNumber, pageSize, totalElements, Map.of());
    }

    /**
     * Creates a {@link PaginatedResponse} with HATEOAS links.
     */
    public static <T> PaginatedResponse<T> of(List<T> content,
                                              long pageNumber,
                                              long pageSize,
                                              long totalElements,
                                              Map<String, URI> links) {
        PageMetadata metadata = new PageMetadata(pageNumber, pageSize, totalElements);
        return new PaginatedResponse<>(content, metadata, links);
    }

    /* =========================================================================
       Utility methods
       ========================================================================= */

    /**
     * Convenience method to transform the internal content while keeping pagination information intact.
     *
     * @param converter a mapping function that transforms each item
     * @return the converted {@link PaginatedResponse}
     */
    public <R> PaginatedResponse<R> map(Function<? super T, ? extends R> converter) {
        Objects.requireNonNull(converter, "Converter must not be null");
        List<R> transformed =
                this.content.stream()
                            .map(converter)
                            .toList();
        return new PaginatedResponse<>(transformed, this.page, this.links);
    }

    /**
     * Returns the list of items contained in the response.
     */
    public List<T> getContent() {
        return content;
    }

    /**
     * Returns pagination metadata.
     */
    public PageMetadata getPage() {
        return page;
    }

    /**
     * Returns a map of HATEOAS links keyed by relation (e.g., "next", "prev", "self").
     */
    public Map<String, URI> getLinks() {
        return links;
    }

    /**
     * Convenience getter that returns {@code true} when there is another page after the current one.
     */
    @JsonIgnore
    public boolean hasNext() {
        return page.getNumber() + 1 < page.getTotalPages();
    }

    /**
     * Convenience getter that returns {@code true} when there is a page before the current one.
     */
    @JsonIgnore
    public boolean hasPrevious() {
        return page.getNumber() > 0;
    }

    @Override
    public String toString() {
        return "PaginatedResponse{" +
               "content=" + content +
               ", page=" + page +
               ", links=" + links +
               '}';
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof PaginatedResponse<?> that)) return false;
        return Objects.equals(content, that.content) &&
               Objects.equals(page, that.page) &&
               Objects.equals(links, that.links);
    }

    @Override
    public int hashCode() {
        return Objects.hash(content, page, links);
    }

    /* =========================================================================
       Nested types
       ========================================================================= */

    /**
     * Immutable value object that holds pagination details.
     *
     * @param number        zero-based page index
     * @param size          the size of the page a client requested
     * @param totalElements the total number of elements available
     */
    public static final class PageMetadata implements Serializable {

        @Serial
        private static final long serialVersionUID = -9080949779324693841L;

        private final long number;
        private final long size;
        private final long totalElements;
        private final long totalPages;

        @JsonCreator
        public PageMetadata(
                @JsonProperty("number") long number,
                @JsonProperty("size") long size,
                @JsonProperty("totalElements") long totalElements) {

            if (number < 0) {
                throw new IllegalArgumentException("Page number must be greater than or equal to 0");
            }
            if (size < 1) {
                throw new IllegalArgumentException("Page size must be greater than 0");
            }
            if (totalElements < 0) {
                throw new IllegalArgumentException("Total elements must be greater than or equal to 0");
            }

            this.number = number;
            this.size = size;
            this.totalElements = totalElements;
            this.totalPages = calculateTotalPages(size, totalElements);
        }

        private long calculateTotalPages(long size, long totalElements) {
            return totalElements == 0 ? 1 : (long) Math.ceil((double) totalElements / size);
        }

        public long getNumber() {
            return number;
        }

        public long getSize() {
            return size;
        }

        public long getTotalElements() {
            return totalElements;
        }

        public long getTotalPages() {
            return totalPages;
        }

        @Override
        public String toString() {
            return "PageMetadata{" +
                   "number=" + number +
                   ", size=" + size +
                   ", totalElements=" + totalElements +
                   ", totalPages=" + totalPages +
                   '}';
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof PageMetadata that)) return false;
            return number == that.number &&
                   size == that.size &&
                   totalElements == that.totalElements &&
                   totalPages == that.totalPages;
        }

        @Override
        public int hashCode() {
            return Objects.hash(number, size, totalElements, totalPages);
        }
    }
}