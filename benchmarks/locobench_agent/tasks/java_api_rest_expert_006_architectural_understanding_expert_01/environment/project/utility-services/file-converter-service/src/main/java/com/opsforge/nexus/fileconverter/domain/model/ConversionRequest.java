package com.opsforge.nexus.fileconverter.domain.model;

import java.io.Serial;
import java.io.Serializable;
import java.time.Instant;
import java.util.Collections;
import java.util.EnumSet;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

/**
 * Domain model representing a request to convert a file from one {@link FileFormat} to another.
 * <p>
 * This class is intentionally immutable to guarantee thread–safety and to ensure that the request
 * received by the application layer cannot be altered by accident during processing.
 * <p>
 * The class performs basic invariants validation through its factory method, keeping hexagonal
 * architecture principles by avoiding dependencies on external frameworks or technologies.
 */
public final class ConversionRequest implements Serializable {

    @Serial
    private static final long serialVersionUID = -2413852361238422204L;

    private final ConversionRequestId requestId;
    private final FileFormat sourceFormat;
    private final FileFormat targetFormat;
    private final byte[] payload;                       // Original content to be converted
    private final Instant createdAt;                   // Timestamp when the request was issued
    private final Map<String, String> options;         // Optional converter-specific parameters

    /**
     * Private constructor – use {@link #of(FileFormat, FileFormat, byte[], Map)} or {@link #builder()}
     * to create an instance.
     */
    private ConversionRequest(
            final ConversionRequestId requestId,
            final FileFormat sourceFormat,
            final FileFormat targetFormat,
            final byte[] payload,
            final Instant createdAt,
            final Map<String, String> options
    ) {
        this.requestId    = requestId;
        this.sourceFormat = sourceFormat;
        this.targetFormat = targetFormat;
        this.payload      = payload;
        this.createdAt    = createdAt;
        this.options      = options;
    }

    /* =======================================================================
     *  Static factory helpers
     * ===================================================================== */

    /**
     * Creates a new {@link ConversionRequest} instance while generating a random {@link ConversionRequestId}.
     *
     * @param sourceFormat Original file format.
     * @param targetFormat Target file format.
     * @param payload      File bytes. Cannot be {@code null} or empty.
     * @param options      Optional parameters. Can be {@code null}.
     * @return A validated, immutable {@link ConversionRequest}.
     * @throws IllegalArgumentException if validation fails.
     */
    public static ConversionRequest of(
            final FileFormat sourceFormat,
            final FileFormat targetFormat,
            final byte[] payload,
            final Map<String, String> options
    ) {
        return builder()
                .sourceFormat(sourceFormat)
                .targetFormat(targetFormat)
                .payload(payload)
                .options(options)
                .build();
    }

    /**
     * Returns a new builder.
     */
    public static Builder builder() {
        return new Builder();
    }

    /* =======================================================================
     *  Getters
     * ===================================================================== */

    public ConversionRequestId getRequestId() {
        return requestId;
    }

    public FileFormat getSourceFormat() {
        return sourceFormat;
    }

    public FileFormat getTargetFormat() {
        return targetFormat;
    }

