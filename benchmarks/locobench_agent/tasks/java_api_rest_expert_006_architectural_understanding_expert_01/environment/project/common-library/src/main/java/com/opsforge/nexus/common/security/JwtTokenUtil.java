package com.opsforge.nexus.common.security;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Header;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.JwtBuilder;
import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.SignatureAlgorithm;
import io.jsonwebtoken.security.Keys;
import io.jsonwebtoken.security.SecurityException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.Collections;
import java.util.Date;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;

/**
 * Thread–safe utility for issuing and validating JSON Web Tokens (JWT) across
 * OpsForge micro-services. <p>
 *
 * Key design goals: <ul>
 *     <li>No framework dependency (can be used from vanilla Java, Spring, Quarkus…)</li>
 *     <li>Immutable once built – safe for application-wide singleton use</li>
 *     <li>Facets for access- and refresh-token handling with independent TTLs</li>
 *     <li>Pluggable blacklist/whitelist for revocation scenarios</li>
 * </ul>
 *
 * A typical bootstrap looks like:
 *
 * <pre>{@code
 * JwtTokenUtil tokenUtil = JwtTokenUtil.builder()
 *     .secret(Base64.getEncoder().encodeToString("32-char-minimum-secret-here".getBytes()))
 *     .accessTokenTtl(Duration.ofMinutes(15))
 *     .refreshTokenTtl(Duration.ofDays(7))
 *     .build();
 * }</pre>
 *
 * @author OpsForge
 */
public final class JwtTokenUtil {

    /* ---------------------------------------------------------- *
     * Static inner support types                                 *
     * ---------------------------------------------------------- */

    /**
     * Lightweight abstraction for token revocation. Backed by Redis, DB, in-memory … –
     * whatever the host application prefers.
     */
    public interface TokenBlacklist {

        /**
         * Returns {@code true} if the presented token has been revoked and must therefore be rejected.
         */
        boolean isRevoked(String token);

        /**
         * Adds the given token to the blacklist (revoked set).
         */
        void revoke(String token);
    }

    /**
     * Default no-op blacklist implementation – i.e., nothing is ever revoked.
     */
    private static final class NoOpBlacklist implements TokenBlacklist {
        @Override public boolean isRevoked(String token) { return false; }
        @Override public void revoke(String token) { /* no-op */ }
    }

    /**
     * JWT-specific runtime exception used within the {@link JwtTokenUtil}.
     */
    public static class JwtTokenException extends RuntimeException {
        public JwtTokenException(String msg, Throwable cause) { super(msg, cause); }
        public JwtTokenException(String msg) { super(msg); }
    }

    /* ---------------------------------------------------------- *
     * Builder                                                     *
     * ---------------------------------------------------------- */

    public static Builder builder() { return new Builder(); }

    public static final class Builder {

        private String secret;
        private SignatureAlgorithm algorithm;
        private Duration accessTtl;
        private Duration refreshTtl;
        private Clock clock = Clock.systemUTC();
        private TokenBlacklist blacklist = new NoOpBlacklist();

        /**
         * Provide the secret as string (plain or Base64-encoded – autodetected).
         * Minimum 32 printable characters are recommended when using HS512.
         */
        public Builder secret(String secret) {
            this.secret = Objects.requireNonNull(secret, "Secret must not be null");
            return this;
        }

        /**
         * Override the default signing algorithm (HS512). The algorithm must
         * be compatible with the supplied secret key size.
         */
        public Builder algorithm(SignatureAlgorithm algorithm) {
            this.algorithm = Objects.requireNonNull(algorithm, "algorithm");
            return this;
        }

        public Builder accessTokenTtl(Duration ttl) {
            this.accessTtl = Objects.requireNonNull(ttl, "accessTokenTtl");
            return this;
        }

        public Builder refreshTokenTtl(Duration ttl) {
            this.refreshTtl = Objects.requireNonNull(ttl, "refreshTokenTtl");
            return this;
        }

        public Builder clock(Clock clock) {
            this.clock = Objects.requireNonNull(clock, "clock");
            return this;
        }

        public Builder blacklist(TokenBlacklist blacklist) {
            this.blacklist = Objects.requireNonNull(blacklist, "blacklist");
            return this;
        }

        public JwtTokenUtil build() {

            if (secret == null || secret.trim().isEmpty()) {
                // Generate random fallback secret for developer convenience – discourage for prod
                LoggerFactory.getLogger(JwtTokenUtil.class)
                             .warn("JWT secret missing – generating random development secret. "
                                   + "NEVER use this in production!");
                secret = generateRandomSecret();
            }

            return new JwtTokenUtil(
                    secret,
                    algorithm != null ? algorithm : SignatureAlgorithm.HS512,
                    accessTtl != null ? accessTtl : Duration.ofMinutes(15),
                    refreshTtl != null ? refreshTtl : Duration.ofDays(7),
                    clock,
                    blacklist != null ? blacklist : new NoOpBlacklist());
        }

        private static String generateRandomSecret() {
            byte[] bytes = new byte[64];
            new SecureRandom().nextBytes(bytes);
            return Base64.getEncoder().encodeToString(bytes);
        }
    }

    /* ---------------------------------------------------------- *
     * Instance members                                            *
     * ---------------------------------------------------------- */

    private static final Logger LOG = LoggerFactory.getLogger(JwtTokenUtil.class);

    private final SecretKey signingKey;
    private final SignatureAlgorithm algorithm;
    private final Duration accessTtl;
    private final Duration refreshTtl;
    private final Clock clock;
    private final TokenBlacklist blacklist;
    private final JwtParser parser;

