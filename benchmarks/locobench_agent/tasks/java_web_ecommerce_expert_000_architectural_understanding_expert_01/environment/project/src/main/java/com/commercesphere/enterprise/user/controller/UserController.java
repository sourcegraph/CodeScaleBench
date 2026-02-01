```java
package com.commercesphere.enterprise.user.controller;

import com.commercesphere.enterprise.common.web.ApiError;
import com.commercesphere.enterprise.common.web.ApiResponse;
import com.commercesphere.enterprise.security.CurrentUser;
import com.commercesphere.enterprise.security.UserPrincipal;
import com.commercesphere.enterprise.user.dto.CreateUserRequest;
import com.commercesphere.enterprise.user.dto.UpdateUserRequest;
import com.commercesphere.enterprise.user.dto.UserDto;
import com.commercesphere.enterprise.user.service.UserService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Positive;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.modelmapper.ModelMapper;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.validation.BindingResult;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.time.Instant;
import java.util.Objects;

/**
 * REST controller that exposes CRUD endpoints for user management within the
 * CommerceSphere Enterprise Suite. All URIs are versioned under /api/v1/users.
 *
 * <p>Responsibility of this class is limited to:</p>
 * <ul>
 *   <li>HTTP layer concerns (request parsing, response shaping)</li>
 *   <li>Delegating business logic to {@link UserService}</li>
 *   <li>Translating validation & business exceptions to proper HTTP status codes</li>
 * </ul>
 *
 * Business rules are implemented in the service layer to keep the controller thin.
 */
@Slf4j
@RestController
@RequestMapping("/api/v1/users")
@RequiredArgsConstructor
public class UserController {

    private final UserService userService;
    private final ModelMapper mapper;

    /* --------------------------------------------------------------------- */
    /* Create                                                                */
    /* --------------------------------------------------------------------- */

    /**
     * Registers a new user account. The caller must have the {@code USER_WRITE} authority
     * (typically an admin or an automated provisioning job).
     *
     * @param request Incoming JSON body with user details
     * @return Created {@link UserDto}
     */
    @PostMapping
    @PreAuthorize("hasAuthority('USER_WRITE')")
    public ResponseEntity<ApiResponse<UserDto>> createUser(
            @Valid @RequestBody CreateUserRequest request,
            BindingResult bindingResult) {

        handleBindingErrors(bindingResult);

        UserDto created = userService.createUser(request);
        return ResponseEntity
                .status(HttpStatus.CREATED)
                .body(ApiResponse.ok(created));
    }

    /* --------------------------------------------------------------------- */
    /* Read                                                                  */
    /* --------------------------------------------------------------------- */

    /**
     * Retrieves a user by its numeric identifier.
     *
     * @param id User ID
     */
    @GetMapping("/{id}")
    @PreAuthorize("hasAuthority('USER_READ')")
    public ResponseEntity<ApiResponse<UserDto>> findById(
            @PathVariable @Positive(message = "User ID must be positive") Long id) {

        UserDto dto = userService.findUserById(id);
        return ResponseEntity.ok(ApiResponse.ok(dto));
    }

    /**
     * Searches users using pagination & optional keyword filter.
     *
     * @param pageable Spring Data slice abstraction
     * @param keyword  Optional free‐text keyword to be matched against username / email
     */
    @GetMapping
    @PreAuthorize("hasAuthority('USER_READ')")
    public ResponseEntity<ApiResponse<Page<UserDto>>> search(
            Pageable pageable,
            @RequestParam(value = "q", required = false) String keyword) {

        Page<UserDto> page = userService.searchUsers(keyword, pageable);
        return ResponseEntity.ok(ApiResponse.ok(page));
    }

    /**
     * Retrieves the profile of the currently authenticated principal.
     */
    @GetMapping("/@me")
    public ResponseEntity<ApiResponse<UserDto>> me(@CurrentUser UserPrincipal principal) {
        UserDto dto = mapper.map(principal, UserDto.class);
        return ResponseEntity.ok(ApiResponse.ok(dto));
    }

    /* --------------------------------------------------------------------- */
    /* Update                                                                */
    /* --------------------------------------------------------------------- */

    /**
     * Updates a user in-place. Only admin users or the account owner can perform the operation.
     */
    @PutMapping("/{id}")
    @PreAuthorize("hasAuthority('USER_WRITE') or #id == principal.id")
    public ResponseEntity<ApiResponse<UserDto>> update(
            @PathVariable Long id,
            @Valid @RequestBody UpdateUserRequest request,
            BindingResult bindingResult) {

        handleBindingErrors(bindingResult);

        if (!Objects.equals(id, request.getId())) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "Path parameter ID must match payload ID");
        }
        UserDto updated = userService.updateUser(request);
        return ResponseEntity.ok(ApiResponse.ok(updated));
    }

    /* --------------------------------------------------------------------- */
    /* Delete / Deactivate                                                   */
    /* --------------------------------------------------------------------- */

    /**
     * Soft‐deletes (deactivates) a user account. Physical deletion is disabled to guarantee
     * referential integrity and auditing requirements.
     *
     * @param id User ID
     */
    @DeleteMapping("/{id}")
    @PreAuthorize("hasAuthority('USER_WRITE')")
    public ResponseEntity<ApiResponse<Void>> deactivate(@PathVariable Long id) {
        userService.deactivateUser(id);
        return ResponseEntity.ok(ApiResponse.ok());
    }

    /* --------------------------------------------------------------------- */
    /* Utility & Exception Handling                                          */
    /* --------------------------------------------------------------------- */

    /**
     * Simple helper that transforms bean‐validation errors into HTTP 400 replies.
     */
    private static void handleBindingErrors(BindingResult bindingResult) {
        if (!bindingResult.hasErrors()) {
            return;
        }

        StringBuilder sb = new StringBuilder("Validation failed: ");
        bindingResult.getFieldErrors().forEach(err ->
                sb.append('[')
                  .append(err.getField())
                  .append(" => ")
                  .append(err.getDefaultMessage())
                  .append(']')
        );
        throw new ResponseStatusException(HttpStatus.BAD_REQUEST, sb.toString());
    }

    /* --------------------------------------------------------------------- */
    /* Fallbacks                                                             */
    /* --------------------------------------------------------------------- */

    /**
     * Fallback handler for any unanticipated exception thrown within controller methods.
     * Returns a sanitized error payload while logging the full stack on the server side.
     */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiError> unexpected(Exception ex) {
        log.error("Unhandled exception in UserController", ex);
        ApiError err = ApiError.builder()
                .timestamp(Instant.now())
                .status(HttpStatus.INTERNAL_SERVER_ERROR.value())
                .error("Internal Server Error")
                .message("An unexpected error occurred. Please contact support.")
                .build();
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(err);
    }
}
```