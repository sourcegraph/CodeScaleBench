#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
### Key Insights

1.  **Upgrade Mechanism:** The project uses the **UUPS (Universal Upgradeable Proxy Standard)**. This is evident from `ShowPassProxy.sol` which points to a logic implementation, and the presence of an `upgradeTo` function (or similar) managed by an admin or governance mechanism (`CarnivalGovernance.sol`). The `UPGRADEABILITY_GUIDE.md` document explicitly details this pattern.

2.  **Off-Chain Dependencies:**
    *   `packages/backend/src/infrastructure/adapters/blockchain/ethers.service.ts`: This service holds the primary dependency. It instantiates an `ethers.Contract` object using the `ShowPass` address and its ABI. Any change to the contract's functions (add, remove, modify signature) requires updating the ABI file used by this service and potentially the code that calls the functions.
    *   `packages/backend/src/infrastructure/adapters/blockchain/contract.mapper.ts`: This mapper translates data from contract events and function return values into the backend's domain entities. If the upgrade changes event signatures or data structures, this file must be updated to prevent data mapping errors.
    *   `packages/backend/src/application/observers/stage-event.observer.ts`: This observer listens for on-chain events. If the upgrade introduces new events or alters existing ones, this observer must be updated to handle them correctly.
    *   **Implicit Dependency:** The compiled ABI JSON file (e.g., `ShowPass.json`), which is a build artifact consumed by the backend services. This file is the source of truth for the contract interface.

3.  **Upgrade Sequence:**
    1.  Develop and thoroughly test the new `ShowPassV2.sol` implementation contract.
    2.  Deploy the new `ShowPassV2.sol` contract to the blockchain. This yields a new implementation address.
    3.  Prepare the backend for the switch: Deploy a new version of the backend services with the updated ABI and any necessary logic changes to a staging environment or as a 'dark' deployment. The new services should not be active yet.
    4.  Execute the upgrade transaction: Call the `upgradeTo(new_implementation_address)` function on the `ShowPassProxy` contract via a governance proposal or an admin key.
    5.  Immediately after the on-chain transaction is confirmed, switch traffic to the new backend instances that are aware of the new ABI. This minimizes the window of inconsistency.
    6.  Monitor all systems (backend logs, on-chain transaction monitoring) for errors.

4.  **Risks and Mitigations:**
    *   **Risk:** **Storage Layout Collision.** If the new implementation contract changes the order of state variables or introduces new ones incorrectly, it can corrupt the proxy's storage. 
        *   **Mitigation:** Use a linter/tool like `hardhat-upgrades` to validate storage layout compatibility between the old and new implementations during development. Follow best practices by only appending new state variables and never changing the order or type of existing ones.
    *   **Risk:** **Backend/Contract Inconsistency.** For a brief period after the `upgradeTo` call and before the backend services are updated, the backend might attempt to call the proxy using an old ABI, leading to failed transactions.
        *   **Mitigation:** Implement a 'maintenance mode' in the backend, activated just before the upgrade, that temporarily pauses all interactions with the `ShowPass` contract. Alternatively, use a blue-green deployment strategy for the backend, where the switch to the new services is timed to coincide exactly with the on-chain upgrade confirmation.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
