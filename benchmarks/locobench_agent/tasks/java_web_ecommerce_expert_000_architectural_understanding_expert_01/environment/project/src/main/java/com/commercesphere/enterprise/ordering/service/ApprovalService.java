package com.commercesphere.enterprise.ordering.service;

import com.commercesphere.enterprise.common.events.DomainEventPublisher;
import com.commercesphere.enterprise.common.exceptions.EntityNotFoundException;
import com.commercesphere.enterprise.ordering.domain.model.*;
import com.commercesphere.enterprise.ordering.domain.repository.ApprovalRepository;
import com.commercesphere.enterprise.ordering.domain.repository.ApprovalRuleRepository;
import com.commercesphere.enterprise.ordering.domain.repository.OrderRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * Service responsible for executing the multi-level approval
 * workflow for {@link Order} entities.  The workflow is entirely
 * data-driven: which roles must approve, in which sequence, and
 * the monetary thresholds that trigger them are configured in
 * {@link ApprovalRule} entities and cached at runtime.
 *
 * This service is intentionally side-effect free except for:
 *  1. State transitions persisted through {@link ApprovalRepository}
 *  2. Domain events emitted through {@link DomainEventPublisher}
 *
 * All other read concerns (e.g. sending email notifications) are
 * performed by asynchronous event handlers listening to the emitted
 * {@code *Event} classes.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ApprovalService {

    private final ApprovalRepository approvalRepository;
    private final ApprovalRuleRepository ruleRepository;
    private final OrderRepository orderRepository;
    private final DomainEventPublisher eventPublisher;

    /**
     * Creates and persists an {@link Approval} for the given order.
     * If the order qualifies for auto-approval (no rules applicable
     * or all rules have a threshold higher than the order amount)
     * the order is transitioned to APPROVED immediately and an
     * {@link OrderApprovedEvent} is emitted.
     *
     * @param orderId   identifier of the order that requires approval
     * @param requester user requesting the approval
     * @return persisted Approval document
     */
    @Transactional
    public Approval submitForApproval(UUID orderId, User requester) {
        Order order = orderRepository.findById(orderId)
                .orElseThrow(() -> new EntityNotFoundException("Order not found: " + orderId));

        validateDraftOrder(order);

        List<ApprovalRule> matchingRules = ruleRepository.findMatchingRules(
                order.getCompanyId(),
                order.getCurrency(),
                order.getTotalNet());

        if (matchingRules.isEmpty()) {
            autoApprove(order, requester);
            return null; // no explicit approval object stored
        }

        Approval approval = Approval.builder()
                .approvalId(UUID.randomUUID())
                .orderId(order.getId())
                .companyId(order.getCompanyId())
                .status(ApprovalStatus.PENDING)
                .requestedBy(requester)
                .requestedAt(OffsetDateTime.now())
                .currentLevel(0)
                .rules(matchingRules)
                .build();

        Approval persisted = approvalRepository.save(approval);

        // fire-and-forget event; asynchronous listener sends notification e-mail
        eventPublisher.publish(new ApprovalRequestedEvent(persisted));

        log.info("Approval [{}] created for Order [{}] with {} rule(s)",
                 persisted.getApprovalId(), order.getId(), matchingRules.size());

        return persisted;
    }

    /**
     * Approves the current step of the approval and, if necessary,
     * escalates to the next level or completes the workflow.
     *
     * @param approvalId approval identifier
     * @param approver   user that performs the approval
     * @param comment    optional textual comment
     * @return updated approval object
     */
    @Transactional
    public Approval approve(UUID approvalId, User approver, String comment) {
        Approval approval = locateActiveApproval(approvalId);

        verifyAuthority(approval, approver);
        approval.recordDecision(approver, comment, Decision.APPROVE);

        // Either escalate to next level or finalize approval
        Optional<ApprovalRule> nextRule = approval.nextPendingRule();
        if (nextRule.isPresent()) {
            approval.advanceToNextLevel();
            eventPublisher.publish(new ApprovalEscalatedEvent(approval, nextRule.get()));
            log.info("Approval [{}] escalated to level {}", approvalId, approval.getCurrentLevel());
        } else {
            approval.markApproved();
            updateOrderStatus(approval.getOrderId(), OrderStatus.APPROVED);
            eventPublisher.publish(new ApprovalCompletedEvent(approval));
            log.info("Approval [{}] completed and Order [{}] approved",
                     approvalId, approval.getOrderId());
        }

        return approvalRepository.save(approval);
    }

    /**
     * Rejects the approval and rolls back the order to DRAFT
     * so that the requester can modify or cancel the order.
     */
    @Transactional
    public Approval reject(UUID approvalId, User approver, String comment) {
        Approval approval = locateActiveApproval(approvalId);
        verifyAuthority(approval, approver);

        approval.recordDecision(approver, comment, Decision.REJECT);
        approval.markRejected();

        updateOrderStatus(approval.getOrderId(), OrderStatus.REJECTED);
        eventPublisher.publish(new ApprovalRejectedEvent(approval));

        log.info("Approval [{}] rejected by [{}]", approvalId, approver.getUserId());
        return approvalRepository.save(approval);
    }

    /**
     * Cancels the current approval request.  Only the original
     * requester or an administrator may perform this action.
     */
    @Transactional
    public Approval cancel(UUID approvalId, User requester) {
        Approval approval = locateActiveApproval(approvalId);

        boolean isRequester = Objects.equals(
                approval.getRequestedBy().getUserId(), requester.getUserId());

        if (!isRequester && !requester.hasRole(Role.SYSTEM_ADMIN)) {
            throw new ApprovalException("User not authorized to cancel approval: " + requester.getUserId());
        }

        approval.markCancelled();
        updateOrderStatus(approval.getOrderId(), OrderStatus.DRAFT);

        eventPublisher.publish(new ApprovalCancelledEvent(approval));
        log.info("Approval [{}] cancelled by [{}]", approvalId, requester.getUserId());
        return approvalRepository.save(approval);
    }

    /**
     * Returns the current status of the approval linked to
     * the provided order.  Empty if the order never required
     * approval (auto-approved path).
     */
    @Transactional(readOnly = true)
    public Optional<ApprovalStatus> getStatusByOrder(UUID orderId) {
        return approvalRepository.findByOrderId(orderId)
                .map(Approval::getStatus);
    }

    // ----------------------------------------------------------------
    // Private helper methods
    // ----------------------------------------------------------------

    private void validateDraftOrder(Order order) {
        if (order.getStatus() != OrderStatus.DRAFT) {
            throw new ApprovalException(
                    "Order must be in DRAFT status before requesting approval. Current status: " + order.getStatus());
        }
    }

    private void autoApprove(Order order, User requester) {
        order.setStatus(OrderStatus.APPROVED);
        order.setApprovedBy(requester);
        order.setApprovedAt(OffsetDateTime.now());

        orderRepository.save(order);
        eventPublisher.publish(new OrderApprovedEvent(order));

        log.info("Order [{}] auto-approved (no matching approval rules)", order.getId());
    }

    private Approval locateActiveApproval(UUID approvalId) {
        Approval approval = approvalRepository.findById(approvalId)
                .orElseThrow(() -> new EntityNotFoundException("Approval not found: " + approvalId));

        if (!approval.isActive()) {
            throw new InvalidApprovalStateException(
                    "Approval " + approvalId + " is already " + approval.getStatus());
        }
        return approval;
    }

    private void verifyAuthority(Approval approval, User approver) {
        if (!approval.canBeProcessedBy(approver)) {
            throw new ApprovalException("User is not authorized to approve/reject at current level");
        }
    }

    private void updateOrderStatus(UUID orderId, OrderStatus newStatus) {
        try {
            orderRepository.updateStatus(orderId, newStatus);
        } catch (OptimisticLockingFailureException e) {
            // concurrency guard: a separate thread may have already updated the order
            throw new ApprovalException("Concurrent modification detected for Order " + orderId, e);
        }
    }
}