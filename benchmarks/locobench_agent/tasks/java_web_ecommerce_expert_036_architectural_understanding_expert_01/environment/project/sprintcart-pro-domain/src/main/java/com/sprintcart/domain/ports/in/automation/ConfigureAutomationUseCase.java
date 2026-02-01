package com.sprintcart.domain.ports.in.automation;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * Inbound Port (Hexagonal Architecture) for configuring task automations in
 * SprintCart Pro’s Automation Studio.
 *
 * The interface intentionally exposes only pure domain objects so that the
 * domain layer remains free of infrastructural concerns.  Implementations
 * belong in the application/service layer and may delegate persistence,
 * validation, and orchestration to outbound ports and domain services.
 *
 * Supported operations:
 *  • create – register a brand-new automation
 *  • update – mutate an existing automation’s definition
 *  • activate/deactivate – toggle runtime execution state
 *  • queries – fetch individual or bulk automation snapshots
 *
 * All methods are expected to be transactional (either by decorator or by the
 * implementing adapter) and to enforce comprehensive validation rules.
 */
public interface ConfigureAutomationUseCase {

    /* ----------------------------------------------------------------------
     * Command–Query methods
     * -------------------------------------------------------------------- */

    /**
     * Create a new automation based on the provided command.
     *
     * @param command validated command object
     * @return immutable snapshot of the newly created automation
     * @throws AutomationValidationException when business rules are violated
     */
    AutomationSnapshot create(CreateAutomationCommand command)
            throws AutomationValidationException;

    /**
     * Update an existing automation. Only fields present in the command will be
     * modified, enabling fine-grained PATCH-like semantics.
     *
     * @param command command containing deltas
     * @return updated automation snapshot
     * @throws AutomationNotFoundException    when the target automation does not exist
     * @throws AutomationValidationException  on domain rule violations (e.g. invalid CRON)
     */
    AutomationSnapshot update(UpdateAutomationCommand command)
            throws AutomationNotFoundException, AutomationValidationException;

    /**
     * Activate (enable) an automation. No-ops when the automation is already active.
     *
     * @param command activation instruction
     */
    void activate(ActivateAutomationCommand command)
            throws AutomationNotFoundException, AutomationAlreadyActiveException;

    /**
     * Deactivate (pause) an automation. No-ops when the automation is already inactive.
     *
     * @param command deactivation instruction
     */
    void deactivate(DeactivateAutomationCommand command)
            throws AutomationNotFoundException, AutomationAlreadyInactiveException;

    /**
     * Retrieve a single automation by its identifier.
     *
     * @param automationId unique ID (UUID v4)
     * @return snapshot wrapped in an Optional
     */
    Optional<AutomationSnapshot> findById(UUID automationId);

    /**
     * List all currently active automations.
     *
     * @return immutable list of snapshots
     */
    List<AutomationSnapshot> listActive();

    /* ----------------------------------------------------------------------
     * Command DTOs
     * -------------------------------------------------------------------- */

    /**
     * Command object for creating a brand-new automation configuration.
     * Instances are immutable and thus thread-safe.
     */
    final class CreateAutomationCommand {
        private final String name;
        private final String description;
        private final TriggerDefinition trigger;
        private final List<ActionDefinition> actions;
        private final Map<String, Object> metadata; // free-form user metadata

        public CreateAutomationCommand(
                String name,
                String description,
                TriggerDefinition trigger,
                List<ActionDefinition> actions,
                Map<String, Object> metadata) {

            this.name = name;
            this.description = description;
            this.trigger = trigger;
            this.actions = List.copyOf(actions);
            this.metadata = Map.copyOf(metadata);
        }

        public String getName() { return name; }
        public String getDescription() { return description; }
        public TriggerDefinition getTrigger() { return trigger; }
        public List<ActionDefinition> getActions() { return actions; }
        public Map<String, Object> getMetadata() { return metadata; }
    }

    /**
     * Command object for updating an existing automation.  Each field is wrapped
     * in Optional to indicate whether a value is intended to be mutated.
     */
    final class UpdateAutomationCommand {
        private final UUID automationId;
        private final Optional<String> name;
        private final Optional<String> description;
        private final Optional<TriggerDefinition> trigger;
        private final Optional<List<ActionDefinition>> actions;
        private final Optional<Map<String, Object>> metadata;

        public UpdateAutomationCommand(
                UUID automationId,
                Optional<String> name,
                Optional<String> description,
                Optional<TriggerDefinition> trigger,
                Optional<List<ActionDefinition>> actions,
                Optional<Map<String, Object>> metadata) {

            this.automationId = automationId;
            this.name = name;
            this.description = description;
            this.trigger = trigger;
            this.actions = actions.map(List::copyOf);
            this.metadata = metadata.map(Map::copyOf);
        }

