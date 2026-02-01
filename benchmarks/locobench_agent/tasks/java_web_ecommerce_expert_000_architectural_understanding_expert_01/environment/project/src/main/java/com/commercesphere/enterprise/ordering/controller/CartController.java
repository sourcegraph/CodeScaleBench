package com.commercesphere.enterprise.ordering.controller;

import com.commercesphere.enterprise.ordering.dto.CartDto;
import com.commercesphere.enterprise.ordering.dto.CartItemDto;
import com.commercesphere.enterprise.ordering.dto.command.AddCartItemCommand;
import com.commercesphere.enterprise.ordering.dto.command.UpdateCartItemCommand;
import com.commercesphere.enterprise.ordering.exception.CartNotFoundException;
import com.commercesphere.enterprise.ordering.exception.InventoryUnavailableException;
import com.commercesphere.enterprise.ordering.service.CartService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.transaction.TransactionSystemException;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.net.URI;
import java.time.OffsetDateTime;
import java.util.List;

/**
 * REST controller that exposes CRUD-like operations over the authenticated
 * customer’s shopping cart.  
 *
 * NOTE: The controller is intentionally lean—input validation, security, and
 * error handling are kept here, while business rules live inside the
 * {@link CartService}.  This separation eases unit-testing and minimizes
 * controller bloat.
 */
@RestController
@RequestMapping("/api/v1/carts")
@Validated
public class CartController {

    private static final Logger LOG = LoggerFactory.getLogger(CartController.class);

    private final CartService cartService;

    public CartController(CartService cartService) {
        this.cartService = cartService;
    }

    /**
     * Returns the current cart for the authenticated user (and optionally, a
     * specific account hierarchy).  If the cart does not exist yet, one is
     * created transparently.
     */
    @GetMapping
    @PreAuthorize("hasAuthority('SCOPE_CART_READ')")
    public ResponseEntity<CartDto> getCurrentCart(
            @RequestParam(value = "accountId", required = false) String accountId) {

        String principalId = getPrincipalId();
        CartDto cart = cartService.getOrCreateCart(principalId, accountId);
        return ResponseEntity.ok(cart);
    }

    /**
     * Adds an item to the cart.  If the item already exists, quantities are
     * merged in the service layer.
     */
    @PostMapping("/items")
    @PreAuthorize("hasAuthority('SCOPE_CART_WRITE')")
    public ResponseEntity<CartItemDto> addItem(
            @Valid @RequestBody AddItemRequest request) {

        String principalId = getPrincipalId();
        CartItemDto addedItem;
        try {
            addedItem = cartService.addItem(
                    new AddCartItemCommand(
                            principalId,
                            request.accountId(),
                            request.sku(),
                            request.quantity()));
        } catch (InventoryUnavailableException ex) {
            return buildError(HttpStatus.CONFLICT, ex.getMessage());
        }

        URI location = URI.create("/api/v1/carts/items/" + addedItem.id());
        return ResponseEntity
                .created(location)
                .body(addedItem);
    }

    /**
     * Updates the quantity of an existing cart line.
     */
    @PatchMapping("/items/{itemId}")
    @PreAuthorize("hasAuthority('SCOPE_CART_WRITE')")
    public ResponseEntity<CartItemDto> updateItem(
            @PathVariable("itemId") String itemId,
            @Valid @RequestBody UpdateItemRequest request) {

        String principalId = getPrincipalId();

        try {
            CartItemDto updated = cartService.updateItem(
                    new UpdateCartItemCommand(
                            principalId,
                            request.accountId(),
                            itemId,
                            request.quantity()));
            return ResponseEntity.ok(updated);
        } catch (InventoryUnavailableException ex) {
            return buildError(HttpStatus.CONFLICT, ex.getMessage());
        } catch (CartNotFoundException ex) {
            return buildError(HttpStatus.NOT_FOUND, ex.getMessage());
        }
    }

