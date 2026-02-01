package com.opsforge.nexus.anonymizer.domain.service;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.time.Duration;
import java.util.Collections;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import org.apache.commons.codec.digest.DigestUtils;
import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVParser;
import org.apache.commons.csv.CSVPrinter;
import org.apache.commons.csv.CSVRecord;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;

import lombok.AccessLevel;
import lombok.Getter;
import lombok.NonNull;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import reactor.core.publisher.Mono;

/**
 * Domain‐level service encapsulating the core anonymization algorithms.
 * <p>
 * The service is framework–agnostic and can be invoked from synchronous or
 * reactive adapters (e.g., Spring MVC controllers, WebFlux handlers, GraphQL
 * resolvers, or messaging listeners).  All heavy lifting—parsing, streaming,
 * and bulk anonymization—is handled in memory‐efficient fashion.
 *
 * <h3>Thread safety</h3>
 * Implementations are stateless; internal caches rely on Caffeine’s
 * {@code Cache} that is thread‐safe and lock-free for reads.
 *
 * <h3>Performance</h3>
 * Compiled {@link java.util.regex.Pattern} instances are cached to avoid
 * recompilation overhead when the same mask expression is used repeatedly.
 */
@Slf4j
@RequiredArgsConstructor
public class DataAnonymizationService {

    /**
     * All known anonymizers keyed by data type.
     * Inject a collection of {@link GenericAnonymizer} implementations
     * provided by the application bootstrap.
     */
    private final Map<DataType, GenericAnonymizer> anonymizers;

    /**
     * Compiled pattern cache (regex string → compiled Pattern).
     */
    private final Cache<String, Pattern> patternCache = Caffeine.newBuilder()
                                                                .maximumSize(256)
                                                                .expireAfterAccess(Duration.ofHours(2))
                                                                .build();

    /**
     * Performs field-level anonymization for a single value.
     *
     * @param value          Plain text value to anonymize.
     * @param dataType       Semantic data type (email, phone …).
     * @param profile        Customization options (can be empty).
     *
     * @return Anonymized value.  If no {@link GenericAnonymizer} is registered
     *         for the {@code dataType}, the original value is returned
     *         unchanged.
     */
    public String anonymize(@NonNull String value,
                            @NonNull DataType dataType,
                            @NonNull AnonymizationProfile profile) {

        GenericAnonymizer anonymizer = anonymizers.get(dataType);
        if (anonymizer == null) {
            log.debug("No specific anonymizer registered for type {} – value left intact", dataType);
            return value;
        }

        try {
            return anonymizer.anonymize(value, profile, this::compilePattern);
        } catch (Exception ex) {
            log.error("Failed to anonymize value for type {}. Fallback to hashing.", dataType, ex);
            // As a last resort, return a deterministic SHA-256 hash
            return DigestUtils.sha256Hex(value);
        }
    }

    /**
     * Bulk-anonymizes a CSV stream and produces a reactive {@code Mono} of the
     * resulting byte[] ready to be written to an outbound stream.
     *
     * <p>This method is I/O bound (CSV parsing) and therefore executes on the
     * Reactor bounded elastic scheduler.</p>
     *
     * @param csvStream          Input CSV data (UTF-8 encoded).
     * @param csvProfile         Column-level anonymization configuration.
     * @return Mono that yields the anonymized CSV as {@code byte[]}.
     */
    public Mono<byte[]> anonymizeCsv(@NonNull InputStream csvStream,
                                     @NonNull CsvAnonymizationProfile csvProfile) {

        return Mono
            .fromCallable(() -> {
                try (BufferedReader br = new BufferedReader(new InputStreamReader(csvStream, StandardCharsets.UTF_8));
                     CSVParser parser = CSVFormat.DEFAULT
                                                  .withFirstRecordAsHeader()
                                                  .parse(br)) {

                    List<String> headers = parser.getHeaderNames();
                    StringBuilder sb = new StringBuilder(1024);
                    try (CSVPrinter printer = CSVFormat.DEFAULT
                                                        .withHeader(headers.toArray(new String[0]))
                                                        .print(sb)) {

                        Map<Integer, ColumnRule> ruleByIndex =
                                mapRulesToIndices(headers, csvProfile.getColumnRules());

                        for (CSVRecord record : parser) {
                            String[] row = new String[headers.size()];
                            for (int i = 0; i < headers.size(); i++) {
                                String original = record.get(i);
                                ColumnRule rule = ruleByIndex.get(i);
                                if (rule != null) {
                                    row[i] = anonymize(
                                            original,
                                            rule.getType(),
                                            Optional.ofNullable(rule.getProfile()).orElse(AnonymizationProfile.EMPTY));
                                } else {
                                    row[i] = original;
                                }
                            }
                            printer.printRecord((Object[]) row);
                        }
                    }
                    return sb.toString().getBytes(StandardCharsets.UTF_8);

                } catch (IOException ex) {
                    throw new DataAnonymizationException("Failed to anonymize CSV data", ex);
                }
            })
            .subscribeOn(reactor.core.scheduler.Schedulers.boundedElastic());
    }

    /**
     * Return a compiled {@link Pattern} from cache or compile and cache it.
     */
    private Pattern compilePattern(@NonNull String regex) {
        return patternCache.get(regex, Pattern::compile);
    }

    /**
     * Build a fast lookup map between column index and anonymization rule.
     */
    private Map<Integer, ColumnRule> mapRulesToIndices(List<String> headers,
                                                       List<ColumnRule> rules) {

        if (rules == null || rules.isEmpty()) {
            return Collections.emptyMap();
        }

        Map<Integer, ColumnRule> result = new ConcurrentHashMap<>();
        for (ColumnRule rule : rules) {
            int idx = headers.indexOf(rule.getColumn());
            if (idx != -1) {
                result.put(idx, rule);
            }
        }
        return result;
    }

