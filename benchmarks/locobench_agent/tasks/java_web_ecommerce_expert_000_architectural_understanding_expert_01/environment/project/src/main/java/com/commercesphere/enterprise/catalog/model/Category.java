package com.commercesphere.enterprise.catalog.model;

import com.fasterxml.jackson.annotation.JsonIdentityInfo;
import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.ObjectIdGenerators;
import org.apache.commons.lang3.StringUtils;
import org.hibernate.annotations.Cache;
import org.hibernate.annotations.CacheConcurrencyStrategy;

import javax.persistence.*;
import java.io.Serial;
import java.io.Serializable;
import java.time.LocalDateTime;
import java.util.*;

/**
 * Category represents a hierarchical classification for products within the
 * CommerceSphere Enterprise Suite catalog. Categories can be nested to an
 * arbitrary depth, allowing merchant administrators to organize assortments
 * in a tree structure (e.g. "Apparel > Men's > Shirts").
 *
 * <p>This entity is designed for read-heavy workloads and therefore leverages
 * Hibernate second-level caching. To prevent cyclic references during JSON
 * serialization, {@link JsonIdentityInfo} is used.</p>
 */
@Entity
@Table(name = "categories",
       indexes = {
           @Index(name = "idx_category_slug", columnList = "slug", unique = true),
           @Index(name = "idx_category_parent", columnList = "parent_id")
       })
@Cacheable
@Cache(usage = CacheConcurrencyStrategy.READ_WRITE)
@JsonIdentityInfo(generator = ObjectIdGenerators.PropertyGenerator.class, property = "id")
public class Category implements Serializable {

    @Serial
    private static final long serialVersionUID = 3410189886999809149L;

    // -------------- Core Attributes --------------------------------------------------------------

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /**
     * Human-readable, localized name of the category.
     */
    @Column(nullable = false, length = 200)
    private String name;

    /**
     * Optional, longer form description displayed on category landing pages.
     */
    @Column(length = 4000)
    private String description;

    /**
     * SEO-friendly slug used for storefront URL routing. Must be unique.
     */
    @Column(nullable = false, length = 256, unique = true, updatable = false)
    private String slug;

    /**
     * Determines whether the category is visible in the storefront.
     */
    @Column(nullable = false)
    private boolean active = true;

    /**
     * Used to explicitly order sibling categories in navigation menus.
     * Lower values appear first.
     */
    @Column(name = "display_order", nullable = false)
    private int displayOrder = 0;

