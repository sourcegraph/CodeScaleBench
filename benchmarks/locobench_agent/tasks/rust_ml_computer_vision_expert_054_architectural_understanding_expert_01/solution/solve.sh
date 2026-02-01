#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
{
  "notes": "This ground truth represents a plausible architecture. The agent's answer should be evaluated on its ability to identify a similarly structured, internally consistent architecture, even if the exact module numbers differ.",
  "core_components": [
    "src/module_30.txt: Likely defines the main `Run` and `Experiment` structs and the primary service trait for tracking.",
    "src/module_9.txt: Contains the implementation for logging and retrieving metrics and parameters.",
    "src/module_38.txt: Handles artifact storage logic, linking file paths or object storage URIs to a specific run."
  ],
  "dependency_analysis": {
    "internal_dependencies": [
      "src/module_6.txt: A generic database connection pool and query builder used by all components that persist data.",
      "src/module_2.txt: Defines shared data types used across the application, like `Timestamp`, `Status`, and custom `Error` types.",
      "src/config.txt: Provides database credentials, artifact storage locations, and other runtime configurations."
    ],
    "external_consumers": [
      "src/module_16.txt: The `model_training` module, which calls the tracking service to create a new run at the start of training and logs epoch-level metrics (loss, accuracy).",
      "src/module_34.txt: The `hyperparameter_tuning` module, which creates a parent run for the tuning job and a nested child run for each trial, logging the parameters and final validation score for each.",
      "src/module_77.txt: The `model_monitoring` service, which periodically logs production performance metrics (e.g., inference latency, prediction drift) to a dedicated experiment."
    ]
  },
  "proposed_api": [
    {
      "endpoint": "POST /api/v1/runs",
      "description": "Create a new run. Takes an `experiment_name` and returns a `run_id`.",
      "payload": "{ \"experiment_name\": \"string\", \"tags\": { \"key\": \"value\" } }"
    },
    {
      "endpoint": "POST /api/v1/runs/{run_id}/metrics",
      "description": "Log a batch of metrics for a given run.",
      "payload": "{ \"metrics\": [{ \"key\": \"loss\", \"value\": 0.123, \"step\": 100 }] }"
    },
    {
      "endpoint": "POST /api/v1/runs/{run_id}/params",
      "description": "Log a batch of parameters for a given run.",
      "payload": "{ \"params\": [{ \"key\": \"learning_rate\", \"value\": \"0.001\" }] }"
    },
    {
      "endpoint": "GET /api/v1/runs/{run_id}",
      "description": "Get all data for a specific run, including its metrics, params, and artifacts."
    },
    {
      "endpoint": "PATCH /api/v1/runs/{run_id}",
      "description": "Update a run's status (e.g., to 'FINISHED' or 'FAILED').",
      "payload": "{ \"status\": \"FINISHED\" }"
    }
  ],
  "refactoring_plan": [
    {
      "module": "src/module_16.txt",
      "change": "Replace direct calls to the internal tracking service (e.g., `tracking_service.log_metric(...)`) with HTTP client calls to the new microservice endpoints (e.g., `POST /api/v1/runs/{run_id}/metrics`)."
    },
    {
      "module": "src/module_34.txt",
      "change": "Modify the tuning loop to create runs via the API. This will likely involve more significant changes to handle the state of each trial asynchronously."
    },
    {
      "module": "src/module_77.txt",
      "change": "Update the monitoring agent to push metrics to the new API endpoint instead of calling the internal Rust functions."
    }
  ]
}
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
