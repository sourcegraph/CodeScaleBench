package com.commercesphere.enterprise.payment.service;

import com.commercesphere.enterprise.payment.gateway.PaymentGatewayClient;
import com.commercesphere.enterprise.payment.model.LedgerEntry;
import com.commercesphere.enterprise.payment.model.Payment;
import com.commercesphere.enterprise.payment.model.enums.PaymentStatus;
import com.commercesphere.enterprise.payment.repository.LedgerEntryRepository;
import com.commercesphere.enterprise.payment.repository.PaymentRepository;
import com.commercesphere.enterprise.payment.repository.ReconciliationAuditRepository;
import com.commercesphere.enterprise.payment.service.dto.ReconciliationReport;
import com.commercesphere.enterprise.payment.service.dto.ReconciliationSummary;
import jakarta.annotation.PreDestroy;
import jakarta.transaction.Transactional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.*;
import java.util.stream.Collectors;

/**
 * Service responsible for reconciling daily payment transactions against the
 * internal general ledger.  A typical reconciliation run will:
 * <ol>
 *     <li>Fetch all captured payments for the business date.</li>
 *     <li>Fetch all ledger entries that were generated for the same period.</li>
 *     <li>Match each payment to its corresponding ledger entry.</li>
 *     <li>Handle mismatches (missing ledger entry, amount drift, etc.) by creating
 *         compensating transactions or alerting finance.</li>
 *     <li>Write an immutable audit trace for compliance.</li>
 * </ol>
 *
 * The service is Spring managed, thread-safe, and executes matching operations in
 * parallel to keep the daily batch window small even with >250k transactions.
 */
@Service
public class FinancialReconciliationService {

    private static final Logger LOG = LoggerFactory.getLogger(FinancialReconciliationService.class);

    /**
     * Fail-safe timeout for the entire reconciliation job (minutes).
     */
    private static final long GLOBAL_TIMEOUT_MINUTES = 50L;

    private final PaymentRepository paymentRepository;
    private final LedgerEntryRepository ledgerEntryRepository;
    private final ReconciliationAuditRepository auditRepository;
    private final PaymentGatewayClient paymentGatewayClient;

    /*
     * Dedicated executor—ensures reconciliation tasks never starve other web-layer thread pools.
     */
    private final ExecutorService executor =
            new ThreadPoolExecutor(
                    Runtime.getRuntime().availableProcessors(),                 // core
                    Runtime.getRuntime().availableProcessors() * 2,             // max
                    60L, TimeUnit.SECONDS,
                    new LinkedBlockingQueue<>(10_000),
                    new ReconciliationThreadFactory()
            );

    public FinancialReconciliationService(final PaymentRepository paymentRepository,
                                          final LedgerEntryRepository ledgerEntryRepository,
                                          final ReconciliationAuditRepository auditRepository,
                                          final PaymentGatewayClient paymentGatewayClient) {
        this.paymentRepository     = Objects.requireNonNull(paymentRepository);
        this.ledgerEntryRepository = Objects.requireNonNull(ledgerEntryRepository);
        this.auditRepository       = Objects.requireNonNull(auditRepository);
        this.paymentGatewayClient  = Objects.requireNonNull(paymentGatewayClient);
    }

    /**
     * Starts a full reconciliation job for the provided business date.  This call blocks
     * until the reconciliation completes or the global timeout is hit.
     *
     * @param businessDate Local date for which to reconcile transactions; normally "yesterday"
     *                     in UTC to guarantee all gateway batches are settled.
     * @return A detailed reconciliation report with per-result breakdowns.
     * @throws ReconciliationException if the job fails or times out.
     */
    @Transactional
    public ReconciliationReport reconcile(final LocalDate businessDate) throws ReconciliationException {

        LOG.info("Starting reconciliation for {}.", businessDate);

        final Instant start = Instant.now();

        /*
         * Step #1 – fetch data sets.  We purposefully isolate DB calls outside of the
         * parallel section to avoid connection pool congestion.
         */
        List<Payment> payments = paymentRepository.findCapturedPayments(businessDate);
        List<LedgerEntry> ledgerEntries = ledgerEntryRepository.findEntriesByBusinessDate(businessDate);

        LOG.debug("Fetched {} payments and {} ledger entries for date {}",
                payments.size(), ledgerEntries.size(), businessDate);

        /*
         * Transform ledger entries into lookup map keyed by paymentId for O(1) matching.
         */
        Map<String, LedgerEntry> entryLookup =
                ledgerEntries.stream()
                             .filter(e -> e.getPaymentId() != null)
                             .collect(Collectors.toConcurrentMap(
                                     LedgerEntry::getPaymentId,
                                     e -> e,
                                     (a, b) -> a)); // duplicates won’t happen but keep compiler happy

        /*
         * Step #2 – distribute reconciliation tasks across the executor service.
         */
        List<Future<ReconciliationSummary>> futures = new ArrayList<>(payments.size());

        for (Payment p : payments) {
            futures.add(
                    executor.submit(() -> reconcileSinglePayment(p, entryLookup.get(p.getId())))
            );
        }

        /*
         * Step #3 – gather results with a global fail-safe timeout.
         */
        Map<ReconciliationSummary.ResultType, Integer> tally = new EnumMap<>(ReconciliationSummary.ResultType.class);
        List<ReconciliationSummary> summaries                = new ArrayList<>(payments.size());

        try {
            for (Future<ReconciliationSummary> future : futures) {
                ReconciliationSummary summary = future.get(GLOBAL_TIMEOUT_MINUTES, TimeUnit.MINUTES);
                summaries.add(summary);
                tally.merge(summary.getResultType(), 1, Integer::sum);
            }
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            throw new ReconciliationException("Reconciliation interrupted", ie);
        } catch (ExecutionException ee) {
            throw new ReconciliationException("Reconciliation failed", ee.getCause());
        } catch (TimeoutException te) {
            throw new ReconciliationException("Reconciliation exceeded global timeout", te);
        }

        /*
         * Step #4 – persist atomic audit record and assemble final report.
         */
        auditRepository.saveBatch(summaries);

        Duration runtime = Duration.between(start, Instant.now());
        ReconciliationReport report = new ReconciliationReport(
                businessDate,
                runtime,
                tally,
                summaries
        );

        LOG.info("Reconciliation for {} finished in {}s (success={}, mismatch={}, error={})",
                businessDate,
                runtime.toSeconds(),
                tally.getOrDefault(ReconciliationSummary.ResultType.SUCCESS, 0),
                tally.getOrDefault(ReconciliationSummary.ResultType.MISMATCH, 0),
                tally.getOrDefault(ReconciliationSummary.ResultType.ERROR, 0));

        return report;
    }

