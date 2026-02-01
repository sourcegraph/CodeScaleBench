package com.opsforge.nexus.gateway.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;

/**
 * Tests for {@link SecurityFilter}.
 *
 * The {@link SecurityFilter} is expected to:
 *  1. Extract a JWT from the {@code Authorization} header.
 *  2. Delegate validation to {@link JwtTokenProvider}.
 *  3. On success, populate the {@link org.springframework.security.core.context.SecurityContext}
 *     with the {@link Authentication} returned by the provider and continue the chain.
 *  4. On failure, abort the chain, clear the context, and send an HTTP 401.
 *  5. Skip processing for whitelisted paths (e.g. actuator, swagger).
 */
@ExtendWith(MockitoExtension.class)
class SecurityFilterTest {

    private static final String VALID_JWT = "header.payload.signature";
    private static final String INVALID_JWT = "invalid.jwt.token";
    private static final String AUTH_HEADER_VALUE = "Bearer " + VALID_JWT;

    @Mock
    private JwtTokenProvider jwtTokenProvider;

    // We inject mocks *after* providing whitelisted paths so they propagate to constructor.
    @InjectMocks
    private SecurityFilter securityFilter =
            new SecurityFilter(
                    jwtTokenProvider,
                    List.of("/actuator/**", "/swagger-ui/**", "/v3/api-docs/**"));

    @BeforeEach
    void setUp() {
        SecurityContextHolder.clearContext();
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
        verifyNoMoreInteractions(jwtTokenProvider);
    }

    @Nested
    @DisplayName("Valid JWT Scenarios")
    class ValidJwtTests {

        @Test
        @DisplayName("Should authenticate request and delegate to next filter")
        void shouldSetAuthenticationForValidJwt() throws ServletException, IOException {
            // Arrange
            MockHttpServletRequest request = new MockHttpServletRequest("GET", "/utilities/convert");
            request.addHeader(HttpHeaders.AUTHORIZATION, AUTH_HEADER_VALUE);
            MockHttpServletResponse response = new MockHttpServletResponse();
            DummyFilterChain chain = new DummyFilterChain();

            Authentication expectedAuth =
                    new UsernamePasswordAuthenticationToken(
                            "john.doe",
                            null,
                            List.of(new SimpleGrantedAuthority("ROLE_USER")));

            when(jwtTokenProvider.resolveToken(any(HttpServletRequest.class))).thenReturn(VALID_JWT);
            when(jwtTokenProvider.validateToken(VALID_JWT)).thenReturn(true);
            when(jwtTokenProvider.getAuthentication(VALID_JWT)).thenReturn(expectedAuth);

            // Act
            securityFilter.doFilter(request, response, chain);

            // Assert
            assertThat(chain.wasCalled()).as("Filter chain should proceed").isTrue();
            assertThat(SecurityContextHolder.getContext().getAuthentication())
                    .as("Authentication should be set")
                    .isEqualTo(expectedAuth);
            assertThat(response.getStatus())
                    .as("Response status should be unchanged")
                    .isEqualTo(HttpStatus.OK.value());

            // Verify interactions
            verify(jwtTokenProvider).resolveToken(any(HttpServletRequest.class));
            verify(jwtTokenProvider).validateToken(VALID_JWT);
            verify(jwtTokenProvider).getAuthentication(VALID_JWT);
        }
    }

    @Nested
    @DisplayName("Invalid or Missing JWT Scenarios")
    class InvalidJwtTests {

        @Test
        @DisplayName("Should send 401 when token is invalid")
        void shouldRejectRequestWithInvalidJwt() throws ServletException, IOException {
            // Arrange
            MockHttpServletRequest request = new MockHttpServletRequest("POST", "/utilities/convert");
            request.addHeader(HttpHeaders.AUTHORIZATION, "Bearer " + INVALID_JWT);
            MockHttpServletResponse response = new MockHttpServletResponse();
            DummyFilterChain chain = new DummyFilterChain();

            when(jwtTokenProvider.resolveToken(any(HttpServletRequest.class))).thenReturn(INVALID_JWT);
            when(jwtTokenProvider.validateToken(INVALID_JWT)).thenReturn(false);

            // Act
            securityFilter.doFilter(request, response, chain);

            // Assert
            assertThat(chain.wasCalled())
                    .as("Filter chain should NOT proceed for invalid tokens")
                    .isFalse();
            assertThat(SecurityContextHolder.getContext().getAuthentication())
                    .as("Authentication context should be empty")
                    .isNull();
            assertThat(response.getStatus())
                    .as("Response status should be 401 Unauthorized")
                    .isEqualTo(HttpStatus.UNAUTHORIZED.value());

            // Verify interactions
            verify(jwtTokenProvider).resolveToken(any(HttpServletRequest.class));
            verify(jwtTokenProvider).validateToken(INVALID_JWT);
        }

        @Test
        @DisplayName("Should send 401 when Authorization header is missing")
        void shouldRejectRequestWhenHeaderMissing() throws ServletException, IOException {
            // Arrange
            MockHttpServletRequest request = new MockHttpServletRequest("GET", "/utilities/convert");
            MockHttpServletResponse response = new MockHttpServletResponse();
            DummyFilterChain chain = new DummyFilterChain();

            when(jwtTokenProvider.resolveToken(any(HttpServletRequest.class))).thenReturn(null);

            // Act
            securityFilter.doFilter(request, response, chain);

            // Assert
            assertThat(chain.wasCalled()).isFalse();
            assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
            assertThat(response.getStatus()).isEqualTo(HttpStatus.UNAUTHORIZED.value());

            verify(jwtTokenProvider).resolveToken(any(HttpServletRequest.class));
        }
    }

    @Nested
    @DisplayName("Whitelist Path Scenarios")
    class WhitelistTests {

        @Test
        @DisplayName("Should bypass filter for whitelisted endpoint")
        void shouldIgnoreWhitelistedPath() throws ServletException, IOException {
            // Arrange
            MockHttpServletRequest request = new MockHttpServletRequest("GET", "/actuator/health");
            MockHttpServletResponse response = new MockHttpServletResponse();
            DummyFilterChain chain = new DummyFilterChain();

            // Act
            securityFilter.doFilter(request, response, chain);

            // Assert
            assertThat(chain.wasCalled()).isTrue();
            assertThat(SecurityContextHolder.getContext().getAuthentication()).isNull();
            assertThat(response.getStatus()).isEqualTo(HttpStatus.OK.value());

            // Verify no interaction with token provider
            verify(jwtTokenProvider, never()).resolveToken(any(HttpServletRequest.class));
            verify(jwtTokenProvider, never()).validateToken(anyString());
            verify(jwtTokenProvider, never()).getAuthentication(anyString());
        }
    }

    /**
     * Simple {@link FilterChain} implementation that records whether it was invoked.
     * Useful for asserting that the filter either continues or stops processing.
     */
    private static class DummyFilterChain implements FilterChain {

        private boolean called;

        @Override
        public void doFilter(
                jakarta.servlet.ServletRequest servletRequest,
                jakarta.servlet.ServletResponse servletResponse)
                throws IOException, ServletException {
            this.called = true;
            // Typical production chain may set response status to 200 OK by default
            if (servletResponse instanceof HttpServletResponse response
                    && response.getStatus() == 0) {
                response.setStatus(HttpStatus.OK.value());
            }
        }

        boolean wasCalled() {
            return called;
        }
    }
}