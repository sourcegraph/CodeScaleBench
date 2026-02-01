package com.sprintcart.application.service;

import com.sprintcart.domain.automation.*;
import com.sprintcart.domain.shared.DomainEventPublisher;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.lang.NonNull;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import javax.validation.Valid;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * Application‐level service that orchestrates CRUD and execution logic for
 * {@link AutomationWorkflow} aggregates. This class belongs to the
 * “Application Service” ring in the Hexagonal Architecture and only speaks
 * to the domain model through ports.
 *
 * Responsibilities:
 *  • Validate and persist workflows.
 *  • Map domain objects to read‐friendly DTOs for adapters.
 *  • Coordinate execution and publish domain events.
 *
 * This class deliberately keeps persistence and side‐effects outside of the
 * domain entities, adhering to Clean Architecture boundaries.
 */
@Service
@RequiredArgsConstructor
@Slf4j
@Transactional
public class AutomationService {

    private final AutomationRepository automationRepository;   // Outbound port
    private final AutomationEngine automationEngine;           // Domain service / engine
    private final DomainEventPublisher eventPublisher;         // Outbound port
    private final Clock clock;                                 // Injectable to ease testing

    /* ------------------------------------------------------------------
     *  WRITE OPERATIONS
     * ------------------------------------------------------------------ */

    /**
     * Creates a new automation workflow from the given command object.
     */
    public AutomationDto create(@NonNull @Valid CreateAutomationCommand command) {
        AutomationWorkflow workflow = AutomationWorkflow.builder()
                .automationId(AutomationId.of(UUID.randomUUID()))
                .name(command.getName())
                .description(command.getDescription())
                .condition(command.getCondition())
                .actions(command.getActions())
                .createdAt(Instant.now(clock))
                .enabled(true)
                .build();

        automationRepository.save(workflow);
        eventPublisher.publish(new AutomationEvents.Created(workflow.getAutomationId()));
        return toDto(workflow);
    }

    /**
     * Updates an existing workflow. In case of concurrent modifications an
     * {@link OptimisticLockingFailureException} will be propagated.
     */
    public AutomationDto update(@NonNull UUID automationUuid,
                                @NonNull @Valid UpdateAutomationCommand command) {
        AutomationWorkflow workflow = getOrThrow(automationUuid);

        workflow.rename(command.getName(), command.getDescription());
        workflow.rewire(command.getCondition(), command.getActions());

        automationRepository.save(workflow);
        eventPublisher.publish(new AutomationEvents.Updated(workflow.getAutomationId()));
        return toDto(workflow);
    }

    /**
     * Enables the given automation so that it will be considered during
     * scheduled evaluations.
     */
    public void enable(@NonNull UUID automationUuid) {
        AutomationWorkflow workflow = getOrThrow(automationUuid);
        if (workflow.enable()) {
            automationRepository.save(workflow);
            eventPublisher.publish(new AutomationEvents.Enabled(workflow.getAutomationId()));
        }
    }

    /**
     * Disables the given automation so that it will no longer be executed.
     */
    public void disable(@NonNull UUID automationUuid) {
        AutomationWorkflow workflow = getOrThrow(automationUuid);
        if (workflow.disable()) {
            automationRepository.save(workflow);
            eventPublisher.publish(new AutomationEvents.Disabled(workflow.getAutomationId()));
        }
    }

    /**
     * Deletes a workflow permanently.
     */
    public void delete(@NonNull UUID automationUuid) {
        AutomationWorkflow workflow = getOrThrow(automationUuid);
        automationRepository.delete(workflow);
        eventPublisher.publish(new AutomationEvents.Removed(workflow.getAutomationId()));
    }

    /* ------------------------------------------------------------------
     *  READ OPERATIONS
     * ------------------------------------------------------------------ */

