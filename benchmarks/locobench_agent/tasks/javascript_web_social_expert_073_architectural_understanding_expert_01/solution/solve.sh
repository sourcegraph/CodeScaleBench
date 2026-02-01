#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
### Architectural Analysis: User Progress Update Latency

#### 1. End-to-End Data Flow

The process involves two distinct paths: a synchronous write path and an asynchronous event path, followed by a separate read path.

*   **Synchronous Write Path:**
    1.  A user interacts with `frontend/src/components/course/LecturePlayer.js`, triggering a progress update.
    2.  The frontend calls a function in `frontend/src/services/courseService.js`, which sends a `PUT` request to an endpoint like `/api/courses/:courseId/progress`.
    3.  The request is routed by `services/api-gateway/nginx.conf` to the `course-service`.
    4.  `services/course-service/src/api/courseController.js` handles the request, calling `services/course-service/src/services/courseService.js`.
    5.  The service logic updates the progress in its PostgreSQL database via `services/course-service/src/repositories/courseRepository.js`.

*   **Asynchronous Event Path (based on `ADR/002`):**
    1.  After successfully updating its database, the `course-service` uses `services/course-service/src/events/producer.js` to publish a `USER_PROGRESS_UPDATED` event to a Kafka topic.
    2.  Other services, such as the `notification-service`, might consume this event to send real-time alerts. The `auth-service` might also consume it to update an aggregated user model.

*   **Frontend Read Path:**
    1.  The `frontend/src/pages/DashboardPage.js` and its components (`ProgressChart.js`, `ActivityStream.js`) are responsible for displaying the data.
    2.  They fetch this data by making `GET` requests to the `course-service` via the API Gateway. This is likely done on a polling interval or upon initial page load.

**The perceived latency is the time delta between the completion of the synchronous write path and the next execution of the frontend read path that retrieves the new state.** The intermittent nature is caused by variable delays in the asynchronous path, which can affect data aggregation or related features, and potential load-related issues in the core services or infrastructure.

#### 2. Key Architectural Components

*   **Services:** `frontend`, `api-gateway`, `course-service`, `notification-service` (as an event consumer example).
*   **Infrastructure:** NGINX (`api-gateway`), Kafka (`message-broker` defined in `docker-compose.yml`), PostgreSQL (database for `course-service`).
*   **Key Files:**
    *   `docs/ADR/002-event-sourcing-with-kafka.md` (Confirms architecture)
    *   `docker-compose.yml` (Defines Kafka service configuration)
    *   `services/course-service/src/services/courseService.js` (Core write logic)
    *   `services/course-service/src/events/producer.js` (Async event publishing)
    *   `frontend/src/pages/DashboardPage.js` (Initiates the read path)

#### 3. Top 3 Potential Bottlenecks

1.  **Kafka Broker Contention/Producer Lag:** The most likely culprit for intermittent delays under load. The `docker-compose.yml` file shows a single Kafka broker configuration. Under high traffic, this single broker can become a bottleneck, increasing the time it takes for the `course-service` producer to successfully publish the `USER_PROGRESS_UPDATED` event. If the producer's configuration is synchronous or has a long timeout, this could even delay the API response to the user, but more likely it just delays the event's propagation through the system, affecting any downstream consumers and creating the eventual consistency lag.

2.  **Eventual Consistency & Frontend Polling Strategy:** This is a design-related bottleneck. The architecture is built on eventual consistency, meaning data updates are not instantaneously reflected everywhere. The frontend (`DashboardPage.js`) is likely not using WebSockets for real-time updates but is instead polling the `course-service` API at a fixed interval (e.g., every 30 seconds). This polling interval creates a baseline perceived latency. The problem becomes "intermittent" because a user's action might occur just after a poll, forcing them to wait for the full interval for the next update.

3.  **Database Transaction Load in `course-service`:** During peak hours, the `course-service`'s PostgreSQL database could be under heavy write load. The transaction to update user progress might take longer to commit. This would delay the entire chain of events, including the subsequent Kafka message publication. While the primary database update is synchronous, its performance degradation under load would directly translate to a longer wait before the asynchronous part of the flow even begins, thus contributing significantly to the overall delay.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