    /**
     * Performs reconciliation for one payment & its ledger entry in isolation.  This method is
     * intentionally package-private to simplify unit testing.
     */
    ReconciliationSummary reconcileSinglePayment(final Payment payment,
                                                 final LedgerEntry ledgerEntry) {

        if (ledgerEntry == null) {
            /*
             * Missing ledger entry → try to create compensating entry or flag for manual review.
             */
            String msg = "Ledger entry missing";
            LOG.warn("Payment {} – {}", payment.getId(), msg);
            try {
                ledgerEntryRepository.createCompensatingEntry(payment);
                return ReconciliationSummary.mismatch(payment.getId(), msg + " – compensating entry created");
            } catch (Exception ex) {
                LOG.error("Failed to create compensating entry for payment {}", payment.getId(), ex);
                return ReconciliationSummary.error(payment.getId(), ex.getMessage());
            }
        }

        /*
         * Amount comparison uses cents (minor units) to dodge floating-point inaccuracies.
         */
        long payCents   = payment.getAmountCents();
        long ledgerCents = ledgerEntry.getAmountCents();

        if (payCents != ledgerCents) {
            String msg = "Amount mismatch: payment=" + payCents + ", ledger=" + ledgerCents;
            LOG.warn("Payment {} – {}", payment.getId(), msg);
            return ReconciliationSummary.mismatch(payment.getId(), msg);
        }

        if (payment.getStatus() != PaymentStatus.CAPTURED) {
            String msg = "Unexpected payment status " + payment.getStatus();
            LOG.warn("Payment {} – {}", payment.getId(), msg);
            return ReconciliationSummary.mismatch(payment.getId(), msg);
        }

        /*
         * Trigger an idempotent settle call to the gateway.  The gateway itself guarantees
         * idempotency via a unique reconciliation key, so duplicate calls are safe.
         */
        try {
            paymentGatewayClient.settle(payment.getGatewayReference());
            return ReconciliationSummary.success(payment.getId());
        } catch (Exception ex) {
            LOG.error("Gateway settle failed for payment {}", payment.getId(), ex);
            return ReconciliationSummary.error(payment.getId(), ex.getMessage());
        }
    }

    @PreDestroy
    public void shutdown() {
        LOG.info("Shutting down reconciliation executor");
        executor.shutdown();
        try {
            if (!executor.awaitTermination(15, TimeUnit.SECONDS)) {
                executor.shutdownNow();
            }
        } catch (InterruptedException e) {
            executor.shutdownNow();
            Thread.currentThread().interrupt();
        }
    }

    /**
     * Custom thread factory that produces daemon threads with descriptive names.
     */
    private static final class ReconciliationThreadFactory implements ThreadFactory {

        private static final String THREAD_NAME_PATTERN = "recon-worker-%d";
        private static final ThreadFactory DELEGATE      = Executors.defaultThreadFactory();
        private static final AtomicInteger COUNTER       = new AtomicInteger(1);

        @Override
        public Thread newThread(Runnable r) {
            Thread t = DELEGATE.newThread(r);
            t.setDaemon(true);
            t.setName(THREAD_NAME_PATTERN.formatted(COUNTER.getAndIncrement()));
            return t;
        }
    }

    /**
     * Generic runtime exception thrown by {@link FinancialReconciliationService}.
     */
    public static class ReconciliationException extends RuntimeException {
        public ReconciliationException(String msg, Throwable cause) { super(msg, cause); }
        public ReconciliationException(String msg) { super(msg); }
    }
}