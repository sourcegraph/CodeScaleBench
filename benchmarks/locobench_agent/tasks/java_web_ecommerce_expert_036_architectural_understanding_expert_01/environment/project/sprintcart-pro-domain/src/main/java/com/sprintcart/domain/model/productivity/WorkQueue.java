package com.sprintcart.domain.model.productivity;

import java.io.Serializable;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

/**
 * Aggregate root representing a queue of work items that merchants/operators
 * can pull from to stay hyper–productive.  The queue is *pure domain* and
 * therefore has no knowledge of persistence, REST, security, etc.
 *
 * The class is intentionally mutable because the aggregate root encapsulates
 * consistency invariants.  All state–changes happen through the public
 * behavioural methods which perform the required validations.
 */
public final class WorkQueue implements Serializable {

    private static final long serialVersionUID = 1L;

    /**
     * Unique identifier for the queue.  In a multi–tenant environment this
     * would be combined with a TenantId value object.
     */
    private final UUID id;

    /**
     * Human-friendly label, e.g. "Catalog Updates", "Urgent Orders".
     */
    private final String name;

    /**
     * Internal storage for enqueued items.  ConcurrentHashMap is used so that
     * the aggregate remains thread–safe inside the JVM.  In a real distributed
     * system, higher-level locking or eventual-consistency mechanisms would be
     * required.
     */
    private final Map<WorkItemId, WorkItem> items = new ConcurrentHashMap<>();

    /**
     * Keeps track of completed item ids for quick KPI computations
     * (e.g. throughput, average cycle time).  This is an optimization that
     * avoids scanning the whole map.
     */
    private final Set<WorkItemId> completed = Collections.synchronizedSet(new HashSet<>());

    /**
     * Constructor is private; use factory method to ensure invariants.
     */
    private WorkQueue(UUID id, String name) {
        this.id = Objects.requireNonNull(id, "queue id cannot be null");
        this.name = Objects.requireNonNull(name, "queue name cannot be null");
    }

    /* -------------------------------------------------- *
     *  Factory
     * -------------------------------------------------- */

    public static WorkQueue create(String name) {
        return new WorkQueue(UUID.randomUUID(), name);
    }

    /* -------------------------------------------------- *
     *  Behavioural Methods – Command Side
     * -------------------------------------------------- */

    /**
     * Adds a brand-new work item to the queue.  Once enqueued the item is in
     * state {@link WorkItemStatus#QUEUED}.
     *
     * @throws WorkQueueException if an identical externalId already exists
     */
    public WorkItemId enqueue(String title,
                              Priority priority,
                              Optional<String> externalId,
                              Map<String, String> metadata) {

        Objects.requireNonNull(title, "title must not be null");
        Objects.requireNonNull(priority, "priority must not be null");

        externalId.ifPresent(id -> {
            boolean duplicate = items.values().stream()
                    .anyMatch(it -> id.equals(it.getExternalId().orElse(null)));
            if (duplicate) {
                throw new WorkQueueException(
                        "Work item with externalId [" + id + "] already exists in queue " + this.id);
            }
        });

        WorkItem item = WorkItem.of(
                WorkItemId.random(),
                title,
                priority,
                externalId,
                metadata);

        items.put(item.getId(), item);
        return item.getId();
    }

    /**
     * Pulls the highest-priority, FIFO work item that is currently
     * {@link WorkItemStatus#QUEUED} and assigns it to the requesting operator.
     *
     * @throws WorkQueueException if the queue is empty
     */
    public WorkItem claimNext(OperatorId operatorId) {
        Objects.requireNonNull(operatorId, "operatorId must not be null");

        WorkItem next = items.values().stream()
                .filter(it -> it.getStatus() == WorkItemStatus.QUEUED)
                .sorted(Comparator
                        .comparing(WorkItem::getPriority).reversed()     // higher priority first
                        .thenComparing(WorkItem::getCreatedAt))          // FIFO for same priority
                .findFirst()
                .orElseThrow(() -> new WorkQueueException("No items available to claim"));

        next.claim(operatorId);
        return next.snapshot(); // Return immutable view
    }

