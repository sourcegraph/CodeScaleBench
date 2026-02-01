package com.sprintcart.domain.model.productivity;

import java.io.Serial;
import java.io.Serializable;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/**
 * UserTask represents an actionable item that appears in a SprintCart operator’s
 * personal work queue.  The class is part of the pure domain layer and therefore
 * keeps zero knowledge about persistence, transport, or presentation concerns.
 *
 * Life-cycle rules:
 *
 *  • A task is created in PENDING state.
 *  • It can be started (IN_PROGRESS) exactly once.
 *  • Only an IN_PROGRESS task can be completed.
 *  • A task can be blocked at any moment, but must be unblocked before it can finish.
 *  • Cancellation is always allowed unless the task is already COMPLETED or CANCELLED.
 *
 * All state transitions emit {@link DomainEvent}s so that callers can forward those
 * events to an asynchronous bus without making the entity dependent on any runtime
 * framework.
 */
public class UserTask implements Serializable {

    @Serial
    private static final long serialVersionUID = -893714721341373934L;

    private final UUID id;
    private final UUID userId;
    private String title;
    private String description;
    private TaskStatus status;
    private TaskPriority priority;
    private final LocalDateTime createdAt;
    private LocalDateTime updatedAt;
    private LocalDateTime completedAt;

    /**
     * Transient queue of domain events raised by this aggregate.
     * The list is cleared every time {@link #pullDomainEvents()} is invoked.
     */
    private final List<DomainEvent> domainEvents = new ArrayList<>();

    // ----------
    // Constructors
    // ----------

    private UserTask(UUID id,
                     UUID userId,
                     String title,
                     String description,
                     TaskPriority priority,
                     LocalDateTime createdAt) {

        this.id = Objects.requireNonNull(id, "id must not be null");
        this.userId = Objects.requireNonNull(userId, "userId must not be null");
        this.title = validateTitle(title);
        this.description = sanitizeDescription(description);
        this.priority = Objects.requireNonNullElse(priority, TaskPriority.MEDIUM);
        this.status = TaskStatus.PENDING;
        this.createdAt = Objects.requireNonNullElseGet(createdAt, LocalDateTime::now);
        this.updatedAt = this.createdAt;
    }

    /**
     * Factory method for creating a new task.
     */
    public static UserTask createNew(UUID userId,
                                     String title,
                                     String description,
                                     TaskPriority priority) {

        UserTask task = new UserTask(UUID.randomUUID(),
                                     userId,
                                     title,
                                     description,
                                     priority,
                                     LocalDateTime.now());

        task.enqueueEvent(new TaskCreatedEvent(task.id, task.userId, task.createdAt));
        return task;
    }

    // ----------
    // Behavior
    // ----------

    /**
     * Moves the task from PENDING or BLOCKED to IN_PROGRESS.
     */
    public void start() {
        assertStatus(TaskStatus.PENDING, TaskStatus.BLOCKED);
        transitionTo(TaskStatus.IN_PROGRESS);
        enqueueEvent(new TaskStartedEvent(id, userId, updatedAt));
    }

    /**
     * Completes the task.
     */
    public void complete() {
        assertStatus(TaskStatus.IN_PROGRESS);
        this.completedAt = LocalDateTime.now();
        transitionTo(TaskStatus.COMPLETED);
        enqueueEvent(new TaskCompletedEvent(id, userId, completedAt));
    }

    /**
     * Cancels the task if it is not already completed or cancelled.
     */
    public void cancel(String reason) {
        if (status == TaskStatus.COMPLETED || status == TaskStatus.CANCELLED) {
            throw new TaskLifecycleException("Cannot cancel a task that is " + status);
        }
        transitionTo(TaskStatus.CANCELLED);
        enqueueEvent(new TaskCancelledEvent(id, userId, updatedAt, sanitizeDescription(reason)));
    }

    /**
     * Blocks the task and records the cause.
     */
    public void block(String cause) {
        if (status == TaskStatus.COMPLETED || status == TaskStatus.CANCELLED) {
            throw new TaskLifecycleException("Cannot block a task that is " + status);
        }
        transitionTo(TaskStatus.BLOCKED);
        enqueueEvent(new TaskBlockedEvent(id, userId, updatedAt, sanitizeDescription(cause)));
    }

    /**
     * Unblocks a blocked task, returning it to PENDING.
     */
    public void unblock() {
        assertStatus(TaskStatus.BLOCKED);
        transitionTo(TaskStatus.PENDING);
        enqueueEvent(new TaskUnblockedEvent(id, userId, updatedAt));
    }

