package com.opsforge.nexus.anonymizer.adapter.in.web.dto;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.opsforge.nexus.anonymizer.domain.model.AnonymizationStrategy;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import java.io.Serial;
import java.io.Serializable;
import java.time.OffsetDateTime;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * DTO representing an anonymization request received through the web layer.
 * <p>
 * The class is intentionally immutable and leverages constructor injection so
 * that Jakarta Bean Validation can be applied directly to the incoming payload
 * before it reaches deeper layers within the service.
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public final class AnonymizationRequestDto implements Serializable {

    @Serial
    private static final long serialVersionUID = 8719283741234L;

    @NotNull(message = "requestId must be supplied to support idempotency")
    @Size(min = 1, max = 64, message = "requestId length must be between 1 and 64 characters")
    private final String requestId;

    @NotNull(message = "strategy must be provided")
    private final AnonymizationStrategy strategy;

    private final boolean dryRun;

    @NotEmpty(message = "At least one data set must be supplied")
    @Valid
    private final List<DataSetDto> datasets;

    /**
     * Strategy-specific parameters to fine-tune the anonymization process.
     * Will be passed through verbatim to the application layer.
     */
    private final Map<String, Object> parameters;

    /**
     * Timestamp captured at request submission to assist with audit logging
     * and request-tracking correlations.
     */
    private final OffsetDateTime requestedAt;

    @JsonCreator
    public AnonymizationRequestDto(
            @JsonProperty("requestId") String requestId,
            @JsonProperty("strategy") AnonymizationStrategy strategy,
            @JsonProperty("dryRun") Boolean dryRun,
            @JsonProperty("datasets") List<DataSetDto> datasets,
            @JsonProperty("parameters") Map<String, Object> parameters,
            @JsonProperty("requestedAt") OffsetDateTime requestedAt) {

        this.requestId   = requestId;
        this.strategy    = strategy;
        this.dryRun      = dryRun != null && dryRun;
        this.datasets    = datasets   == null ? Collections.emptyList() : List.copyOf(datasets);
        this.parameters  = parameters == null ? Collections.emptyMap()  : Map.copyOf(parameters);
        this.requestedAt = requestedAt == null ? OffsetDateTime.now()   : requestedAt;
    }

    public String getRequestId() {
        return requestId;
    }

    public AnonymizationStrategy getStrategy() {
        return strategy;
    }

    public boolean isDryRun() {
        return dryRun;
    }

    public List<DataSetDto> getDatasets() {
        return datasets;
    }

    public Map<String, Object> getParameters() {
        return parameters;
    }

    public OffsetDateTime getRequestedAt() {
        return requestedAt;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof AnonymizationRequestDto that)) return false;
        return dryRun == that.dryRun
                && Objects.equals(requestId, that.requestId)
                && strategy == that.strategy
                && Objects.equals(datasets, that.datasets)
                && Objects.equals(parameters, that.parameters)
                && Objects.equals(requestedAt, that.requestedAt);
    }

    @Override
    public int hashCode() {
        return Objects.hash(requestId, strategy, dryRun, datasets, parameters, requestedAt);
    }

    @Override
    public String toString() {
        return "AnonymizationRequestDto{" +
                "requestId='" + requestId + '\'' +
                ", strategy=" + strategy +
                ", dryRun=" + dryRun +
                ", datasets=" + datasets +
                ", parameters=" + parameters +
                ", requestedAt=" + requestedAt +
                '}';
    }

    /**
     * Builder for {@link AnonymizationRequestDto}.
     */
    public static Builder builder() {
        return new Builder();
    }

    public static final class Builder {

        private String requestId;
        private AnonymizationStrategy strategy;
        private boolean dryRun;
        private List<DataSetDto> datasets;
        private Map<String, Object> parameters;
        private OffsetDateTime requestedAt;

        private Builder() { }

        public Builder requestId(String requestId) {
            this.requestId = requestId;
            return this;
        }

        public Builder strategy(AnonymizationStrategy strategy) {
            this.strategy = strategy;
            return this;
        }

        public Builder dryRun(boolean dryRun) {
            this.dryRun = dryRun;
            return this;
        }

        public Builder datasets(List<DataSetDto> datasets) {
            this.datasets = datasets;
            return this;
        }

        public Builder parameters(Map<String, Object> parameters) {
            this.parameters = parameters;
            return this;
        }

        public Builder requestedAt(OffsetDateTime requestedAt) {
            this.requestedAt = requestedAt;
            return this;
        }

        public AnonymizationRequestDto build() {
            return new AnonymizationRequestDto(
                    requestId,
                    strategy,
                    dryRun,
                    datasets,
                    parameters,
                    requestedAt
            );
        }
    }

    /**
     * Nested DTO describing a single input data set that needs anonymization.
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static final class DataSetDto implements Serializable {

        @Serial
        private static final long serialVersionUID = -1293849182394L;

        @NotNull(message = "name must be provided")
        @Size(min = 1, max = 128, message = "Dataset name must be between 1 and 128 characters")
        private final String name;

        /**
         * MIME type describing the content (e.g., text/csv, application/json).
         */
        @NotNull(message = "mimeType is required to correctly route the data set")
        private final String mimeType;

        /**
         * Content encoded as base64 to remain transport-encoding agnostic.
         */
        @NotNull(message = "contentBase64 must be provided")
        private final String contentBase64;

        @JsonCreator
        public DataSetDto(
                @JsonProperty("name") String name,
                @JsonProperty("mimeType") String mimeType,
                @JsonProperty("contentBase64") String contentBase64) {

            this.name          = name;
            this.mimeType      = mimeType;
            this.contentBase64 = contentBase64;
        }

        public String getName() {
            return name;
        }

        public String getMimeType() {
            return mimeType;
        }

        public String getContentBase64() {
            return contentBase64;
        }

        @Override
        public boolean equals(Object o) {
            if (this == o) return true;
            if (!(o instanceof DataSetDto that)) return false;
            return Objects.equals(name, that.name)
                    && Objects.equals(mimeType, that.mimeType)
                    && Objects.equals(contentBase64, that.contentBase64);
        }

        @Override
        public int hashCode() {
            return Objects.hash(name, mimeType, contentBase64);
        }

        @Override
        public String toString() {
            return "DataSetDto{" +
                    "name='" + name + '\'' +
                    ", mimeType='" + mimeType + '\'' +
                    ", contentBase64='[protected]'" +
                    '}';
        }
    }
}