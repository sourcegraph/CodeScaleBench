#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The agent is expected to uncover the following architectural details:

*   **Data Flow Map:** The core pipeline consists of a chain of modules: `module_14` (Data Ingestor) -> `module_38` (Text Sanitizer & Normalizer) -> `module_46` (Named Entity Recognition) -> `module_50` (Feature Vectorizer) -> `module_60` (Model Serving Dispatcher).

*   **Communication Pattern:** The system uses a **tightly-coupled, pseudo-asynchronous chain of direct function calls**. Although `async/await` is used, `module_14` directly invokes a method on `module_38`, which in turn directly invokes a method on `module_46`, and so on. There is no message queue or event bus decoupling these stages, making the entire pipeline behave like a single, long-running synchronous operation from the perspective of a single data item.

*   **The Bottleneck:** The primary bottleneck is the interaction between `module_46` and `module_50`. `module_46`'s entity recognition process produces a large, complex object with nested arrays and metadata. To pass this data to `module_50`, the code performs a `JSON.stringify()` on this large object. `module_50`'s first step is to immediately call `JSON.parse()` on the received string. These `JSON.stringify/parse` operations are **synchronous and CPU-intensive**. Under high load, the Node.js event loop becomes blocked by these operations, preventing it from handling other incoming requests and causing a system-wide latency pile-up. The tight coupling ensures that `module_50` cannot start its work until `module_46` has fully completed its synchronous serialization, creating a major chokepoint.

*   **Refactoring Plan:** The correct proposal is to **decouple the pipeline stages with a message queue** (e.g., RabbitMQ, Kafka, or Redis Streams, which may be listed as a dependency in `package.json`).
    *   **New Pattern:** A Producer/Consumer or Pub/Sub pattern.
    *   **Modules to Change:** `module_14`, `module_38`, `module_46`, `module_50`, and `module_60` must all be refactored.
    *   **New Interaction:** `module_14` (the producer) would publish raw data to a `raw_posts` queue/topic. `module_38` would subscribe to `raw_posts`, process the data, and publish its result to a `sanitized_posts` topic. `module_46` would subscribe to that, and so on. This allows each stage to scale independently and removes the synchronous blocking call chain. It also potentially obviates the need for the costly stringify/parse step if the message broker's protocol is more efficient for passing structured data.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
