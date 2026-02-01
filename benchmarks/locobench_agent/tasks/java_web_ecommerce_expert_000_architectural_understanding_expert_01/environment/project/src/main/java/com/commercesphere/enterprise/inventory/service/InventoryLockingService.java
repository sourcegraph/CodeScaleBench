package com.commercesphere.enterprise.inventory.service;

import com.commercesphere.enterprise.inventory.domain.InventoryItem;
import com.commercesphere.enterprise.inventory.repository.InventoryRepository;
import com.commercesphere.enterprise.order.dto.OrderLine;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.DisposableBean;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.dao.PessimisticLockingFailureException;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.persistence.LockModeType;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * InventoryLockingService is responsible for reserving (“locking”) sellable inventory
 * during the order-processing workflow to guarantee that concurrent check-out
 * threads cannot oversell SKUs.  The reservation is strictly time-bound; if the caller
 * does not confirm the order within {@code inventory.lock.ttl} the lock will
 * automatically expire and the inventory is released back into the pool.
 *
 * <p>Usage pattern:</p>
 *
 * <pre>{@code
 * InventoryLockToken token = lockingService.acquireLock(orderLines);
 * // … perform payment, tax calculations, etc.
 * lockingService.commitReservation(token.getLockId());  // hard-allocate items
 * }</pre>
 *
 * The implementation combines an in-process lock registry (to short-circuit JVM
 * contention) with pessimistic row-level locks in the RDBMS, ensuring safety in
 * clustered deployments that share the same database.
 */
@Service
public class InventoryLockingService implements InitializingBean, DisposableBean {

    private static final Logger LOG = LoggerFactory.getLogger(InventoryLockingService.class);

    /**
     * Default time-to-live for reservations that were not explicitly provided by the caller.
     */
    @Value("${inventory.lock.ttl:PT5M}")
    private Duration defaultTtl;

    private final InventoryRepository inventoryRepository;
    private final ApplicationEventPublisher eventPublisher;
    private final Clock clock;

    /**
     * Keeps track of active lock contexts inside this JVM.  The true source of
     * truth is still the database but this cache prevents excessive trips inside
     * high-throughput check-out peaks.
     */
    private final Map<UUID, LockContext> activeLocks = new ConcurrentHashMap<>();

    /**
     * Schedules automatic expiration of the locks.
     */
    private TaskScheduler scheduler;

    public InventoryLockingService(InventoryRepository inventoryRepository,
                                   ApplicationEventPublisher eventPublisher,
                                   Clock clock) {
        this.inventoryRepository = inventoryRepository;
        this.eventPublisher = eventPublisher;
        this.clock = clock;
    }

    // ------------------------------------------------------------------------
    // PUBLIC API
    // ------------------------------------------------------------------------

    /**
     * Acquire a lock (i.e. reserve inventory) for the supplied order lines.
     *
     * @param orderLines SKUs with quantities to reserve
     * @return token representing the lock
     * @throws InventoryLockException if not enough sellable quantity exists
     */
    @Transactional
    public InventoryLockToken acquireLock(Collection<OrderLine> orderLines) throws InventoryLockException {
        return acquireLock(orderLines, defaultTtl);
    }

    /**
     * Acquire a lock with an explicit TTL.
     */
    @Transactional
    public InventoryLockToken acquireLock(Collection<OrderLine> orderLines, Duration ttl) throws InventoryLockException {
        Objects.requireNonNull(orderLines, "orderLines must not be null");
        validateRequest(orderLines);

        UUID lockId = UUID.randomUUID();
        Map<String, Integer> reserved = new HashMap<>();

        Instant start = Instant.now(clock);

        try {
            // pessimistic lock each SKU to prevent oversells
            for (OrderLine line : orderLines) {
                InventoryItem item = inventoryRepository.findBySku(line.getSku(), LockModeType.PESSIMISTIC_WRITE)
                        .orElseThrow(() -> new InventoryLockException("Unknown SKU " + line.getSku()));

                int sellable = item.getSellableQuantity();
                if (sellable < line.getQuantity()) {
                    throw new InventoryLockException("Insufficient inventory for SKU " + line.getSku());
                }

                item.setReservedQuantity(item.getReservedQuantity() + line.getQuantity());
                inventoryRepository.save(item);
                reserved.put(line.getSku(), line.getQuantity());
            }
        } catch (PessimisticLockingFailureException e) {
            throw new InventoryLockException("Failed to obtain database lock", e);
        }

        Instant expiresAt = start.plus(ttl);
        LockContext ctx = new LockContext(lockId, reserved, expiresAt);
        activeLocks.put(lockId, ctx);
        scheduleExpiration(ctx);

        LOG.debug("Lock {} created for {} lines, expires at {}", lockId, reserved.size(), expiresAt);

        eventPublisher.publishEvent(new InventoryLockedEvent(this, lockId, reserved, expiresAt));
        return new InventoryLockToken(lockId, expiresAt);
    }

    /**
     * Releases a previously acquired lock.  All reserved quantities are rolled back.
     */
    @Transactional
    public void releaseLock(UUID lockId) {
        LockContext ctx = activeLocks.remove(lockId);
        if (ctx == null) {
            LOG.debug("Release called for non-existing lock {}", lockId);
            return;
        }

        for (Map.Entry<String, Integer> entry : ctx.reserved.entrySet()) {
            InventoryItem item = inventoryRepository.findBySku(entry.getKey(), LockModeType.PESSIMISTIC_WRITE)
                    .orElse(null);
            if (item == null) {
                LOG.warn("SKU {} vanished while releasing lock {}", entry.getKey(), lockId);
                continue;
            }
            item.setReservedQuantity(item.getReservedQuantity() - entry.getValue());
            inventoryRepository.save(item);
        }

        LOG.debug("Lock {} released", lockId);
        eventPublisher.publishEvent(new InventoryUnlockedEvent(this, lockId));
    }

