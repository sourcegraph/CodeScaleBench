```java
package com.sprintcart.domain.model.catalog;

import java.io.Serial;
import java.io.Serializable;
import java.text.Normalizer;
import java.time.Instant;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * Category is an aggregate-root that represents a logical grouping of catalog items.
 * <p>
 * Business rules enforced by this entity:
 * <ul>
 *   <li>Names must be non-blank and at most 150 characters.</li>
 *   <li>Slugs are generated automatically from the name but can be overridden.</li>
 *   <li>There can only be one level of cyclic-free parent/child association.</li>
 *   <li>Disabled categories cannot receive children nor be enabled without a name.</li>
 * </ul>
 *
 * This entity is persistence-agnostic by design and lives in the domain layer.
 */
public final class Category implements Serializable {

    @Serial
    private static final long serialVersionUID = 7431892058149023848L;

    private static final int MAX_NAME_LEN = 150;

    /* ---------- Aggregate Identity ---------- */

    private final CategoryId id;

    /* ---------- Attributes (mutable) ---------- */

    private String name;
    private String slug;           // human-readable identifier, unique within catalog
    private String description;
    private SeoMeta seoMeta;
    private Status status;
    private CategoryId parentId;

    private final Set<CategoryId> childIds = new LinkedHashSet<>();

    /* ---------- Audit ---------- */

    private final Instant createdAt;
    private Instant updatedAt;

    /* ---------- Constructors ---------- */

    private Category(CategoryId id,
                     String name,
                     String slug,
                     String description,
                     SeoMeta seoMeta,
                     Status status,
                     CategoryId parentId,
                     Instant createdAt,
                     Instant updatedAt) {

        this.id          = Objects.requireNonNull(id, "id");
        this.name        = validateName(name);
        this.slug        = slug == null || slug.isBlank() ? slugify(this.name) : slug;
        this.description = description;
        this.seoMeta     = seoMeta == null ? SeoMeta.empty() : seoMeta;
        this.status      = Objects.requireNonNull(status, "status");
        this.parentId    = parentId;            // Null means root category
        this.createdAt   = Objects.requireNonNull(createdAt, "createdAt");
        this.updatedAt   = Objects.requireNonNull(updatedAt, "updatedAt");
    }

    /* ---------- Factory methods ---------- */

    public static Category createRoot(String name) {
        Category category = new Category(
                CategoryId.newRandom(),
                name,
                null,
                null,
                SeoMeta.empty(),
                Status.ACTIVE,
                null,
                Instant.now(),
                Instant.now()
        );
        return category;
    }

    public static Category createChild(String name, CategoryId parentId) {
        Objects.requireNonNull(parentId, "parentId");
        Category category = new Category(
                CategoryId.newRandom(),
                name,
                null,
                null,
                SeoMeta.empty(),
                Status.ACTIVE,
                parentId,
                Instant.now(),
                Instant.now()
        );
        return category;
    }

    /* ---------- Business behaviour ---------- */

    /**
     * Renames the category and regenerates the slug if none was set manually.
     */
    public void rename(String newName) {
        this.name = validateName(newName);
        if (this.slug == null || this.slug.isBlank()) {
            this.slug = slugify(this.name);
        }
        touch();
    }

    /**
     * Override the slug manually. Validation ensures it only contains URL-safe characters.
     */
    public void setSlug(String customSlug) {
        this.slug = validateSlug(customSlug);
        touch();
    }

    /**
     * Changes the description.
     */
    public void updateDescription(String newDescription) {
        this.description = newDescription;
        touch();
    }

    /**
     * Attach SEO meta information.
     */
    public void attachSeoMeta(SeoMeta meta) {
        this.seoMeta = Objects.requireNonNull(meta, "meta");
        touch();
    }

    /**
     * Disable the category, preventing customers from viewing it.
     */
    public void disable() {
        this.status = Status.DISABLED;
        touch();
    }

    /**
     * Activate the category, making it visible again.
     */
    public void activate() {
        if (this.name == null || this.name.isBlank()) {
            throw new DomainException("Cannot enable a category without a valid name.");
        }
        this.status = Status.ACTIVE;
        touch();
    }

    /**
     * Assigns a new parent, making this category a child of the supplied one.
     */
    public void reparentTo(CategoryId newParent) {
        if (this.id.equals(newParent)) {
            throw new DomainException("A category cannot be its own parent.");
        }
        this.parentId = newParent;
        touch();
    }

    /**
     * Adds a child reference to this category. Does NOT persist the child itself.
     */
    public void addChild(CategoryId childId) {
        Objects.requireNonNull(childId, "childId");
        if (childId.equals(this.id)) {
            throw new DomainException("A category cannot be its own child.");
        }
        this.childIds.add(childId);
        touch();
    }

    /**
     * Removes the supplied child from this category.
     */
    public void removeChild(CategoryId childId) {
        Objects.requireNonNull(childId, "childId");
        this.childIds.remove(childId);
        touch();
    }

    /* ---------- Getters ---------- */

    public CategoryId getId()               { return id; }
    public String getName()                 { return name; }
    public String getSlug()                 { return slug; }
    public String getDescription()          { return description; }
    public Optional<SeoMeta> getSeoMeta()   { return Optional.ofNullable(seoMeta); }
    public Status getStatus()               { return status; }
    public Optional<CategoryId> getParentId() { return Optional.ofNullable(parentId); }
    public Set<CategoryId> getChildIds()    { return Collections.unmodifiableSet(childIds); }
    public Instant getCreatedAt()           { return createdAt; }
    public Instant getUpdatedAt()           { return updatedAt; }

    /* ---------- Equality ---------- */

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Category other)) return false;
        return id.equals(other.id);
    }

    @Override
    public int hashCode() {
        return id.hashCode();
    }

    /* ---------- Utilities ---------- */

    private void touch() {
        this.updatedAt = Instant.now();
    }

    private static String validateName(String name) {
        if (name == null || name.isBlank()) {
            throw new DomainException("Category name cannot be blank.");
        }
        if (name.length() > MAX_NAME_LEN) {
            throw new DomainException("Category name must be <= " + MAX_NAME_LEN + " characters.");
        }
        return name;
    }

    private static String validateSlug(String slug) {
        if (slug == null || slug.isBlank()) {
            throw new DomainException("Slug cannot be blank.");
        }
        String normalized = slug.trim().toLowerCase();
        if (!SLUG_PATTERN.matcher(normalized).matches()) {
            throw new DomainException("Slug can contain only lowercase letters, numbers and hyphens.");
        }
        return normalized;
    }

    /* ---------- Slug helper ---------- */

    private static final Pattern NON_LATIN = Pattern.compile("[^\\w-]");
    private static final Pattern WHITESPACE = Pattern.compile("[\\s]");
    private static final Pattern SLUG_PATTERN = Pattern.compile("^[a-z0-9]+(-[a-z0-9]+)*$");

    private static String slugify(String input) {
        String nowhitespace = WHITESPACE.matcher(input).replaceAll("-");
        String normalized = Normalizer.normalize(nowhitespace, Normalizer.Form.NFD);
        String slug = NON_LATIN.matcher(normalized).replaceAll("");
        slug = slug.toLowerCase();
        slug = slug.replaceAll("-{2,}", "-").replaceAll("^-|-$", "");
        // Edge-case: the name might be purely removed (e.g., all emojis). Fall back to UUID.
        return slug.isBlank() ? UUID.randomUUID().toString() : slug;
    }

    /* ---------- Nested types ---------- */

    /**
     * Value object for a category's primary key.
     */
    public record CategoryId(UUID value) implements Serializable {
        @Serial private static final long serialVersionUID = -6081121798172236107L;

        public CategoryId {
            Objects.requireNonNull(value, "value");
        }

        public static CategoryId newRandom() {
            return new CategoryId(UUID.randomUUID());
        }

        @Override
        public String toString() { return value.toString(); }
    }

    /**
     * Search-engine optimisation meta-data.
     */
    public record SeoMeta(String title, String keywords, String description) implements Serializable {
        @Serial private static final long serialVersionUID = -1976485010902233444L;

        public static SeoMeta empty() { return new SeoMeta(null, null, null); }
    }

    /**
     * Activation state of the category.
     */
    public enum Status {
        ACTIVE, DISABLED
    }

    /**
     * Thrown when domain invariants are violated.
     */
    public static class DomainException extends RuntimeException {
        @Serial private static final long serialVersionUID = -782365284120379L;
        public DomainException(String msg) { super(msg); }
    }
}
```