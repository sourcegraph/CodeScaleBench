# Team Handoff: Terraform State Backend Subsystem

## Scenario

You are taking over ownership of Terraform's state backend subsystem from a departing team member. The state backend is responsible for storing and managing Terraform state files, which contain the mapping between configured resources and real-world infrastructure.

Your team member has left limited documentation. Your task is to explore the codebase and produce a comprehensive handoff document that will help you and future team members understand, maintain, and extend the state backend system.

## Your Task

Explore the hashicorp/terraform codebase and create a structured handoff document covering the state backend subsystem. Your document should address the following sections:

### 1. Purpose
- What problem does the state backend subsystem solve?
- Why do we need different backend types (local, S3, remote, etc.)?
- What are the key responsibilities of a backend?

### 2. Dependencies
- What other Terraform subsystems does the backend interact with?
- What are the upstream dependencies (what calls into backends)?
- What are the downstream dependencies (what do backends call)?
- How does the backend system integrate with the broader Terraform architecture?

### 3. Relevant Components
- What are the main source files and directories for the backend subsystem?
- What modules/interfaces define the Backend interface?
- Where are concrete backend implementations located?
- What modules/interfaces define the state locking mechanism?
- What files are critical for understanding how backends work?

### 4. Failure Modes
- What can go wrong with state backends?
- How does the system handle state locking failures (stale locks, timeouts)?
- What happens when storage is unavailable?
- How are state corruption scenarios handled?
- What are common configuration errors and how are they detected?

### 5. Testing
- How are backends tested?
- What test patterns are used for backend implementations?
- Where are the backend tests located?
- How do you test state locking behavior?
- What integration tests exist for backends?

### 6. Debugging
- How do you troubleshoot state lock issues?
- How do you verify state consistency?
- What logs or diagnostics are available for debugging backend problems?
- How do you investigate stale locks or lock contention?

### 7. Adding a New Backend
- If you needed to add a new backend type (e.g., for a new cloud provider), what would be the step-by-step process?
- What interfaces need to be implemented?
- What files need to be created or modified?
- How is a new backend registered with the system?

## Deliverable

Create your handoff document as a markdown file at `/logs/agent/onboarding.md`.

Deliver a clear, well-structured document that covers all requested sections. Include:
- Specific file paths and directory names
- Key function/type names
- Code flow descriptions
- Concrete examples where helpful

## Evaluation

Your handoff document will be evaluated on:
- **Completeness**: All 7 sections addressed with substantive content
- **Accuracy**: Correct identification of relevant components, interfaces, and architectural patterns
- **Specificity**: Concrete file paths, type names, and code references (not generic descriptions)
- **Understanding**: Demonstrates comprehension of how the subsystem works, not just surface-level file listing

Good luck with your exploration!
