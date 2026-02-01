package com.sprintcart.adapters.web.rest;

import com.sprintcart.domain.catalog.model.Product;
import com.sprintcart.domain.catalog.port.in.CatalogMaintenancePort;
import com.sprintcart.shared.exceptions.DomainException;
import com.sprintcart.shared.validation.ValidationError;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVParser;
import org.apache.commons.csv.CSVRecord;
import org.springframework.core.io.InputStreamResource;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.util.StringUtils;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.time.Instant;
import java.util.List;
import java.util.stream.Collectors;

/**
 * REST controller that exposes product-related endpoints.
 *
 * <p>Acts as a thin layer that validates/serializes HTTP payloads and delegates business logic
 * to the {@link CatalogMaintenancePort}, which is part of the application (use-case) layer in
 * SprintCart's Hexagonal Architecture.</p>
 */
@RestController
@RequestMapping("/api/v1/products")
@Validated
public class ProductController {

    private final CatalogMaintenancePort catalogMaintenancePort;
    private final ProductWebMapper mapper;

    public ProductController(CatalogMaintenancePort catalogMaintenancePort,
                             ProductWebMapper mapper) {
        this.catalogMaintenancePort = catalogMaintenancePort;
        this.mapper = mapper;
    }

    /* ------------------------------------------------------------------
     * Query endpoints
     * ------------------------------------------------------------------ */

    @GetMapping
    public ResponseEntity<Page<ProductResponse>> list(
            @RequestParam(name = "q", required = false) String query,
            @RequestParam(defaultValue = "0") @Min(0) int page,
            @RequestParam(defaultValue = "20") @Min(1) int size,
            @RequestParam(defaultValue = "createdAt") String sortBy,
            @RequestParam(defaultValue = "DESC") Sort.Direction direction) {

        PageRequest pageRequest = PageRequest.of(page, size, Sort.by(direction, sortBy));
        Page<Product> products = catalogMaintenancePort.search(query, pageRequest);

        return ResponseEntity.ok(products.map(mapper::toResponse));
    }

    @GetMapping("/{sku}")
    public ResponseEntity<ProductResponse> getBySku(@PathVariable("sku") @NotBlank String sku) {
        Product product = catalogMaintenancePort.findBySku(sku);
        return ResponseEntity.ok(mapper.toResponse(product));
    }

    /* ------------------------------------------------------------------
     * Command endpoints
     * ------------------------------------------------------------------ */

    @PostMapping
    public ResponseEntity<ProductResponse> create(@Valid @RequestBody ProductRequest request) {
        Product created = catalogMaintenancePort.create(mapper.toDomain(request));
        return ResponseEntity
                .status(HttpStatus.CREATED)
                .body(mapper.toResponse(created));
    }

    @PutMapping("/{sku}")
    public ResponseEntity<ProductResponse> update(@PathVariable("sku") @NotBlank String sku,
                                                  @Valid @RequestBody ProductRequest request) {
        Product updated = catalogMaintenancePort.update(sku, mapper.toDomain(request));
        return ResponseEntity.ok(mapper.toResponse(updated));
    }

    @DeleteMapping("/{sku}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable("sku") @NotBlank String sku) {
        catalogMaintenancePort.delete(sku);
    }

    /* ------------------------------------------------------------------
     * Bulk import endpoint
     * ------------------------------------------------------------------ */

    /**
     * Imports products via a CSV file.
     *
     * Expected columns (header row mandatory):
     *  sku,name,description,price,currency,quantity
     */
    @PostMapping(path = "/bulk-upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<BulkUploadResponse> bulkUpload(@RequestPart("file") MultipartFile file) throws IOException {
        if (file.isEmpty()) {
            throw new IllegalArgumentException("Uploaded file is empty.");
        }
        if (!StringUtils.getFilenameExtension(file.getOriginalFilename()).equalsIgnoreCase("csv")) {
            throw new IllegalArgumentException("Only CSV uploads are supported.");
        }

        int success = 0;
        int failed = 0;

        try (BufferedReader reader = new BufferedReader(new InputStreamReader(file.getInputStream()))) {
            CSVParser parser = CSVFormat.DEFAULT
                    .withFirstRecordAsHeader()
                    .parse(reader);

            for (CSVRecord record : parser) {
                try {
                    ProductRequest pr = ProductRequest.fromCsv(record);
                    catalogMaintenancePort.create(mapper.toDomain(pr));
                    success++;
                } catch (Exception ex) {
                    // We swallow individual record failures but count them,
                    // while still logging for post-mortem analysis.
                    failed++;
                    // TODO: replace with structured logging framework
                    System.err.printf("Failed to import SKU %s – %s%n",
                            record.get("sku"), ex.getMessage());
                }
            }
        }

        BulkUploadResponse response = new BulkUploadResponse(success, failed, Instant.now());
        return ResponseEntity.ok(response);
    }

