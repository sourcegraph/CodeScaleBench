package com.commercesphere.enterprise.catalog.controller;

import com.commercesphere.enterprise.catalog.dto.CategoryDTO;
import com.commercesphere.enterprise.catalog.dto.CategoryRequest;
import com.commercesphere.enterprise.catalog.dto.PagedResponse;
import com.commercesphere.enterprise.catalog.service.CategoryService;
import com.commercesphere.enterprise.common.exception.ResourceNotFoundException;
import com.commercesphere.enterprise.common.security.AuthenticatedUser;
import com.commercesphere.enterprise.common.security.LoggedInUser;
import com.commercesphere.enterprise.common.validation.Marker.OnCreate;
import com.commercesphere.enterprise.common.validation.Marker.OnUpdate;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import javax.validation.constraints.Min;
import javax.validation.constraints.PositiveOrZero;
import java.util.List;

/**
 * REST controller responsible for exposing CRUD and utility operations
 * for the product-category domain object.
 *
 * <p>
 * Category data are critical for virtually every downstream flow—
 * including pricing, tax calculation, entitlement and search facets—so
 * we keep the controller intentionally thin and delegate all business
 * invariants to {@link CategoryService}.  Every modifying endpoint is
 * protected by the {@code CATALOG_WRITE} authority, while read-only
 * operations require {@code CATALOG_READ}.
 * </p>
 *
 * <p>
 * Audit information (who created/updated a category) is wired via a
 * custom {@link LoggedInUser} resolver that pulls the currently
 * authenticated {@link AuthenticatedUser} from the Spring Security
 * context without leaking security-framework specifics into the
 * service layer.
 * </p>
 *
 * @author CommerceSphere
 */
@RestController
@RequestMapping("/api/v1/catalog/categories")
@Slf4j
@RequiredArgsConstructor
@Validated
public class CategoryController {

    private final CategoryService categoryService;

    /**
     * Returns a paginated list of categories, optionally filtered by
     * a free-text query string.  The endpoint supports client-controlled
     * sorting and default page/size fallbacks that are aligned with the
     * global storefront settings.
     */
    @GetMapping
    @PreAuthorize("hasAuthority('CATALOG_READ')")
    public ResponseEntity<PagedResponse<CategoryDTO>> searchCategories(
            @RequestParam(value = "q", required = false) String query,
            @RequestParam(value = "page", defaultValue = "0") @PositiveOrZero int page,
            @RequestParam(value = "size", defaultValue = "20") @PositiveOrZero int size,
            @RequestParam(value = "sort", defaultValue = "name") String sortBy,
            @RequestParam(value = "dir", defaultValue = "asc") String direction) {

        log.debug("Searching categories q='{}', page={}, size={}, sort={} {}", query, page, size, sortBy, direction);
        PagedResponse<CategoryDTO> response = categoryService.search(query, page, size, sortBy, direction);
        return ResponseEntity.ok(response);
    }

    /**
     * Retrieves a single category by its technical identifier.
     */
    @GetMapping("/{id}")
    @PreAuthorize("hasAuthority('CATALOG_READ')")
    public ResponseEntity<CategoryDTO> getCategory(
            @PathVariable("id") @Min(1) long id) {

        CategoryDTO dto = categoryService.findById(id)
                                         .orElseThrow(() -> new ResourceNotFoundException("Category", id));
        return ResponseEntity.ok(dto);
    }

    /**
     * Persists a new category in the catalog.
     */
    @PostMapping
    @PreAuthorize("hasAuthority('CATALOG_WRITE')")
    public ResponseEntity<CategoryDTO> createCategory(
            @Validated(OnCreate.class) @RequestBody CategoryRequest request,
            @LoggedInUser AuthenticatedUser user) {

        log.info("User '{}' is creating category '{}'", user.getUsername(), request.getName());
        CategoryDTO dto = categoryService.create(request, user.getId());
        return ResponseEntity.status(HttpStatus.CREATED).body(dto);
    }

    /**
     * Updates an existing category in place, identified by its ID.
     */
    @PutMapping("/{id}")
    @PreAuthorize("hasAuthority('CATALOG_WRITE')")
    public ResponseEntity<CategoryDTO> updateCategory(
            @PathVariable("id") @Min(1) long id,
            @Validated(OnUpdate.class) @RequestBody CategoryRequest request,
            @LoggedInUser AuthenticatedUser user) {

        log.info("User '{}' is updating category {} with payload {}", user.getUsername(), id, request);
        CategoryDTO dto = categoryService.update(id, request, user.getId());
        return ResponseEntity.ok(dto);
    }

    /**
     * Soft-deletes a category. Products linked to the category are not
     * removed; visibility is instead controlled by status flags so that
     * historical orders keep their referential integrity intact.
     */
    @DeleteMapping("/{id}")
    @PreAuthorize("hasAuthority('CATALOG_WRITE')")
    public ResponseEntity<Void> deleteCategory(
            @PathVariable("id") @Min(1) long id,
            @LoggedInUser AuthenticatedUser user) {

        log.info("User '{}' is deleting category {}", user.getUsername(), id);
        categoryService.softDelete(id, user.getId());
        return ResponseEntity.noContent().build();
    }

    /**
     * Moves a category under a different parent (or detaches it by passing
     * {@code parentId = null}).  This is a lightweight wrapper around the
     * tree-manipulation logic, which is enforced entirely in
     * {@link CategoryService}.
     */
    @PatchMapping("/{id}/parent")
    @PreAuthorize("hasAuthority('CATALOG_WRITE')")
    public ResponseEntity<CategoryDTO> changeParent(
            @PathVariable("id") @Min(1) long id,
            @RequestParam(value = "parentId", required = false) Long parentId,
            @LoggedInUser AuthenticatedUser user) {

        log.info("User '{}' is moving category {} under parent {}", user.getUsername(), id, parentId);
        CategoryDTO dto = categoryService.changeParent(id, parentId, user.getId());
        return ResponseEntity.ok(dto);
    }

    /**
     * Reorders all direct children of the given parent category according
     * to the supplied list of category IDs. The operation fails fast if
     * the provided list is incomplete or contains foreign keys.
     */
    @PatchMapping("/reorder")
    @PreAuthorize("hasAuthority('CATALOG_WRITE')")
    public ResponseEntity<Void> reorderCategories(
            @RequestParam("parentId") @Min(0) long parentId,
            @RequestBody List<Long> orderedIds,
            @LoggedInUser AuthenticatedUser user) {

        log.info("User '{}' requests reorder of children under parent {} -> {}", user.getUsername(), parentId, orderedIds);
        categoryService.reorder(parentId, orderedIds, user.getId());
        return ResponseEntity.noContent().build();
    }

    /**
     * Returns a nested category tree. The {@code depth} parameter limits
     * the number of hierarchy levels returned and defaults to {@code 3}
     * to avoid excessive payload sizes on mobile networks.
     */
    @GetMapping("/tree")
    @PreAuthorize("hasAuthority('CATALOG_READ')")
    public ResponseEntity<List<CategoryDTO>> getCategoryTree(
            @RequestParam(value = "depth", defaultValue = "3") @Min(1) int depth) {

        List<CategoryDTO> tree = categoryService.getTree(depth);
        return ResponseEntity.ok(tree);
    }
}