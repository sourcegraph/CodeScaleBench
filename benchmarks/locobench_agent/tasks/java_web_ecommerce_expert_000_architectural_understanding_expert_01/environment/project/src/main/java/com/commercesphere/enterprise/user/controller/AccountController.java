package com.commercesphere.enterprise.user.controller;

import com.commercesphere.enterprise.common.dto.PagedResponse;
import com.commercesphere.enterprise.common.exceptions.EntityNotFoundException;
import com.commercesphere.enterprise.user.dto.AccountResponse;
import com.commercesphere.enterprise.user.dto.CreateAccountRequest;
import com.commercesphere.enterprise.user.dto.UpdateAccountRequest;
import com.commercesphere.enterprise.user.service.AccountService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Size;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.util.MultiValueMap;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.server.ResponseStatusException;

import java.net.URI;
import java.net.URISyntaxException;
import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * REST controller that exposes CRUD operations for business accounts.
 * <p>
 * Account represents a legal entity (buyer or seller) and can contain
 * one or more {@code User}s with hierarchical permissions. For security reasons,
 * every method is protected by Spring Security
 * {@code PreAuthorize} expressions that consult both static roles and
 * dynamic ACL checks inside {@link AccountService}.
 */
@Slf4j
@Validated
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/v1/accounts")
public class AccountController {

    private static final String HEADER_ETAG = "ETag";

    private final AccountService accountService;

    /**
     * Create a new account including a root administrator user.
     *
     * @param request       validated body
     * @param authentication current principal information
     * @return created representation with HTTP 201
     */
    @PostMapping
    @PreAuthorize("hasAuthority('ACCOUNT_CREATE')")
    public ResponseEntity<AccountResponse> createAccount(@Valid @RequestBody CreateAccountRequest request,
                                                         Authentication authentication) throws URISyntaxException {

        log.debug("User '{}' attempts to create account '{}'", authentication.getName(), request.getLegalName());

        AccountResponse created = accountService.createAccount(request, authentication);

        MultiValueMap<String, String> headers = new HttpHeaders();
        headers.setETag(buildEtag(created.getVersion()));
        headers.setLocation(new URI("/api/v1/accounts/" + created.getId()));

        return new ResponseEntity<>(created, headers, HttpStatus.CREATED);
    }

    /**
     * Retrieve an account by id.
     *
     * @param accountId account identifier (UUID)
     * @return account representation
     */
    @GetMapping("/{accountId}")
    @PreAuthorize("@accountPermissionEvaluator.canViewAccount(authentication, #accountId)")
    public ResponseEntity<AccountResponse> getAccount(@PathVariable UUID accountId,
                                                      WebRequest webRequest) {

        AccountResponse account = accountService.getAccount(accountId)
                                                .orElseThrow(() ->
                                                        new ResponseStatusException(HttpStatus.NOT_FOUND,
                                                                "Account not found: " + accountId));

        // ETag / Conditional GET
        String currentEtag = buildEtag(account.getVersion());
        if (webRequest.checkNotModified(currentEtag)) {
            return ResponseEntity.status(HttpStatus.NOT_MODIFIED).build();
        }

        return ResponseEntity.ok().eTag(currentEtag).body(account);
    }

    /**
     * Perform a paginated search of accounts.
     *
     * @param searchTerm optional fuzzy search
     * @param page       page index (0-based)
     * @param size       page size
     * @param sort       sort by property
     * @param dir        sort direction
     * @return page of accounts
     */
    @GetMapping
    @PreAuthorize("hasAuthority('ACCOUNT_READ')")
    public ResponseEntity<PagedResponse<AccountResponse>> searchAccounts(
            @RequestParam(required = false) @Size(min = 3, max = 64) String searchTerm,
            @RequestParam(defaultValue = "0") @Min(0) int page,
            @RequestParam(defaultValue = "20") @Min(1) int size,
            @RequestParam(defaultValue = "legalName") String sort,
            @RequestParam(defaultValue = "ASC") Sort.Direction dir) {

        PageRequest pageable = PageRequest.of(page, size, dir, sort);
        Page<AccountResponse> resultPage = accountService.searchAccounts(searchTerm, pageable);

        PagedResponse<AccountResponse> response =
                new PagedResponse<>(resultPage.getContent(),
                                    resultPage.getNumber(),
                                    resultPage.getSize(),
                                    resultPage.getTotalElements(),
                                    resultPage.getTotalPages(),
                                    resultPage.isLast());

        return ResponseEntity.ok(response);
    }

