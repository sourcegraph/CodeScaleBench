package com.sprintcart.domain.ports.out.persistence;

import com.sprintcart.domain.exceptions.PersistenceException;
import com.sprintcart.domain.model.order.Order;
import com.sprintcart.domain.model.order.OrderId;
import com.sprintcart.domain.model.order.OrderStatus;
import com.sprintcart.domain.shared.Page;
import com.sprintcart.domain.shared.PageRequest;
import com.sprintcart.domain.shared.Sort;
import com.sprintcart.domain.shared.criteria.OrderCriteria;

import java.time.Instant;
import java.util.Collection;
import java.util.Optional;

/**
 * Outbound port that abstracts all persistence-related concerns for the {@link Order} aggregate.
 * <p>
 * Implementations may rely on any storage technology (SQL, NoSQL, event store, etc.) as long as the
 * contract defined here is honored.  No domain code should depend on concrete implementations.
 *
 * <h3>Concurrency guarantees</h3>
 * Certain methods explicitly state their isolation requirements (e.g. pessimistic lock for update)
 * so that implementations can provide the most efficient mechanism available in their stack.
 *
 * <h3>Error handling</h3>
 * All persistence-related failures should be wrapped in a {@link PersistenceException} to avoid
 * leaking low-level details to the domain layer.
 */
public interface OrderRepositoryPort {

    /**
     * Persists a new {@link Order} aggregate.
     *
     * @param order the aggregate in <em>new</em> state
     * @return the generated {@link OrderId}
     * @throws PersistenceException when the write could not be completed
     */
    OrderId insert(Order order) throws PersistenceException;

    /**
     * Updates an existing {@link Order}.
     *
     * @param order the modified aggregate (must already exist in storage)
     * @throws PersistenceException when the write could not be completed
     */
    void update(Order order) throws PersistenceException;

    /**
     * Retrieves an order by its identifier.
     *
     * @param id aggregate key
     * @return an {@link Optional} containing the order if found
     * @throws PersistenceException on read failure
     */
    Optional<Order> findById(OrderId id) throws PersistenceException;

    /**
     * Retrieves an order by its identifier while acquiring a <em>pessimistic write lock</em>
     * (or implementation-specific equivalent) so that concurrent modifications are serialized.
     *
     * @param id aggregate key
     * @return an optional containing the locked order, empty if it does not exist
     * @throws PersistenceException on read failure or lock acquisition failure
     */
    Optional<Order> findByIdForUpdate(OrderId id) throws PersistenceException;

    /**
     * Deletes an order permanently.
     *
     * @param id aggregate key
     * @throws PersistenceException when the delete could not be completed
     */
    void delete(OrderId id) throws PersistenceException;

    /**
     * Bulk-loads orders based on a set of identifiers.
     *
     * @param ids collection of keys
     * @return matching orders (ordering is implementation-defined)
     * @throws PersistenceException on read failure
     */
    Collection<Order> fetchByIds(Collection<OrderId> ids) throws PersistenceException;

    /**
     * Returns a <em>paged</em> collection of orders that satisfy the given criteria.
     *
     * @param criteria   typed filter object
     * @param pageRequest paging options (page number, size)
     * @param sort       sort definition (multiple fields allowed)
     * @return a {@link Page} with content and metadata
     * @throws PersistenceException on read failure
     */
    Page<Order> findAll(OrderCriteria criteria,
                        PageRequest pageRequest,
                        Sort sort) throws PersistenceException;

    /**
     * Atomically updates the status of an order. Implementations <b>must</b> guarantee that:
     * <ol>
     *   <li>the order exists and is in {@code expectedStatus}</li>
     *   <li>the status is changed to {@code newStatus}</li>
     *   <li>the {@code updatedAt} timestamp is persisted</li>
     * </ol>
     * If the expected status does not match the current value, no change occurs and
     * {@code false} must be returned.
     *
     * @param id             order key
     * @param expectedStatus optimistic condition
     * @param newStatus      desired status
     * @param updatedAt      domain timestamp
     * @return {@code true} if the status was updated, {@code false} otherwise
     * @throws PersistenceException on write failure
     */
    boolean updateStatusAtomic(OrderId id,
                               OrderStatus expectedStatus,
                               OrderStatus newStatus,
                               Instant updatedAt) throws PersistenceException;

    /**
     * Convenience helper that saves an order—delegating to {@link #insert(Order)} if it is new,
     * otherwise to {@link #update(Order)}.
     *
     * Implementations <em>may</em> override the default behavior for efficiency.
     *
     * @param order the aggregate to persist
     * @throws PersistenceException when the write could not be completed
     */
    default void save(Order order) throws PersistenceException {
        if (order.isNew()) {
            insert(order);
        } else {
            update(order);
        }
    }
}