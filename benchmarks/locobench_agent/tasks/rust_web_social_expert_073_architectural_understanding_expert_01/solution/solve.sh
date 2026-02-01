#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The hidden architecture is a modular monolith implementing CQRS with a NATS message bus.

-   **Core Components:**
    -   `package.json` dependencies include `axum`, `tokio`, `sqlx`, `nats`, `serde`, `jsonwebtoken`.
    -   `src/config.txt` defines `NATS_URL`, `DATABASE_WRITE_URL`, `DATABASE_READ_URL`, and `JWT_SECRET`.
    -   **API Gateway:** `src/module_1.txt` contains the `axum::Router` setup. It receives HTTP requests and uses `module_15` for auth.
    -   **Authentication:** `src/module_15.txt` handles JWT validation and session logic.
    -   **Command Publishing:** The API Gateway (`module_1`) publishes commands (e.g., `CreatePostCommand`) to the NATS bus after a successful request.
    -   **Command Handlers:** `src/module_68.txt` and `src/module_35.txt` subscribe to command topics. They contain business logic and, upon success, publish domain events (e.g., `PostCreatedEvent`).
    -   **Event Consumers (Write-Side):** `src/module_48.txt` and `src/module_22.txt` are consumers that subscribe to domain events and update the 'write' database, which is the source of truth.
    -   **Query Service / Denormalizers:** `src/module_4.txt` is a separate service/module that also consumes domain events to update a denormalized 'read' database. It exposes read-only API endpoints for fetching data efficiently.

-   **Data Flow (Create Post):**
    1.  HTTP POST `/posts` hits `module_1`.
    2.  `module_1` authenticates the user via `module_15`.
    3.  `module_1` constructs and publishes a `CreatePostCommand` to the `commands.posts` NATS topic.
    4.  `module_68` (Post Command Handler) consumes the command, validates it, saves the core post data to the 'write' DB, and publishes a `PostCreatedEvent` to the `events.posts` topic.
    5.  `module_4` (Query Denormalizer) consumes the `PostCreatedEvent` and updates its 'read' database with the new post data for fast retrieval.

-   **Proposed Whiteboard Architecture:**
    -   A new, independent module (`ProposedWhiteboardService`) that manages WebSocket connections.
    -   This service subscribes to the main NATS bus for events like `StudyGroupSessionStarted` to know when to create a whiteboard session.
    -   Client-side drawing actions are sent over the WebSocket directly to this service.
    -   The service broadcasts drawing data to all other clients in the same session's WebSocket room.
    -   For persistence, the service takes a snapshot of the whiteboard state (e.g., as SVG or JSON) every 10-20 seconds and issues a `SaveWhiteboardSnapshotCommand` to the NATS bus, which is then handled by a standard command handler to save to the primary DB.

-   **Diagrams (MermaidJS):** The ground truth would include valid MermaidJS code for the 'Existing' and 'Proposed' architectures, reflecting the component interactions described above.

-   **Risks:**
    1.  **Scalability of WebSocket Service:** The new service is stateful (maintaining active connections) and could become a bottleneck. It needs to be designed for horizontal scaling.
    2.  **Increased Load on Auth Service:** Every WebSocket connection will need to be authenticated, potentially DDOSing the auth module (`module_15`) if not handled carefully (e.g., with tickets or token-based auth).
    3.  **Data Consistency:** There's a risk of inconsistency between the real-time state seen by users and the persisted snapshot in the database if the server crashes between snapshots.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
