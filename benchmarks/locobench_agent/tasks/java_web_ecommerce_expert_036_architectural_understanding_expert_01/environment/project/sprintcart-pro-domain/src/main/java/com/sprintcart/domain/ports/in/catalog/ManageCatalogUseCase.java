package com.sprintcart.domain.ports.in.catalog;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import com.sprintcart.domain.models.catalog.ProductId;
import com.sprintcart.domain.models.catalog.ProductSnapshot;

/**
 * Inbound Port that exposes all write-side use-cases for catalog management.
 * <p>
 * The implementation of this interface lives in the application/service layer.
 * It must remain free of any transport-specific concerns (REST, GraphQL, etc.)
 * and infrastructure details (JPA, MongoDB, etc.). Validation that is purely
 * business-oriented is encoded in the {@code *Command} value objects defined
 * below; cross-cutting concerns such as authentication and request tracing are
 * handled by external middleware.
 *
 * <p><strong>Thread-safety:</strong> implementations <em>must</em> be stateless
 * and therefore thread-safe. All state-mutating operations are delegated to
 * repositories that sit behind outbound ports.
 */
public interface ManageCatalogUseCase {

    /**
     * Creates a new product (draft or published) in the catalog.
     *
     * @param command validated data for the new product
     * @return an immutable representation of the persisted product
     * @throws InvalidProductException  if business invariants are violated
     * @throws CatalogWriteException    if the product cannot be persisted
     */
    ProductSnapshot createProduct(CreateProductCommand command)
            throws InvalidProductException, CatalogWriteException;

    /**
     * Updates an existing product. Fields omitted in the command will remain
     * unchanged (partial update).
     */
    ProductSnapshot updateProduct(UpdateProductCommand command)
            throws ProductNotFoundException, InvalidProductException, CatalogWriteException;

    /**
     * Soft-deletes (archives) a product so it is no longer sellable but remains
     * available for historical reporting.
     */
    void archiveProduct(ArchiveProductCommand command)
            throws ProductNotFoundException, CatalogWriteException;

    /**
     * Bulk updates the price (and optionally the cost) of multiple products
     * using a single, atomic operation.
     *
     * @return immutable snapshots of all affected products
     */
    List<ProductSnapshot> bulkUpdatePrices(BulkPriceUpdateCommand command)
            throws InvalidPriceException, CatalogWriteException;

    /**
     * Imports a large set of products—typically supplied via CSV/Excel—into the
     * catalog. The import runs asynchronously; the returned {@link ImportReport}
     * only reflects validation that could be performed synchronously.
     */
    ImportReport importProducts(ImportProductsCommand command)
            throws InvalidImportException;

    /* ---------------------------------------------------------------------- */
    /*                          COMMAND VALUE OBJECTS                         */
    /* ---------------------------------------------------------------------- */

    /**
     * Command for creating a fresh product entry.
     */
    record CreateProductCommand(
            String sku,
            String name,
            String description,
            BigDecimal price,
            String currency,
            int initialStock,
            boolean publishNow,
            Set<UUID> categoryIds,
            Map<String, String> attributes
    ) {
        public CreateProductCommand {
            validateSku(sku);
            validateName(name);
            validatePrice(price);
            validateCurrency(currency);
            validateStock(initialStock);
        }
    }

    /**
     * Command for updating an existing product. Fields that may remain unchanged
     * are nullable.
     */
    record UpdateProductCommand(
            ProductId productId,
            String name,
            String description,
            BigDecimal price,
            String currency,
            Integer stockAdjustment, // delta – may be negative
            Boolean publish,
            Set<UUID> categoryIds,
            Map<String, String> attributes
    ) {
        public UpdateProductCommand {
            if (productId == null) {
                throw new IllegalArgumentException("productId must not be null");
            }
            if (price != null) {
                validatePrice(price);
            }
            if (currency != null) {
                validateCurrency(currency);
            }
        }
    }

    /**
     * Command for archiving (soft-deleting) a product.
     */
    record ArchiveProductCommand(ProductId productId) {
        public ArchiveProductCommand {
            if (productId == null) {
                throw new IllegalArgumentException("productId must not be null");
            }
        }
    }

