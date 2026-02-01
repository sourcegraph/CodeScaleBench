package com.sprintcart.adapters.persistence.repository;

import com.sprintcart.adapters.persistence.entity.OrderEntity;
import com.sprintcart.adapters.persistence.entity.OrderEntity.OrderStatus;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import javax.persistence.LockModeType;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.lang.NonNull;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * Spring-Data repository that acts as the primary data source gateway for the {@link
 * com.sprintcart.domain.order.Order Order} aggregate.
 *
 * <p>Only persistence‐level concerns live here (query tuning, fetch graphs, locking, etc.).
 * Business-level semantics are handled by the domain repository adapter, which composes this
 * interface and performs entity–aggregate mapping.</p>
 *
 * <p>The interface is deliberately verbose: we prefer explicit, well-documented queries over
 * “magic method names” once a query becomes performance-sensitive or spans multiple relations.
 * All methods are <em>read-only</em> unless otherwise annotated; mutating operations must be
 * wrapped in the calling service’s transaction boundary.</p>
 *
 * <p>NOTE: Do NOT inject this repository directly in application services. Always go through the
 * domain-level {@code OrderRepository} port.</p>
 */
@Transactional(readOnly = true, propagation = Propagation.MANDATORY)
public interface OrderSpringDataRepository
    extends JpaRepository<OrderEntity, UUID>, JpaSpecificationExecutor<OrderEntity> {

  /* ---------- Simple finders ---------- */

  /**
   * Returns an order by its externally visible reference (e.g. {@code ORD-2023-000123}).
   *
   * <p>{@code publicId} is unique and indexed for fast look-ups coming from the storefront,
   * customer emails, and webhooks.</p>
   */
  Optional<OrderEntity> findByPublicId(@NonNull String publicId);

  /**
   * Retrieves a paginated slice of a customer's orders, ordered by creation timestamp descending.
   * Useful for the "My Orders" area in the customer account portal.
   */
  @EntityGraph(attributePaths = {"items", "items.productSnapshot"})
  List<OrderEntity> findByCustomerIdOrderByCreatedAtDesc(
      @NonNull UUID customerId, @NonNull Pageable page);

  /**
   * Fetches orders in one of the given statuses created within the provided time-window.
   * Back-office dashboards stream these results in real-time for live monitoring.
   */
  List<OrderEntity> findByStatusInAndCreatedAtBetween(
      @NonNull Collection<OrderStatus> statuses, @NonNull Instant start, @NonNull Instant end);

  /* ---------- Aggregations ---------- */

  /**
   * Calculates gross revenue in the given period — leveraged by finance reports and KPI widgets.
   */
  @Query(
      "select coalesce(sum(o.grandTotal), 0) "
          + "from OrderEntity o "
          + "where o.status = com.sprintcart.adapters.persistence.entity.OrderEntity$OrderStatus.COMPLETED "
          + "and o.createdAt between :start and :end")
  BigDecimal sumCompletedOrdersGrossRevenue(
      @NonNull Instant start, @NonNull Instant end);

  /* ---------- Concurrency / locking ---------- */

  /**
   * Acquires a pessimistic lock on the order row to guard against double-payment capture or
   * concurrent state mutations during webhook bursts.
   */
  @Lock(LockModeType.PESSIMISTIC_WRITE)
  @Query("select o from OrderEntity o where o.id = :id")
  Optional<OrderEntity> findForUpdate(@NonNull UUID id);

  /* ---------- State transitions ---------- */

  /**
   * Archives "soft-deleted" orders that haven't been updated for a configurable amount of time.
   *
   * @return the number of rows affected
   */
  @Transactional
  @Modifying(clearAutomatically = true, flushAutomatically = true)
  @Query(
      "update OrderEntity o "
          + "set o.archived = true "
          + "where o.archived = false "
          + "and o.updatedAt < :cutoff")
  int archiveOrdersNotModifiedSince(@NonNull Instant cutoff);

  /**
   * Updates the status of an order directly in the database, bypassing the entity manager's dirty
   * checking to execute in constant time for mass-status updates (e.g. "mark 2 000 orders as
   * exported").
   *
   * @return number of orders whose status has been updated
   */
  @Transactional
  @Modifying(clearAutomatically = true, flushAutomatically = true)
  @Query(
      "update OrderEntity o "
          + "set o.status = :newStatus, "
          + "o.updatedAt = :now "
          + "where o.id in :orderIds")
  int bulkUpdateStatus(
      @NonNull Collection<UUID> orderIds,
      @NonNull OrderStatus newStatus,
      @NonNull Instant now);
}