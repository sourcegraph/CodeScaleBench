```java
package com.sprintcart.app.config;

import com.sprintcart.app.security.jwt.JwtAuthenticationFilter;
import com.sprintcart.app.security.jwt.JwtTokenProvider;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.dao.DaoAuthenticationProvider;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.authentication.configuration.AuthenticationConfiguration;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.access.AccessDeniedHandler;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.security.web.csrf.CookieCsrfTokenRepository;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;

import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.Instant;
import java.util.List;

/**
 * Configures Spring Security for SprintCart Pro.
 * <p>
 * The platform authenticates API calls with stateless JWT tokens and
 * uses method-level security across the service layer. Certain public
 * resources (product catalog read APIs, login, static assets) are
 * exposed without prior authentication while everything else is locked down.
 */
@Configuration
@EnableMethodSecurity // Enables @PreAuthorize, @PostAuthorize, etc.
@RequiredArgsConstructor
@Slf4j
public class WebSecurityConfig {

    private static final String[] PUBLIC_ENDPOINTS = {
            "/api/v1/auth/**",
            "/api/v1/health/**",
            "/api/v1/webhook/**",                // Used for payment-provider callbacks
            "/_next/**",                         // Vue/Vite dev-server assets
            "/favicon.ico",
            "/resources/**",
            "/static/**",
            "/public/**"
    };

    private static final String[] SWAGGER_ENDPOINTS = {
            "/swagger-ui/**",
            "/v3/api-docs/**",
            "/swagger-resources/**"
    };

    private final UserDetailsService      userDetailsService;
    private final JwtAuthenticationFilter jwtAuthenticationFilter;
    private final JwtTokenProvider        jwtTokenProvider;
    private final Environment             env;

    @Value("${sprintcart.csrf.cookieName:XSRF-TOKEN}")
    private String csrfCookieName;

    /**
     * Main security filter chain. Configures CORS, CSRF, stateless sessions,
     * endpoint authorization rules and custom exception handlers.
     */
    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {

        // Enable/disable frame options for H2 console in dev profile
        if (List.of(env.getActiveProfiles()).contains("dev")) {
            http.headers(headers -> headers.frameOptions().sameOrigin());
        }

        http
            .cors(Customizer.withDefaults())
            .csrf(csrf -> csrf
                    .csrfTokenRepository(CookieCsrfTokenRepository.withHttpOnlyFalse())
                    .csrfTokenRepository(CookieCsrfTokenRepository.withHttpOnlyFalse())
            )
            .sessionManagement(sm -> sm.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .exceptionHandling(ex -> ex
                    .authenticationEntryPoint(restAuthenticationEntryPoint())
                    .accessDeniedHandler(restAccessDeniedHandler())
            )
            .authorizeHttpRequests(auth -> auth
                    .requestMatchers(PUBLIC_ENDPOINTS).permitAll()
                    .requestMatchers(SWAGGER_ENDPOINTS).permitAll()
                    .requestMatchers(HttpMethod.GET,
                            "/api/v1/products/**",
                            "/api/v1/categories/**")
                    .permitAll()
                    .anyRequest().authenticated()
            )
            .addFilterBefore(jwtAuthenticationFilter, UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }

    /**
     * Password encoder used by the {@link DaoAuthenticationProvider}.
     * BCrypt with strength 12 is a good balance between security and performance.
     */
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder(12);
    }

    /**
     * Authentication manager delegating to {@link DaoAuthenticationProvider}.
     */
    @Bean
    public AuthenticationManager authenticationManager(
            AuthenticationConfiguration configuration,
            PasswordEncoder             passwordEncoder) throws Exception {

        DaoAuthenticationProvider provider = new DaoAuthenticationProvider();
        provider.setPasswordEncoder(passwordEncoder);
        provider.setUserDetailsService(userDetailsService);

        return configuration.getAuthenticationManager();
    }

    /**
     * Defines global CORS policy. In production we allow the SPA
     * origin plus internal micro-services. In dev profile we allow
     * everything to avoid local setup friction.
     */
    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        var cors = new CorsConfiguration();
        if (List.of(env.getActiveProfiles()).contains("dev")) {
            cors.addAllowedOriginPattern("*");
        } else {
            cors.setAllowedOrigins(List.of(
                    "https://admin.sprintcart.io",
                    "https://shop.sprintcart.io"
            ));
        }
        cors.setAllowedMethods(List.of("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"));
        cors.setAllowedHeaders(List.of("Authorization", "Content-Type", "X-Requested-With", "X-XSRF-TOKEN"));
        cors.setExposedHeaders(List.of("Authorization", "X-XSRF-TOKEN"));
        cors.setAllowCredentials(true);
        cors.setMaxAge(3600L);
        return request -> cors;
    }

    /* ------------------------------------------------------------------------
     * Custom exception handlers to guarantee JSON responses for API clients.
     * --------------------------------------------------------------------- */

    @Bean
    public AuthenticationEntryPoint restAuthenticationEntryPoint() {
        return new AuthenticationEntryPoint() {
            @Override
            public void commence(
                    HttpServletRequest  request,
                    HttpServletResponse response,
                    org.springframework.security.core.AuthenticationException authException)
                    throws IOException {

                log.warn("Unauthorized access: {} {}", request.getMethod(), request.getRequestURI());
                writeErrorResponse(response, HttpStatus.UNAUTHORIZED, "Unauthorized");
            }
        };
    }

    @Bean
    public AccessDeniedHandler restAccessDeniedHandler() {
        return new AccessDeniedHandler() {
            @Override
            public void handle(
                    HttpServletRequest request,
                    HttpServletResponse response,
                    org.springframework.security.access.AccessDeniedException accessDeniedException)
                    throws IOException {

                log.warn("Forbidden access: {} {}", request.getMethod(), request.getRequestURI());
                writeErrorResponse(response, HttpStatus.FORBIDDEN, "Forbidden");
            }
        };
    }

    /* ------------------------------------------------------------------------
     * Internal helper
     * --------------------------------------------------------------------- */

    private void writeErrorResponse(HttpServletResponse response,
                                    HttpStatus          status,
                                    String              message) throws IOException {

        response.setStatus(status.value());
        response.setContentType("application/json");
        response.getWriter().format("""
                {
                  "timestamp": "%s",
                  "status": %d,
                  "error": "%s",
                  "message": "%s"
                }
                """, Instant.now().toString(), status.value(), status.getReasonPhrase(), message);
    }
}
```