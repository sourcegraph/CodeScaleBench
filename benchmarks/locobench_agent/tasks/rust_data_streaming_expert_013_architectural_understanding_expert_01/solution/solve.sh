#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
{
  "pipeline_map": {
    "Ingestion": "`module_18.txt`, `module_79.txt` - Responsible for connecting to external APIs and receiving raw data.",
    "Normalization & Quality Checks": "`module_30.txt`, `module_67.txt` - Responsible for parsing raw data, validating schema, cleaning text, and creating a standardized `NormalizedChirp` struct.",
    "Sentiment Analysis": "`module_41.txt` - A CPU-intensive stage that takes `NormalizedChirp` objects, runs them through an analysis model, and produces an `EnrichedChirp` with a sentiment score. This is implemented as a fixed-size worker pool.",
    "Orchestration": "`module_22.txt` - Initializes all components, wires them together, and manages the lifecycle of the various tasks.",
    "Storage Sink": "`module_74.txt` - Batches `EnrichedChirp` objects and writes them to the data lake (abstracted S3 client)."
  },
  "bottleneck_coupling": "Data is passed from the normalization stage (`module_30`) to the sentiment analysis worker pool (`module_41`) via a `tokio::mpsc::channel`. This is an in-memory, bounded queue. If the sentiment analysis workers are slow and cannot consume messages fast enough, the channel buffer will fill up. When full, the `send` operation in the normalization stage will block asynchronously (`await`), creating backpressure that propagates backward and stalls the entire ingestion pipeline.",
  "architectural_solution": "Introduce a durable, external message queue (like Apache Kafka, AWS SQS, or Redis Streams) to act as a buffer between the normalization and sentiment analysis stages. The architecture would change from a linear pipeline to a producer-consumer model.",
  "justification": "1.  **Scalability:** The normalization service (Producer) and the sentiment analysis service (Consumer) can be scaled independently. If sentiment analysis is slow, we can add more consumer instances without affecting the ingestion rate. \n2.  **Resilience:** The message queue acts as a durable buffer. If the sentiment analysis service fails, messages are not lost; they remain in the queue to be processed once the service recovers. \n3.  **Backpressure Management:** The ingestion pipeline is no longer blocked by the slow downstream service. It can publish messages to the queue at its maximum rate. The queue absorbs the load, effectively handling the backpressure and preventing it from impacting ingestion.",
  "affected_components": [
    {
      "module": "`module_30.txt` (Normalization)",
      "change": "Remove the logic that sends data to the `tokio::mpsc::channel`. Replace it with a message queue client (e.g., a Kafka producer) to serialize the `NormalizedChirp` and send it to a specific topic."
    },
    {
      "module": "`module_41.txt` (Sentiment Analysis)",
      "change": "Remove the logic that receives data from the `tokio::mpsc::channel`. Replace it with a message queue client (e.g., a Kafka consumer) to receive messages from the topic, deserialize them, and then perform the analysis."
    },
    {
      "module": "`module_22.txt` (Orchestration)",
      "change": "The orchestration logic needs to be updated. Instead of creating a channel and linking the two stages directly, it would now be responsible for initializing the producer service and the consumer service as separate, potentially independently deployable, tasks."
    },
    {
      "module": "`src/config.txt`",
      "change": "Add new configuration parameters for the message queue, such as broker addresses, topic names, and consumer group IDs."
    }
  ]
}
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