    /**
     * Update an existing account.
     *
     * @param accountId id to update
     * @param request   update request body
     * @param ifMatch   optimistic locking header (required)
     * @return updated representation
     */
    @PutMapping("/{accountId}")
    @PreAuthorize("hasAuthority('ACCOUNT_UPDATE') && " +
            "@accountPermissionEvaluator.canManageAccount(authentication, #accountId)")
    public ResponseEntity<AccountResponse> updateAccount(
            @PathVariable UUID accountId,
            @Valid @RequestBody UpdateAccountRequest request,
            @RequestHeader(name = HttpHeaders.IF_MATCH) String ifMatch) {

        long expectedVersion = parseEtag(ifMatch);

        AccountResponse updated = accountService.updateAccount(accountId, request, expectedVersion);

        return ResponseEntity
                .ok()
                .eTag(buildEtag(updated.getVersion()))
                .body(updated);
    }

    /**
     * Deactivate an account (soft delete). Existing orders remain untouched.
     *
     * @param accountId account identifier
     * @return 204 NO_CONTENT
     */
    @PatchMapping("/{accountId}/deactivate")
    @PreAuthorize("hasAuthority('ACCOUNT_DEACTIVATE') && " +
            "@accountPermissionEvaluator.canManageAccount(authentication, #accountId)")
    public ResponseEntity<Void> deactivateAccount(@PathVariable UUID accountId) {

        accountService.deactivateAccount(accountId);
        log.info("Account '{}' deactivated at {}", accountId, OffsetDateTime.now());

        return ResponseEntity.noContent().build();
    }

    /* ====================================================================== */
    /* ----------------------------  Utilities  ----------------------------- */
    /* ====================================================================== */

    private static String buildEtag(long version) {
        // Strong ETag format --> "v123"
        return String.format("\"v%d\"", version);
    }

    private static long parseEtag(String etag) {
        if (etag == null || !etag.matches("\"v\\d+\"")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Missing or malformed If-Match header");
        }
        return Long.parseLong(etag.substring(2, etag.length() - 1));
    }
}

/* ========================================================================== */
/* ----------------------  Package-private Exception Handler  ---------------- */
/* ========================================================================== */

@Slf4j
@RestControllerAdvice(basePackageClasses = AccountController.class)
class AccountControllerAdvice {

    @ExceptionHandler(EntityNotFoundException.class)
    public ResponseEntity<ApiError> handleNotFound(EntityNotFoundException ex) {
        return buildError(HttpStatus.NOT_FOUND, ex);
    }

    @ExceptionHandler(IllegalStateException.class)
    public ResponseEntity<ApiError> handleConflict(IllegalStateException ex) {
        return buildError(HttpStatus.CONFLICT, ex);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiError> handleUnexpected(Exception ex) {
        log.error("Unexpected error:", ex);
        return buildError(HttpStatus.INTERNAL_SERVER_ERROR, ex);
    }

    private ResponseEntity<ApiError> buildError(HttpStatus status, Exception ex) {
        ApiError body = new ApiError(
                OffsetDateTime.now(),
                status.value(),
                status.getReasonPhrase(),
                ex.getMessage());
        return ResponseEntity.status(status).body(body);
    }

    /**
     * Lightweight error response object.
     * In a real project this would live in the common error-handling module.
     */
    private record ApiError(OffsetDateTime timestamp,
                            int status,
                            String error,
                            String message) { }
}