    /**
     * Returns a defensive copy of the original file bytes.
     */
    public byte[] getPayload() {
        return payload.clone();
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    /**
     * Returns an unmodifiable view of the options map. May be empty.
     */
    public Map<String, String> getOptions() {
        return options;
    }

    /**
     * Convenience accessor for retrieving a single conversion option.
     */
    public Optional<String> getOption(final String key) {
        return Optional.ofNullable(options.get(key));
    }

    /* =======================================================================
     *  Domain behaviour
     * ===================================================================== */

    /**
     * Returns the size of the payload in bytes.
     */
    public long sizeInBytes() {
        return payload.length;
    }

    /**
     * In‐line validation logic centralised in a single place in order to avoid
     * scattering invariants checks across the project.
     */
    private static void validate(
            final FileFormat sourceFormat,
            final FileFormat targetFormat,
            final byte[] payload
    ) {
        Objects.requireNonNull(sourceFormat,  "sourceFormat cannot be null");
        Objects.requireNonNull(targetFormat,  "targetFormat cannot be null");
        Objects.requireNonNull(payload,       "payload cannot be null");

        if (payload.length == 0) {
            throw new IllegalArgumentException("payload cannot be empty");
        }
        if (sourceFormat == targetFormat) {
            throw new IllegalArgumentException("sourceFormat and targetFormat must differ");
        }
        if (!ConverterCapabilityRegistry.isConversionSupported(sourceFormat, targetFormat)) {
            throw new IllegalArgumentException("Unsupported conversion: " + sourceFormat + " → " + targetFormat);
        }
    }

    /* =======================================================================
     *  Value object overrides
     * ===================================================================== */

    @Override
    public boolean equals(final Object o) {
        if (this == o) { return true; }
        if (!(o instanceof ConversionRequest that)) { return false; }
        return requestId.equals(that.requestId);
    }

    @Override
    public int hashCode() {
        return requestId.hashCode();
    }

    @Override
    public String toString() {
        return "ConversionRequest{" +
                "requestId=" + requestId +
                ", sourceFormat=" + sourceFormat +
                ", targetFormat=" + targetFormat +
                ", createdAt=" + createdAt +
                ", size=" + payload.length + " bytes" +
                '}';
    }

    /* =======================================================================
     *  Builder implementation
     * ===================================================================== */

    public static final class Builder {

        private ConversionRequestId requestId;
        private FileFormat sourceFormat;
        private FileFormat targetFormat;
        private byte[] payload;
        private Instant createdAt;
        private Map<String, String> options;

        private Builder() {
            // Default initialisation
            requestId = new ConversionRequestId(UUID.randomUUID());
            createdAt = Instant.now();
            options   = Collections.emptyMap();
        }

        public Builder requestId(final UUID uuid) {
            this.requestId = new ConversionRequestId(uuid);
            return this;
        }

        public Builder sourceFormat(final FileFormat format) {
            this.sourceFormat = format;
            return this;
        }

        public Builder targetFormat(final FileFormat format) {
            this.targetFormat = format;
            return this;
        }

        public Builder payload(final byte[] bytes) {
            this.payload = bytes != null ? bytes.clone() : null;
            return this;
        }

        public Builder options(final Map<String, String> opts) {
            if (opts == null || opts.isEmpty()) {
                this.options = Collections.emptyMap();
            } else {
                this.options = Collections.unmodifiableMap(Map.copyOf(opts));
            }
            return this;
        }

        public Builder createdAt(final Instant instant) {
            this.createdAt = instant;
            return this;
        }

        /**
         * Validates all mandatory fields and builds a {@link ConversionRequest}.
         *
         * @throws IllegalArgumentException if validation fails
         */
        public ConversionRequest build() {
            validate(sourceFormat, targetFormat, payload);
            return new ConversionRequest(
                    requestId,
                    sourceFormat,
                    targetFormat,
                    payload.clone(),   // defensive copy
                    createdAt,
                    options
            );
        }
    }

    /* =======================================================================
     *  Nested value types
     * ===================================================================== */

    /**
     * Strongly-typed ID to avoid primitive obsession.
     */
    public record ConversionRequestId(UUID value) implements Serializable {

        @Serial
        private static final long serialVersionUID = -5718183685531633070L;

        public ConversionRequestId {
            Objects.requireNonNull(value, "ConversionRequestId value cannot be null");
        }

        @Override
        public String toString() {
            return value.toString();
        }
    }

    /**
     * Enumeration of file formats supported by the file-converter service.
     * <p>
     * Only generic types were modelled for brevity; new values can be added without
     * affecting external clients since they are part of the internal domain model.
     */
    public enum FileFormat {
        TXT("text/plain"),
        CSV("text/csv"),
        JSON("application/json"),
        XML("application/xml"),
        YAML("application/x-yaml"),
        PDF("application/pdf"),
        DOCX("application/vnd.openxmlformats-officedocument.wordprocessingml.document");

        private final String mimeType;

        FileFormat(final String mimeType) {
            this.mimeType = mimeType;
        }

        public String mimeType() {
            return mimeType;
        }
    }

    /**
     * Extremely light-weight registry describing which conversions the service can handle.
     * In a real-world scenario this would probably query an external system or configuration file.
     * For now it is kept simple, in-memory, and synchronous.
     */
    private static final class ConverterCapabilityRegistry {

        // This could be loaded from configuration or discovered at runtime
        private static final Set<ConversionPair> SUPPORTED_CONVERSIONS = Set.of(
                new ConversionPair(FileFormat.TXT,  FileFormat.PDF),
                new ConversionPair(FileFormat.CSV,  FileFormat.JSON),
                new ConversionPair(FileFormat.JSON, FileFormat.CSV),
                new ConversionPair(FileFormat.XML,  FileFormat.JSON),
                new ConversionPair(FileFormat.JSON, FileFormat.XML),
                new ConversionPair(FileFormat.DOCX, FileFormat.PDF)
        );

        private ConverterCapabilityRegistry() { /* static helper */ }

        public static boolean isConversionSupported(final FileFormat source, final FileFormat target) {
            return SUPPORTED_CONVERSIONS.contains(new ConversionPair(source, target));
        }

        private record ConversionPair(FileFormat src, FileFormat tgt) {

            // Pre-compute hashCode because the record will be used in a HashSet
            private static final int HASH = Objects.hash(FileFormat.class, FileFormat.class);

            @Override
            public int hashCode() {
                return HASH ^ Objects.hash(src, tgt);
            }
        }
    }
}