package com.opsforge.nexus.common.exception;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;

/**
 * Thrown when a requested resource cannot be located within the system.
 * <p>
 * OpsForge utilities resolve resources by their unique identifiers.  This
 * exception is raised when a lookup fails and the requested entity does not
 * exist or is no longer available.  The class is intentionally <em>rich</em>;
 * besides the canonical exception message it captures contextual metadata
 * that can be rendered by HTTP or GraphQL adapters, logged by observability
 * interceptors, or forwarded across service boundaries.
 *
 * <pre>{@code
 * throw new ResourceNotFoundException(
 *         "conversionJob",
 *         Map.of("jobId", uuid))
 * }</pre>
 */
public class ResourceNotFoundException extends RuntimeException {

    private static final long serialVersionUID = -4439732998127132711L;

    /**
     * A human-readable resource label (e.g. {@code "user"}, {@code "document"}).
     */
    private final String resource;

    /**
     * A map of the lookup keys used when the resource was requested.  The map
     * is preserved <strong>verbatim</strong> so that a downstream handler can
     * decide what, if anything, should be redacted before returning a payload
     * to the client.
     */
    private final Map<String, Object> identifiers;

    /**
     * Optional cross-service error code that adheres to OpsForge’s central
     * error taxonomy.  When provided, gateway and UI layers can localize the
     * error without having to inspect the textual message.
     */
    private final String errorCode;

    /**
     * Creates a new {@code ResourceNotFoundException}.
     *
     * @param resource    the logical name of the resource
     * @param identifiers the keys used to locate the resource
     */
    public ResourceNotFoundException(final String resource,
                                     final Map<String, ?> identifiers) {
        this(resource, identifiers, null, null);
    }

    /**
     * Creates a new {@code ResourceNotFoundException} with an explicit error
     * code recognised by the OpsForge platform.
     *
     * @param resource    the logical name of the resource
     * @param identifiers the keys used to locate the resource
     * @param errorCode   a platform-wide error code, may be {@code null}
     */
    public ResourceNotFoundException(final String resource,
                                     final Map<String, ?> identifiers,
                                     final String errorCode) {
        this(resource, identifiers, errorCode, null);
    }

    /**
     * Creates a fully specified {@code ResourceNotFoundException}.
     *
     * @param resource     the logical name of the resource
     * @param identifiers  the keys used to locate the resource
     * @param errorCode    a platform-wide error code, may be {@code null}
     * @param cause        underlying cause, may be {@code null}
     */
    public ResourceNotFoundException(final String resource,
                                     final Map<String, ?> identifiers,
                                     final String errorCode,
                                     final Throwable cause) {
        super(buildMessage(resource, identifiers), cause);
        this.resource = Objects.requireNonNull(resource, "resource must not be null");
        this.identifiers = Collections.unmodifiableMap(
                identifiers == null ? Map.of() : new LinkedHashMap<>(identifiers));
        this.errorCode = errorCode;
    }

    /**
     * Builds the canonical exception message.  The resulting string is stable
     * so that alerting tools can deduplicate occurrences.
     */
    private static String buildMessage(final String resource,
                                       final Map<String, ?> identifiers) {
        final var builder = new StringBuilder("Resource '")
                .append(resource)
                .append("' not found");
        if (identifiers != null && !identifiers.isEmpty()) {
            builder.append(" for ").append(identifiers);
        }
        return builder.toString();
    }

    // ---------------------------------------------------------------------
    // Accessors
    // ---------------------------------------------------------------------

    public String getResource() {
        return resource;
    }

    public Map<String, Object> getIdentifiers() {
        return identifiers;
    }

    public String getErrorCode() {
        return errorCode;
    }

    // ---------------------------------------------------------------------
    // Utility
    // ---------------------------------------------------------------------

    /**
     * Converts the exception into a machine-readable error response that can
     * be serialized by a controller/adaptor.  The method purposely refrains
     * from using any framework-specific types (e.g. Spring’s {@code ResponseEntity})
     * to keep the common-library decoupled from presentation layers.
     */
    public Map<String, Object> toPayload() {
        final var payload = new LinkedHashMap<String, Object>();
        payload.put("message", getMessage());
        payload.put("resource", resource);
        payload.put("identifiers", identifiers);
        if (errorCode != null) {
            payload.put("errorCode", errorCode);
        }
        return payload;
    }

    @Override
    public String toString() {
        return "ResourceNotFoundException{" +
               "resource='" + resource + '\'' +
               ", identifiers=" + identifiers +
               (errorCode != null ? ", errorCode='" + errorCode + '\'' : "") +
               '}';
    }
}