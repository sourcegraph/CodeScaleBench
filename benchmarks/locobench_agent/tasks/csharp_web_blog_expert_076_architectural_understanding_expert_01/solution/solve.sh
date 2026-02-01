#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
**Part 1: Architectural Analysis (Example Mapping)**
*   **Domain Models:** `module_3.txt` (likely a `Post` entity), `module_5.txt` (likely an `Author` entity). These files contain POCOs with business properties and methods, but no dependencies on external frameworks.
*   **Application Services:** `module_42.txt` (likely `PublishPostService.cs`). This file contains a class that orchestrates the publishing process, depending on interfaces (ports) like a repository and a payment processor.
*   **Primary Adapters:** `module_25.txt` (likely a `PostsController.cs`). This file defines API endpoints, takes HTTP requests, and calls application services.
*   **Secondary Adapters:** `module_65.txt` (likely `SqlPostRepository.cs`, implementing a repository port), `module_67.txt` (likely a `StripePaymentAdapter.cs`, implementing a payment port), and `module_20.txt` (likely a `SerilogLoggingAdapter.cs`). These files contain concrete implementations with external dependencies.
*   **Ports:** `module_15.txt` (likely `IPostRepository.cs`), `module_16.txt` (likely `IPaymentGateway.cs`). These files define the interfaces that the application core uses to communicate with outside systems.

**Part 2: Implementation Plan**
1.  **New Components:**
    *   **New Port:** Create a new interface `IContentSyndicator` inside the Application Core's port directory (e.g., logically alongside `module_15.txt`). It will define a single method: `Task SyndicatePostAsync(Post post);`.
    *   **New Adapter:** Create a new class `HttpContentSyndicatorAdapter` in the infrastructure layer (e.g., logically alongside `module_65.txt`). This class will implement `IContentSyndicator`. Its constructor will take `HttpClient` and `IConfiguration`. The `SyndicatePostAsync` method will build and send the HTTP POST request to the external API.

2.  **Existing Modifications:**
    *   **Modify `module_42.txt` (`PublishPostService`):** Inject the `IContentSyndicator` interface into its constructor. In the `ExecuteAsync` (or similar) method, after the logic that saves the post to the repository, add a call to `_contentSyndicator.SyndicatePostAsync(post);`.
    *   **Modify Dependency Injection Configuration:** The DI setup (likely referenced in `config.txt` or a startup class) must be updated to register the new service: `services.AddScoped<IContentSyndicator, HttpContentSyndicatorAdapter>();` and configure the `HttpClient` for it.

3.  **Configuration:**
    *   Add the following keys to `src/config.txt` (or the file it points to, like `appsettings.json`):
        ```json
        "ContentSyndication": {
          "ApiEndpoint": "https://api.content-aggregator.com/v1/posts",
          "ApiKey": "YOUR_API_KEY_HERE"
        }
        ```

4.  **Dependency Flow:**
    *   This solution maintains the correct dependency flow. The `PublishPostService` (Application Core) depends on the `IContentSyndicator` interface (Port, also in the Core). It has no knowledge of the `HttpContentSyndicatorAdapter`. The `HttpContentSyndicatorAdapter` (Infrastructure) depends on the `IContentSyndicator` interface (Core), thus the dependency arrow points inward, correctly adhering to the Hexagonal Architecture's dependency rule.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
