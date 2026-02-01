#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
{
  "data_flow_analysis": "The minting flow is: `wallet_proxy` -> `gallery_gateway` (API request) -> `ledger_core` (on-chain transaction submission) -> `consensus_manager` (block finalization) -> Kafka event (`TransactionConfirmed`) -> `mint_factory` (event consumption, artifact generation via `recipe_composer` and `artifact_factory`) -> Kafka event (`ArtifactCreated`) -> `gallery_gateway` (`query_service` consumes event and updates local state).",
  "bottleneck_identification": "The primary architectural bottleneck is the serial processing of each mint request as an individual, on-chain transaction that must be finalized by the `ledger_core`'s consensus mechanism. This creates a low-throughput choke point, as the system's minting rate is rigidly tied to the blockchain's transaction-per-second (TPS) limit. A secondary bottleneck is the synchronous, computationally expensive art generation within the `mint_factory`'s event handler, which can cause back-pressure on the Kafka topic.",
  "proposed_solution": "Implement a Layer-2-style batching mechanism for minting.\n1. **Introduce a Minting Intent Queue**: The `gallery_gateway` will no longer submit transactions directly to the ledger. Instead, it will publish a lightweight 'MintIntent' message to a dedicated, high-throughput Kafka topic.\n2. **Create a Batch Aggregator**: A new component, either within `ledger_core` or as a separate microservice, will consume from the 'MintIntent' queue. It will collect multiple intents into a 'batch', compute a Merkle root of the batch, and submit a single `BatchCommit` transaction to the `ledger_core`. The full batch data can be stored off-chain (e.g., on IPFS).\n3. **Modify Downstream Consumers**: The `mint_factory` will be updated to listen for a `BatchConfirmed` event from the ledger. Upon receiving it, it will fetch the full batch data and can process the artifact generation for all items in the batch, potentially in parallel using a worker pool. This decouples the slow generation process from the main event loop.",
  "key_files_for_modification": [
    {
      "file": "HoloCanvas/services/gallery_gateway/src/api_handler.c",
      "reason": "Change logic from submitting a transaction to `ledger_core` to publishing a `MintIntent` message to the new Kafka topic."
    },
    {
      "file": "HoloCanvas/services/ledger_core/src/transaction_processor.c",
      "reason": "Needs to be modified to recognize and process the new `BatchCommit` transaction type, validating the Merkle root against the state."
    },
    {
      "file": "HoloCanvas/services/ledger_core/src/batch_aggregator.c",
      "reason": "A new file/component responsible for consuming from the `MintIntent` queue, creating batches, and submitting the `BatchCommit` transaction."
    },
    {
      "file": "HoloCanvas/services/mint_factory/src/event_handler.c",
      "reason": "Change logic to consume `BatchConfirmed` events instead of individual `TransactionConfirmed` events, and to dispatch batch processing work."
    },
    {
      "file": "HoloCanvas/shared/protocol/holocanvas.proto",
      "reason": "Define new message types for `MintIntent` and `BatchCommit`."
    },
    {
      "file": "HoloCanvas/ARCHITECTURE.md",
      "reason": "Document the new batch-minting architecture and data flow."
    }
  ]
}
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
