package com.commercesphere.enterprise.payment.repository;

import com.commercesphere.enterprise.payment.model.PaymentTransaction;
import com.commercesphere.enterprise.payment.model.TransactionStatus;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

import javax.persistence.EntityManager;
import javax.persistence.LockModeType;
import javax.persistence.PersistenceContext;
import javax.persistence.TypedQuery;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.*;

/**
 * Spring-Data facade for {@link PaymentTransaction} entities. <br/>
 * Clients should favor the higher-level {@code PaymentService} where possible,
 * but advanced, batch-oriented jobs (e.g. nightly reconciliation) may interact
 * with this repository directly.
 *
 * For complex, non-trivial queries we delegate to {@link PaymentTransactionRepositoryImpl}
 * through the Spring-Data “fragment” mechanism.
 */
@Repository
public interface PaymentTransactionRepository extends
        JpaRepository<PaymentTransaction, UUID>,
        PaymentTransactionCustomRepository {

    /**
     * Resolves a transaction by the PSP (Payment Service Provider) reference.
     */
    Optional<PaymentTransaction> findByProviderReference(String providerReference);

    /**
     * Returns all transactions for a single order.
     */
    List<PaymentTransaction> findByOrderId(UUID orderId);

    /**
     * Fetches and locks the record for in-place mutation,
     * protecting invariants such as double capture.
     */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT tx FROM PaymentTransaction tx WHERE tx.id = :id")
    Optional<PaymentTransaction> lockByIdForUpdate(@Param("id") UUID id);

    /**
     * Lightweight existence check used by validation layers.
     */
    boolean existsByOrderIdAndStatus(UUID orderId, TransactionStatus status);
}

/**
 * Custom query fragment offering bulk reconciliation and error handling.
 */
interface PaymentTransactionCustomRepository {

    /**
     * Finds transactions that are still in one of the supplied {@code statuses} and
     * have been last modified before {@code before}. The result set is limited to
     * {@code limit} rows to guarantee predictable memory usage for batch jobs.
     */
    List<PaymentTransaction> findForReconciliation(LocalDateTime before,
                                                   Set<TransactionStatus> statuses,
                                                   int limit);

    /**
     * Marks the provided transactions as {@link TransactionStatus#RECONCILED}.
     *
     * @return number of rows updated
     */
    int markAsReconciled(Collection<UUID> transactionIds, String reconciledBy);

    /**
     * Sets status to {@link TransactionStatus#ERROR} and attaches the root cause.
     */
    int markAsError(UUID transactionId, String errorReason);

    /**
     * Returns authorizations that have not yet been captured and are older
     * than the provided {@code olderThan} duration.
     */
    List<PaymentTransaction> findPendingAuthorizations(Duration olderThan, int limit);
}

/**
 * Concrete implementation picked up automatically by Spring-Data because
 * of the “Impl” suffix.
 */
class PaymentTransactionRepositoryImpl implements PaymentTransactionCustomRepository {

    @PersistenceContext
    private EntityManager em;

    @Override
    @Transactional(readOnly = true)
    public List<PaymentTransaction> findForReconciliation(LocalDateTime before,
                                                          Set<TransactionStatus> statuses,
                                                          int limit) {
        if (statuses == null || statuses.isEmpty()) {
            return Collections.emptyList();
        }

        TypedQuery<PaymentTransaction> query = em.createQuery(
                "SELECT tx " +
                    "FROM PaymentTransaction tx " +
                    "WHERE tx.lastModified < :before " +
                    "  AND tx.status IN :statuses " +
                    "ORDER BY tx.lastModified ASC", PaymentTransaction.class);

        query.setParameter("before", before);
        query.setParameter("statuses", statuses);
        query.setMaxResults(limit);
        return query.getResultList();
    }

    @Override
    @Transactional
    @Modifying(clearAutomatically = true)
    public int markAsReconciled(Collection<UUID> transactionIds, String reconciledBy) {
        if (transactionIds == null || transactionIds.isEmpty()) {
            return 0;
        }

        return em.createQuery(
                "UPDATE PaymentTransaction tx " +
                    "SET tx.status = :reconciled, " +
                    "    tx.reconciledAt = :now, " +
                    "    tx.reconciledBy = :by " +
                    "WHERE tx.id IN :ids")
                .setParameter("reconciled", TransactionStatus.RECONCILED)
                .setParameter("now", LocalDateTime.now())
                .setParameter("by", reconciledBy)
                .setParameter("ids", transactionIds)
                .executeUpdate();
    }

    @Override
    @Transactional
    @Modifying(clearAutomatically = true)
    public int markAsError(UUID transactionId, String errorReason) {
        return em.createQuery(
                "UPDATE PaymentTransaction tx " +
                    "SET tx.status = :error, " +
                    "    tx.errorReason = :reason, " +
                    "    tx.lastModified = :now " +
                    "WHERE tx.id = :id")
                .setParameter("error", TransactionStatus.ERROR)
                .setParameter("reason", errorReason)
                .setParameter("now", LocalDateTime.now())
                .setParameter("id", transactionId)
                .executeUpdate();
    }

    @Override
    @Transactional(readOnly = true)
    public List<PaymentTransaction> findPendingAuthorizations(Duration olderThan, int limit) {
        LocalDateTime threshold = LocalDateTime.now().minus(olderThan);

        TypedQuery<PaymentTransaction> query = em.createQuery(
                "SELECT tx " +
                    "FROM PaymentTransaction tx " +
                    "WHERE tx.status = :authStatus " +
                    "  AND tx.createdAt < :threshold " +
                    "ORDER BY tx.createdAt ASC", PaymentTransaction.class);

        query.setParameter("authStatus", TransactionStatus.AUTHORIZED);
        query.setParameter("threshold", threshold);
        query.setMaxResults(limit);
        return query.getResultList();
    }
}