    /**
     * Permanently deducts (commits) the reservation from sellable inventory.
     * Typically invoked once the order is paid.
     */
    @Transactional
    public void commitReservation(UUID lockId) throws InventoryLockException {
        LockContext ctx = activeLocks.remove(lockId);
        if (ctx == null) {
            throw new InventoryLockException("Lock " + lockId + " does not exist or already committed");
        }

        for (Map.Entry<String, Integer> entry : ctx.reserved.entrySet()) {
            InventoryItem item = inventoryRepository.findBySku(entry.getKey(), LockModeType.PESSIMISTIC_WRITE)
                    .orElseThrow(() -> new InventoryLockException("SKU " + entry.getKey() + " disappeared"));

            item.setReservedQuantity(item.getReservedQuantity() - entry.getValue());
            item.setOnHandQuantity(item.getOnHandQuantity() - entry.getValue());
            inventoryRepository.save(item);
        }

        LOG.debug("Lock {} committed", lockId);
        eventPublisher.publishEvent(new InventoryCommittedEvent(this, lockId));
    }

    /**
     * Extends the lifetime of the lock, e.g. when extra time is needed for the user
     * to complete the payment gateway redirect.
     */
    public InventoryLockToken extendLock(UUID lockId, Duration extension) throws InventoryLockException {
        LockContext ctx = activeLocks.get(lockId);
        if (ctx == null) {
            throw new InventoryLockException("Cannot extend non-existing lock " + lockId);
        }

        Instant newExpiry = ctx.expiresAt.plus(extension);
        ctx.expiresAt = newExpiry;
        scheduleExpiration(ctx); // re-schedule

        LOG.debug("Lock {} extended by {}, new expiry {}", lockId, extension, newExpiry);
        return new InventoryLockToken(lockId, newExpiry);
    }

    // ------------------------------------------------------------------------
    // INTERNAL HELPERS
    // ------------------------------------------------------------------------

    private void validateRequest(Collection<OrderLine> orderLines) {
        if (orderLines.isEmpty()) {
            throw new IllegalArgumentException("orderLines must not be empty");
        }
        for (OrderLine line : orderLines) {
            if (line.getQuantity() <= 0) {
                throw new IllegalArgumentException("Quantity must be > 0 for SKU " + line.getSku());
            }
        }
    }

    private void scheduleExpiration(LockContext ctx) {
        scheduler.schedule(() -> safeExpire(ctx.lockId), Date.from(ctx.expiresAt));
    }

    private void safeExpire(UUID lockId) {
        try {
            releaseLock(lockId);
        } catch (Exception e) {
            LOG.error("Error while auto-expiring lock {}", lockId, e);
        }
    }

    // ------------------------------------------------------------------------
    // LIFECYCLE
    // ------------------------------------------------------------------------

    @Override
    public void afterPropertiesSet() {
        ThreadPoolTaskScheduler tpts = new ThreadPoolTaskScheduler();
        tpts.setPoolSize(2);
        tpts.setThreadNamePrefix("inventory-lock-expirer-");
        tpts.initialize();
        this.scheduler = tpts;
    }

    @Override
    public void destroy() {
        if (scheduler != null) {
            ((ThreadPoolTaskScheduler) scheduler).shutdown();
        }
    }

    // ------------------------------------------------------------------------
    // INNER CLASSES & EVENTS
    // ------------------------------------------------------------------------

    /**
     * Captures the reservation context for a single lock.
     */
    private static final class LockContext {
        final UUID lockId;
        final Map<String, Integer> reserved; // SKU -> qty
        volatile Instant expiresAt;

        LockContext(UUID lockId, Map<String, Integer> reserved, Instant expiresAt) {
            this.lockId = lockId;
            this.reserved = reserved;
            this.expiresAt = expiresAt;
        }
    }

    /**
     * DTO returned to callers when a lock is created or extended.
     */
    public record InventoryLockToken(UUID lockId, Instant expiresAt) {
    }

    public static class InventoryLockedEvent {
        private final Object source;
        private final UUID lockId;
        private final Map<String, Integer> reserved;
        private final Instant expiresAt;

        public InventoryLockedEvent(Object source, UUID lockId, Map<String, Integer> reserved, Instant expiresAt) {
            this.source = source;
            this.lockId = lockId;
            this.reserved = Collections.unmodifiableMap(reserved);
            this.expiresAt = expiresAt;
        }

        public Object getSource() { return source; }
        public UUID getLockId() { return lockId; }
        public Map<String, Integer> getReserved() { return reserved; }
        public Instant getExpiresAt() { return expiresAt; }
    }

    public static class InventoryUnlockedEvent {
        private final Object source;
        private final UUID lockId;
        public InventoryUnlockedEvent(Object source, UUID lockId) {
            this.source = source;
            this.lockId = lockId;
        }
        public Object getSource() { return source; }
        public UUID getLockId() { return lockId; }
    }

    public static class InventoryCommittedEvent {
        private final Object source;
        private final UUID lockId;
        public InventoryCommittedEvent(Object source, UUID lockId) {
            this.source = source;
            this.lockId = lockId;
        }
        public Object getSource() { return source; }
        public UUID getLockId() { return lockId; }
    }

    // ------------------------------------------------------------------------
    // EXCEPTION CLASS
    // ------------------------------------------------------------------------

    public static class InventoryLockException extends Exception {
        public InventoryLockException(String message) { super(message); }
        public InventoryLockException(String message, Throwable cause) { super(message, cause); }
    }
}