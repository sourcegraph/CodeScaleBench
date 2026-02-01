/*
 * Copyright 2024 OpsForge
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not
 * use this file except in compliance with the License. You may obtain a copy of
 * the License at
 *
 *      https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software distributed
 * under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
 * CONDITIONS OF ANY KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations under the License.
 */

package com.opsforge.nexus.gateway.config;

import java.time.Duration;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.lang.Nullable;
import org.springframework.util.CollectionUtils;
import org.springframework.util.StringUtils;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.reactive.CorsConfigurationSource;
import org.springframework.web.cors.reactive.UrlBasedCorsConfigurationSource;
import org.springframework.web.filter.reactive.CorsWebFilter;

/**
 * Global CORS configuration for the {@code api-gateway}.<br>
 * <br>
 * The gateway is the single entry-point for <em>all</em> OpsForge utilities,
 * therefore it must be able to handle requests originating from a variety of
 * front-end domains (internal admin console, customer portals, 3rd-party
 * ecosystems, etc.).<br>
 * <br>
 * Behaviour can be tuned via {@code application.yml} or the
 * {@code CORS_ALLOWED_ORIGINS} environment variable, e.g.:
 *
 * <pre>{@code
 * nexus:
 *   gateway:
 *     cors:
 *       allowed-origins:
 *         - https://admin.opsforge.com
 *         - https://*.customer.io
 *       allowed-methods: GET,POST,PUT,PATCH,DELETE,OPTIONS
 *       allowed-headers: X-Request-Id,Content-Type,Authorization
 *       allow-credentials: true
 *       max-age: 3600
 * }</pre>
 *
 * A wildcard origin ({@code "*"}) can be specified for fully public endpoints.
 * When {@code allow-credentials=true} and wildcard is used, the filter will
 * gracefully degrade to <em>reflecting</em> the {@code Origin} header back to
 * the caller as mandated by the CORS specification.
 */
@Configuration
@EnableConfigurationProperties(CorsGlobalConfiguration.CorsProps.class)
public class CorsGlobalConfiguration {

    private static final Logger log = LoggerFactory.getLogger(CorsGlobalConfiguration.class);

    private static final Pattern WILDCARD_PATTERN = Pattern.compile("^\\*$");

    private final CorsProps props;
    private final Environment environment;

    public CorsGlobalConfiguration(CorsProps props, Environment environment) {
        this.props = props;
        this.environment = environment;
    }

    /**
     * Registers a {@link CorsWebFilter} bean that applies to <strong>all</strong>
     * routes handled by Spring Cloud Gateway.
     *
     * @return a singleton {@link CorsWebFilter}
     */
    @Bean
    @ConditionalOnMissingBean // consumers may override with a custom implementation
    public CorsWebFilter corsWebFilter() {
        final CorsConfiguration configuration = buildGlobalCorsConfiguration();
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        // Apply the same configuration to every path
        source.registerCorsConfiguration("/**", configuration);

        log.info("CORS global configuration initialised: {}", sanitizeForLog(configuration));
        return new CorsWebFilter(adaptForWildcard(configuration), source);
    }

    /**
     * Build a {@link CorsConfiguration} based on externalised {@link CorsProps}
     * or fallback environment variables.
     */
    private CorsConfiguration buildGlobalCorsConfiguration() {
        CorsConfiguration cors = new CorsConfiguration();
        cors.setAllowedOrigins(resolveAllowedOrigins());
        cors.setAllowedMethods(defaultIfEmpty(props.getAllowedMethods(),
                Arrays.asList(HttpMethod.GET.name(),
                               HttpMethod.POST.name(),
                               HttpMethod.PUT.name(),
                               HttpMethod.PATCH.name(),
                               HttpMethod.DELETE.name(),
                               HttpMethod.OPTIONS.name())));
        cors.setAllowedHeaders(defaultIfEmpty(props.getAllowedHeaders(),
                Arrays.asList(HttpHeaders.AUTHORIZATION,
                              HttpHeaders.CONTENT_TYPE,
                              "X-Request-Id",
                              "X-Correlation-Id")));
        cors.setExposedHeaders(defaultIfEmpty(props.getExposedHeaders(),
                Collections.singletonList(HttpHeaders.LOCATION)));
        cors.setAllowCredentials(props.isAllowCredentials());
        cors.setMaxAge(Duration.ofSeconds(props.getMaxAge()).getSeconds());
        return cors;
    }

