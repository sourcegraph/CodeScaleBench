package com.opsforge.nexus.anonymizer.domain.port.in;

import java.io.Closeable;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.Charset;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/**
 * Inbound (driving) port that represents the core use-case for data anonymisation.
 * <p>
 * Implementations MUST be pure application services that orchestrate domain logic only.
 * They MAY delegate to outbound ports (e.g. persistence, SaaS connectors) but MUST NOT
 * depend on any framework–specific concerns (Spring, JPA, etc.).
 *
 * <h3>Thread-Safety</h3>
 * Implementations SHOULD be stateless and thread-safe. Any state required for a single
 * invocation must be confined to the call stack.
 *
 * <h3>Error Handling</h3>
 * All recoverable violations MUST be signalled with a checked {@link AnonymizationException}
 * subclass. Unrecoverable problems (e.g. {@link OutOfMemoryError}) need not be handled.
 */
public interface DataAnonymizationUseCase {

    /**
     * Perform the anonymisation operation defined by the supplied command object and return
     * an immutable {@link AnonymizationResult}.
     *
     * @param command fully-specified anonymisation command
     * @return anonymised result
     * @throws AnonymizationException if the command is semantically invalid or anonymisation fails
     * @throws IOException            if the underlying stream cannot be processed
     */
    AnonymizationResult anonymize(AnonymizationCommand command) throws AnonymizationException, IOException;

    /* --------------------------------------------------------------------- */
    /*                             Helper Types                              */
    /* --------------------------------------------------------------------- */

    /**
     * Enumeration of supported input data formats.  Add new formats here when the
     * core anonymisation engine is enhanced to handle them.
     */
    enum DataFormat {
        CSV,
        JSON,
        XML,
        AVRO,
        PARQUET
    }

    /**
     * A single anonymisation rule describing <em>what</em> to anonymise and <em>how</em>.
     */
    record AnonymizationRule(String fieldPath, Strategy strategy) implements java.io.Serializable {

        public AnonymizationRule {
            Objects.requireNonNull(fieldPath, "fieldPath");
            Objects.requireNonNull(strategy, "strategy");
        }

        /**
         * The supported anonymisation strategies.
         */
        public enum Strategy {
            MASK,     // replace each character with a masking symbol ('*')
            HASH,     // cryptographic hash of the value
            NULLIFY,  // replace with null/blank
            RANDOMIZE // replace with random but valid surrogate value
        }
    }

    /**
     * Command-object (a.k.a. DTO/ValueObject) that fully describes an anonymisation request.
     * <p>Immutable, builder-based and serialisable for safe transport across process boundaries.</p>
     */
    final class AnonymizationCommand implements java.io.Serializable {

        private final InputStream dataStream;
        private final DataFormat dataFormat;
        private final Charset charset;
        private final List<AnonymizationRule> rules;
        private final UUID correlationId;

        private AnonymizationCommand(Builder builder) {
            this.dataStream   = builder.dataStream;
            this.dataFormat   = builder.dataFormat;
            this.charset      = builder.charset;
            this.rules        = Collections.unmodifiableList(new ArrayList<>(builder.rules));
            this.correlationId = builder.correlationId != null
                    ? builder.correlationId
                    : UUID.randomUUID();
        }

        public InputStream getDataStream()     { return dataStream; }
        public DataFormat   getDataFormat()    { return dataFormat; }
        public Charset      getCharset()       { return charset; }
        public List<AnonymizationRule> getRules() { return rules; }
        public UUID         getCorrelationId() { return correlationId; }

        /* ------------------------------ Builder ----------------------------- */

        public static Builder builder() { return new Builder(); }

        public static final class Builder {
            private InputStream dataStream;
            private DataFormat dataFormat;
            private Charset charset = Charset.forName("UTF-8");
            private final List<AnonymizationRule> rules = new ArrayList<>();
            private UUID correlationId;

            private Builder() { /* static factory */ }

            public Builder withDataStream(InputStream dataStream) {
                this.dataStream = dataStream;
                return this;
            }

            public Builder withDataFormat(DataFormat dataFormat) {
                this.dataFormat = dataFormat;
                return this;
            }

            public Builder withCharset(Charset charset) {
                this.charset = charset;
                return this;
            }

            public Builder addRule(AnonymizationRule rule) {
                this.rules.add(rule);
                return this;
            }