    /**
     * Command for updating the prices of multiple products at once.
     */
    record BulkPriceUpdateCommand(
            List<ProductPricePatch> patches,
            boolean skipIfHasActiveDiscount
    ) {
        public BulkPriceUpdateCommand {
            if (patches == null || patches.isEmpty()) {
                throw new IllegalArgumentException("patches must not be empty");
            }
            patches.forEach(ProductPricePatch::validate);
        }
    }

    /**
     * Single price mutation inside a bulk update.
     */
    record ProductPricePatch(ProductId productId, BigDecimal newPrice, BigDecimal newCost) {
        private static void validate(ProductPricePatch patch) {
            if (patch.productId == null) {
                throw new IllegalArgumentException("productId cannot be null");
            }
            validatePrice(patch.newPrice);
            if (patch.newCost != null && patch.newCost.compareTo(BigDecimal.ZERO) < 0) {
                throw new IllegalArgumentException("newCost cannot be negative");
            }
        }
    }

    /**
     * Command that encapsulates an import run.
     */
    record ImportProductsCommand(
            String originalFileName,
            byte[] payload,
            boolean dryRun
    ) {
        public ImportProductsCommand {
            if (originalFileName == null || originalFileName.isBlank()) {
                throw new IllegalArgumentException("originalFileName must not be blank");
            }
            if (payload == null || payload.length == 0) {
                throw new IllegalArgumentException("payload must not be empty");
            }
            if (!originalFileName.endsWith(".csv") && !originalFileName.endsWith(".xlsx")) {
                throw new IllegalArgumentException("file type must be .csv or .xlsx");
            }
        }
    }

    /* ---------------------------------------------------------------------- */
    /*                            USE-CASE RESULTS                            */
    /* ---------------------------------------------------------------------- */

    /**
     * Outcome of validating an import request. A successful synchronous
     * validation does not guarantee that the async job will succeed.
     */
    record ImportReport(
            int rowsAccepted,
            int rowsRejected,
            List<RowError> errors,
            OffsetDateTime queuedAt
    ) {
        public boolean hasErrors() {
            return rowsRejected > 0;
        }
    }

    /**
     * Error discovered while validating or parsing a row within an import file.
     */
    record RowError(
            long rowNumber,
            String message
    ) {
    }

    /* ---------------------------------------------------------------------- */
    /*                               EXCEPTIONS                               */
    /* ---------------------------------------------------------------------- */

    class InvalidProductException extends Exception {
        public InvalidProductException(String message) {
            super(message);
        }
    }

    class ProductNotFoundException extends Exception {
        public ProductNotFoundException(String message) {
            super(message);
        }
    }

    class InvalidPriceException extends Exception {
        public InvalidPriceException(String message) {
            super(message);
        }
    }

    class CatalogWriteException extends Exception {
        public CatalogWriteException(String message, Throwable cause) {
            super(message, cause);
        }
    }

    class InvalidImportException extends Exception {
        public InvalidImportException(String message) {
            super(message);
        }
    }

    /* ---------------------------------------------------------------------- */
    /*                               VALIDATION                               */
    /* ---------------------------------------------------------------------- */

    private static void validateSku(String sku) {
        if (sku == null || sku.isBlank()) {
            throw new IllegalArgumentException("SKU must not be blank");
        }
        if (sku.length() > 64) {
            throw new IllegalArgumentException("SKU exceeds maximum length (64)");
        }
    }

    private static void validateName(String name) {
        if (name == null || name.isBlank()) {
            throw new IllegalArgumentException("name must not be blank");
        }
        if (name.length() > 255) {
            throw new IllegalArgumentException("name exceeds maximum length (255)");
        }
    }

    private static void validatePrice(BigDecimal price) {
        if (price == null) {
            throw new IllegalArgumentException("price must not be null");
        }
        if (price.scale() > 2) {
            throw new IllegalArgumentException("price scale must not exceed 2");
        }
        if (price.compareTo(BigDecimal.ZERO) < 0) {
            throw new IllegalArgumentException("price cannot be negative");
        }
    }

    private static void validateCurrency(String currency) {
        if (currency == null || currency.isBlank()) {
            throw new IllegalArgumentException("currency must not be blank");
        }
        if (currency.length() != 3) {
            throw new IllegalArgumentException("currency must be ISO-4217 code (3 letters)");
        }
    }

    private static void validateStock(int stock) {
        if (stock < 0) {
            throw new IllegalArgumentException("initialStock cannot be negative");
        }
    }
}