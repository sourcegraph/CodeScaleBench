#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The optimal solution is to introduce a new microservice dedicated to orchestration, adhering to the existing architectural principles.

**1. Current Architecture Summary:** The system is a Java/Spring Boot-based microservices architecture. It uses Spring Cloud for an API Gateway (`api-gateway`), Service Discovery (`service-discovery`), and Centralized Configuration (`config-server`). Services are designed with a Hexagonal Architecture, separating domain logic from external-facing adapters (web, persistence, messaging). Communication is primarily synchronous REST via the gateway, with some asynchronous capabilities demonstrated by messaging listeners (e.g., `FileConversionMessageListener`).

**2. Proposed Solution: A New `pipeline-orchestrator-service`:**
The best approach is to create a new `pipeline-orchestrator-service`. This centralizes the complex workflow logic, making it explicit and manageable, which is preferable to a fragile, hard-to-trace event-driven choreography for this use case. This new service will be responsible for accepting a pipeline definition, executing the steps by calling the appropriate services, managing the state of the pipeline, and handling errors.

**3. Data Flow for 'Anonymize then Convert' Pipeline:**
    a.  A client sends a POST request to `/api/v1/pipelines` via the `api-gateway` with a body specifying the sequence of tasks (e.g., `[{ "service": "anonymizer", "params": {...} }, { "service": "converter", "params": {...} }]`) and the initial data.
    b.  The `api-gateway` routes the request to the new `pipeline-orchestrator-service`.
    c.  The orchestrator service creates a new pipeline job record in its database with a `PENDING` status, and immediately returns a `202 Accepted` response with a `jobId` to the client.
    d.  Asynchronously, the orchestrator begins processing. It calls the `data-anonymizer-service` via a REST client (looking it up via service discovery).
    e.  Upon successful completion, it takes the output and calls the `file-converter-service`.
    f.  If any step fails, the orchestrator updates the job status to `FAILED` and stores the error details. If all steps succeed, it updates the status to `COMPLETED` and stores the final result's location.
    g.  The client can poll the status endpoint `/api/v1/pipelines/{jobId}` to check progress and retrieve the final result upon completion.

**4. Required Changes and New Files:**
    *   **New Module:**
        *   `opsforge-utility-nexus/utility-services/pipeline-orchestrator-service/`
    *   **Key New Files:**
        *   `.../pipeline-orchestrator-service/pom.xml` (dependencies on `common-library`, `spring-cloud-starter-netflix-eureka-client`, `spring-boot-starter-web`, `spring-boot-starter-data-jpa`).
        *   `.../pipeline-orchestrator-service/src/main/java/.../PipelineOrchestratorApplication.java`
        *   `.../adapter/in/web/PipelineController.java` (to handle `/pipelines` requests).
        *   `.../domain/model/PipelineJob.java` (to model the state, steps, and status).
        *   `.../domain/service/PipelineService.java` (implements `PipelineUseCase` port, contains core orchestration logic).
        *   `.../domain/port/in/PipelineUseCase.java`
        *   `.../domain/port/out/AnonymizerServicePort.java`, `.../domain/port/out/FileConverterServicePort.java` (output ports for communicating with other services).
        *   `.../adapter/out/rest/AnonymizerServiceAdapter.java` (implements the port using a `RestTemplate` or `WebClient`).
    *   **Existing Files to Modify:**
        *   `opsforge-utility-nexus/pom.xml`: Add the new `pipeline-orchestrator-service` module.
        *   `opsforge-utility-nexus/api-gateway/src/main/java/com/opsforge/nexus/gateway/config/GatewayRouteConfig.java`: Add a new route definition to direct traffic from `/api/v1/pipelines/**` to the `pipeline-orchestrator-service` (lb://pipeline-orchestrator-service).
        *   `opsforge-utility-nexus/docker-compose.yml`: Add a service definition for the new orchestrator.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