    /**
     * Removes an item from the cart.
     */
    @DeleteMapping("/items/{itemId}")
    @PreAuthorize("hasAuthority('SCOPE_CART_WRITE')")
    public ResponseEntity<Void> deleteItem(
            @PathVariable("itemId") String itemId,
            @RequestParam(value = "accountId", required = false) String accountId) {
        String principalId = getPrincipalId();
        try {
            cartService.removeItem(principalId, accountId, itemId);
            return ResponseEntity.noContent().build();
        } catch (CartNotFoundException ex) {
            return buildError(HttpStatus.NOT_FOUND, ex.getMessage());
        }
    }

    /**
     * Clears the entire cart for the current user/account.
     */
    @DeleteMapping
    @PreAuthorize("hasAuthority('SCOPE_CART_WRITE')")
    public ResponseEntity<Void> clearCart(
            @RequestParam(value = "accountId", required = false) String accountId) {
        cartService.clearCart(getPrincipalId(), accountId);
        return ResponseEntity.noContent().build();
    }

    /**
     * Proceeds to checkout.  The heavy lifting (payment capture, inventory
     * locking, etc.) is delegated to service layer and subsequent orchestrators.
     */
    @PostMapping("/checkout")
    @PreAuthorize("hasAuthority('SCOPE_CHECKOUT')")
    public ResponseEntity<Void> checkout(
            @RequestParam(value = "accountId", required = false) String accountId) {
        try {
            String orderId = cartService.checkout(getPrincipalId(), accountId);
            // The Location header points callers to the newly created order
            URI location = URI.create("/api/v1/orders/" + orderId);
            return ResponseEntity.accepted()
                    .location(location)
                    .header(HttpHeaders.RETRY_AFTER, "0")   // client can poll immediately
                    .build();
        } catch (TransactionSystemException ex) {
            // generic failure, surface as 409 to let clients retry after fixing issues
            return buildError(HttpStatus.CONFLICT, "Checkout could not be completed: " + ex.getMostSpecificCause().getMessage());
        }
    }

    // -----------------------------------------------------------------------
    // Utility helpers
    // -----------------------------------------------------------------------

    private static ResponseEntity buildError(HttpStatus status, String message) {
        ErrorResponse body = new ErrorResponse(
                status.value(),
                message,
                OffsetDateTime.now());
        return ResponseEntity.status(status).body(body);
    }

    private static String getPrincipalId() {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null || auth.getName() == null) {
            LOG.error("No authenticated principal found in security context");
            throw new IllegalStateException("Unauthenticated access");
        }
        return auth.getName();
    }

    // -----------------------------------------------------------------------
    // DTO definitions (normally live in dedicated files)
    // -----------------------------------------------------------------------

    /**
     * Request payload to add an item to the cart.
     */
    public record AddItemRequest(
            @NotBlank String sku,
            @NotNull @Min(1) Integer quantity,
            String accountId) {
    }

    /**
     * Request payload to update item quantity.
     */
    public record UpdateItemRequest(
            String accountId,
            @NotNull @Min(1) Integer quantity) {
    }

    /**
     * Standardized error response structure for REST APIs.
     */
    public record ErrorResponse(
            int status,
            String message,
            OffsetDateTime timestamp) {
    }

    // -----------------------------------------------------------------------
    // Experimental multi-item bulk endpoint (future-proofing)
    // -----------------------------------------------------------------------

    /**
     * Adds or updates multiple items in one roundtrip (idempotent).
     */
    @PutMapping("/items/bulk")
    @PreAuthorize("hasAuthority('SCOPE_CART_WRITE')")
    public ResponseEntity<CartDto> addOrUpdateItemsBulk(
            @Valid @RequestBody List<@Valid BulkUpsertItemRequest> request) {

        String principalId = getPrincipalId();
        CartDto cart;
        try {
            cart = cartService.upsertItemsBulk(principalId, request.stream()
                    .map(r -> new AddCartItemCommand(principalId, r.accountId, r.sku, r.quantity))
                    .toList());
        } catch (InventoryUnavailableException ex) {
            return buildError(HttpStatus.CONFLICT, ex.getMessage());
        }
        return ResponseEntity.ok(cart);
    }

    public static class BulkUpsertItemRequest {
        @NotBlank public String sku;
        @NotNull @Min(1) public Integer quantity;
        public String accountId;
    }
}