        public UUID getAutomationId() { return automationId; }
        public Optional<String> getName() { return name; }
        public Optional<String> getDescription() { return description; }
        public Optional<TriggerDefinition> getTrigger() { return trigger; }
        public Optional<List<ActionDefinition>> getActions() { return actions; }
        public Optional<Map<String, Object>> getMetadata() { return metadata; }
    }

    /** Activates an automation at a given timestamp. */
    final class ActivateAutomationCommand {
        private final UUID automationId;
        private final Instant activatedAt;

        public ActivateAutomationCommand(UUID automationId, Instant activatedAt) {
            this.automationId = automationId;
            this.activatedAt = activatedAt;
        }

        public UUID getAutomationId() { return automationId; }
        public Instant getActivatedAt() { return activatedAt; }
    }

    /** Deactivates an automation at a given timestamp and stores a user-friendly reason. */
    final class DeactivateAutomationCommand {
        private final UUID automationId;
        private final Instant deactivatedAt;
        private final String reason; // e.g. "seasonal pause", "A/B test ended"

        public DeactivateAutomationCommand(UUID automationId, Instant deactivatedAt, String reason) {
            this.automationId = automationId;
            this.deactivatedAt = deactivatedAt;
            this.reason = reason;
        }

        public UUID getAutomationId() { return automationId; }
        public Instant getDeactivatedAt() { return deactivatedAt; }
        public String getReason() { return reason; }
    }

    /* ----------------------------------------------------------------------
     * Read-only DTOs (Snapshots)
     * -------------------------------------------------------------------- */

    /**
     * Immutable representation of a persisted automation record.  Returned by
     * query methods and treated as read-only outside the domain layer.
     */
    final class AutomationSnapshot {
        private final UUID id;
        private final String name;
        private final String description;
        private final TriggerDefinition trigger;
        private final List<ActionDefinition> actions;
        private final boolean active;
        private final Instant createdAt;
        private final Instant updatedAt;
        private final Map<String, Object> metadata;

        public AutomationSnapshot(
                UUID id,
                String name,
                String description,
                TriggerDefinition trigger,
                List<ActionDefinition> actions,
                boolean active,
                Instant createdAt,
                Instant updatedAt,
                Map<String, Object> metadata) {

            this.id = id;
            this.name = name;
            this.description = description;
            this.trigger = trigger;
            this.actions = List.copyOf(actions);
            this.active = active;
            this.createdAt = createdAt;
            this.updatedAt = updatedAt;
            this.metadata = Map.copyOf(metadata);
        }

        public UUID getId() { return id; }
        public String getName() { return name; }
        public String getDescription() { return description; }
        public TriggerDefinition getTrigger() { return trigger; }
        public List<ActionDefinition> getActions() { return actions; }
        public boolean isActive() { return active; }
        public Instant getCreatedAt() { return createdAt; }
        public Instant getUpdatedAt() { return updatedAt; }
        public Map<String, Object> getMetadata() { return metadata; }
    }

    /* ----------------------------------------------------------------------
     * Value Objects
     * -------------------------------------------------------------------- */

    /**
     * Domain value object describing a Trigger (WHEN).  It is deliberately simple –
     * complex parsing/evaluation is delegated to the automation engine.
     */
    final class TriggerDefinition {
        public enum Type { EVENT, SCHEDULE, CONDITIONAL }

        private final Type type;
        private final String expression; // e.g. event name, CRON string, DSL expression

        public TriggerDefinition(Type type, String expression) {
            this.type = type;
            this.expression = expression;
        }

        public Type getType() { return type; }
        public String getExpression() { return expression; }

        @Override
        public String toString() {
            return type + ":" + expression;
        }
    }

    /**
     * Domain value object describing an Action (THEN).
     */
    final class ActionDefinition {
        private final String actionName;               // e.g. "send_email"
        private final Map<String, Object> parameters;  // e.g. {template: "stock_low"}

        public ActionDefinition(String actionName, Map<String, Object> parameters) {
            this.actionName = actionName;
            this.parameters = Map.copyOf(parameters);
        }

        public String getActionName() { return actionName; }
        public Map<String, Object> getParameters() { return parameters; }
    }

    /* ----------------------------------------------------------------------
     * Domain-level Exceptions
     * -------------------------------------------------------------------- */

    /** Thrown when validation of an automation command fails. */
    class AutomationValidationException extends Exception {
        public AutomationValidationException(String message) { super(message); }
    }

    /** Thrown when an automation requested for update/delete is not found. */
    class AutomationNotFoundException extends Exception {
        public AutomationNotFoundException(UUID id) {
            super("Automation " + id + " not found.");
        }
    }

    /** Thrown when attempting to activate an automation that is already active. */
    class AutomationAlreadyActiveException extends Exception {
        public AutomationAlreadyActiveException(UUID id) {
            super("Automation " + id + " is already active.");
        }
    }

    /** Thrown when attempting to deactivate an automation that is already inactive. */
    class AutomationAlreadyInactiveException extends Exception {
        public AutomationAlreadyInactiveException(UUID id) {
            super("Automation " + id + " is already inactive.");
        }
    }
}