    /**
     * Completes the given item, moving it to {@link WorkItemStatus#DONE}.
     *
     * @throws WorkQueueException if the item is not found or cannot be completed
     */
    public void complete(WorkItemId itemId, OperatorId operatorId) {
        WorkItem item = locateItemOrThrow(itemId);

        if (!item.isClaimedBy(operatorId)) {
            throw new WorkQueueException("Operator " + operatorId + " has not claimed item " + itemId);
        }
        item.complete();
        completed.add(itemId);
    }

    /**
     * Releases an item that was previously claimed, returning it to
     * {@link WorkItemStatus#QUEUED}.  Use–case: operator hit a blocker.
     *
     * @throws WorkQueueException if the item is not found or not in progress
     */
    public void release(WorkItemId itemId, OperatorId operatorId) {
        WorkItem item = locateItemOrThrow(itemId);

        if (!item.isClaimedBy(operatorId)) {
            throw new WorkQueueException("Operator " + operatorId + " has not claimed item " + itemId);
        }
        item.release();
    }

    /**
     * Removes a DONE item from the queue.  Soft-delete semantics; the item
     * remains in `completed` set for historical metrics.
     */
    public void archive(WorkItemId itemId) {
        WorkItem item = locateItemOrThrow(itemId);
        if (item.getStatus() != WorkItemStatus.DONE) {
            throw new WorkQueueException("Only DONE items may be archived");
        }
        items.remove(itemId);
    }

    /* -------------------------------------------------- *
     *  Query Methods – Read Side
     * -------------------------------------------------- */

    public UUID getId() {
        return id;
    }

    public String getName() {
        return name;
    }

    public int size() {
        return items.size();
    }

    public int queuedCount() {
        return (int) items.values().stream()
                .filter(it -> it.getStatus() == WorkItemStatus.QUEUED)
                .count();
    }

    public int inProgressCount() {
        return (int) items.values().stream()
                .filter(it -> it.getStatus() == WorkItemStatus.IN_PROGRESS)
                .count();
    }

    public int completedCount() {
        return completed.size();
    }

    /**
     * Returns an immutable snapshot of items filtered by status.  Intended for
     * projection layers (e.g. REST, GraphQL) to build view models.
     */
    public List<WorkItem> findByStatus(WorkItemStatus status) {
        return items.values().stream()
                .filter(it -> it.getStatus() == status)
                .map(WorkItem::snapshot)
                .collect(Collectors.toUnmodifiableList());
    }

    /**
     * For supervisors: list of operators currently working on items.
     */
    public Set<OperatorId> activeOperators() {
        return items.values().stream()
                .filter(it -> it.getStatus() == WorkItemStatus.IN_PROGRESS)
                .map(WorkItem::getClaimedBy)
                .flatMap(Optional::stream)
                .collect(Collectors.toUnmodifiableSet());
    }

    /* -------------------------------------------------- *
     *  Private helpers
     * -------------------------------------------------- */

    private WorkItem locateItemOrThrow(WorkItemId id) {
        WorkItem item = items.get(id);
        if (item == null) {
            throw new WorkQueueException("Item " + id + " not found in queue " + this.id);
        }
        return item;
    }

    /* -------------------------------------------------- *
     *  Value Objects & Entities
     * -------------------------------------------------- */

    /**
     * Comparison is reversed so that {@code CRITICAL} ranks higher than
     * {@code LOW} when sorting natural order.
     */
    public enum Priority {
        LOW, MEDIUM, HIGH, CRITICAL
    }

    /**
     * Status of a given work item.
     */
    public enum WorkItemStatus {
        QUEUED,
        IN_PROGRESS,
        DONE
    }

    /**
     * Immutable identifier for {@link WorkItem}.
     */
    public record WorkItemId(UUID value) implements Serializable {
        public static WorkItemId random() {
            return new WorkItemId(UUID.randomUUID());
        }

        @Override
        public String toString() {
            return value.toString();
        }
    }

    /**
     * Identifier value object for an operator (authenticated back-office user).
     * Domain layer does not care how users are stored/authenticated.
     */
    public record OperatorId(UUID value) implements Serializable {
        public static OperatorId of(UUID id) { return new OperatorId(id); }

