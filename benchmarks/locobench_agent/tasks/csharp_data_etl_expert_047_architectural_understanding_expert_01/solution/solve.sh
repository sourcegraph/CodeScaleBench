#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
{
  "current_flow_analysis": "The `TransformationWorker` class in the `PaletteStream.Transformer` service, after processing data, serializes the entire resulting DataFrame. It then constructs a `DataTransformedEvent` (defined in `src/Shared/PaletteStream.Shared.Events/DataEvents.cs`) and embeds this large serialized payload into the event. This event is published to the `palette-data-transformed` Kafka topic using the `KafkaProducer`. The `QualityCheckRunner` class in the `PaletteStream.Quality` service is a consumer of this topic. It receives the `DataTransformedEvent`, deserializes the large payload back into a DataFrame, and then proceeds with the quality checks.",
  "bottleneck_explanation": "Sending large payloads (1GB+) via Kafka is a bottleneck due to: \n1. **Message Size Limits:** Kafka has a configurable but practical limit on message size (`message.max.bytes`). Exceeding this causes failures.\n2. **Broker/Network Strain:** Pushing large messages consumes significant network bandwidth and puts heavy memory/IO pressure on the Kafka brokers, slowing down the entire event bus for all services.\n3. **Serialization/Deserialization Overhead:** The CPU and memory cost of serializing and deserializing gigabyte-scale objects in both the producer (`Transformer`) and consumer (`Quality`) services is substantial and adds significant latency.\n4. **Consumer Lag:** A consumer taking a long time to process one large message can cause consumer lag, delaying the processing of all subsequent messages in its partition.",
  "proposed_solution_claim_check": {
    "description": "Implement the Claim Check pattern.",
    "implementation_steps": [
      "The `Transformer` service, after processing, will upload the large DataFrame payload to a shared, high-throughput blob storage system (e.g., Azure Blob Storage, leveraging a similar pattern to the `DataLakeClient` in the `Loader` service).",
      "The `Transformer` service then generates the 'claim check'\u2014a URI or unique identifier pointing to the stored object in blob storage.",
      "A modified `DataTransformedEvent` is published to Kafka. This event is now lightweight and contains metadata and the 'claim check' URI instead of the full data payload.",
      "The `Quality` service consumes the lightweight event, extracts the 'claim check' URI, and uses a blob storage client to stream the data directly from the external store for processing."
    ]
  },
  "system_changes": [
    {
      "file": "src/Shared/PaletteStream.Shared.Events/DataEvents.cs",
      "change": "Modify the `DataTransformedEvent` class to remove the data payload property (e.g., `byte[] ProcessedData`) and add a `string DataLocationUri` property."
    },
    {
      "file": "src/Services/PaletteStream.Transformer/Core/TransformationWorker.cs",
      "change": "Inject a blob storage client. Modify the logic to upload the processed DataFrame to blob storage and publish the event with the returned URI."
    },
    {
      "file": "src/Services/PaletteStream.Quality/Core/QualityCheckRunner.cs",
      "change": "Inject a blob storage client. Modify the event handling logic to read the URI from the event and download the data from blob storage before running checks."
    },
    {
      "file": "src/Services/PaletteStream.Transformer/appsettings.json",
      "change": "Add a new configuration section for the blob storage connection string and container name."
    },
    {
      "file": "src/Services/PaletteStream.Quality/appsettings.json",
      "change": "Add a new configuration section for the blob storage connection string and container name."
    },
    {
      "file": "src/Services/PaletteStream.Transformer/PaletteStream.Transformer.csproj",
      "change": "Add a package reference for the required blob storage SDK (e.g., Azure.Storage.Blobs)."
    },
    {
      "file": "src/Services/PaletteStream.Quality/PaletteStream.Quality.csproj",
      "change": "Add a package reference for the required blob storage SDK."
    }
  ],
  "trade_off_analysis": {
    "pros": [
      "**Performance:** Drastically reduces latency and improves throughput for large datasets.",
      "**Scalability:** Reduces load on the Kafka cluster, allowing the event bus to scale and remain performant for its primary purpose: event notification.",
      "**Stability:** Avoids message size limit errors and reduces the risk of service memory exhaustion."
    ],
    "cons": [
      "**Increased Complexity:** Introduces a new component (blob storage) into the data flow between these two services.",
      "**New Dependency:** Both services now depend on the availability and performance of the blob storage system.",
      "**Data Lifecycle Management:** A mechanism is needed to clean up the temporary data from blob storage after it has been processed (or if processing fails) to prevent orphaned data and control costs. This could involve a separate cleanup job or TTL policies on the storage.",
      "**Transactional Complexity:** The operation is no longer a single 'publish' step. It's now a two-phase process (upload, then publish). Failure after the upload but before the publish can lead to orphaned data."
    ]
  }
}
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
