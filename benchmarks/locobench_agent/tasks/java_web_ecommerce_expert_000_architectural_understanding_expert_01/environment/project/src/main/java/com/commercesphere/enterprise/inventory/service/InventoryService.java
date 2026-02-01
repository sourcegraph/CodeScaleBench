package com.commercesphere.enterprise.inventory.service;

import com.commercesphere.enterprise.inventory.domain.InventoryItem;
import com.commercesphere.enterprise.inventory.domain.Reservation;
import com.commercesphere.enterprise.inventory.events.InventoryAdjustedEvent;
import com.commercesphere.enterprise.inventory.events.InventoryReservedEvent;
import com.commercesphere.enterprise.inventory.events.InventoryReservationReleasedEvent;
import com.commercesphere.enterprise.inventory.exception.InsufficientStockException;
import com.commercesphere.enterprise.inventory.exception.InventoryException;
import com.commercesphere.enterprise.inventory.repository.InventoryRepository;
import com.commercesphere.enterprise.inventory.repository.ReservationRepository;
import com.commercesphere.enterprise.shared.events.DomainEventPublisher;
import com.commercesphere.enterprise.shared.logging.AuditTrail;
import org.apache.commons.lang3.StringUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.PessimisticLockingFailureException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.persistence.LockModeType;
import java.time.OffsetDateTime;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * InventoryService encapsulates all stock–related operations such as real-time availability,
 * reservation processing (a.k.a. soft-allocations) and hard adjustments triggered by
 * warehouse reconciliation or return merchandise authorizations (RMA).
 *
 * <p>All mutating methods are wrapped in a single database transaction and leverage pessimistic
 * locking to avoid overselling in high-concurrency ordering scenarios.</p>
 *
 * <p>Domain events are emitted after the end of the transaction boundary to keep the write
 * model decoupled from read-side projections or asynchronous integrations.</p>
 */
@Service
public class InventoryService {

    private static final Logger log = LoggerFactory.getLogger(InventoryService.class);

    private final InventoryRepository inventoryRepository;
    private final ReservationRepository reservationRepository;
    private final DomainEventPublisher eventPublisher;
    private final AuditTrail auditTrail;

    public InventoryService(final InventoryRepository inventoryRepository,
                            final ReservationRepository reservationRepository,
                            final DomainEventPublisher eventPublisher,
                            final AuditTrail auditTrail) {
        this.inventoryRepository = inventoryRepository;
        this.reservationRepository = reservationRepository;
        this.eventPublisher = eventPublisher;
        this.auditTrail = auditTrail;
    }

    /**
     * Retrieves the number of sellable units currently on hand for a given SKU and warehouse.
     *
     * @param sku           unique Stock Keeping Unit
     * @param warehouseCode identifier of the warehouse
     * @return sellable quantity (excludes allocated / reserved units)
     */
    @Transactional(readOnly = true)
    public int getAvailableQuantity(final String sku, final String warehouseCode) {
        validateSkuAndWarehouse(sku, warehouseCode);
        return inventoryRepository.findAvailableQuantity(sku, warehouseCode)
                                  .orElse(0);
    }

    /**
     * Reserves a specific quantity of inventory for an outbound business process (e.g. sales order).
     *
     * @param externalRef   identifier of the business process (orderId, quoteId, etc.)
     * @param sku           Stock Keeping Unit to reserve
     * @param quantity      units to reserve
     * @param warehouseCode warehouse where inventory should be reserved
     * @return Reservation persistent entity
     * @throws InsufficientStockException if not enough inventory is available
     */
    @Transactional
    public Reservation reserve(final String externalRef,
                               final String sku,
                               final int quantity,
                               final String warehouseCode) {

        validateSkuAndWarehouse(sku, warehouseCode);
        validateQuantity(quantity);

        try {
            // Acquire row-level lock to serialize reservations on the same item/warehouse
            InventoryItem item = inventoryRepository.findBySkuAndWarehouseForUpdate(
                    sku, warehouseCode, LockModeType.PESSIMISTIC_WRITE)
                    .orElseThrow(() -> new InventoryException(
                            String.format("Inventory record not found for SKU %s at warehouse %s", sku, warehouseCode)));

            if (item.getAvailableQuantity() < quantity) {
                throw new InsufficientStockException(
                        String.format("Not enough stock for sku=%s (requested=%d, available=%d)",
                                sku, quantity, item.getAvailableQuantity()));
            }

            item.reserve(quantity);
            inventoryRepository.save(item);

            Reservation reservation = new Reservation();
            reservation.setId(generateReservationId());
            reservation.setExternalRef(externalRef);
            reservation.setSku(sku);
            reservation.setWarehouseCode(warehouseCode);
            reservation.setQuantity(quantity);
            reservation.setCreatedAt(OffsetDateTime.now());
            reservationRepository.save(reservation);

            auditTrail.record("INVENTORY_RESERVED",
                    "Reserved %d units of %s for %s".formatted(quantity, sku, externalRef));

            // Publish domain event (post-commit by default)
            eventPublisher.publish(new InventoryReservedEvent(reservation));

            return reservation;
        } catch (PessimisticLockingFailureException ex) {
            // Convert low-level database lock exception to a domain-specific one
            throw new InventoryException("Unable to acquire lock for inventory reservation " +
                    "(high contention detected). Please retry.", ex);
        }
    }

