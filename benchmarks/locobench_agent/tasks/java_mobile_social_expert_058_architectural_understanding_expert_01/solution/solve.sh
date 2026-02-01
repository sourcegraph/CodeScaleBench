#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
Here are the key insights the agent should uncover:

1.  **High-Level Flow:**
    *   **Trigger:** The `SyncWorker` is likely enqueued by `WorkManager` based on constraints like network availability or on a periodic basis (e.g., every few hours).
    *   **Fetch Local Changes:** `SyncWorker` starts and calls a method on `JournalRepository`, like `getUnsyncedEntries()`, to get all local journal entries marked as dirty or new.
    *   **API Call:** For each unsynced entry, the `JournalRepository` makes an API call (e.g., POST for new entries, PUT for updated ones) to the server.
    *   **Conflict Detection:** If the API returns a success code (e.g., 200 OK), the local entry is marked as synced. If it returns a conflict error (e.g., 409 Conflict), this indicates the server has a newer version of the entry.
    *   **Conflict Resolution:** The repository catches the conflict and passes the local and a newly fetched server version of the entry to the `SyncConflictResolver`.
    *   **Resolution Strategy:** `SyncConflictResolver` implements a strategy. For example, it might compare timestamps. If the server's version is newer ('last-write-wins'), it might overwrite the local data. If it cannot auto-resolve, it might mark the local entry with a 'conflict' state for the user to resolve manually in the UI.
    *   **Completion:** The `SyncWorker` returns `Result.success()` if the process completes, or `Result.retry()`/`Result.failure()` if systemic issues occur.

2.  **Component Responsibilities:**
    *   `SyncWorker`: An Android `WorkManager` implementation responsible for orchestrating the entire background sync process. It's the entry point and manages the lifecycle of the background task.
    *   `JournalRepository`: Implements the Repository Pattern. It abstracts the data sources, providing a single source of truth for the `SyncWorker`. It contains the business logic to fetch from the local DB, push to the remote API, and handle API responses.
    *   `SyncConflictResolver`: Implements the Strategy Pattern for conflict resolution. It's a specialized component whose only job is to compare two versions of a `JournalEntry` and decide on a resolution. The current strategy appears to be a hybrid: it uses a 'server-authoritative' or 'last-write-wins' approach based on a `lastModified` timestamp, but with a fallback to flag the entry for manual user intervention if automatic resolution is too risky (e.g., significant text changes).
    *   `DatabaseModule` & `NetworkModule`: These Dagger modules provide singleton instances of the `AppDatabase` (and its DAOs) and the `ApiService` (Retrofit instance) respectively. This allows components like `JournalRepositoryImpl` to receive these dependencies via constructor injection, decoupling them from the specifics of how the database or network client are created and configured.

3.  **Architectural Patterns:**
    *   **Worker Pattern:** Using `WorkManager` for reliable, deferrable background execution.
    *   **Repository Pattern:** Decoupling data sources (local/remote) from the business logic.
    *   **Dependency Injection:** Used throughout to manage dependencies and promote loose coupling and testability.
    *   **Strategy Pattern:** `SyncConflictResolver` encapsulates different resolution algorithms, allowing the strategy to be changed without altering the repository that uses it.

4.  **Architectural Justification & Trade-offs:**
    *   **Benefits:** The primary benefit is a robust **offline-first user experience**. Users are not blocked by poor connectivity. The architecture ensures data consistency across devices and prevents data loss. It's highly scalable and maintainable due to the separation of concerns (sync orchestration, data access, and conflict logic are all in separate components).
    *   **Reasoning vs. Simpler Approach:** A 'fetch-on-load' strategy is simple but fails completely when offline. It also doesn't handle cases where the same user modifies data from two different devices (e.g., a phone and a tablet), which would lead to data overwrites and loss. This more complex design is necessary for a reliable, multi-platform experience.
    *   **Trade-offs:**
        *   **Complexity:** The logic is significantly more complex than a simple fetch, making it harder to debug and maintain.
        *   **Battery Consumption:** Poorly configured background jobs can lead to significant battery drain.
        *   **Data Immediacy:** Data is not real-time. There is a lag between a change being made on one device and it appearing on another, dependent on the sync interval.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
