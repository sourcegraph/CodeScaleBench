#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The optimal solution involves capturing player inputs for replay, as it's the most efficient and scalable approach for a deterministic engine like this.

**REPLAY_SYSTEM_DESIGN.md**

### 1. Overview
This document proposes a replay system for LedgerQuest by capturing the sequence of player commands for each game tick. This command stream will be stored in Amazon S3. A new Replay Service will provide clients with this command stream, allowing them to reconstruct the game session locally by feeding the commands into the deterministic game engine.

### 2. Data Capture Strategy
-   **Capture Point**: The ideal capture point is immediately after the `InputProcessor` state in the `game_loop_statemachine.asl.json`. The corresponding service logic is in `ledgerquest/services/game_loop/input_processor.py`.
-   **Data to Capture**: We will capture the finalized, validated queue of commands for each game tick. This is the minimal data required to reconstruct the game state if the engine is deterministic.
-   **Justification**: Capturing commands instead of full state snapshots drastically reduces storage requirements (kilobytes vs. megabytes per tick). While it relies on engine determinism, this is a standard assumption for replay systems. Hooking into the Step Function ensures the capture is an integral, reliable part of the game loop.

### 3. Data Storage and Management
-   **Storage Service**: Amazon S3 is the best choice due to its low cost for long-term storage, high durability, and scalability.
-   **Data Structure**: For each game session (identified by a `session_id`), a single compressed file (e.g., `session_id.json.gz`) will be created in an S3 bucket. This file will contain an ordered list of objects, where each object represents a tick and contains the command queue for that tick.
    ```json
    // Example: session_123.json.gz
    {
      "version": "1.0.0",
      "initial_state_ref": "s3://.../initial_state.json",
      "ticks": [
        { "tick": 1, "commands": [{"player_id": "p1", "action": "move", "params": [10, 5]}] },
        { "tick": 2, "commands": [] },
        { "tick": 3, "commands": [{"player_id": "p1", "action": "fire"}] }
      ]
    }
    ```

### 4. Replay Playback Mechanism
-   **Architecture**: A new serverless service, `ReplayService`, will be created using API Gateway and AWS Lambda.
-   **API Endpoints**:
    -   `GET /replays/{session_id}`: A Lambda function will fetch the corresponding replay file from S3, decompress it, and return it to the client.
-   **Playback Logic**: The client (or a local simulation) will initialize the game engine with the initial state. It will then iterate through the `ticks` array from the replay file, feeding the `commands` for each tick into the engine's input processing system and running the engine simulation for one tick. This will perfectly reconstruct the game session.

### 5. Architectural Impact and Risks
-   **Performance**: A new step will be added to the Step Function to write the command data to S3. To minimize latency impact on the critical path, this should be implemented as a 'fire-and-forget' task or by invoking a separate Lambda asynchronously.
-   **Cost**: The primary cost will be S3 storage and data transfer, plus Lambda invocations for capture and retrieval. This design is highly cost-effective compared to state-snapshotting.
-   **Risks**:
    -   **Determinism Bugs**: If any part of the engine (e.g., physics, AI) is non-deterministic, replays will desynchronize. This requires rigorous testing.
    -   **Engine Versioning**: A change to the game logic in a future patch may render old replays incompatible. The replay data format must include an engine version number (`"version": "1.0.0"`) to allow clients to handle this gracefully (e.g., by refusing to play an incompatible replay).
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
