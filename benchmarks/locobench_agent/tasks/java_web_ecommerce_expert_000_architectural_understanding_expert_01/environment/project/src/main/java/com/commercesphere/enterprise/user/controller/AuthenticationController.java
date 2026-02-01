package com.commercesphere.enterprise.user.controller;

import com.commercesphere.enterprise.common.audit.AuditTrail;
import com.commercesphere.enterprise.common.audit.AuditTrail.Action;
import com.commercesphere.enterprise.common.error.APIError;
import com.commercesphere.enterprise.common.error.ErrorCode;
import com.commercesphere.enterprise.security.jwt.TokenPair;
import com.commercesphere.enterprise.user.service.AuthenticationService;
import com.commercesphere.enterprise.user.service.TokenService;
import com.commercesphere.enterprise.user.service.UserService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

/**
 * AuthenticationController exposes RESTful endpoints for login, token refresh,
 * and logout. All actions are audited and leverage HTTP-only cookies to mitigate
 * XSS token exfiltration.
 *
 * Endpoints:
 *  POST /api/v1/auth/login         — Username/password authentication
 *  POST /api/v1/auth/refresh-token — Issue a new access token using a refresh token
 *  POST /api/v1/auth/logout        — Revoke and delete tokens
 *
 * The controller purposely avoids exposing session-specific information (e.g.,
 * refresh token) in the response body; instead, refresh tokens are stored in
 * HTTP-only, Secure cookies.
 */
@Slf4j
@RestController
@RequestMapping(
        value = "/api/v1/auth",
        produces = MediaType.APPLICATION_JSON_VALUE)
@Validated
@RequiredArgsConstructor
public class AuthenticationController {

    private static final String REFRESH_TOKEN_COOKIE = "CS_REFRESH_TOKEN";
    private static final int REFRESH_TOKEN_TTL_SEC = 30 * 24 * 60 * 60; // 30 days

    private final AuthenticationService authenticationService;
    private final TokenService tokenService;
    private final UserService userService;
    private final AuditTrail auditTrail;

    /**
     * Authenticates a user with username/email and password.
     *
     * @param request        validated login request
     * @param servletRequest raw servlet request for IP extraction
     * @return AuthResponse  containing a short-lived JWT access token
     */
    @PostMapping(
            path = "/login",
            consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<AuthResponse> login(
            @Valid @RequestBody LoginRequest request,
            HttpServletRequest servletRequest) {

        final String clientIp = extractClientIp(servletRequest);
        try {
            TokenPair tokenPair = authenticationService.authenticate(
                    request.getIdentifier(),
                    request.getPassword(),
                    clientIp);

            ResponseCookie refreshCookie = buildRefreshCookie(tokenPair.getRefreshToken());

            auditTrail.record(Action.LOGIN_SUCCESS, request.getIdentifier(), clientIp);

            return ResponseEntity.ok()
                    .header(HttpHeaders.SET_COOKIE, refreshCookie.toString())
                    .body(new AuthResponse(tokenPair.getAccessToken()));
        } catch (AuthenticationService.AuthenticationException ex) {
            auditTrail.record(Action.LOGIN_FAILURE, request.getIdentifier(), clientIp);
            throw APIError.of(ErrorCode.AUTH_INVALID_CREDENTIALS, ex.getMessage());
        }
    }

    /**
     * Uses the refresh token (stored in an HTTP-only cookie) to mint a new
     * access token.
     *
     * @param servletRequest raw servlet request
     * @return AuthResponse  containing a fresh access token
     */
    @PostMapping("/refresh-token")
    public ResponseEntity<AuthResponse> refreshToken(HttpServletRequest servletRequest) {
        String refreshToken = extractRefreshToken(servletRequest);
        if (refreshToken == null) {
            throw APIError.of(ErrorCode.AUTH_TOKEN_MISSING, "Refresh token is not present");
        }

        try {
            String newAccessToken = tokenService.refreshAccessToken(refreshToken);
            return ResponseEntity.ok(new AuthResponse(newAccessToken));
        } catch (TokenService.TokenException ex) {
            // Revoke cookie on client side if refresh fails (e.g., expired/black-listed)
            ResponseCookie cookie = buildExpiredRefreshCookie();
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED)
                    .header(HttpHeaders.SET_COOKIE, cookie.toString())
                    .body(new AuthResponse(null));
        }
    }

    /**
     * Logs out the user by revoking the refresh token (server-side blacklist)
     * and instructing the client to delete its cookie.
     *
     * @param servletRequest raw servlet request
     * @return 204 NO CONTENT
     */
    @PostMapping("/logout")
    public ResponseEntity<Void> logout(HttpServletRequest servletRequest) {
        String refreshToken = extractRefreshToken(servletRequest);
        if (refreshToken != null) {
            tokenService.revokeRefreshToken(refreshToken);
        }

        ResponseCookie cookie = buildExpiredRefreshCookie();
        return ResponseEntity.noContent()
                .header(HttpHeaders.SET_COOKIE, cookie.toString())
                .build();
    }

    // ------------------------------------------------------------------------
    // Helper methods
    // ------------------------------------------------------------------------

    private String extractClientIp(HttpServletRequest request) {
        String xfHeader = request.getHeader("X-Forwarded-For");
        return xfHeader != null ? xfHeader.split(",")[0] : request.getRemoteAddr();
    }

    private String extractRefreshToken(HttpServletRequest request) {
        if (request.getCookies() == null) {
            return null;
        }
        for (javax.servlet.http.Cookie cookie : request.getCookies()) {
            if (REFRESH_TOKEN_COOKIE.equals(cookie.getName())) {
                return cookie.getValue();
            }
        }
        return null;
    }

    private ResponseCookie buildRefreshCookie(String token) {
        return ResponseCookie.from(REFRESH_TOKEN_COOKIE, token)
                .httpOnly(true)
                .secure(true)
                .sameSite("Strict")
                .path("/api/v1/auth")
                .maxAge(REFRESH_TOKEN_TTL_SEC)
                .build();
    }

    private ResponseCookie buildExpiredRefreshCookie() {
        return ResponseCookie.from(REFRESH_TOKEN_COOKIE, "")
                .httpOnly(true)
                .secure(true)
                .sameSite("Strict")
                .path("/api/v1/auth")
                .maxAge(0)
                .build();
    }

    // ------------------------------------------------------------------------
    // DTOs
    // ------------------------------------------------------------------------

    @Data
    static class LoginRequest {

        /**
         * Username or e-mail address.
         */
        @NotBlank
        @Size(min = 2, max = 128)
        private String identifier;

        /**
         * Clear-text password (will be hashed by the service layer).
         */
        @NotBlank
        @Size(min = 8, max = 128)
        private String password;
    }

    @Data
    @AllArgsConstructor
    static class AuthResponse {

        /**
         * Short-lived (e.g., 15-minute) JWT used for authenticating API calls.
         */
        private String accessToken;
    }
}