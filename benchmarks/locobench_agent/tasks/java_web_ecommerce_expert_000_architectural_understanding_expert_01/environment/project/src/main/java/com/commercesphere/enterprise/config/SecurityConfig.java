```java
package com.commercesphere.enterprise.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.AuthenticationProvider;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.authentication.dao.DaoAuthenticationProvider;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.authentication.configuration.AuthenticationConfiguration;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.HeadersConfigurer;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.HttpStatusEntryPoint;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.security.web.csrf.CookieCsrfTokenRepository;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.time.Duration;
import java.util.Collection;
import java.util.List;

/**
 * Security configuration for CommerceSphere Enterprise Suite.
 * <p>
 * - Configures session, CSRF, CORS, and HTTP header hardening<br>
 * - Registers a DaoAuthenticationProvider backed by our {@link UserDetailsService}<br>
 * - Installs JWT-based auth for stateless REST endpoints while still allowing
 *   session cookies for traditional MVC views<br>
 * - Enables method-level authorization through {@code @PreAuthorize}, etc.<br>
 */
@Configuration
@EnableMethodSecurity(securedEnabled = true, jsr250Enabled = true)
public class SecurityConfig {

    private static final Logger log = LoggerFactory.getLogger(SecurityConfig.class);

    @Value("${security.jwt.header:Authorization}")
    private String jwtHeader;

    @Value("${security.jwt.prefix:Bearer }")
    private String jwtPrefix;

    private final UserDetailsService userDetailsService;
    private final JwtTokenService jwtTokenService; // Provided elsewhere in the codebase

    @Autowired
    public SecurityConfig(UserDetailsService userDetailsService,
                          JwtTokenService jwtTokenService) {
        this.userDetailsService = userDetailsService;
        this.jwtTokenService = jwtTokenService;
    }

    /**
     * Primary security filter chain. We keep everything in a single chain but
     * you can split per path with {@link Order} if desired.
     */
    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http,
                                           AuthenticationManager authenticationManager) throws Exception {

        http
            // Enable CORS with custom config
            .cors(cors -> cors.configurationSource(corsConfigurationSource()))
            // CSRF with HttpOnly=false so SPA frameworks can read it
            .csrf(csrf -> csrf
                .ignoringRequestMatchers("/api/**") // JWT-protected APIs are stateless
                .csrfTokenRepository(CookieCsrfTokenRepository.withHttpOnlyFalse()))
            // Session handling
            .sessionManagement(session -> session
                .sessionCreationPolicy(SessionCreationPolicy.IF_REQUIRED)
                .invalidSessionUrl("/login?expired")
                .maximumSessions(5)
                .maxSessionsPreventsLogin(false))
            // Authorization rules
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/api/auth/**", "/public/**", "/actuator/**").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/catalog/**").hasAnyRole("BUYER", "SALES_REP", "ACCOUNT_MANAGER", "ADMIN")
                .requestMatchers("/admin/**").hasRole("ADMIN")
                .anyRequest().authenticated())
            // Exception handling converts unauthenticated requests to 401 JSON for API paths
            .exceptionHandling(eh -> eh
                .defaultAuthenticationEntryPointFor(
                    restAuthenticationEntryPoint(),
                    request -> request.getRequestURI().startsWith("/api/"))
            )
            // Security headers
            .headers(headers -> buildSecurityHeaders(headers))
            // Custom filters
            .addFilterBefore(new JwtAuthenticationFilter(jwtHeader, jwtPrefix, jwtTokenService, userDetailsService),
                             UsernamePasswordAuthenticationFilter.class)
            .authenticationProvider(daoAuthenticationProvider())
            .authenticationManager(authenticationManager)
            .logout(logout -> logout
                .logoutUrl("/logout")
                .deleteCookies("JSESSIONID", "XSRF-TOKEN")
                .invalidateHttpSession(true)
                .clearAuthentication(true));

        return http.build();
    }

    private void buildSecurityHeaders(HeadersConfigurer<HttpSecurity> headers) {
        headers
            .contentSecurityPolicy(csp -> csp.policyDirectives(
                "default-src 'self'; " +
                "script-src 'self' 'unsafe-inline'; " +
                "style-src 'self' 'unsafe-inline'; " +
                "img-src 'self' data: https:; " +
                "frame-ancestors 'self';"))
            .frameOptions(HeadersConfigurer.FrameOptionsConfig::sameOrigin)
            .httpStrictTransportSecurity(hsts -> hsts
                .includeSubDomains(true)
                .maxAgeInSeconds(Duration.ofDays(180).toSeconds()))
            .xssProtection(Customizer.withDefaults());
    }

    /**
     * Default CORS policy; may be overridden via application-properties in ops.
     */
    @Bean
    public UrlBasedCorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration conf = new CorsConfiguration();
        conf.setAllowedOrigins(List.of("https://*.commercesphere.com", "https://portal.customer.com"));
        conf.setAllowedMethods(List.of("GET", "POST", "PUT", "DELETE", "OPTIONS"));
        conf.setAllowedHeaders(List.of(
                HttpHeaders.AUTHORIZATION,
                HttpHeaders.CONTENT_TYPE,
                HttpHeaders.ACCEPT,
                "X-CSRF-TOKEN"));
        conf.setAllowCredentials(true);
        conf.setMaxAge(Duration.ofHours(1));
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", conf);
        return source;
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder(12); // strength=12 is a good trade-off in 2024
    }

    @Bean
    public AuthenticationProvider daoAuthenticationProvider() {
        DaoAuthenticationProvider provider = new DaoAuthenticationProvider();
        provider.setPasswordEncoder(passwordEncoder());
        provider.setUserDetailsService(userDetailsService);
        // Optional: delay brute-force attacks
        provider.setPostAuthenticationChecks(userDetails -> {
            // Add lockout, MFA checks, etc.
        });
        return provider;
    }

    /**
     * Expose the authentication manager so that non-web components (e.g., a
     * GraphQL endpoint) can delegate authentication.
     */
    @Bean
    public AuthenticationManager authenticationManager(
            final AuthenticationConfiguration authConfig) throws Exception {
        return authConfig.getAuthenticationManager();
    }

    /**
     * Returns an {@link AuthenticationEntryPoint} that emits JSON instead of a
     * redirect whenever an unauthenticated client hits "/api/**".
     */
    @Bean
    public AuthenticationEntryPoint restAuthenticationEntryPoint() {
        return new HttpStatusEntryPoint(org.springframework.http.HttpStatus.UNAUTHORIZED);
    }

    /* --------------------------------------------------------------------- */
    /* ---- Nested classes --------------------------------------------------*/
    /* --------------------------------------------------------------------- */

    /**
     * Stateless filter that extracts and validates a JWT from the request.
     * <p>
     * If the token is valid, a {@link UsernamePasswordAuthenticationToken} is
     * placed into the {@link org.springframework.security.core.context.SecurityContext}.
     */
    public static class JwtAuthenticationFilter extends OncePerRequestFilter {

        private static final Logger log = LoggerFactory.getLogger(JwtAuthenticationFilter.class);
        private static final ObjectMapper mapper = new ObjectMapper();

        private final String header;
        private final String prefix;
        private final JwtTokenService jwtService;
        private final UserDetailsService userDetailsService;

        public JwtAuthenticationFilter(String header,
                                       String prefix,
                                       JwtTokenService jwtService,
                                       UserDetailsService userDetailsService) {
            this.header = header;
            this.prefix = prefix;
            this.jwtService = jwtService;
            this.userDetailsService = userDetailsService;
        }

        @Override
        protected void doFilterInternal(HttpServletRequest request,
                                        HttpServletResponse response,
                                        FilterChain filterChain) throws ServletException, IOException {

            String authHeader = request.getHeader(header);
            if (StringUtils.hasText(authHeader) && authHeader.startsWith(prefix)) {
                String token = authHeader.substring(prefix.length()).trim();
                try {
                    String username = jwtService.extractUsername(token);
                    if (username != null &&
                            org.springframework.security.core.context.SecurityContextHolder.getContext().getAuthentication() == null) {

                        var userDetails = userDetailsService.loadUserByUsername(username);
                        if (jwtService.isTokenValid(token, userDetails)) {
                            Collection<? extends GrantedAuthority> authorities = userDetails.getAuthorities();
                            Authentication auth =
                                    new UsernamePasswordAuthenticationToken(userDetails, null, authorities);
                            org.springframework.security.core.context.SecurityContextHolder.getContext().setAuthentication(auth);
                        }
                    }
                } catch (AuthenticationException ex) {
                    log.warn("JWT authentication failed: {}", ex.getMessage());
                    handleAuthError(response, ex.getMessage());
                    return; // Abort filter chain
                } catch (Exception ex) {
                    log.error("Unexpected error while validating JWT", ex);
                    handleAuthError(response, "Internal authentication error");
                    return;
                }
            }

            filterChain.doFilter(request, response);
        }

        private void handleAuthError(HttpServletResponse response, String message) throws IOException {
            response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            response.setContentType(MediaType.APPLICATION_JSON_VALUE);
            mapper.writeValue(response.getOutputStream(), new ErrorResponse(message));
        }

        private record ErrorResponse(String error) {}
    }

    /* --------------------------------------------------------------------- */
    /* ---- Helper beans/interfaces used in config --------------------------*/
    /* --------------------------------------------------------------------- */

    /**
     * Simple facade for issuing & validating JWTs. Actual implementation lives
     * in the security module, but an interface allows us to avoid circular deps.
     */
    public interface JwtTokenService {
        String extractUsername(String token);
        boolean isTokenValid(String token, org.springframework.security.core.userdetails.UserDetails userDetails);
    }
}
```