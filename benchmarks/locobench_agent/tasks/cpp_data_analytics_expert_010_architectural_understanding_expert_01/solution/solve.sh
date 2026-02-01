#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The core architectural flaw is the lack of explicit resource management and workload prioritization. All services compete in a single, shared resource domain, leading to the starvation of the latency-sensitive stream processing workload by the throughput-oriented batch workload.

**Key Insight:** The system needs a mechanism to partition resources. The most effective and architecturally sound solution is the introduction of dedicated, configurable thread pools for different workload types.

**Implementation Plan Outline:**
1.  **Configuration (`main_config.json.template`):**
    - Add a new section, `thread_pools`, to the configuration.
    - Define two pools: `realtime_critical` (e.g., 4 threads, high priority) and `batch_analytics` (e.g., 8 threads, normal priority).
2.  **Configuration Manager (`core/config_manager.h/cpp`):**
    - Add logic to parse the `thread_pools` configuration into a structured data model.
3.  **Service Manager (`services/service_manager.h/cpp`):**
    - In the constructor or an `init` method, create the thread pools based on the loaded configuration. Store them in a map (e.g., `std::map<std::string, std::unique_ptr<ThreadPool>>`).
    - Add a getter method like `getThreadPool(const std::string& name)`.
    - Modify the service creation logic. When creating `StreamProcessor`, pass it the `realtime_critical` pool. When creating `BatchProcessor`, pass it the `batch_analytics` pool.
4.  **Processor Components (`processing/stream_processor.h/cpp`, `processing/batch_processor.h/cpp`):**
    - Modify their constructors to accept a `ThreadPool&` or `std::shared_ptr<ThreadPool>`.
    - All asynchronous tasks within these components must be submitted to their assigned pool instead of a global or new pool.

This solution effectively isolates the workloads, ensuring the real-time path always has the resources it needs, directly addressing the latency problem without requiring a major rewrite of the business logic.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
