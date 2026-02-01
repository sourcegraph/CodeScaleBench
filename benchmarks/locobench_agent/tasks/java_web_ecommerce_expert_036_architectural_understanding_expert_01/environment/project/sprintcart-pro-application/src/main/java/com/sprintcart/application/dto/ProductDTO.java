```java
package com.sprintcart.application.dto;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.io.Serial;
import java.io.Serializable;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.*;

/**
 * ProductDTO is the wire-format representation of a Product that travels in and out of
 * the hexagonal boundary—e.g. REST controllers, messaging adapters, or bulk-upload jobs.
 *
 * The class purposefully avoids any domain-specific behavior; it only contains
 * validation annotations and very light object-creation utilities.
 *
 * NOTE: When adding fields, mind backward compatibility on public APIs.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public final class ProductDTO implements Serializable {

    @Serial
    private static final long serialVersionUID = 1L;

    // -----------------------------------------------------------------------
    // Core identity
    // -----------------------------------------------------------------------
    @JsonProperty("id")
    private final UUID id;

    @JsonProperty("sku")
    @NotBlank(message = "SKU must not be blank")
    @Size(max = 64, message = "SKU cannot exceed 64 characters")
    private final String sku;

    // -----------------------------------------------------------------------
    // Descriptive data
    // -----------------------------------------------------------------------
    @JsonProperty("name")
    @NotBlank(message = "Product name must not be blank")
    @Size(max = 256, message = "Product name cannot exceed 256 characters")
    private final String name;

    @JsonProperty("description")
    @Size(max = 4096, message = "Description cannot exceed 4096 characters")
    private final String description;

    // -----------------------------------------------------------------------
    // Pricing & stock
    // -----------------------------------------------------------------------
    @JsonProperty("price")
    @NotNull(message = "Price is required")
    @PositiveOrZero(message = "Price cannot be negative")
    private final BigDecimal price;

    @JsonProperty("currency")
    @NotNull(message = "Currency is required")
    @Pattern(regexp = "^[A-Z]{3}$", message = "Currency must be a valid ISO-4217 code")
    private final String currency;

    @JsonProperty("stock")
    @NotNull(message = "Stock is required")
    @PositiveOrZero(message = "Stock cannot be negative")
    private final Integer stock;

    @JsonProperty("active")
    @NotNull
    private final Boolean active;

    // -----------------------------------------------------------------------
    // Classification & metadata
    // -----------------------------------------------------------------------
    @JsonProperty("categories")
    @NotNull
    private final Set<@Size(max = 128) String> categories;

    @JsonProperty("attributes")
    private final Map<
            @Size(max = 64) String,
            @Size(max = 256) String> attributes;

    // -----------------------------------------------------------------------
    // Media
    // -----------------------------------------------------------------------
    @JsonProperty("mediaGallery")
    @Valid
    private final List<MediaDTO> mediaGallery;

    // -----------------------------------------------------------------------
    // Audit
    // -----------------------------------------------------------------------
    @JsonProperty("createdAt")
    private final Instant createdAt;

    @JsonProperty("updatedAt")
    private final Instant updatedAt;

    // -----------------------------------------------------------------------
    // Constructors / factory
    // -----------------------------------------------------------------------

    /**
     * Use {@link Builder} instead of calling this constructor directly.
     */
    @JsonCreator
    private ProductDTO(
            @JsonProperty("id") UUID id,
            @JsonProperty("sku") String sku,
            @JsonProperty("name") String name,
            @JsonProperty("description") String description,
            @JsonProperty("price") BigDecimal price,
            @JsonProperty("currency") String currency,
            @JsonProperty("stock") Integer stock,
            @JsonProperty("active") Boolean active,
            @JsonProperty("categories") Set<String> categories,
            @JsonProperty("attributes") Map<String, String> attributes,
            @JsonProperty("mediaGallery") List<MediaDTO> mediaGallery,
            @JsonProperty("createdAt") Instant createdAt,
            @JsonProperty("updatedAt") Instant updatedAt) {

        this.id = id;
        this.sku = sku;
        this.name = name;
        this.description = description;
        this.price = price;
        this.currency = currency;
        this.stock = stock;
        this.active = active;
        this.categories = categories == null ? Collections.emptySet() :
                Collections.unmodifiableSet(new LinkedHashSet<>(categories));
        this.attributes = attributes == null ? Collections.emptyMap() :
                Collections.unmodifiableMap(new LinkedHashMap<>(attributes));
        this.mediaGallery = mediaGallery == null ? Collections.emptyList() :
                Collections.unmodifiableList(new ArrayList<>(mediaGallery));
        this.createdAt = createdAt;
        this.updatedAt = updatedAt;
    }

    // -----------------------------------------------------------------------
    // Getters
    // -----------------------------------------------------------------------

    public UUID getId() {
        return id;
    }

    public String getSku() {
        return sku;
    }

    public String getName() {
        return name;
    }

    public String getDescription() {
        return description;
    }

    public BigDecimal getPrice() {
        return price;
    }

    public String getCurrency() {
        return currency;
    }

    public Integer getStock() {
        return stock;
    }

    public Boolean getActive() {
        return active;
    }

    public Set<String> getCategories() {
        return categories;
    }

    public Map<String, String> getAttributes() {
        return attributes;
    }

    public List<MediaDTO> getMediaGallery() {
        return mediaGallery;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    // -----------------------------------------------------------------------
    // Builder
    // -----------------------------------------------------------------------

    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {
        private UUID id;
        private String sku;
        private String name;
        private String description;
        private BigDecimal price;
        private String currency;
        private Integer stock = 0;
        private Boolean active = Boolean.TRUE;
        private Set<String> categories = new LinkedHashSet<>();
        private Map<String, String> attributes = new LinkedHashMap<>();
        private List<MediaDTO> mediaGallery = new ArrayList<>();
        private Instant createdAt;
        private Instant updatedAt;

        private Builder() {}

        public Builder id(UUID id) {
            this.id = id;
            return this;
        }

        public Builder sku(String sku) {
            this.sku = sku;
            return this;
        }

        public Builder name(String name) {
            this.name = name;
            return this;
        }

        public Builder description(String description) {
            this.description = description;
            return this;
        }

        public Builder price(BigDecimal price) {
            this.price = price;
            return this;
        }

        public Builder currency(String currency) {
            this.currency = currency;
            return this;
        }

        public Builder stock(Integer stock) {
            this.stock = stock;
            return this;
        }

        public Builder active(Boolean active) {
            this.active = active;
            return this;
        }

        public Builder categories(Collection<String> categories) {
            this.categories = categories == null ? new LinkedHashSet<>() : new LinkedHashSet<>(categories);
            return this;
        }

        public Builder addCategory(String category) {
            this.categories.add(category);
            return this;
        }

        public Builder attributes(Map<String, String> attributes) {
            this.attributes = attributes == null ? new LinkedHashMap<>() : new LinkedHashMap<>(attributes);
            return this;
        }

        public Builder putAttribute(String key, String value) {
            this.attributes.put(key, value);
            return this;
        }

        public Builder mediaGallery(Collection<MediaDTO> media) {
            this.mediaGallery = media == null ? new ArrayList<>() : new ArrayList<>(media);
            return this;
        }

        public Builder addMedia(MediaDTO media) {
            this.mediaGallery.add(media);
            return this;
        }

        public Builder createdAt(Instant createdAt) {
            this.createdAt = createdAt;
            return this;
        }

        public Builder updatedAt(Instant updatedAt) {
            this.updatedAt = updatedAt;
            return this;
        }

        /**
         * Builds an immutable instance of {@link ProductDTO}.
         *
         * @return the newly created ProductDTO
         */
        public ProductDTO build() {
            // Ensure timestamps are set if missing
            Instant now = Instant.now();
            if (createdAt == null) {
                createdAt = now;
            }
            if (updatedAt == null) {
                updatedAt = now;
            }
            return new ProductDTO(
                    id,
                    sku,
                    name,
                    description,
                    price,
                    currency,
                    stock,
                    active,
                    categories,
                    attributes,
                    mediaGallery,
                    createdAt,
                    updatedAt
            );
        }
    }

    // -----------------------------------------------------------------------
    // Utility
    // -----------------------------------------------------------------------

    @Override
    public String toString() {
        return "ProductDTO{" +
                "id=" + id +
                ", sku='" + sku + '\'' +
                ", name='" + name + '\'' +
                ", price=" + price +
                ", currency='" + currency + '\'' +
                '}';
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, sku);
    }

    @Override
    public boolean equals(Object obj) {
        if (this == obj) return true;
        if (!(obj instanceof ProductDTO other)) return false;
        return Objects.equals(id, other.id) && Objects.equals(sku, other.sku);
    }

    // -----------------------------------------------------------------------
    // Nested DTOs
    // -----------------------------------------------------------------------

    /**
     * Lightweight representation of media assets (images, videos, 3D models, …)
     * associated with a product.
     *
     * Could be promoted to a top-level class if other aggregate roots need it.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static final class MediaDTO implements Serializable {

        @Serial
        private static final long serialVersionUID = 1L;

        @JsonProperty("type")
        @NotNull(message = "Media type is required")
        @Pattern(regexp = "image|video|model3d", flags = Pattern.Flag.CASE_INSENSITIVE,
                 message = "Media type must be one of: image, video, model3d")
        private final String type;

        @JsonProperty("url")
        @NotBlank(message = "Media URL must not be blank")
        @Size(max = 2048, message = "Media URL cannot exceed 2048 characters")
        private final String url;

        @JsonProperty("altText")
        @Size(max = 512, message = "Alt text cannot exceed 512 characters")
        private final String altText;

        @JsonCreator
        private MediaDTO(
                @JsonProperty("type") String type,
                @JsonProperty("url") String url,
                @JsonProperty("altText") String altText) {
            this.type = type;
            this.url = url;
            this.altText = altText;
        }

        public String getType() {
            return type;
        }

        public String getUrl() {
            return url;
        }

        public String getAltText() {
            return altText;
        }

        public static MediaDTO of(String type, String url, String altText) {
            return new MediaDTO(type, url, altText);
        }

        @Override
        public String toString() {
            return "MediaDTO{type='%s', url='%s'}".formatted(type, url);
        }

        @Override
        public int hashCode() {
            return Objects.hash(type, url);
        }

        @Override
        public boolean equals(Object obj) {
            if (this == obj) return true;
            if (!(obj instanceof MediaDTO other)) return false;
            return Objects.equals(type, other.type) && Objects.equals(url, other.url);
        }
    }
}
```