        @Override
        public String toString() {
            return value.toString();
        }
    }

    /**
     * Entity representing a single task in the queue.
     */
    public static final class WorkItem implements Serializable {

        private static final long serialVersionUID = 1L;

        private final WorkItemId id;
        private final String title;
        private final Priority priority;
        private final Instant createdAt;
        private final Optional<String> externalId;           // e.g. Order-ID, SKU
        private final Map<String, String> metadata;          // small bag of key-values

        private WorkItemStatus status;
        private Instant startedAt;                           // set when claimed
        private Instant finishedAt;                          // set when done
        private OperatorId claimedBy;                        // null when not claimed

        private WorkItem(WorkItemId id,
                         String title,
                         Priority priority,
                         Optional<String> externalId,
                         Map<String, String> metadata) {
            this.id = id;
            this.title = title;
            this.priority = priority;
            this.createdAt = Instant.now();
            this.externalId = externalId;
            this.metadata = new HashMap<>(metadata); // defensive copy
            this.status = WorkItemStatus.QUEUED;
        }

        static WorkItem of(WorkItemId id,
                           String title,
                           Priority priority,
                           Optional<String> externalId,
                           Map<String, String> metadata) {
            return new WorkItem(id, title, priority, externalId, metadata);
        }

        /* ----- State changes ----- */

        void claim(OperatorId operatorId) {
            if (status != WorkItemStatus.QUEUED) {
                throw new WorkQueueException("Item " + id + " is not available for claim");
            }
            this.status = WorkItemStatus.IN_PROGRESS;
            this.claimedBy = operatorId;
            this.startedAt = Instant.now();
        }

        void complete() {
            if (status != WorkItemStatus.IN_PROGRESS) {
                throw new WorkQueueException("Only in-progress items can be completed");
            }
            this.status = WorkItemStatus.DONE;
            this.finishedAt = Instant.now();
        }

        void release() {
            if (status != WorkItemStatus.IN_PROGRESS) {
                throw new WorkQueueException("Only in-progress items can be released");
            }
            this.status = WorkItemStatus.QUEUED;
            this.claimedBy = null;
            this.startedAt = null;
        }

        /* ----- Getters ----- */

        public WorkItemId getId()               { return id; }
        public String getTitle()                { return title; }
        public Priority getPriority()           { return priority; }
        public Instant getCreatedAt()           { return createdAt; }
        public Optional<String> getExternalId() { return externalId; }
        public Map<String, String> getMetadata(){ return Collections.unmodifiableMap(metadata); }
        public WorkItemStatus getStatus()       { return status; }
        public Optional<Instant> getStartedAt() { return Optional.ofNullable(startedAt); }
        public Optional<Instant> getFinishedAt(){ return Optional.ofNullable(finishedAt); }
        public Optional<OperatorId> getClaimedBy() { return Optional.ofNullable(claimedBy); }

        /* ----- Helpers ----- */

        boolean isClaimedBy(OperatorId operatorId) {
            return claimedBy != null && claimedBy.equals(operatorId);
        }

        /**
         * Returns an immutable defensive copy so that consumers (e.g. projection
         * layers) cannot accidentally mutate internal aggregate state.
         */
        public WorkItem snapshot() {
            WorkItem clone = new WorkItem(
                    this.id,
                    this.title,
                    this.priority,
                    this.externalId,
                    this.metadata);
            clone.status = this.status;
            clone.startedAt = this.startedAt;
            clone.finishedAt = this.finishedAt;
            clone.claimedBy = this.claimedBy;
            return clone;
        }

        @Override
        public String toString() {
            return "WorkItem{" +
                    "id=" + id +
                    ", title='" + title + '\'' +
                    ", status=" + status +
                    ", priority=" + priority +
                    '}';
        }
    }

    /* -------------------------------------------------- *
     *  Domain-level Exception
     * -------------------------------------------------- */

    public static final class WorkQueueException extends RuntimeException {
        private static final long serialVersionUID = 1L;

        public WorkQueueException(String message) {
            super(message);
        }
    }
}