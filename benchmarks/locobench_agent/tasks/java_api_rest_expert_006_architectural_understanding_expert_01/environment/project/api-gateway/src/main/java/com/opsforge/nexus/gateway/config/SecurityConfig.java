```java
package com.opsforge.nexus.gateway.config;

import com.opsforge.nexus.gateway.security.JwtAuthenticationEntryPoint;
import com.opsforge.nexus.gateway.security.JwtAuthenticationFilter;
import com.opsforge.nexus.gateway.security.JwtTokenProvider;
import com.opsforge.nexus.gateway.security.RateLimiterService;
import com.opsforge.nexus.gateway.user.CustomUserDetailsService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.dao.DaoAuthenticationProvider;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.security.web.util.matcher.AntPathRequestMatcher;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.time.Duration;
import java.util.Arrays;
import java.util.List;

/**
 * Central Spring Security configuration for the API Gateway.
 *
 * <p>This class configures:
 * <ul>
 *     <li>CORS with a strict whitelist of allowed origins.</li>
 *     <li>Stateless JWT-based authentication.</li>
 *     <li>Role-based authorization rules for public, user and admin endpoints.</li>
 *     <li>A pluggable, token-bucket rate limiter to fend off abuse.</li>
 * </ul>
 *
 * <p>The configuration is intentionally feature-rich to showcase real-world
 * concerns such as exception handling, custom filters, and composition of
 * security adapters.</p>
 */
@Configuration
@EnableMethodSecurity(prePostEnabled = true)
public class SecurityConfig {

    private static final AntPathRequestMatcher[] PUBLIC_MATCHERS = {
            new AntPathRequestMatcher("/actuator/**"),
            new AntPathRequestMatcher("/swagger-ui/**"),
            new AntPathRequestMatcher("/v3/api-docs/**"),
            new AntPathRequestMatcher("/auth/**"),
            new AntPathRequestMatcher("/graphql/schema"),
            new AntPathRequestMatcher("/error")
    };

    private final JwtTokenProvider tokenProvider;
    private final CustomUserDetailsService userDetailsService;
    private final AuthenticationEntryPoint authenticationEntryPoint;
    private final RateLimiterService rateLimiterService;

    /**
     * Allowed cross-origin hosts. Injected from application.yaml to support runtime reconfiguration.
     */
    @Value("${opsforge.gateway.cors.allowed-origins}")
    private List<String> allowedOrigins;

    public SecurityConfig(JwtTokenProvider tokenProvider,
                          CustomUserDetailsService userDetailsService,
                          JwtAuthenticationEntryPoint authenticationEntryPoint,
                          RateLimiterService rateLimiterService) {
        this.tokenProvider = tokenProvider;
        this.userDetailsService = userDetailsService;
        this.authenticationEntryPoint = authenticationEntryPoint;
        this.rateLimiterService = rateLimiterService;
    }

    /**
     * Spring Security's entry point. Tells HttpSecurity to adopt our chain of filters.
     */
    @Bean
    @Order(Ordered.HIGHEST_PRECEDENCE)
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
            // Enable fine-grained CORS handling before the security chain kicks in.
            .cors(cors -> cors.configurationSource(corsConfigurationSource()))
            // Disable CSRF because the gateway is stateless and only exposes APIs, not forms.
            .csrf(csrf -> csrf.disable())
            .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            // Configure exception handling so that invalid tokens result in 401 instead of 403.
            .exceptionHandling(ex -> ex.authenticationEntryPoint(authenticationEntryPoint))
            // Wire in the authentication provider that delegates to our UserDetailsService.
            .authenticationProvider(daoAuthenticationProvider())
            // Authorization rules go from most-specific to least-specific.
            .authorizeHttpRequests(auth -> auth
                .requestMatchers(PUBLIC_MATCHERS).permitAll()
                .requestMatchers(HttpMethod.GET,  "/graphql").permitAll()
                .requestMatchers("/admin/**").hasRole("ADMIN")
                .anyRequest().authenticated())
            // Custom filters must be positioned explicitly.
            .addFilterBefore(new RateLimitingFilter(rateLimiterService), UsernamePasswordAuthenticationFilter.class)
            .addFilterBefore(jwtAuthenticationFilter(), UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    /**
     * Delegates credential validation to our domain-specific {@link CustomUserDetailsService}.
     */
    @Bean
    public DaoAuthenticationProvider daoAuthenticationProvider() {
        DaoAuthenticationProvider provider = new DaoAuthenticationProvider();
        provider.setPasswordEncoder(passwordEncoder());
        provider.setUserDetailsService(userDetailsService);
        return provider;
    }

    /**
     * A BCrypt password encoder with a configurable strength factor (default 10).
     * Changing the strength factor allows gradual hardening with future CPU gains.
     */
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder(10);
    }

    /**
     * Expose {@link AuthenticationManager} for components outside the security configuration
     * (e.g., application services performing programmatic authentication).
     */
    @Bean
    public AuthenticationManager authenticationManager(HttpSecurity http) throws Exception {
        return http.getSharedObject(AuthenticationManager.class);
    }

    /**
     * Custom JWT authentication filter that parses Authorization headers and populates
     * the Spring SecurityContext if the token is valid.
     */
    @Bean
    public JwtAuthenticationFilter jwtAuthenticationFilter() {
        return new JwtAuthenticationFilter(tokenProvider, userDetailsService);
    }

    /**
     * Centralized CORS configuration that white-lists consumer UIs while allowing
     * Swagger and GraphiQL to function in development.
     */
    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration configuration = new CorsConfiguration();
        configuration.setAllowedOriginPatterns(allowedOrigins);
        configuration.setAllowedMethods(Arrays.asList(
                HttpMethod.GET.name(),
                HttpMethod.POST.name(),
                HttpMethod.PUT.name(),
                HttpMethod.DELETE.name(),
                HttpMethod.PATCH.name(),
                HttpMethod.OPTIONS.name()
        ));
        configuration.setAllowedHeaders(Arrays.asList(
                HttpHeaders.AUTHORIZATION,
                HttpHeaders.CONTENT_TYPE,
                "X-Request-Id",
                "X-Correlation-Id"
        ));
        configuration.setExposedHeaders(List.of("X-Rate-Limit-Remaining"));
        configuration.setAllowCredentials(true);
        configuration.setMaxAge(Duration.ofHours(2));

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", configuration);
        return source;
    }

    /**
     * Inline rate-limiting filter that applies a token-bucket algorithm per caller identity.
     * <p>
     * The implementation relies on a {@link RateLimiterService} abstraction so that the
     * concrete backing (in-memory, Redis, Hazelcast…) can be swapped without code changes.
     */
    static class RateLimitingFilter extends OncePerRequestFilter {

        private final RateLimiterService rateLimiterService;

        RateLimitingFilter(RateLimiterService rateLimiterService) {
            this.rateLimiterService = rateLimiterService;
        }

        @Override
        protected void doFilterInternal(HttpServletRequest request,
                                        HttpServletResponse response,
                                        FilterChain filterChain) throws ServletException, IOException {
            String identity = resolveIdentity(request);
            if (!rateLimiterService.tryConsume(identity)) {
                response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
                response.setHeader("Retry-After", Long.toString(rateLimiterService.retryAfterSeconds(identity)));
                return;
            }

            // Expose remaining quota for observability purposes.
            response.setHeader("X-Rate-Limit-Remaining",
                    Long.toString(rateLimiterService.remainingTokens(identity)));

            filterChain.doFilter(request, response);
        }

        /**
         * Resolve the caller's unique identity.
         *
         * <p>If the request is authenticated, use the subject claim from the JWT;
         * otherwise fall back to the remote IP address to avoid anonymous flooding.</p>
         */
        private String resolveIdentity(HttpServletRequest request) {
            String authHeader = request.getHeader(HttpHeaders.AUTHORIZATION);
            if (authHeader != null && authHeader.startsWith("Bearer ")) {
                // Subject is everything after "Bearer "
                return authHeader.substring(7, authHeader.length() - 1);
            }
            return request.getRemoteAddr();
        }
    }
}
```