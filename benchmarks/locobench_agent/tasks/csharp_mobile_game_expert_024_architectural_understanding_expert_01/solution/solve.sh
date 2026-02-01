#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
{
  "analysis_of_conflict": "The core conflict is between the immediate, transactional nature of 'Hardcore Mode' and the asynchronous, resilient nature of the offline-first approach detailed in `ADR-003-Offline-Sync-Strategy.md`. The current architecture, visible in `SyncPlayerActionsCommand.cs`, is designed to batch local changes and send them to the server, which is fundamentally different from the required real-time, per-action synchronization.",
  "proposed_architectural_pattern": {
    "pattern": "Strategy Pattern",
    "justification": "The Strategy pattern is ideal because it allows the synchronization algorithm to be selected at runtime without coupling the command handlers (the clients) to the specific implementation details of how syncing is performed. It cleanly separates the 'what' (e.g., create a company) from the 'how' (sync it immediately vs. queue it). This is highly scalable and adheres to the Open/Closed Principle, as new sync modes could be added in the future without modifying the command handlers."
  },
  "component_placement": {
    "new_files": [
      {
        "path": "TycoonVerse/src/TycoonVerse.Application/Interfaces/Strategies/IActionSyncStrategy.cs",
        "description": "Defines the common interface for all synchronization strategies."
      },
      {
        "path": "TycoonVerse/src/TycoonVerse.Application/Strategies/OfflineQueuingStrategy.cs",
        "description": "The concrete implementation that encapsulates the existing logic of queuing actions locally."
      },
      {
        "path": "TycoonVerse/src/TycoonVerse.Infrastructure/Strategies/RealTimeSyncStrategy.cs",
        "description": "The concrete implementation for 'Hardcore Mode'. It belongs in Infrastructure because it will directly use Infrastructure components like `ApiClient.cs`."
      }
    ],
    "modified_files": [
      {
        "path": "TycoonVerse/src/TycoonVerse.Core/Entities/Player.cs",
        "change": "Add a new property, such as `public GameMode Mode { get; set; }`, to the Player entity."
      },
      {
        "path": "TycoonVerse/src/TycoonVerse.Application/Features/**/*.cs",
        "change": "All relevant command handlers (e.g., `CreateCompanyCommand`) will be modified to accept an `IActionSyncStrategy` via dependency injection and use it to process the action, replacing the direct queuing logic."
      },
      {
        "path": "TycoonVerse/src/TycoonVerse.Application/Common/ServiceLocator.cs",
        "change": "Or a new factory class. This component will be modified to include logic for resolving the correct `IActionSyncStrategy` implementation based on the current player's `GameMode`."
      }
    ]
  },
  "decision_logic": "The decision logic will be centralized in a factory or service resolution component, such as the `ServiceLocator` or a new `SyncStrategyFactory`. When a command handler is instantiated, this factory will inspect the currently authenticated player's `GameMode` property. Based on this value, it will inject either an instance of `OfflineQueuingStrategy` or `RealTimeSyncStrategy` into the command handler. The command handler itself remains agnostic to the decision, simply executing the `Sync()` method on the provided strategy interface."
}
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