    /**
     * Updates the task’s meta-data. Only allowed while the task
     * is not completed or cancelled.
     */
    public void edit(String newTitle, String newDescription, TaskPriority newPriority) {
        if (status == TaskStatus.COMPLETED || status == TaskStatus.CANCELLED) {
            throw new TaskLifecycleException("Cannot edit a task that is " + status);
        }
        boolean dirty = false;

        if (newTitle != null && !newTitle.equals(title)) {
            this.title = validateTitle(newTitle);
            dirty = true;
        }

        if (newDescription != null && !newDescription.equals(description)) {
            this.description = sanitizeDescription(newDescription);
            dirty = true;
        }

        if (newPriority != null && newPriority != priority) {
            this.priority = newPriority;
            dirty = true;
        }

        if (dirty) {
            touch();
            enqueueEvent(new TaskEditedEvent(id, userId, updatedAt));
        }
    }

    // ----------
    // Domain-event handling
    // ----------

    private void enqueueEvent(DomainEvent event) {
        domainEvents.add(event);
    }

    /**
     * Returns an immutable copy of domain events emitted since the last pull,
     * and empties the internal buffer. This method is typically invoked by the
     * outer application service layer after {@code repository.save(userTask)}.
     */
    public List<DomainEvent> pullDomainEvents() {
        List<DomainEvent> events = List.copyOf(domainEvents);
        domainEvents.clear();
        return events;
    }

    // ----------
    // Internal helpers
    // ----------

    private void assertStatus(TaskStatus... expected) {
        for (TaskStatus s : expected) {
            if (s == status) {
                return;
            }
        }
        throw new TaskLifecycleException(
                "Illegal status transition: current=" + status + " expected=" + List.of(expected));
    }

    private void transitionTo(TaskStatus nextState) {
        status = nextState;
        touch();
    }

    private void touch() {
        this.updatedAt = LocalDateTime.now();
    }

    private static String validateTitle(String value) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("title must not be blank");
        }
        if (value.length() > 120) {
            throw new IllegalArgumentException("title length must be ≤ 120 characters");
        }
        return value.strip();
    }

    private static String sanitizeDescription(String value) {
        if (value == null) {
            return "";
        }
        return value.strip();
    }

    // ----------
    // Getters (immutable views)
    // ----------

    public UUID getId() {
        return id;
    }

    public UUID getUserId() {
        return userId;
    }

    public String getTitle() {
        return title;
    }

    public String getDescription() {
        return description;
    }

    public TaskStatus getStatus() {
        return status;
    }

    public TaskPriority getPriority() {
        return priority;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }

    public LocalDateTime getCompletedAt() {
        return completedAt;
    }

    // ----------
    // Value semantics
    // ----------

    @Override
    public boolean equals(Object o) {
        return this == o || (o instanceof UserTask that && id.equals(that.id));
    }

    @Override
    public int hashCode() {
        return Objects.hash(id);
    }

    // ----------
    // Nested types
    // ----------

    public enum TaskStatus {
        PENDING,
        IN_PROGRESS,
        BLOCKED,
        COMPLETED,
        CANCELLED
    }

    public enum TaskPriority {
        LOW,
        MEDIUM,
        HIGH
    }

    /**
     * Marker interface for domain events generated by {@link UserTask}.
     * Application services are expected to forward these events to an
     * outbox, message broker, or in-memory async dispatcher.
     */
    public interface DomainEvent extends Serializable {
        UUID taskId();
        UUID userId();
        LocalDateTime occurredAt();
    }

    // -----
    // Event implementations
    // -----

    public record TaskCreatedEvent(UUID taskId, UUID userId, LocalDateTime occurredAt)
            implements DomainEvent {}

    public record TaskStartedEvent(UUID taskId, UUID userId, LocalDateTime occurredAt)
            implements DomainEvent {}

    public record TaskCompletedEvent(UUID taskId, UUID userId, LocalDateTime occurredAt)
            implements DomainEvent {}

    public record TaskCancelledEvent(UUID taskId,
                                     UUID userId,
                                     LocalDateTime occurredAt,
                                     String reason) implements DomainEvent {}

    public record TaskBlockedEvent(UUID taskId,
                                   UUID userId,
                                   LocalDateTime occurredAt,
                                   String cause) implements DomainEvent {}

    public record TaskUnblockedEvent(UUID taskId,
                                     UUID userId,
                                     LocalDateTime occurredAt) implements DomainEvent {}

    public record TaskEditedEvent(UUID taskId,
                                  UUID userId,
                                  LocalDateTime occurredAt) implements DomainEvent {}

    /**
     * Thrown when an illegal state transition or invalid operation
     * is attempted on a {@link UserTask}.
     */
    public static class TaskLifecycleException extends RuntimeException {
        public TaskLifecycleException(String message) {
            super(message);
        }
    }
}