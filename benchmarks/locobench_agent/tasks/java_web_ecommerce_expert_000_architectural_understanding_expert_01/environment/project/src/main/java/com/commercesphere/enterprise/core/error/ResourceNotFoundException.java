```java
/*
 * Copyright (c) CommerceSphere
 *
 * This file is part of CommerceSphere Enterprise Suite.
 * 
 * CommerceSphere Enterprise Suite is proprietary software; you may not use, copy,
 * reproduce, modify or distribute this software except in compliance with the terms
 * and conditions set forth in the applicable commercial license agreement.
 */

package com.commercesphere.enterprise.core.error;

import java.net.URI;
import java.time.Instant;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.ResponseStatus;

/**
 * Thrown to indicate that a requested resource does not exist in the system.
 * <p>
 * This exception is annotated with {@link ResponseStatus} so that when it is
 * propagated back through a Spring MVC controller stack, a
 * {@code 404 NOT FOUND} HTTP response is returned to the client automatically.
 *
 * <pre>
 * // Example usage within a service layer
 * Customer customer = repository.findById(id)
 *      .orElseThrow(() -> new ResourceNotFoundException("Customer", "id", id));
 * </pre>
 *
 * The class also captures contextual metadata such as the {@code resourceName},
 * {@code fieldName}, and {@code fieldValue} to make troubleshooting easier
 * in production environments.
 */
@ResponseStatus(HttpStatus.NOT_FOUND)
public class ResourceNotFoundException extends RuntimeException {

    private static final long serialVersionUID = 7189967717121251114L;

    private static final String DEFAULT_MESSAGE_TEMPLATE =
            "%s not found with %s: '%s'";

    /**
     * The simple entity name (e.g. {@code "Product"} or {@code "Customer"}).
     */
    private final String resourceName;

    /**
     * The attribute/column/key used to search (e.g. {@code "id"} or {@code "sku"}).
     */
    private final String fieldName;

    /**
     * The value of {@link #fieldName} that was requested.
     */
    private final Object fieldValue;

    /**
     * Optional absolute URI of the resource that was attempted to be resolved.
     * Provided when the caller has sufficient information to build such URI.
     */
    private final URI resourceUri;

    /**
     * Arbitrary, additional metadata that might be helpful for diagnostics.
     * Implemented as an immutable map to maintain thread-safety.
     */
    private final Map<String, Object> metadata;

    /* -----------------------------------------------------------------------
     * Constructors
     * -------------------------------------------------------------------- */

    /**
     * Creates a new {@link ResourceNotFoundException} using the default message
     * template: {@code <Resource> not found with <field>: '<value>'}.
     */
    public ResourceNotFoundException(String resourceName,
                                     String fieldName,
                                     Object fieldValue) {
        this(resourceName, fieldName, fieldValue, null, null);
    }

    /**
     * Creates a fully customized {@link ResourceNotFoundException}.
     *
     * @param resourceName name of the missing entity
     * @param fieldName    the property/key used for lookup
     * @param fieldValue   supplied value for {@code fieldName}
     * @param resourceUri  optional URI that was dereferenced
     * @param metadata     optional diagnostic metadata
     */
    public ResourceNotFoundException(String resourceName,
                                     String fieldName,
                                     Object fieldValue,
                                     URI resourceUri,
                                     Map<String, Object> metadata) {
        super(buildMessage(resourceName, fieldName, fieldValue, resourceUri));
        this.resourceName = Objects.requireNonNull(resourceName, "resourceName");
        this.fieldName    = Objects.requireNonNull(fieldName,    "fieldName");
        this.fieldValue   = fieldValue;
        this.resourceUri  = resourceUri;
        this.metadata     = metadata == null
                ? Collections.emptyMap()
                : Collections.unmodifiableMap(new LinkedHashMap<>(metadata));
    }

    /**
     * Alternative constructor that accepts a custom, pre-formatted message
     * while still capturing contextual fields.
     */
    public ResourceNotFoundException(String message,
                                     String resourceName,
                                     String fieldName,
                                     Object fieldValue,
                                     URI resourceUri,
                                     Map<String, Object> metadata) {
        super(message);
        this.resourceName = Objects.requireNonNull(resourceName, "resourceName");
        this.fieldName    = Objects.requireNonNull(fieldName,    "fieldName");
        this.fieldValue   = fieldValue;
        this.resourceUri  = resourceUri;
        this.metadata     = metadata == null
                ? Collections.emptyMap()
                : Collections.unmodifiableMap(new LinkedHashMap<>(metadata));
    }

    /* -----------------------------------------------------------------------
     * Factory helpers
     * -------------------------------------------------------------------- */

    /**
     * Fluent builder for adding extra metadata.
     *
     * @param key   metadata key
     * @param value metadata value
     * @return a copy of the current exception with the new metadata entry
     */
    public ResourceNotFoundException with(String key, Object value) {
        Objects.requireNonNull(key, "metadata key");
        Map<String, Object> newMeta = new LinkedHashMap<>(this.metadata);
        newMeta.put(key, value);
        return new ResourceNotFoundException(getMessage(),
                                             resourceName,
                                             fieldName,
                                             fieldValue,
                                             resourceUri,
                                             newMeta);
    }

    /**
     * Convenience method for attaching the timestamp at which the exception
     * was created.
     */
    public ResourceNotFoundException stamped() {
        return with("timestamp", Instant.now());
    }

    /* -----------------------------------------------------------------------
     * Getters
     * -------------------------------------------------------------------- */

    public String getResourceName() {
        return resourceName;
    }

    public String getFieldName() {
        return fieldName;
    }

    public Object getFieldValue() {
        return fieldValue;
    }

    public URI getResourceUri() {
        return resourceUri;
    }

    public Map<String, Object> getMetadata() {
        return metadata;
    }

    /**
     * Always returns {@link HttpStatus#NOT_FOUND}.
     */
    public HttpStatus getStatus() {
        return HttpStatus.NOT_FOUND;
    }

    /* -----------------------------------------------------------------------
     * Internal helpers
     * -------------------------------------------------------------------- */

    private static String buildMessage(String resourceName,
                                       String fieldName,
                                       Object fieldValue,
                                       URI resourceUri) {

        String base = String.format(DEFAULT_MESSAGE_TEMPLATE,
                                    resourceName,
                                    fieldName,
                                    Objects.toString(fieldValue, "null"));

        return resourceUri == null ? base : base + " [" + resourceUri + ']';
    }
}
```