            public Builder withRules(List<AnonymizationRule> rules) {
                this.rules.clear();
                this.rules.addAll(rules);
                return this;
            }

            public Builder withCorrelationId(UUID correlationId) {
                this.correlationId = correlationId;
                return this;
            }

            public AnonymizationCommand build() {
                Objects.requireNonNull(dataStream, "dataStream");
                Objects.requireNonNull(dataFormat, "dataFormat");
                if (rules.isEmpty()) {
                    throw new IllegalStateException("At least one anonymisation rule must be provided.");
                }
                return new AnonymizationCommand(this);
            }
        }
    }

    /**
     * Value-object returned by a successful anonymisation invocation.
     * <p>
     * Holds the stream of anonymised data plus a set of useful metrics for auditing purposes.
     */
    final class AnonymizationResult implements Closeable, java.io.Serializable {

        private final InputStream anonymizedStream;
        private final long bytesProcessed;
        private final long anonymizedFieldCount;
        private final Duration processingTime;
        private final String checksumSha256;
        private final UUID correlationId;

        private AnonymizationResult(Builder builder) {
            this.anonymizedStream       = builder.anonymizedStream;
            this.bytesProcessed         = builder.bytesProcessed;
            this.anonymizedFieldCount   = builder.anonymizedFieldCount;
            this.processingTime         = builder.processingTime;
            this.checksumSha256         = builder.checksumSha256;
            this.correlationId          = builder.correlationId;
        }

        public InputStream getAnonymizedStream()     { return anonymizedStream; }
        public long        getBytesProcessed()       { return bytesProcessed; }
        public long        getAnonymizedFieldCount() { return anonymizedFieldCount; }
        public Duration    getProcessingTime()       { return processingTime; }
        public String      getChecksumSha256()       { return checksumSha256; }
        public UUID        getCorrelationId()        { return correlationId; }

        @Override
        public void close() throws IOException {
            anonymizedStream.close();
        }

        /* ------------------------------ Builder ----------------------------- */

        public static Builder builder() { return new Builder(); }

        public static final class Builder {
            private InputStream anonymizedStream;
            private long bytesProcessed;
            private long anonymizedFieldCount;
            private Duration processingTime = Duration.ZERO;
            private String checksumSha256;
            private UUID correlationId;
            private Instant start = Instant.now();

            public Builder startTiming() {
                this.start = Instant.now();
                return this;
            }

            public Builder stopTiming() {
                this.processingTime = Duration.between(start, Instant.now());
                return this;
            }

            public Builder withAnonymizedStream(InputStream anonymizedStream) {
                this.anonymizedStream = anonymizedStream;
                return this;
            }

            public Builder withBytesProcessed(long bytesProcessed) {
                this.bytesProcessed = bytesProcessed;
                return this;
            }

            public Builder withAnonymizedFieldCount(long anonymizedFieldCount) {
                this.anonymizedFieldCount = anonymizedFieldCount;
                return this;
            }

            public Builder withChecksumSha256(String checksumSha256) {
                this.checksumSha256 = checksumSha256;
                return this;
            }

            public Builder withCorrelationId(UUID correlationId) {
                this.correlationId = correlationId;
                return this;
            }

            public AnonymizationResult build() {
                Objects.requireNonNull(anonymizedStream, "anonymizedStream");
                Objects.requireNonNull(checksumSha256, "checksumSha256");
                Objects.requireNonNull(correlationId, "correlationId");
                if (processingTime.isZero()) {
                    stopTiming();
                }
                return new AnonymizationResult(this);
            }
        }
    }

    /* --------------------------------------------------------------------- */
    /*                               Exceptions                              */
    /* --------------------------------------------------------------------- */

    /**
     * Base class for all anonymisation-related checked exceptions.
     */
    class AnonymizationException extends Exception {
        public AnonymizationException(String message) { super(message); }
        public AnonymizationException(String message, Throwable cause) { super(message, cause); }
    }

    /**
     * Indicates that the supplied data format is not supported by the underlying engine.
     */
    class UnsupportedDataFormatException extends AnonymizationException {
        public UnsupportedDataFormatException(DataFormat format) {
            super("Unsupported data format: " + format);
        }
    }

    /**
     * Indicates that one or more anonymisation rules are semantically invalid.
     */
    class InvalidAnonymizationRuleException extends AnonymizationException {
        public InvalidAnonymizationRuleException(String message) { super(message); }
    }
}