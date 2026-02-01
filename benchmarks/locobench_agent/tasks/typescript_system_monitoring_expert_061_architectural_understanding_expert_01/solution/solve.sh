#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The agent is expected to identify the following sequence and architectural pattern. The exact description of each module's role may vary, but it should capture the core function.

**Core Architectural Pattern:** The system uses an **Event-Driven (Publish/Subscribe)** architecture to decouple its components. A central event bus is likely defined or configured in `src/config.ts` and used throughout the application.

**Module-by-Module Data Flow:**

1.  **Configuration Ingestion & Validation:**
    -   `src/module_49.ts`: **API Handler.** Receives raw configuration data from an external source (e.g., REST API). Performs initial sanitization and publishes a `CONFIG_RECEIVED` event.
    -   `src/module_20.ts`: **Validation Service.** Subscribes to `CONFIG_RECEIVED`. It validates the configuration data against a schema and business logic. On success, it publishes a `CONFIG_VALIDATED` event.

2.  **Configuration Persistence & Caching:**
    -   `src/module_63.ts`: **Persistence Manager.** Subscribes to `CONFIG_VALIDATED`. It is responsible for writing the validated alert rule to the primary database, interacting with lower-level storage abstractions.
    -   `src/module_1.ts`: **Configuration Cache.** Also subscribes to `CONFIG_VALIDATED`. It updates a high-performance, in-memory cache of active alerting rules to be used by the evaluation engine.

3.  **Metric Processing & Alert Evaluation:**
    -   `src/module_5.ts`: **Metric Ingestor.** Receives raw performance metrics from monitored systems and publishes a `METRIC_RECEIVED` event.
    -   `src/module_10.ts`: **Alerting Engine.** Subscribes to `METRIC_RECEIVED`. When a metric arrives, this module fetches the relevant rules from the Configuration Cache (`module_1`), evaluates the metric against the rules, and publishes an `ALERT_TRIGGERED` event if a threshold is breached.

4.  **Notification Dispatch:**
    -   `src/module_45.ts`: **Notification Dispatcher.** Subscribes to `ALERT_TRIGGERED`. This module acts as a router, determining which channel(s) (e.g., email, Slack) the alert should be sent to based on the rule's configuration.
    -   `src/module_29.ts` / `src/module_66.ts`: **Notification Handlers.** These are concrete implementation modules called by the Dispatcher to send the alert over a specific channel (e.g., `module_29` for a Slack integration, `module_66` for email). The agent only needs to identify one of these as the final step.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
