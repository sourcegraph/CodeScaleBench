package com.sprintcart.adapters.web.rest;

import com.sprintcart.adapters.web.rest.dto.AuthResponseDto;
import com.sprintcart.adapters.web.rest.dto.LoginRequestDto;
import com.sprintcart.adapters.web.rest.dto.RefreshTokenRequestDto;
import com.sprintcart.adapters.web.rest.dto.RegisterRequestDto;
import com.sprintcart.adapters.web.rest.util.ClientIpExtractor;
import com.sprintcart.adapters.web.rest.util.CookieUtils;
import com.sprintcart.domain.model.auth.AuthenticatedUser;
import com.sprintcart.domain.ports.in.auth.AuthenticateUserUseCase;
import com.sprintcart.domain.ports.in.auth.RefreshTokenUseCase;
import com.sprintcart.domain.ports.in.auth.RegisterUserUseCase;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import java.time.Duration;
import java.time.Instant;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

/**
 * REST controller that exposes authentication-related endpoints to the outside world.
 * <p>
 * The controller is located in the Web Adapter layer (Hexagonal Architecture) and
 * therefore never contains business logic. All domain operations are delegated to
 * inbound ports (use cases) which are implemented inside the application core.
 */
@Slf4j
@Validated
@RestController
@RequestMapping(path = "/api/v1/auth", produces = MediaType.APPLICATION_JSON_VALUE)
@RequiredArgsConstructor
public class AuthController {

    private static final String REFRESH_TOKEN_COOKIE = "sprintcart_rt";
    private static final long    REFRESH_TOKEN_TTL_SECONDS = Duration.ofDays(7).toSeconds();

    private final AuthenticateUserUseCase authenticateUserUseCase;
    private final RefreshTokenUseCase     refreshTokenUseCase;
    private final RegisterUserUseCase     registerUserUseCase;

    /**
     * Authenticates a user by e-mail and password.
     *
     * @param loginRequest request body
     * @param request      HTTP servlet request
     * @param response     HTTP servlet response
     * @return an {@link AuthResponseDto} containing JWT access token and basic user profile
     */
    @PostMapping(path = "/login", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<AuthResponseDto> login(@Valid @RequestBody LoginRequestDto loginRequest,
                                                 HttpServletRequest request,
                                                 HttpServletResponse response) {

        String clientIp  = ClientIpExtractor.from(request);
        String userAgent = request.getHeader("User-Agent");

        AuthenticatedUser authenticatedUser = authenticateUserUseCase.authenticate(
                loginRequest.email(),
                loginRequest.password(),
                clientIp,
                userAgent
        );

        // Store refresh token as HttpOnly cookie for XSS protection
        ResponseCookie refreshCookie = buildRefreshTokenCookie(authenticatedUser.refreshToken());
        response.addHeader("Set-Cookie", refreshCookie.toString());

        AuthResponseDto dto = AuthResponseDto.builder()
                .accessToken(authenticatedUser.jwt())
                .expiresIn(authenticatedUser.expiresAt().getEpochSecond())
                .userId(authenticatedUser.userId().value())
                .email(authenticatedUser.email().value())
                .build();

        return ResponseEntity
                .ok()
                .cacheControl(CacheControl.noStore())
                .body(dto);
    }

    /**
     * Issues a new access token given a valid refresh token. The refresh token can be supplied
     * either in the request body or via the {@code sprintcart_rt} cookie.
     */
    @PostMapping(path = "/token", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<AuthResponseDto> refreshToken(@Valid @RequestBody RefreshTokenRequestDto body,
                                                        HttpServletRequest request,
                                                        HttpServletResponse response) {

        String refreshToken = body.refreshToken();
        if (refreshToken == null || refreshToken.isBlank()) {
            // Fallback to cookie
            refreshToken = CookieUtils.readCookie(request, REFRESH_TOKEN_COOKIE).orElse(null);
        }

        AuthenticatedUser authenticatedUser = refreshTokenUseCase.refresh(refreshToken);

        ResponseCookie refreshCookie = buildRefreshTokenCookie(authenticatedUser.refreshToken());
        response.addHeader("Set-Cookie", refreshCookie.toString());

        AuthResponseDto dto = AuthResponseDto.builder()
                .accessToken(authenticatedUser.jwt())
                .expiresIn(authenticatedUser.expiresAt().getEpochSecond())
                .userId(authenticatedUser.userId().value())
                .email(authenticatedUser.email().value())
                .build();

        return ResponseEntity.ok(dto);
    }

    /**
     * Registers a new customer/merchant operator account.
     */
    @PostMapping(path = "/register", consumes = MediaType.APPLICATION_JSON_VALUE)
    @ResponseStatus(HttpStatus.CREATED)
    public void register(@Valid @RequestBody RegisterRequestDto request,
                         HttpServletRequest servletRequest) {

        registerUserUseCase.register(request.toCommand(ClientIpExtractor.from(servletRequest)));
        // Registration is asynchronous – confirmation e-mail will be sent by application service
    }

    /**
     * Performs logout by invalidating the refresh token cookie on the client side.
     */
    @PostMapping("/logout")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void logout(HttpServletResponse response) {
        ResponseCookie expiredCookie = ResponseCookie.from(REFRESH_TOKEN_COOKIE, "")
                .httpOnly(true)
                .secure(true)
                .sameSite("Strict")
                .maxAge(Duration.ZERO)
                .path("/")
                .build();

        response.addHeader("Set-Cookie", expiredCookie.toString());
    }

    /* --------------------------------------------------------------------- */
    /* private helper methods                                                */
    /* --------------------------------------------------------------------- */

    private ResponseCookie buildRefreshTokenCookie(@NotBlank String refreshToken) {
        Instant now = Instant.now();
        return ResponseCookie.from(REFRESH_TOKEN_COOKIE, refreshToken)
                .httpOnly(true)
                .secure(true)
                .sameSite("Strict")
                .maxAge(REFRESH_TOKEN_TTL_SECONDS)
                .path("/")
                .build();
    }
}