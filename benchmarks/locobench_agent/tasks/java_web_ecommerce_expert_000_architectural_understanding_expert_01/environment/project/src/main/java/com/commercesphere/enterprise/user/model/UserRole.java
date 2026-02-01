package com.commercesphere.enterprise.user.model;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonValue;
import org.springframework.security.core.GrantedAuthority;

import javax.persistence.AttributeConverter;
import javax.persistence.Converter;
import java.io.Serializable;
import java.util.Collections;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * UserRole is a Spring-Security compatible {@link GrantedAuthority} that drives
 * role-based authorization across the CommerceSphere Enterprise Suite.
 *
 * <p>Each role comes with a predefined immutable set of {@link Permission permissions}.
 * Custom permissions can still be granted at the account or user level, but these
 * defaults guarantee that a fresh installation behaves as expected.</p>
 *
 * <p>The enum is JPA-aware via the {@link UserRoleConverter} and
 * JSON-friendly thanks to Jackson annotations, making it suitable for persistence
 * as well as REST payloads.</p>
 */
@SuppressWarnings("unused")
public enum UserRole implements GrantedAuthority, Serializable {

    /**
     * Root administrator with unrestricted access to every module in the system.
     */
    SUPER_ADMIN(
            "ROLE_SUPER_ADMIN",
            "Super Administrator",
            "Full access to all platform capabilities, including high-risk operations " +
            "such as payment key rotation and irreversible data purges.",
            EnumSet.allOf(Permission.class)),

    /**
     * Organization-specific administrator who manages users, catalogs and settings
     * but is restricted from system-wide, infrastructure-level actions.
     */
    ACCOUNT_ADMIN(
            "ROLE_ACCOUNT_ADMIN",
            "Account Administrator",
            "Manages account-scoped resources like users, catalogs, and pricing policies.",
            EnumSet.of(
                    Permission.VIEW_USERS,
                    Permission.MANAGE_USERS,
                    Permission.VIEW_PRODUCTS,
                    Permission.MANAGE_PRODUCTS,
                    Permission.VIEW_ORDERS,
                    Permission.MANAGE_ORDERS,
                    Permission.VIEW_PRICING,
                    Permission.MANAGE_PRICING
            )),

    /**
     * Sales representative capable of generating quotes and placing orders on behalf of
     * assigned customers.
     */
    SALES_REP(
            "ROLE_SALES_REP",
            "Sales Representative",
            "Creates quotes, negotiates pricing, and places orders on behalf of customers.",
            EnumSet.of(
                    Permission.VIEW_PRODUCTS,
                    Permission.VIEW_PRICING,
                    Permission.CREATE_QUOTE,
                    Permission.PLACE_ORDER,
                    Permission.VIEW_ORDERS
            )),

    /**
     * Approver responsible for order approval flows within tiered buying models.
     */
    APPROVER(
            "ROLE_APPROVER",
            "Order Approver",
            "Approves or rejects orders according to the organization's workflow rules.",
            EnumSet.of(
                    Permission.VIEW_ORDERS,
                    Permission.APPROVE_ORDER,
                    Permission.REJECT_ORDER
            )),

    /**
     * Financial manager with access to payment reconciliation and invoicing modules.
     */
    FINANCE_MANAGER(
            "ROLE_FINANCE_MANAGER",
            "Finance Manager",
            "Views payment information, issues refunds, and reconciles invoices.",
            EnumSet.of(
                    Permission.VIEW_PAYMENTS,
                    Permission.PROCESS_REFUND,
                    Permission.VIEW_INVOICES,
                    Permission.VIEW_REPORTS
            )),

    /**
     * Authenticated buyer with the ability to browse the catalog and submit orders
     * within an approval chain.
     */
    BUYER(
            "ROLE_BUYER",
            "Buyer",
            "Places orders subject to approval rules and contract pricing.",
            EnumSet.of(
                    Permission.VIEW_PRODUCTS,
                    Permission.VIEW_PRICING,
                    Permission.PLACE_ORDER,
                    Permission.VIEW_ORDERS
            )),

    /**
     * Anonymous or read-only user; has the most limited permissions.
     */
    GUEST(
            "ROLE_GUEST",
            "Guest",
            "Unauthenticated, read-only access to public resources.",
            EnumSet.of(
                    Permission.VIEW_PRODUCTS
            ));

    // -----------------------------------------------------------------------
    // Fields
    // -----------------------------------------------------------------------

    private static final Map<String, UserRole> CODE_INDEX = new HashMap<>();

    static {
        for (UserRole role : values()) {
            CODE_INDEX.put(role.code, role);
        }
    }

    private final String code;
    private final String label;
    private final String description;
    private final Set<Permission> defaultPermissions;

