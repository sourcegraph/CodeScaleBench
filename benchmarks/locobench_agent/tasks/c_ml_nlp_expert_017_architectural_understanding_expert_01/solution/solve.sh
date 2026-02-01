#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
{
  "component_mapping": {
    "Model": "Contains the entire ML domain logic. Key components: `src/model` directory, including `ml_pipeline/` (training, evaluation), `ml_models/` (model implementations), `feature_store/`, and `preprocessing/`.",
    "View": "Responsible for presenting data and system status. Key components: `src/view` directory, primarily `dashboard_server.c` which serves monitoring data, and `src/common/ll_logger.c` which outputs logs that can be considered a form of view.",
    "Controller": "The core orchestration and decision-making engine. Key components: `src/controller` directory, including `orchestrator.c` (the main controller), `pipeline/` (managing pipeline stages), `monitoring/` (detecting events), and `scheduler/` (executing tasks)."
  },
  "workflow_trace": "1. `drift_detector.c` detects drift and notifies its parent `model_monitor.c`. 2. `model_monitor.c`, acting as an observable subject, uses the observer pattern (`observer.h`) to send a notification. 3. `orchestrator.c`, registered as an observer, receives the drift notification. 4. `orchestrator.c` invokes logic in `retraining_trigger.c` to evaluate the drift against predefined thresholds. 5. If retraining is confirmed, `orchestrator.c` calls `pipeline_manager.c` to create a new training pipeline. 6. `pipeline_manager.c` defines the stages (`ingestion`, `training`, `deployment`) and uses `job_factory.c` to package this pipeline into a runnable job. 7. The job is submitted to `task_scheduler.c`, which queues it for execution.",
  "architectural_critique": {
    "benefits": [
      "**Separation of Concerns:** Isolates complex ML logic (Model) from orchestration (Controller) and reporting (View).",
      "**Modularity:** New models (`hybrid_model.c`) or monitoring techniques can be added to the Model layer with minimal changes to the Controller."
    ],
    "drawbacks": [
      "**Pattern Mismatch:** MVC is for UI event loops, not for long-running, asynchronous backend tasks. This leads to a 'leaky abstraction'.",
      "**Controller Bloat:** The Controller layer becomes overly complex, managing state, scheduling, and error handling for all pipeline operations, risking it becoming a 'God Object'.",
      "**Inefficient Communication:** The interaction between the long-running Model (a training job) and the Controller is not a simple request/response. In C, this requires complex mechanisms like callbacks, observer patterns, or IPC, which can be more cumbersome than patterns designed for data pipelines (e.g., Pipes and Filters)."
    ]
  }
}
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