    /**
     * The CORS specification forbids {@code Access-Control-Allow-Origin: *}
     * when {@code Access-Control-Allow-Credentials: true}. In such scenario,
     * we switch to a more permissive strategy that <em>mirrors</em> the
     * {@code Origin} header back to the caller.
     */
    private CorsWebFilter adaptForWildcard(CorsConfiguration configuration) {
        if (configuration.getAllowedOrigins().stream().anyMatch(WILDCARD_PATTERN.asMatchPredicate())
                && Boolean.TRUE.equals(configuration.getAllowCredentials())) {

            log.warn("Wildcard origin detected alongside 'allow-credentials=true'. "
                     + "Switching to reflecting strategy per CORS spec.");

            UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource() {
                @Override
                public CorsConfiguration getCorsConfiguration(org.springframework.web.server.ServerWebExchange exchange) {
                    String requestOrigin = exchange.getRequest().getHeaders().getOrigin();
                    if (!StringUtils.hasText(requestOrigin)) {
                        return null; // Not a CORS request
                    }
                    CorsConfiguration config = new CorsConfiguration();
                    config.setAllowedOrigins(Collections.singletonList(requestOrigin));
                    config.setAllowedMethods(configuration.getAllowedMethods());
                    config.setAllowedHeaders(configuration.getAllowedHeaders());
                    config.setExposedHeaders(configuration.getExposedHeaders());
                    config.setAllowCredentials(true);
                    config.setMaxAge(configuration.getMaxAge());
                    return config;
                }
            };
            source.registerCorsConfiguration("/**", configuration);
            return new CorsWebFilter(source);
        }
        return new CorsWebFilter(configuration);
    }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private List<String> resolveAllowedOrigins() {
        if (!CollectionUtils.isEmpty(props.getAllowedOrigins())) {
            return props.getAllowedOrigins();
        }

        // Fall back to ENV var to ease containerised deployments
        String envOrigins = environment.getProperty("CORS_ALLOWED_ORIGINS");
        if (StringUtils.hasText(envOrigins)) {
            return Arrays.stream(envOrigins.split(","))
                         .map(String::trim)
                         .filter(StringUtils::hasText)
                         .collect(Collectors.toList());
        }
        // Open up completely if nothing is configured (reasonable default for dev)
        log.info("No CORS allowed-origins configured. Falling back to wildcard \"*\".");
        return Collections.singletonList("*");
    }

    private static List<String> defaultIfEmpty(@Nullable List<String> candidate, List<String> defaultVal) {
        return CollectionUtils.isEmpty(candidate) ? defaultVal : candidate;
    }

    private static String sanitizeForLog(CorsConfiguration configuration) {
        return String.format("origins=%s, methods=%s, headers=%s, exposed=%s, credentials=%s, maxAge=%ss",
                configuration.getAllowedOrigins(),
                configuration.getAllowedMethods(),
                configuration.getAllowedHeaders(),
                configuration.getExposedHeaders(),
                configuration.getAllowCredentials(),
                configuration.getMaxAge());
    }

    // -----------------------------------------------------------------------
    // Configuration Properties
    // -----------------------------------------------------------------------

    /**
     * Strongly-typed configuration properties backing {@code nexus.gateway.cors.*}
     */
    @ConfigurationProperties(prefix = "nexus.gateway.cors")
    public static class CorsProps {

        /**
         * Allowed origins in fully-qualified form (e.g. https://foo.bar) or wildcards
         * (e.g. https://*.example.com, *).
         */
        private List<String> allowedOrigins;

        /**
         * HTTP methods accepted by the utilities.
         */
        private List<String> allowedMethods;

        /**
         * HTTP headers allowed in the actual request.
         */
        private List<String> allowedHeaders;

        /**
         * Additional headers to expose to the client.
         */
        private List<String> exposedHeaders;

        /**
         * Whether user credentials are supported.
         */
        private boolean allowCredentials = true;

        /**
         * Amount of time, in seconds, the results of a preflight request can be cached.
         */
        private long maxAge = 1_800; // 30 minutes

        // Getters & setters

        public List<String> getAllowedOrigins() {
            return allowedOrigins;
        }

        public void setAllowedOrigins(List<String> allowedOrigins) {
            this.allowedOrigins = sanitize(allowedOrigins);
        }

        public List<String> getAllowedMethods() {
            return allowedMethods;
        }

        public void setAllowedMethods(List<String> allowedMethods) {
            this.allowedMethods = sanitize(allowedMethods);
        }

        public List<String> getAllowedHeaders() {
            return allowedHeaders;
        }

        public void setAllowedHeaders(List<String> allowedHeaders) {
            this.allowedHeaders = sanitize(allowedHeaders);
        }

        public List<String> getExposedHeaders() {
            return exposedHeaders;
        }

        public void setExposedHeaders(List<String> exposedHeaders) {
            this.exposedHeaders = sanitize(exposedHeaders);
        }

        public boolean isAllowCredentials() {
            return allowCredentials;
        }

        public void setAllowCredentials(boolean allowCredentials) {
            this.allowCredentials = allowCredentials;
        }

        public long getMaxAge() {
            return maxAge;
        }

        public void setMaxAge(long maxAge) {
            this.maxAge = maxAge;
        }

        private static List<String> sanitize(@Nullable List<String> raw) {
            if (CollectionUtils.isEmpty(raw)) {
                return raw;
            }
            return raw.stream()
                      .filter(Objects::nonNull)
                      .map(String::trim)
                      .filter(StringUtils::hasText)
                      .collect(Collectors.toList());
        }
    }
}