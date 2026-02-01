#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The expected output is a detailed markdown document. Key insights the agent must demonstrate include:

*   **Centrality of `ccs_common` and `node_service`**: The most critical changes are to the shared `Nft` struct in `crates/ccs_common/src/nft.rs` and the state transition logic in `services/node_service/src/state_machine.rs`. Any valid plan must start here.
*   **State Representation**: A new data structure must be proposed for the state database (`ccs_db`) to track fractional owners and their shares, linking them back to the original NFT's ID.
*   **New Transaction Type**: The plan must specify a new transaction type (e.g., `Fractionalize { nft_id, fraction_count }`) and describe how the `state_machine` would process it atomically.
*   **Communication Protocol**: The plan must correctly identify gRPC as the primary inter-service communication method and propose new `.proto` definitions in `crates/ccs_proto/` and corresponding server/client implementations.
*   **Impact on Marketplace Logic**: The agent must recognize that selling fractions is different from selling a whole NFT. The logic in `marketplace_service/src/listing_manager.rs` and `auction_engine.rs` needs to be adapted to handle fungible fractions of a non-fungible asset.
*   **Flow Example (Purchase)**: A correct purchase flow would look like: `Client -> api_gateway (REST)` -> `api_gateway -> marketplace_service (gRPC)` -> `marketplace_service creates purchase transaction` -> `Transaction submitted to node_service mempool` -> `node_service consensus handler includes in block` -> `node_service state_machine updates ownership in state_db`.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