    // -----------------------------------------------------------------------
    // Constructor
    // -----------------------------------------------------------------------

    UserRole(String code,
             String label,
             String description,
             Set<Permission> defaultPermissions) {

        this.code = code;
        this.label = label;
        this.description = description;
        // Ensure immutability
        this.defaultPermissions = Collections.unmodifiableSet(defaultPermissions);
    }

    // -----------------------------------------------------------------------
    // Public API
    // -----------------------------------------------------------------------

    /**
     * Jackson & Spring-Security representation of the role.
     */
    @Override
    @JsonValue
    public String getAuthority() {
        return code;
    }

    public String getCode() {
        return code;
    }

    public String getLabel() {
        return label;
    }

    public String getDescription() {
        return description;
    }

    /**
     * Immutable default permission set associated with this role.
     */
    public Set<Permission> getDefaultPermissions() {
        return defaultPermissions;
    }

    /**
     * Convenience wrapper to check whether the role's default permission set
     * includes the supplied permission.
     */
    public boolean hasPermission(Permission permission) {
        return defaultPermissions.contains(permission);
    }

    /**
     * Performs a case-insensitive lookup by role code.
     *
     * @throws IllegalArgumentException if the code is unknown.
     */
    @JsonCreator
    public static UserRole fromCode(String code) {
        if (code == null) {
            throw new IllegalArgumentException("Role code cannot be null");
        }
        UserRole role = CODE_INDEX.get(code.toUpperCase());
        if (role == null) {
            throw new IllegalArgumentException("Unknown role code: " + code);
        }
        return role;
    }

    // -----------------------------------------------------------------------
    // Object Overrides
    // -----------------------------------------------------------------------

    @Override
    public String toString() {
        return code;
    }

    // Enums already implement equals/hashCode based on identity; no override needed.

    // -----------------------------------------------------------------------
    // JPA Converter
    // -----------------------------------------------------------------------

    /**
     * JPA {@link AttributeConverter} to persist the enum code as a VARCHAR column
     * and restore the enum from the stored value.
     */
    @Converter(autoApply = true)
    public static class UserRoleConverter implements AttributeConverter<UserRole, String> {

        @Override
        public String convertToDatabaseColumn(UserRole attribute) {
            return attribute != null ? attribute.code : null;
        }

        @Override
        public UserRole convertToEntityAttribute(String dbData) {
            return dbData != null ? UserRole.fromCode(dbData) : null;
        }
    }

    // -----------------------------------------------------------------------
    // Nested Permission Enum
    // -----------------------------------------------------------------------

    /**
     * A curated list of coarse-grained permissions used across the platform.
     * <p>
     * These are intentionally kept generic; more granular, resource-level ACLs
     * are handled by the Policy Engine subsystem.
     * </p>
     */
    public enum Permission {

        // Catalog & Product Management
        VIEW_PRODUCTS,
        MANAGE_PRODUCTS,

        // Pricing
        VIEW_PRICING,
        MANAGE_PRICING,

        // User & Account Management
        VIEW_USERS,
        MANAGE_USERS,

        // Orders & Quotes
        VIEW_ORDERS,
        MANAGE_ORDERS,
        CREATE_QUOTE,
        PLACE_ORDER,
        APPROVE_ORDER,
        REJECT_ORDER,

        // Payments & Finance
        VIEW_PAYMENTS,
        PROCESS_REFUND,
        VIEW_INVOICES,

        // Reporting
        VIEW_REPORTS,

        // Catch-all
        ALL  // Only used by SUPER_ADMIN
    }

    // -----------------------------------------------------------------------
    // Utility Methods
    // -----------------------------------------------------------------------

    /**
     * Returns true when the provided role is higher in the hierarchy than this role.
     * The natural enum declaration order dictates hierarchy precedence.
     */
    public boolean isHigherThan(UserRole other) {
        Objects.requireNonNull(other, "Other role may not be null");
        return this.ordinal() < other.ordinal();
    }

    /**
     * Returns true when the provided role is lower in the hierarchy than this role.
     */
    public boolean isLowerThan(UserRole other) {
        Objects.requireNonNull(other, "Other role may not be null");
        return this.ordinal() > other.ordinal();
    }

    /**
     * Elevates the current role to a higher one if allowed, otherwise returns itself.
     * The method is safe-guarded to avoid skipping multiple levels in one call.
     *
     * @throws IllegalStateException if an attempt is made to elevate past SUPER_ADMIN.
     */
    public UserRole elevate() {
        if (this == SUPER_ADMIN) {
            throw new IllegalStateException("SUPER_ADMIN cannot be elevated further.");
        }
        return values()[this.ordinal() - 1];
    }
}