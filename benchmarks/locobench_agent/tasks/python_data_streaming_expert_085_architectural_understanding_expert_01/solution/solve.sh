#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
### Ground Truth Analysis & Solution

**1. Component Identification:**

The primary monolithic component is **`module_30.py`**. 
- It contains the `MasterBatchOrchestrator` class, which has a `run_pipeline` method that sequentially handles fetching data, running validation checks, and triggering transformations.
- It directly imports and calls validation logic from **`module_17`** (`ValidationRuleEngine`) and transformation logic from **`module_8`** (`DataTransformer`) within its main execution loop. This tight, synchronous coupling makes it impossible to insert a real-time, record-by-record flow without a major rewrite.

**2. Target Architecture Proposal:**

An **event-driven architecture using a message queue** is the ideal solution. The monolithic `MasterBatchOrchestrator` will be decomposed into three distinct services:

-   **Ingestion Service:** Responsible solely for interfacing with data sources and publishing raw data to a `raw-data` topic on the message queue.
-   **Validation Service:** Subscribes to the `raw-data` topic, applies validation rules to each message, and publishes valid records to a `validated-data` topic and invalid records to a `dead-letter-queue`.
-   **Batch Processing Service:** Subscribes to the `validated-data` topic, performs windowing, aggregation, and batch transformations before writing to the final destination.

**3. Logic Mapping:**

-   **Ingestion Service:** Would reuse the data fetching logic from `module_30.py`, specifically methods like `_fetch_from_s3_source`. It would also contain the *new* logic for a Kafka consumer.
-   **Validation Service:** Would be built around the `ValidationRuleEngine` from **`module_17.py`**. The loop that iterates through rules inside `module_30.run_pipeline` would be the core logic of this new service.
-   **Batch Processing Service:** Would reuse the `DataTransformer` class from **`module_8.py`** and the batching/windowing logic from **`module_37.py`** (`TimeWindowAggregator`), which are currently invoked by `module_30`.

**4. Data Flow Explanation (Mermaid Diagram):**

```mermaid
sequenceDiagram
    participant S3 Source
    participant Kafka Source
    participant Ingestion Service
    participant Message Queue
    participant Validation Service
    participant Processing Service

    S3 Source->>+Ingestion Service: New file notification
    Ingestion Service->>+Message Queue: Publishes records to 'raw-data'
    deactivate Ingestion Service

    Kafka Source->>+Ingestion Service: Consumes real-time stream
    Ingestion Service->>+Message Queue: Publishes records to 'raw-data'
    deactivate Ingestion Service

    Message Queue-->>+Validation Service: Consumes from 'raw-data'
    Validation Service-->>Validation Service: Applies rules from module_17
    Validation Service-->>+Message Queue: Publishes to 'validated-data' or 'dlq'
    deactivate Validation Service

    Message Queue-->>+Processing Service: Consumes from 'validated-data'
    Processing Service-->>Processing Service: Applies transforms from module_8 & module_37
    Processing Service-->>Data Warehouse: Writes final batch
    deactivate Processing Service
```

**5. Configuration Impact Analysis:**

`src/config.py` would undergo a fundamental change. 
- The current monolithic `PIPELINE_CONFIG` dictionary, which defines linear stages, would be deprecated.
- It would be replaced by separate configuration sections for each new service: `INGESTION_SERVICE_CONFIG`, `VALIDATION_SERVICE_CONFIG`, etc.
- A new `MESSAGE_QUEUE_CONFIG` section would be added to define broker URLs, topic names (`raw-data`, `validated-data`), and consumer group IDs. This externalizes the data flow from the code to the configuration.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