    /* --------------------------------------------------------------------- */
    /* –––––––––––––––––––––––––– Nested contracts –––––––––––––––––––––––––– */
    /* --------------------------------------------------------------------- */

    /**
     * Generic interface implemented by all anonymizers.
     */
    @FunctionalInterface
    public interface GenericAnonymizer {

        /**
         * @param value          Raw input value (never {@code null}).
         * @param profile        Additional parameters.
         * @param patternLoader  Lazy loader for compiled regex patterns.
         *
         * @return Anonymized value.  Must never return {@code null}.
         */
        String anonymize(String value,
                         AnonymizationProfile profile,
                         java.util.function.Function<String, Pattern> patternLoader);
    }

    /**
     * Semantic data types supported by the platform.
     */
    public enum DataType {
        EMAIL,
        PHONE,
        FULL_NAME,
        ADDRESS,
        CREDIT_CARD,
        GENERIC_STRING
    }

    /**
     * Marker interface for profiles.  Concrete profiles should extend and add
     * type-specific parameters.
     */
    public interface AnonymizationProfile {

        AnonymizationProfile EMPTY = builder().build();

        static SimpleProfileBuilder builder() { return new SimpleProfileBuilder(); }

        class SimpleProfileBuilder {
            private final Map<String, Object> map = new ConcurrentHashMap<>();

            public SimpleProfileBuilder put(String key, Object value) {
                map.put(key, value);
                return this;
            }

            public AnonymizationProfile build() {
                return () -> Collections.unmodifiableMap(map);
            }
        }

        Map<String, Object> parameters();

        default String param(String key, String fallback) {
            return Objects.toString(parameters().getOrDefault(key, fallback), fallback);
        }
    }

    /**
     * Column-level mapping for CSV anonymization.
     */
    @Getter
    @RequiredArgsConstructor(access = AccessLevel.PRIVATE)
    public static class ColumnRule {
        private final String column;
        private final DataType type;
        private final AnonymizationProfile profile;

        public static ColumnRule of(String column, DataType type, AnonymizationProfile profile) {
            return new ColumnRule(column, type, profile);
        }
    }

    /**
     * Profile for CSV anonymization use case.
     */
    @Getter
    @RequiredArgsConstructor
    public static class CsvAnonymizationProfile {
        private final List<ColumnRule> columnRules;
    }

    /**
     * Dedicated unchecked exception for the anonymizer module.
     */
    public static class DataAnonymizationException extends RuntimeException {
        public DataAnonymizationException(String message, Throwable cause) { super(message, cause); }
    }

    /* --------------------------------------------------------------------- */
    /* ––––––––––––––––––– Sample internal anonymizer set ––––––––––––––––––– */
    /* --------------------------------------------------------------------- */

    /**
     * Factory method that creates a default registry of anonymizers.
     * Can be used by legacy code not relying on DI container.
     */
    public static DataAnonymizationService withDefaults() {
        Map<DataType, GenericAnonymizer> registry = new EnumMap<>(DataType.class);

        registry.put(DataType.EMAIL, new EmailAnonymizer());
        registry.put(DataType.PHONE, new PhoneAnonymizer());
        registry.put(DataType.FULL_NAME, new NameAnonymizer());
        registry.put(DataType.GENERIC_STRING, (value, profile, loader) -> DigestUtils.sha256Hex(value));

        return new DataAnonymizationService(registry);
    }

    /* ======================= Concrete strategies ======================== */

    private static final class EmailAnonymizer implements GenericAnonymizer {

        @Override
        public String anonymize(String value,
                                AnonymizationProfile profile,
                                java.util.function.Function<String, Pattern> patternLoader) {

            int atIdx = value.indexOf('@');
            if (atIdx < 1) {
                // Invalid email – hash instead
                return DigestUtils.sha256Hex(value);
            }
            String domain = value.substring(atIdx);
            String hash = DigestUtils.sha256Hex(value.substring(0, atIdx)).substring(0, 8);
            return hash + domain;
        }
    }

    private static final class PhoneAnonymizer implements GenericAnonymizer {

        @Override
        public String anonymize(String value,
                                AnonymizationProfile profile,
                                java.util.function.Function<String, Pattern> patternLoader) {

            String digits = value.replaceAll("\\D", "");
            if (digits.length() < 4) {
                return "****";
            }
            String last4 = digits.substring(digits.length() - 4);
            return "********" + last4;
        }
    }

    private static final class NameAnonymizer implements GenericAnonymizer {

        private static final SecureRandom RANDOM = new SecureRandom();
        private static final List<String> DICTIONARY = List.of(
                "Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot",
                "Golf", "Hotel", "India", "Juliet", "Kilo", "Lima", "Mike",
                "November", "Oscar", "Papa", "Quebec", "Romeo", "Sierra",
                "Tango", "Uniform", "Victor", "Whiskey", "Xray", "Yankee", "Zulu");

        @Override
        public String anonymize(String value,
                                AnonymizationProfile profile,
                                java.util.function.Function<String, Pattern> patternLoader) {

            // Preserve initials if requested, otherwise pick random callsign
            boolean keepInitial = Boolean.parseBoolean(profile.param("keepInitial", "false"));
            String callsign = DICTIONARY.get(RANDOM.nextInt(DICTIONARY.size()));

            return keepInitial && !value.isBlank()
                    ? value.charAt(0) + ". " + callsign
                    : callsign;
        }
    }
}