    // -------------- Hierarchical Mapping ---------------------------------------------------------

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "parent_id")
    private Category parent;

    /**
     * Children are loaded lazily to avoid performance penalties when
     * retrieving a category tree root for navigation menus.
     */
    @OneToMany(mappedBy = "parent",
               cascade = CascadeType.ALL,
               orphanRemoval = true,
               fetch = FetchType.LAZY)
    @OrderBy("displayOrder asc")
    @Cache(usage = CacheConcurrencyStrategy.READ_WRITE)
    private Set<Category> children = new LinkedHashSet<>();

    // -------------- Audit Columns ----------------------------------------------------------------

    @Column(name = "created_at", nullable = false, updatable = false)
    private LocalDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private LocalDateTime updatedAt;

    /**
     * For optimistic locking—increments automatically on each update statement.
     */
    @Version
    private long version;

    // -------------- Constructors ----------------------------------------------------------------

    protected Category() {
        /* Required by JPA */
    }

    private Category(Builder builder) {
        this.name         = builder.name;
        this.description  = builder.description;
        this.active       = builder.active;
        this.displayOrder = builder.displayOrder;
        this.parent       = builder.parent;

        // slug is generated only once at creation time
        this.slug = SlugUtil.toSlug(builder.name);
    }

    // -------------- Domain Logic -----------------------------------------------------------------

    /**
     * Adds a category as a child of this category. Both sides of the
     * bidirectional relationship are synchronized.
     *
     * @param child Child category to attach.
     * @throws IllegalArgumentException if {@code child} is {@code null} or references this node.
     * @throws IllegalStateException    if the hierarchy would contain cycles.
     */
    public void addChild(Category child) {
        validateChild(child);
        child.setParent(this);
        children.add(child);
    }

    /**
     * Removes a child category, maintaining referential integrity.
     *
     * @param child Child to remove.
     */
    public void removeChild(Category child) {
        if (child == null) {
            return;
        }
        if (children.remove(child)) {
            child.setParent(null);
        }
    }

    /**
     * Calculates the breadcrumb path from the root category down to this category.
     *
     * @return Immutable list representing the path, excluding {@code null}s, first element is the root.
     */
    public List<Category> breadcrumb() {
        LinkedList<Category> breadcrumbs = new LinkedList<>();
        Category current = this;
        while (current != null) {
            breadcrumbs.addFirst(current);
            current = current.parent;
        }
        return Collections.unmodifiableList(breadcrumbs);
    }

    /**
     * Convenience helper to determine if this category is a top-level node.
     */
    public boolean isRoot() {
        return parent == null;
    }

    /**
     * Reactivates the category, making it visible in storefront navigations.
     */
    public void activate() {
        this.active = true;
    }

    /**
     * Deactivates the category, removing it from storefront navigations.
     */
    public void deactivate() {
        this.active = false;
    }

    // -------------- Getters & Setters -------------------------------------------------------------

    public Long getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public void setName(String name) {
        if (StringUtils.isBlank(name)) {
            throw new IllegalArgumentException("Category name may not be blank.");
        }
        this.name = name;

        // Disallow slug regeneration after persist to prevent URL breaks.
        if (id == null) { // new entity
            this.slug = SlugUtil.toSlug(name);
        }
    }

    public String getDescription() {
        return description;
    }

    public void setDescription(String description) {
        this.description = description;
    }

    public String getSlug() {
        return slug;
    }

    public boolean isActive() {
        return active;
    }

    public int getDisplayOrder() {
        return displayOrder;
    }

    public void setDisplayOrder(int displayOrder) {
        this.displayOrder = displayOrder;
    }

    public Category getParent() {
        return parent;
    }

    private void setParent(Category parent) {
        this.parent = parent;
    }

    @JsonIgnore
    public Set<Category> getChildren() {
        return Collections.unmodifiableSet(children);
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }

    // -------------- JPA Lifecycle Callbacks -------------------------------------------------------

    @PrePersist
    private void beforeInsert() {
        this.createdAt = LocalDateTime.now();
        this.updatedAt = this.createdAt;
    }

    @PreUpdate
    private void beforeUpdate() {
        this.updatedAt = LocalDateTime.now();
    }

    // -------------- Equality  ---------------------------------------------------------------------

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Category category)) return false;
        // Persistent identity
        return id != null && id.equals(category.id);
    }

    @Override
    public int hashCode() {
        return Objects.hashCode(id);
    }

    // -------------- Builder -----------------------------------------------------------------------

    /**
     * Builder for immutable construction of {@link Category} instances.
     */
    public static class Builder {
        private String   name;
        private String   description;
        private boolean  active       = true;
        private int      displayOrder = 0;
        private Category parent;

        public Builder name(String name) {
            this.name = name;
            return this;
        }

        public Builder description(String description) {
            this.description = description;
            return this;
        }

        public Builder active(boolean active) {
            this.active = active;
            return this;
        }

        public Builder displayOrder(int displayOrder) {
            this.displayOrder = displayOrder;
            return this;
        }

        public Builder parent(Category parent) {
            this.parent = parent;
            return this;
        }

        /**
         * Builds a new {@link Category}. Validation is executed before the
         * object is instantiated.
         */
        public Category build() {
            if (StringUtils.isBlank(name)) {
                throw new IllegalStateException("Category name is mandatory.");
            }
            return new Category(this);
        }
    }

    // -------------- Private Helpers ---------------------------------------------------------------

    /**
     * Ensures child hierarchy rules are respected.
     */
    private void validateChild(Category child) {
        if (child == null) {
            throw new IllegalArgumentException("Child category cannot be null.");
        }
        if (child == this) {
            throw new IllegalArgumentException("Category cannot be its own child.");
        }
        if (isAncestorOf(child)) {
            throw new IllegalStateException("Circular category hierarchy detected.");
        }
    }

    /**
     * Returns {@code true} if this category is an ancestor of the supplied node.
     */
    private boolean isAncestorOf(Category node) {
        Category current = node;
        while (current != null) {
            if (current == this) {
                return true;
            }
            current = current.getParent();
        }
        return false;
    }

    // -------------- Utility -----------------------------------------------------------------------

    /**
     * SlugUtil is a lightweight, local helper class to generate SEO-friendly slugs.
     * Extracted here to avoid pulling in large third-party dependencies.
     */
    private static final class SlugUtil {
        private static final String NON_LATIN = "[^\\w-]";
        private static final String WHITESPACE = "[\\s]";
        private static final int MAX_LENGTH = 100;

        private SlugUtil() {
        }

        static String toSlug(String input) {
            if (StringUtils.isBlank(input)) {
                throw new IllegalArgumentException("Slug input cannot be blank.");
            }
            String nowhitespace = input.trim().replaceAll(WHITESPACE, "-");
            String normalized = java.text.Normalizer.normalize(nowhitespace, java.text.Normalizer.Form.NFD);
            String slug = normalized.replaceAll(NON_LATIN, "")
                                    .replaceAll("[-]{2,}", "-")    // collapse consecutive dashes
                                    .toLowerCase(Locale.ROOT);
            if (slug.length() > MAX_LENGTH) {
                slug = slug.substring(0, MAX_LENGTH);
            }
            return slug;
        }
    }
}