    /* ------------------------------------------------------------------
     * CSV template endpoint
     * ------------------------------------------------------------------ */

    @GetMapping("/template")
    public ResponseEntity<InputStreamResource> downloadCsvTemplate() {
        String header = "sku,name,description,price,currency,quantity\n";
        InputStreamResource resource =
                new InputStreamResource(header.getBytes().length > 0
                        ? new java.io.ByteArrayInputStream(header.getBytes())
                        : InputStream.nullInputStream());

        HttpHeaders headers = new HttpHeaders();
        headers.set(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"product-template.csv\"");
        headers.setContentType(MediaType.TEXT_PLAIN);

        return new ResponseEntity<>(resource, headers, HttpStatus.OK);
    }

    /* ------------------------------------------------------------------
     * Error handling
     * ------------------------------------------------------------------ */

    @ExceptionHandler({DomainException.class})
    public ResponseEntity<ApiError> handleDomainException(DomainException ex) {
        ApiError error = new ApiError("DOMAIN_ERROR", ex.getMessage());
        return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY).body(error);
    }

    @ExceptionHandler({MethodArgumentNotValidException.class})
    public ResponseEntity<ApiError> handleValidation(MethodArgumentNotValidException ex) {
        List<String> details = ex.getBindingResult()
                                 .getFieldErrors()
                                 .stream()
                                 .map(err -> err.getField() + " " + err.getDefaultMessage())
                                 .collect(Collectors.toList());
        ApiError error = new ApiError("VALIDATION_ERROR", String.join("; ", details));
        return ResponseEntity.badRequest().body(error);
    }

    @ExceptionHandler({IllegalArgumentException.class})
    public ResponseEntity<ApiError> handleIllegalArg(IllegalArgumentException ex) {
        ApiError error = new ApiError("BAD_REQUEST", ex.getMessage());
        return ResponseEntity.badRequest().body(error);
    }

    /* ------------------------------------------------------------------
     * DTOs & helper classes
     * ------------------------------------------------------------------ */

    /**
     * Maps between web DTOs and domain entities.
     * Implemented using MapStruct or manually as shown below.
     * Declared as a component so that Spring can inject it.
     */
    @org.springframework.stereotype.Component
    public static class ProductWebMapper {

        public ProductResponse toResponse(Product product) {
            return new ProductResponse(
                    product.getSku(),
                    product.getName(),
                    product.getDescription(),
                    product.getPrice().getAmount(),
                    product.getPrice().getCurrency(),
                    product.getAvailableQuantity(),
                    product.getCreatedAt(),
                    product.getUpdatedAt()
            );
        }

        public Product toDomain(ProductRequest request) {
            return Product.builder()
                    .sku(request.sku())
                    .name(request.name())
                    .description(request.description())
                    .price(request.price(), request.currency())
                    .availableQuantity(request.quantity())
                    .build();
        }
    }

    public record ProductRequest(
            @NotBlank String sku,
            @NotBlank String name,
            String description,
            @NotNull @Min(0) Double price,
            @NotBlank String currency,
            @NotNull @Min(0) Integer quantity
    ) {
        static ProductRequest fromCsv(CSVRecord record) {
            return new ProductRequest(
                    record.get("sku"),
                    record.get("name"),
                    record.get("description"),
                    Double.valueOf(record.get("price")),
                    record.get("currency"),
                    Integer.valueOf(record.get("quantity"))
            );
        }
    }

    public record ProductResponse(
            String sku,
            String name,
            String description,
            Double price,
            String currency,
            Integer quantity,
            Instant createdAt,
            Instant updatedAt
    ) { }

    public record BulkUploadResponse(
            int imported,
            int failed,
            Instant timestamp
    ) { }

    public record ApiError(
            String code,
            String message
    ) { }
}