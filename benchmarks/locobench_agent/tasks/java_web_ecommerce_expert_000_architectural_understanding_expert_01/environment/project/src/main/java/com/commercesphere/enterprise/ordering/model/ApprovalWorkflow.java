package com.commercesphere.enterprise.ordering.model;

import jakarta.persistence.CascadeType;
import jakarta.persistence.CollectionTable;
import jakarta.persistence.Column;
import jakarta.persistence.ElementCollection;
import jakarta.persistence.Embeddable;
import jakarta.persistence.Embedded;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.OrderColumn;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import java.io.Serial;
import java.io.Serializable;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * Domain aggregate representing an approval workflow for an {@code Order}.
 *
 * <p>Each workflow consists of an ordered chain of {@linkplain ApprovalStep approval
 * steps}.  The workflow transitions through a deterministic set of {@linkplain
 * Status states} until it is either {@code COMPLETED} or {@code CANCELLED}.  All
 * state mutations are guarded by business rules and publish {@linkplain
 * DomainEvent domain events} so that application services can react to the changes
 * (e.g. send notification e-mails, update dashboards, etc.).</p>
 *
 * <p>Persistence is handled by JPA/Hibernate.  Note that setters are intentionally
 * omitted; mutating the workflow is only possible through explicit domain methods
 * such as {@link #approve(UUID, String)} or {@link #reject(UUID, String)}.</p>
 *
 * @author CommerceSphere
 */
@Entity
@Table(name = "approval_workflows")
public class ApprovalWorkflow implements Serializable {

    @Serial
    private static final long serialVersionUID = 6641758537499778357L;

    @Id
    @GeneratedValue(strategy = GenerationType.AUTO)
    private UUID id;

    /**
     * Identifier of the order this workflow belongs to.
     */
    @Column(name = "order_id", nullable = false, updatable = false)
    private UUID orderId;

    /**
     * User that initially created (and owns) the workflow.
     */
    @Column(name = "initiator_id", nullable = false, updatable = false)
    private UUID initiatorId;

    @Enumerated(EnumType.STRING)
    @Column(name = "status", nullable = false)
    private Status status = Status.PENDING;

    /**
     * Zero-based index of the step the workflow is currently waiting on.
     */
    @Column(name = "current_step_index", nullable = false)
    private int currentStepIndex = 0;

    /**
     * Ordered list of approval steps. Hibernate will persist it via a secondary
     * table "approval_steps".
     */
    @ElementCollection(fetch = FetchType.EAGER)
    @CollectionTable(name = "approval_steps")
    @OrderColumn(name = "step_position")
    private final List<ApprovalStep> steps = new ArrayList<>();

    @Column(name = "created_at", nullable = false, updatable = false)
    private OffsetDateTime createdAt;

    @Column(name = "updated_at", nullable = false)
    private OffsetDateTime updatedAt;

    @Version
    private long version;

    // -----------------------------------------------------------------------
    // Constructors
    // -----------------------------------------------------------------------

    /**
     * Required by JPA.
     */
    protected ApprovalWorkflow() {
        /* JPA constructor */
    }

    private ApprovalWorkflow(Builder builder) {
        this.orderId = Objects.requireNonNull(builder.orderId, "orderId");
        this.initiatorId = Objects.requireNonNull(builder.initiatorId, "initiatorId");
        builder.approverChain.forEach(userId -> this.steps.add(new ApprovalStep(userId)));
        if (this.steps.isEmpty()) {
            throw new IllegalArgumentException("Approval chain must contain at least one approver.");
        }
        this.createdAt = OffsetDateTime.now();
        this.updatedAt = this.createdAt;
        builder.eventPublisher.publish(new WorkflowCreated(id, orderId, initiatorId));
    }

    // -----------------------------------------------------------------------
    // Domain methods
    // -----------------------------------------------------------------------

    /**
     * Approves the current pending step.  If the final step is approved, the whole
     * workflow transitions to {@code COMPLETED}.
     *
     * @param approverId User that approves
     * @param comments   Optional comments
     *
     * @throws WorkflowException if the action is not permissible
     */
    public void approve(UUID approverId, String comments) {
        assertAlive();
        ApprovalStep step = currentStep();
        step.approve(approverId, comments);
        this.updatedAt = OffsetDateTime.now();

        if (currentStepIndex == steps.size() - 1) {
            transitionTo(Status.COMPLETED);
        } else {
            ++currentStepIndex;
        }
    }

    /**
     * Rejects the workflow outright. No further approvals are possible afterwards.
     */
    public void reject(UUID approverId, String reason) {
        assertAlive();
        ApprovalStep step = currentStep();
        step.reject(approverId, reason);
        transitionTo(Status.REJECTED);
    }

    /**
     * Cancels the workflow. Only the initiator is allowed to do so and only while
     * the workflow is still {@link Status#PENDING pending}.
     */
    public void cancel(UUID actorId, String reason) {
        if (!Objects.equals(actorId, initiatorId)) {
            throw new WorkflowException("Only the initiator can cancel the workflow.");
        }
        if (status != Status.PENDING) {
            throw new WorkflowException("Only pending workflows can be cancelled.");
        }
        transitionTo(Status.CANCELLED);
    }

    /**
     * Escalates the current step by injecting an additional approver directly
     * after the current one.
     *
     * <p>The current approver remains unchanged, i.e. they still need to decide
     * before the escalated user gets their turn.</p>
     */
    public void escalate(UUID escalatedTo, String note) {
        assertAlive();
        steps.add(currentStepIndex + 1, new ApprovalStep(escalatedTo, note));
        this.updatedAt = OffsetDateTime.now();
    }

    // -----------------------------------------------------------------------
    // Internal helpers
    // -----------------------------------------------------------------------

    private ApprovalStep currentStep() {
        return steps.get(currentStepIndex);
    }

    private void transitionTo(Status targetState) {
        if (!status.isTransitionAllowed(targetState)) {
            throw new WorkflowException("Cannot transition workflow from " + status + " to " + targetState);
        }
        this.status = targetState;
        this.updatedAt = OffsetDateTime.now();
    }

    private void assertAlive() {
        if (status.isTerminal()) {
            throw new WorkflowException("Workflow already finished with state " + status);
        }
    }

    // -----------------------------------------------------------------------
    // Getters
    // -----------------------------------------------------------------------

    public UUID getId() {
        return id;
    }

    public UUID getOrderId() {
        return orderId;
    }

    public UUID getInitiatorId() {
        return initiatorId;
    }

    public Status getStatus() {
        return status;
    }

    public int getCurrentStepIndex() {
        return currentStepIndex;
    }

    /**
     * Immutable snapshot of the steps to protect internal state.
     */
    public List<ApprovalStep> getSteps() {
        return Collections.unmodifiableList(steps);
    }

    public OffsetDateTime getCreatedAt() {
        return createdAt;
    }

    public OffsetDateTime getUpdatedAt() {
        return updatedAt;
    }

    // -----------------------------------------------------------------------
    // Builder
    // -----------------------------------------------------------------------

    public static Builder builder(DomainEventPublisher publisher) {
        return new Builder(publisher);
    }

    public static final class Builder {
        private final List<UUID> approverChain = new ArrayList<>();
        private final DomainEventPublisher eventPublisher;

        private UUID orderId;
        private UUID initiatorId;

        private Builder(DomainEventPublisher eventPublisher) {
            this.eventPublisher = Objects.requireNonNull(eventPublisher);
        }

        public Builder orderId(UUID orderId) {
            this.orderId = orderId;
            return this;
        }

        public Builder initiator(UUID initiator) {
            this.initiatorId = initiator;
            return this;
        }

        public Builder addApprover(UUID userId) {
            this.approverChain.add(userId);
            return this;
        }

        public ApprovalWorkflow build() {
            return new ApprovalWorkflow(this);
        }
    }

    // -----------------------------------------------------------------------
    // Nested types
    // -----------------------------------------------------------------------

    /**
     * Life-cycle states of the workflow.
     */
    public enum Status {
        PENDING,
        COMPLETED,
        REJECTED,
        CANCELLED;

        boolean isTransitionAllowed(Status target) {
            return switch (this) {
                case PENDING -> target == COMPLETED || target == REJECTED || target == CANCELLED;
                default -> false;
            };
        }

        boolean isTerminal() {
            return this != PENDING;
        }
    }

    /**
     * Single approval step inside the workflow.
     */
    @Embeddable
    public static class ApprovalStep implements Serializable {

        @Serial
        private static final long serialVersionUID = 5509635088326698923L;

        @Column(name = "approver_id", nullable = false)
        private UUID approverId;

        @Enumerated(EnumType.STRING)
        @Column(name = "step_status", nullable = false)
        private StepStatus status = StepStatus.PENDING;

        @Column(name = "acted_at")
        private OffsetDateTime actedAt;

        @Column(name = "comments", length = 1024)
        private String comments;

        /**
         * JPA constructor.
         */
        protected ApprovalStep() {}

        ApprovalStep(UUID approverId) {
            this(approverId, null);
        }

        ApprovalStep(UUID approverId, String note) {
            this.approverId = Objects.requireNonNull(approverId);
            this.comments = note;
        }

        void approve(UUID actor, String note) {
            verifyPendingAndActor(actor);
            this.status  = StepStatus.APPROVED;
            this.actedAt = OffsetDateTime.now();
            this.comments = note;
        }

        void reject(UUID actor, String note) {
            verifyPendingAndActor(actor);
            this.status  = StepStatus.REJECTED;
            this.actedAt = OffsetDateTime.now();
            this.comments = note;
        }

        private void verifyPendingAndActor(UUID actor) {
            if (status != StepStatus.PENDING) {
                throw new WorkflowException("Step is already " + status);
            }
            if (!Objects.equals(actor, approverId)) {
                throw new WorkflowException("Actor " + actor + " is not authorized for this step.");
            }
        }

        public UUID getApproverId() {
            return approverId;
        }

        public StepStatus getStatus() {
            return status;
        }

        public Optional<OffsetDateTime> getActedAt() {
            return Optional.ofNullable(actedAt);
        }

        public Optional<String> getComments() {
            return Optional.ofNullable(comments);
        }

        public enum StepStatus {
            PENDING,
            APPROVED,
            REJECTED
        }
    }

    // -----------------------------------------------------------------------
    // Domain events
    // -----------------------------------------------------------------------

    public interface DomainEvent extends Serializable {}

    public record WorkflowCreated(UUID workflowId,
                                  UUID orderId,
                                  UUID initiatorId) implements DomainEvent {}

    // -----------------------------------------------------------------------
    // Event publisher port
    // -----------------------------------------------------------------------

    /**
     * Simple port for publishing domain events.  Real implementations will be
     * provided by the application layer (e.g. Spring’s {@code ApplicationEventPublisher}).
     */
    public interface DomainEventPublisher {
        void publish(DomainEvent event);
    }

    // -----------------------------------------------------------------------
    // Exception type
    // -----------------------------------------------------------------------

    public static class WorkflowException extends RuntimeException {
        @Serial private static final long serialVersionUID = 7474715633722021433L;
        public WorkflowException(String message) { super(message); }
    }
}