    /**
     * Releases a previously created reservation. Quantity will be returned to available stock.
     *
     * @param reservationId reservation identifier
     * @param reason        reason of release (e.g. order cancelled, payment failure)
     */
    @Transactional
    public void releaseReservation(final String reservationId, final String reason) {
        Objects.requireNonNull(reservationId, "reservationId must not be null");
        Objects.requireNonNull(reason, "reason must not be null");

        Reservation reservation = reservationRepository.findByIdForUpdate(reservationId, LockModeType.PESSIMISTIC_WRITE)
                .orElseThrow(() -> new InventoryException("Reservation not found: " + reservationId));

        InventoryItem item = inventoryRepository.findBySkuAndWarehouseForUpdate(
                reservation.getSku(), reservation.getWarehouseCode(), LockModeType.PESSIMISTIC_WRITE)
                .orElseThrow(() -> new InventoryException(
                        String.format("Inventory record not found for SKU %s at warehouse %s",
                                reservation.getSku(), reservation.getWarehouseCode())));

        item.release(reservation.getQuantity());
        inventoryRepository.save(item);

        reservation.markReleased(reason);
        reservationRepository.save(reservation);

        auditTrail.record("INVENTORY_RELEASED",
                "Released reservation %s (%d units of %s) because %s"
                        .formatted(reservationId, reservation.getQuantity(), reservation.getSku(), reason));

        eventPublisher.publish(new InventoryReservationReleasedEvent(reservation));
    }

    /**
     * Adjusts on-hand inventory quantity (positive or negative) due to external operations such as
     * stock reconciliation, manual corrections, or returns.
     *
     * @param sku           Stock Keeping Unit
     * @param warehouseCode warehouse identifier
     * @param delta         positive to add, negative to subtract
     * @param reason        mandatory adjustment reason
     */
    @Transactional
    public void adjustStock(final String sku, final String warehouseCode, final int delta, final String reason) {
        validateSkuAndWarehouse(sku, warehouseCode);
        Objects.requireNonNull(reason, "reason must not be null");
        if (delta == 0) {
            log.debug("Ignoring no-op adjustment for sku={} at warehouse={}", sku, warehouseCode);
            return;
        }

        InventoryItem item = inventoryRepository
                .findBySkuAndWarehouseForUpdate(sku, warehouseCode, LockModeType.PESSIMISTIC_WRITE)
                .orElseThrow(() -> new InventoryException(
                        String.format("Inventory record not found for SKU %s at warehouse %s", sku, warehouseCode)));

        item.adjust(delta);
        inventoryRepository.save(item);

        auditTrail.record("INVENTORY_ADJUSTED",
                "Adjusted %s by %d units: %s".formatted(sku, delta, reason));

        eventPublisher.publish(new InventoryAdjustedEvent(item, delta, reason));
    }

    /* --------------------------------------------------------------------- */
    /* Helper methods                                                        */
    /* --------------------------------------------------------------------- */

    private static void validateSkuAndWarehouse(final String sku, final String warehouseCode) {
        if (StringUtils.isBlank(sku)) {
            throw new IllegalArgumentException("sku must not be blank");
        }
        if (StringUtils.isBlank(warehouseCode)) {
            throw new IllegalArgumentException("warehouseCode must not be blank");
        }
    }

    private static void validateQuantity(final int qty) {
        if (qty <= 0) {
            throw new IllegalArgumentException("quantity must be > 0");
        }
    }

    private static String generateReservationId() {
        return "RSV-" + UUID.randomUUID();
    }
}