    /**
     * Retrieves a single workflow as DTO.
     */
    @Transactional(readOnly = true)
    public AutomationDto findOne(@NonNull UUID automationUuid) {
        return toDto(getOrThrow(automationUuid));
    }

    /**
     * Returns a paginated list of workflows.
     */
    @Transactional(readOnly = true)
    public Page<AutomationDto> findAll(Pageable pageable) {
        return automationRepository.findAll(pageable)
                .map(this::toDto);
    }

    /* ------------------------------------------------------------------
     *  SCHEDULING / EXECUTION
     * ------------------------------------------------------------------ */

    /**
     * Periodically polls for due workflows and executes them.
     * <p>
     * NOTE: The fixed delay is kept intentionally small; back-pressure is
     * handled by the {@link AutomationEngine} which runs the heavy lifting
     * on a bounded worker pool.
     */
    @Scheduled(fixedDelayString = "${sprintcart.automation.poll-interval-ms:5000}")
    public void evaluateDueWorkflows() {
        Instant now = Instant.now(clock);
        List<AutomationWorkflow> due =
                automationRepository.findEnabledAndDue(now);

        if (due.isEmpty()) {
            return;
        }

        log.debug("Found {} due automation(s) to evaluate", due.size());

        for (AutomationWorkflow workflow : due) {
            try {
                automationEngine.evaluateAndExecute(workflow);
                workflow.markLastRun(now);
                eventPublisher.publish(new AutomationEvents.Executed(workflow.getAutomationId()));
            } catch (ConditionEvaluationException ex) {
                log.warn("Condition failed for automation={} – {}", workflow.getAutomationId(), ex.getMessage());
            } catch (ActionExecutionException ex) {
                log.error("Action execution failed for automation={} – {}", workflow.getAutomationId(), ex.getMessage(), ex);
            } finally {
                automationRepository.save(workflow); // Persist lastRun timestamp or error state
            }
        }
    }

    /* ------------------------------------------------------------------
     *  PRIVATE HELPERS
     * ------------------------------------------------------------------ */

    private AutomationWorkflow getOrThrow(UUID uuid) {
        return automationRepository
                .findById(AutomationId.of(uuid))
                .orElseThrow(() -> new AutomationNotFoundException(uuid));
    }

    /* DTO mapping – avoids leaking domain objects to adapters */
    private AutomationDto toDto(AutomationWorkflow workflow) {
        return AutomationDto.builder()
                .id(workflow.getAutomationId().value())
                .name(workflow.getName())
                .description(workflow.getDescription())
                .condition(workflow.getCondition().toHumanReadable())
                .actions(workflow.getActions().stream()
                        .map(Action::toHumanReadable)
                        .collect(Collectors.toList()))
                .enabled(workflow.isEnabled())
                .lastRunAt(workflow.getLastRunAt())
                .createdAt(workflow.getCreatedAt())
                .updatedAt(workflow.getUpdatedAt())
                .build();
    }

    /* ------------------------------------------------------------------
     *  COMMANDS, DTOs & EXCEPTIONS (inner classes for brevity)
     *  In production code these would live in dedicated packages.
     * ------------------------------------------------------------------ */

    @lombok.Value
    public static class CreateAutomationCommand {
        @NonNull String name;
        String description;
        @NonNull Condition condition;
        @NonNull List<Action> actions;
    }

    @lombok.Value
    public static class UpdateAutomationCommand {
        @NonNull String name;
        String description;
        @NonNull Condition condition;
        @NonNull List<Action> actions;
    }

    @lombok.Builder
    @lombok.Value
    public static class AutomationDto {
        UUID id;
        String name;
        String description;
        String condition;
        List<String> actions;
        boolean enabled;
        Instant lastRunAt;
        Instant createdAt;
        Instant updatedAt;
    }

    public static class AutomationNotFoundException extends RuntimeException {
        public AutomationNotFoundException(UUID id) {
            super("AutomationWorkflow with id " + id + " not found");
        }
    }
}