    private JwtTokenUtil(String secret,
                         SignatureAlgorithm algorithm,
                         Duration accessTtl,
                         Duration refreshTtl,
                         Clock clock,
                         TokenBlacklist blacklist) {

        this.signingKey = keyFromSecret(secret, algorithm);
        this.algorithm = algorithm;
        this.accessTtl = accessTtl;
        this.refreshTtl = refreshTtl;
        this.clock = clock;
        this.blacklist = blacklist;
        this.parser = Jwts.parserBuilder()
                          .setClock(() -> Date.from(clock.instant()))
                          .setSigningKey(signingKey)
                          .build();
    }

    /* ---------------------------------------------------------- *
     * Public API – token generation                              *
     * ---------------------------------------------------------- */

    /**
     * Issues an <strong>access token</strong> containing the given subject and optional claims.
     *
     * @param subject canonical identifier (e.g., username or service account id)
     * @param claims  extra claims – may be {@code null}/empty
     */
    public String generateAccessToken(String subject, Map<String, ?> claims) {
        return buildToken(subject, claims, accessTtl);
    }

    /**
     * Issues a <strong>refresh token</strong> for renewing expired access tokens.
     */
    public String generateRefreshToken(String subject) {
        return buildToken(subject, Collections.emptyMap(), refreshTtl);
    }

    /* ---------------------------------------------------------- *
     * Public API – token parsing/validation                       *
     * ---------------------------------------------------------- */

    /**
     * Validates the token and returns its claims. Throws a
     * {@link JwtTokenException} on any error (signature, expiration, revoked…).
     */
    public Claims validateToken(String token) {
        String compact = stripBearerPrefix(token);
        try {
            if (blacklist.isRevoked(compact)) {
                throw new JwtTokenException("Token has been revoked");
            }
            return parser.parseClaimsJws(compact).getBody();
        } catch (SecurityException ex) { // includes malformed signature
            throw new JwtTokenException("Invalid JWT signature", ex);
        } catch (io.jsonwebtoken.ExpiredJwtException ex) {
            throw new JwtTokenException("Token expired", ex);
        } catch (io.jsonwebtoken.JwtException ex) { // malformed, unsupported etc.
            throw new JwtTokenException("Invalid JWT", ex);
        }
    }

    /**
     * Returns {@code true} if the token is structurally valid and not expired/revoked.
     * Does <em>not</em> check scopes/authorities – caller's job.
     */
    public boolean isValid(String token) {
        try {
            validateToken(token);
            return true;
        } catch (JwtTokenException ex) {
            LOG.debug("Token validation failed: {}", ex.getMessage());
            return false;
        }
    }

    /**
     * Transparently refreshes the provided <em>refresh-token</em> into a brand-new <em>access-token</em>.
     *
     * @throws JwtTokenException if the refresh token is invalid/expired/etc.
     */
    public String refreshAccessToken(String refreshToken, Map<String, ?> extendedClaims) {
        Claims claims = validateToken(refreshToken);

        // a refresh token should not itself be revoked, but let's double-check:
        if (isRefreshToken(claims)) {
            // Re-issue fresh access token preserving subject + optionally merging extended claims
            return generateAccessToken(claims.getSubject(), extendedClaims);
        }
        throw new JwtTokenException("Provided token is not a refresh token");
    }

    /**
     * Revokes a token by adding it to the configured blacklist.
     */
    public void revokeToken(String token) {
        blacklist.revoke(stripBearerPrefix(token));
    }

    /* ---------------------------------------------------------- *
     * Helpers                                                     *
     * ---------------------------------------------------------- */

    private String buildToken(String subject, Map<String, ?> claims, Duration ttl) {

        Instant now = clock.instant();
        Instant expiry = now.plus(ttl);

        JwtBuilder builder = Jwts.builder()
                                 .signWith(signingKey, algorithm)
                                 .setIssuer("opsforge-nexus")
                                 .setSubject(subject)
                                 .setIssuedAt(Date.from(now))
                                 .setExpiration(Date.from(expiry))
                                 .addClaims(Optional.ofNullable(claims).orElse(Collections.emptyMap()))
                                 // token type to aid refresh/access distinction
                                 .setHeaderParam(Header.TYPE, "JWT");

        if (Objects.equals(ttl, refreshTtl)) {
            builder.claim("typ", "REFRESH");
        } else {
            builder.claim("typ", "ACCESS");
        }

        return builder.compact();
    }

    private static String stripBearerPrefix(String token) {
        if (token == null) {
            throw new JwtTokenException("Token is null");
        }
        return token.startsWith("Bearer ") ? token.substring("Bearer ".length()) : token;
    }

    private static SecretKey keyFromSecret(String secret, SignatureAlgorithm algorithm) {
        byte[] bytes;
        try {
            // Autodetect Base64
            if (Base64.getDecoder().decode(secret).length >= 32) {
                bytes = Base64.getDecoder().decode(secret);
            } else {
                bytes = secret.getBytes(StandardCharsets.UTF_8);
            }
        } catch (IllegalArgumentException ex) {
            // Not Base64 – treat as raw string
            bytes = secret.getBytes(StandardCharsets.UTF_8);
        }
        return Keys.hmacShaKeyFor(bytes);
    }

    private boolean isRefreshToken(Claims claims) {
        return "REFRESH".equals(claims.get("typ"));
    }

    /* ---------------------------------------------------------- *
     * Getter section                                              *
     * ---------------------------------------------------------- */

    public Duration getAccessTtl()    { return accessTtl; }
    public Duration getRefreshTtl()   { return refreshTtl; }
    public SignatureAlgorithm getAlgorithm() { return algorithm; }
    public Clock getClock()           { return clock; }
    public TokenBlacklist getBlacklist() { return blacklist; }
}