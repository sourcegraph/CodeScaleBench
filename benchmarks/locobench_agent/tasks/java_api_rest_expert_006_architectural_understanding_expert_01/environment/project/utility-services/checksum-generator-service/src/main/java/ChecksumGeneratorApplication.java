```java
package com.opsforge.utilitynexus.checksum;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.Arrays;
import java.util.Objects;
import java.util.concurrent.TimeUnit;

import javax.validation.constraints.NotEmpty;
import javax.validation.constraints.NotNull;

import org.springframework.boot.Banner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.cache.CacheManager;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.graphql.data.method.annotation.Argument;
import org.springframework.graphql.data.method.annotation.QueryMapping;
import org.springframework.graphql.execution.RuntimeWiringConfigurer;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.lang.Nullable;
import org.springframework.util.StreamUtils;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import com.github.benmanes.caffeine.cache.Caffeine;

import io.micrometer.core.instrument.MeterRegistry;

/**
 * Application entry-point for the Checksum Generator micro-service.
 *
 * The service demonstrates a typical Spring Boot application that adheres to
 * Hexagonal Architecture principles.  Domain logic is encapsulated in
 * dedicated components and exposed to the outside world through HTTP and
 * GraphQL adapters.  Cross-cutting concerns such as caching, metrics, and
 * error handling are wired centrally to guarantee consistent behaviour.
 */
@SpringBootApplication
@EnableConfigurationProperties(ChecksumGeneratorApplication.ChecksumCacheProperties.class)
public class ChecksumGeneratorApplication {

    public static void main(String[] args) {
        SpringApplication app = new SpringApplication(ChecksumGeneratorApplication.class);
        app.setBanner(new OpsForgeBanner());
        app.run(args);
    }

    /* --------------------------------------------------------------------- */
    /* Infrastructure & Cross-Cutting Beans                                  */
    /* --------------------------------------------------------------------- */

    /**
     * Configure a Caffeine cache that stores checksums; cache settings are
     * defined via externalised configuration (see application.yml).
     */
    @Bean
    CacheManager cacheManager(ChecksumCacheProperties props) {
        CaffeineCacheManager manager = new CaffeineCacheManager("checksum");
        manager.setCaffeine(Caffeine.newBuilder()
                                    .expireAfterWrite(Duration.ofSeconds(props.getTtlSeconds()))
                                    .maximumSize(props.getMaximumEntries()));
        return manager;
    }

    /**
     * Wire our domain service implementation.  In a real project this would be
     * placed in a dedicated application module—kept here only for brevity.
     */
    @Bean
    ChecksumService checksumService(MessageDigestFactory digestFactory,
                                    MeterRegistry registry) {
        return new ChecksumServiceImpl(digestFactory, registry);
    }

    /**
     * Factory responsible for creating {@link MessageDigest} instances in a
     * safe, validated manner.
     */
    @Bean
    MessageDigestFactory messageDigestFactory() {
        return new MessageDigestFactory();
    }

    /* --------------------------------------------------------------------- */
    /* Inner Classes: Domain, Application, Adapters                          */
    /* --------------------------------------------------------------------- */

    /**
     * Supported hashing algorithms. Map the canonical JCA algorithm name to a
     * legal enum constant so we can expose a “clean” public API.
     */
    enum Algorithm {
        MD5("MD5"),
        SHA1("SHA-1"),
        SHA256("SHA-256"),
        SHA512("SHA-512");

        private final String jcaName;

        Algorithm(String jcaName) {
            this.jcaName = jcaName;
        }

        MessageDigest newDigest() throws NoSuchAlgorithmException {
            return MessageDigest.getInstance(jcaName);
        }

        static Algorithm fromString(String value) {
            return Arrays.stream(values())
                         .filter(a -> a.name().equalsIgnoreCase(value) ||
                                      a.jcaName.equalsIgnoreCase(value))
                         .findFirst()
                         .orElseThrow(() -> new IllegalArgumentException(
                                 "Unsupported algorithm: " + value));
        }
    }

    /**
     * Exception thrown whenever checksum generation fails for business reasons.
     */
    static class ChecksumGenerationException extends RuntimeException {
        ChecksumGenerationException(String msg, Throwable cause) { super(msg, cause); }
        ChecksumGenerationException(String msg)               { super(msg);           }
    }

    /**
     * Factory that encapsulates creation & validation of {@link MessageDigest}.
     */
    static final class MessageDigestFactory {
        MessageDigest getInstance(Algorithm algorithm) {
            try {
                return algorithm.newDigest();
            } catch (NoSuchAlgorithmException ex) {
                throw new ChecksumGenerationException("Algorithm not available: " +
                        algorithm, ex);
            }
        }
    }

    /**
     * Application-level service (Use-case) that computes checksums while taking
     * care of error handling, caching, and metrics.
     */
    interface ChecksumService {
        String generate(@NotNull byte[] data, @NotNull Algorithm algorithm);
    }

    /**
     * Concrete service implementation.
     */
    static final class ChecksumServiceImpl implements ChecksumService {

        private final MessageDigestFactory digestFactory;
        private final MeterRegistry registry;

        ChecksumServiceImpl(MessageDigestFactory digestFactory,
                            MeterRegistry registry) {
            this.digestFactory = digestFactory;
            this.registry      = registry;
        }

        @Override
        @Cacheable(value = "checksum",
                   key = "#algorithm.name() + '-' + T(java.util.Arrays).hashCode(#data)")
        public String generate(@NotNull byte[] data, @NotNull Algorithm algorithm) {

            Objects.requireNonNull(data, "Data must not be null");
            Objects.requireNonNull(algorithm, "Algorithm must not be null");

            long startNanos = System.nanoTime();
            try {
                MessageDigest digest = digestFactory.getInstance(algorithm);
                byte[] hash = digest.digest(data);
                return toHex(hash);
            } finally {
                long duration = System.nanoTime() - startNanos;
                registry.timer("checksum.calculate",
                               "algorithm", algorithm.name())
                        .record(duration, TimeUnit.NANOSECONDS);
            }
        }

        private static String toHex(byte[] bytes) {
            StringBuilder sb = new StringBuilder(bytes.length * 2);
            for (byte b : bytes) {
                String hex = Integer.toHexString(0xff & b);
                if (hex.length() == 1) sb.append('0');
                sb.append(hex);
            }
            return sb.toString();
        }
    }

    /* --------------------------------------------------------------------- */
    /* REST Adapter                                                           */
    /* --------------------------------------------------------------------- */

    @RestController
    @RequestMapping(path = "/api/v1/checksums")
    static class ChecksumController {

        private final ChecksumService service;

        ChecksumController(ChecksumService service) {
            this.service = service;
        }

        /**
         * Computes a checksum for the given byte array.
         *
         * Example cURL:
         *   curl --data-binary @file.txt \
         *        -H "Content-Type: application/octet-stream" \
         *        http://localhost:8080/api/v1/checksums/SHA256
         */
        @PostMapping(path = "/{algorithm}",
                     consumes = MediaType.APPLICATION_OCTET_STREAM_VALUE,
                     produces = MediaType.TEXT_PLAIN_VALUE)
        public ResponseEntity<String> createChecksum(@NotEmpty @RequestBody byte[] payload,
                                                     @org.springframework.web.bind.annotation.PathVariable
                                                     String algorithm) {
            Algorithm algo;
            try {
                algo = Algorithm.fromString(algorithm);
            } catch (IllegalArgumentException ex) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                        ex.getMessage(), ex);
            }

            String checksum = service.generate(payload, algo);
            return ResponseEntity.ok(checksum);
        }

        /* -- Centralised error mapping ------------------------------------ */

        @ExceptionHandler(ChecksumGenerationException.class)
        public ResponseEntity<String> onChecksumFailure(ChecksumGenerationException ex) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                                 .body("checksum_error: " + ex.getMessage());
        }
    }

    /* --------------------------------------------------------------------- */
    /* GraphQL Adapter                                                        */
    /* --------------------------------------------------------------------- */

    /**
     * Exposes the checksum use-case via GraphQL.
     *
     * Example Query:
     *   query {
     *     checksum(input: {algorithm: "SHA256", text: "hello"}) 
     *   }
     */
    @org.springframework.stereotype.Controller
    static class ChecksumGraphQLController {

        private final ChecksumService service;

        ChecksumGraphQLController(ChecksumService service) {
            this.service = service;
        }

        /**
         * GraphQL Query mapping (acts like REST's GET).
         */
        @QueryMapping("checksum")
        public String checksum(@Validated @Argument ChecksumInput input) {
            Algorithm algo = Algorithm.fromString(input.getAlgorithm());
            byte[] data = input.rawBytes();
            return service.generate(data, algo);
        }

        /**
         * GraphQL schema-mapped DTO.
         */
        record ChecksumInput(@NotNull String algorithm,
                             @Nullable String text,
                             @Nullable String base64) {

            byte[] rawBytes() {
                if (text != null) {
                    return text.getBytes(StandardCharsets.UTF_8);
                }
                if (base64 != null) {
                    return java.util.Base64.getDecoder().decode(base64);
                }
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                        "Either 'text' or 'base64' must be supplied.");
            }

            String getAlgorithm() {
                return algorithm;
            }
        }
    }

    /* --------------------------------------------------------------------- */
    /* Misc. Utility & Configuration                                         */
    /* --------------------------------------------------------------------- */

    /**
     * Simple ASCII banner shown on service start-up.
     */
    private static final class OpsForgeBanner implements Banner {
        @Override
        public void printBanner(org.springframework.core.env.Environment env,
                                Class<?> source, java.io.PrintStream out) {
            out.println("""
             _____           __   ______                     _            
            / ___/____ _____/ /__/ ____/_____________  _____(_)___  ____ _
            \\__ \\/ __ `/ __  / _  / __ \\/ ___/ ___/ / / / _  / __ \\/ __ `/
           ___/ / /_/ / /_/ /  __/ /_/ (__  ) /__/ /_/ /  __/ / / / /_/ / 
          /____/\\__,_/\\__,_/\\___/\\____/____/\\___/\\__,_/\\___/_/_/ /\\__, /  
                                                              /____/     
            """);
        }
    }

    /**
     * Externalised cache configuration that can be tuned without recompiling.
     */
    @ConfigurationProperties(prefix = "checksum.cache")
    @Validated
    static class ChecksumCacheProperties {

        /**
         * Maximum number of cache entries to keep in memory.
         */
        private long maximumEntries = 20_000;

        /**
         * Time-to-live for cache entries in seconds.
         */
        private long ttlSeconds = 600;

        public long getMaximumEntries() {
            return maximumEntries;
        }

        public void setMaximumEntries(long maximumEntries) {
            this.maximumEntries = maximumEntries;
        }

        public long getTtlSeconds() {
            return ttlSeconds;
        }

        public void setTtlSeconds(long ttlSeconds) {
            this.ttlSeconds = ttlSeconds;
        }
    }

    /**
     * Configure custom GraphQL scalar, in case the default wiring needs tweaks.
     * Currently just a placeholder to illustrate how to hook into runtime
     * wiring without polluting domain code.
     */
    @Bean
    RuntimeWiringConfigurer runtimeWiringConfigurer() {
        return wiringBuilder -> {
            // Add custom scalars or directives here if needed.
        };
    }
}
```