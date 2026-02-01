# LoCoBench-Agent Task

## Task Information

**Task ID**: python_desktop_development_expert_021_cross_file_refactoring_expert_01
**Category**: cross_file_refactoring
**Difficulty**: expert
**Language**: python
**Context Length**: 1026075 tokens
**Files**: 73

## Task Title

Refactor User State Management by Unifying Profile and Presence Services

## Description

In the FlockDesk application, user-related data is currently fragmented across two distinct services: `ProfileService` handles static user data like names and avatars, while `PresenceService` manages dynamic real-time data like online status. This separation leads to several architectural problems: components needing a complete user view must interact with two different services, increasing complexity and coupling. It also creates a risk of data inconsistency and makes state management more difficult. This task involves a major architectural refactoring to consolidate these two services into a single, authoritative `UserService`, creating a single source of truth for all user information.

## Your Task

Your task is to refactor the user management system by unifying `ProfileService` and `PresenceService`.

1.  **Create a New Service:** Create a new file at `flockdesk/core/services/user_service.py`. Inside this file, define a new `UserService` class. This class will be the new single source of truth for all user data.

2.  **Consolidate Logic:** Migrate all functionality from `flockdesk/core/services/profile_service.py` and `flockdesk/modules/presence/service.py` into the new `UserService`. The new service should manage both static profile data (e.g., from `shared/schemas/user_profile.py`) and dynamic status data (e.g., from `modules/presence/model/user_status.py`). Design a unified API, for example, a method `get_user_view(user_id)` that returns a combined object/dictionary with the user's name, avatar, and current online status.

3.  **Update Consumers:** Systematically refactor all application components that currently depend on `ProfileService` or `PresenceService`. They must now import and use the new `UserService`. Key files to investigate include, but are not limited to:
    *   `flockdesk/modules/chat/viewmodel/chat_vm.py`
    *   `flockdesk/modules/presence/viewmodel/presence_vm.py`
    *   `flockdesk/modules/presence/view/presence_widget.py`
    *   `flockdesk/shared/widgets/avatar_widget.py`
    *   `flockdesk/core/app.py` (for service initialization)

4.  **Update Tests:** Adapt the existing tests to reflect this new architecture. You may need to merge tests from `tests/integration/test_profile_sync.py` and create a new test file like `tests/unit/core/test_user_service.py`. Ensure the core functionality remains tested.

5.  **Cleanup:** Once all references have been updated and the application is stable, delete the now-redundant files: `flockdesk/core/services/profile_service.py` and `flockdesk/modules/presence/service.py`.

## Expected Approach

An expert developer would approach this task methodically:

1.  **Analysis Phase:** 
    *   Thoroughly read `profile_service.py` and `presence/service.py` to understand their public APIs, internal state, and responsibilities.
    *   Use a global search (e.g., `grep` or IDE search) for `ProfileService` and `PresenceService` to identify all call sites and points of dependency injection across the codebase.
    *   Analyze how these services are instantiated and registered, likely within `flockdesk/core/app.py` or `flockdesk/core/main.py`.

2.  **Design Phase:**
    *   Design the public API for the new `UserService`. It should provide clear, consolidated methods like `get_current_user_profile()`, `get_user_view(user_id)`, `observe_user_status(user_id, callback)`, and `set_my_status(new_status)`.
    *   Plan for the service to be a singleton, likely following the pattern in `shared/utils/singleton.py` if used elsewhere.
    *   Decide on an internal data structure, probably a dictionary, to cache user data, combining profile and status information.

3.  **Implementation Phase (Incremental):**
    *   Create the new file `flockdesk/core/services/user_service.py` and the `UserService` class skeleton.
    *   Begin by migrating the logic from `ProfileService` and `PresenceService` into the new `UserService`, adapting method signatures and internal logic to coexist.
    *   Update the service instantiation logic in `app.py` or `main.py` to create `UserService` and remove the old services. This is a critical step to ensure the new service is available for dependency injection.
    *   Refactor consumers one by one. For each file that uses an old service, change the import, update the dependency injection (if applicable), and modify the method calls to use the new `UserService` API.
    *   Run relevant unit tests frequently during this process to catch regressions early.

4.  **Testing Phase:**
    *   Create `tests/unit/core/test_user_service.py`. Port and adapt relevant tests from the old services' test files.
    *   Write new tests for the unified API methods.
    *   Modify existing integration tests like `test_profile_sync.py` to use the new service, or merge its functionality into a new integration test for `UserService`.
    *   Run the entire test suite to ensure the refactoring is complete and correct.

5.  **Cleanup Phase:**
    *   After all tests pass and all references are updated, confidently delete `flockdesk/core/services/profile_service.py` and `flockdesk/modules/presence/service.py`.
    *   Delete their corresponding test files if they are no longer needed.

## Evaluation Criteria

- **Correctness & Functionality:** The application must compile and run without errors. All user-related features (displaying avatars, names, online statuses) must work as before. All tests in the suite must pass.
- **Completeness of Refactoring:** All usages of `ProfileService` and `PresenceService` must be successfully replaced with `UserService`. The two old service files must be deleted.
- **Architectural Soundness:** The new `UserService` must be well-designed, providing a clean and unified API that effectively encapsulates the combined responsibilities of the former services.
- **Code Quality:** The new and modified code must adhere to existing project conventions, be readable, and not introduce new bugs or code smells.
- **Test Maintenance:** The agent must demonstrate an ability to manage the test suite by creating, modifying, and deleting test files and test cases as appropriate for the refactoring.
- **File System Operations:** The agent must correctly create the new service file in the specified location and correctly delete the old files without leaving orphans or deleting incorrect files.

---

## CRITICAL INSTRUCTIONS

### Step 1: Understand the Task Type

**For Code Understanding/Analysis Tasks** (architectural_understanding, bug_investigation):
- Focus on exploring and analyzing the codebase
- Document your findings thoroughly in solution.md

**For Code Modification Tasks** (cross_file_refactoring, feature_implementation):
- **IMPLEMENT the code changes directly in /app/project/**
- Then document your changes in solution.md
- Your actual code modifications will be evaluated

### Step 2: Explore the Codebase

The repository is mounted at /app/project/. Use file exploration tools to:
- Understand directory structure
- Read relevant source files
- Trace dependencies and relationships

### Step 3: Write Your Solution

**OUTPUT FILE**: /logs/agent/solution.md

Your solution **MUST** include ALL of the following sections:

---

## Required Solution Structure

When writing your solution.md, use this exact structure:

# Solution: [Task ID]

## Key Files Identified

List ALL relevant files with their full paths and descriptions:
- /app/project/path/to/file1.ext - Brief description of relevance
- /app/project/path/to/file2.ext - Brief description of relevance
- /app/project/path/to/file3.ext - Brief description of relevance

## Code Evidence

Include relevant code blocks that support your analysis.
For each code block, include a comment with the file path and line numbers.
Example format:
  // File: /app/project/src/module/file.ts
  // Lines: 42-58
  [paste the relevant code here]

## Analysis

Detailed explanation of your findings:
- How the components interact
- The architectural patterns used
- Dependencies and relationships identified
- For bugs: root cause analysis
- For refactoring: impact assessment

## Implementation (For Code Modification Tasks)

If this is a code modification task, describe the changes you made:
- Files modified: list each file
- Changes made: describe each modification
- Testing: how you verified the changes work

## Summary

Concise answer addressing the original question:
- **Primary finding**: [main answer to the task question]
- **Key components**: [list major files/modules involved]
- **Architectural pattern**: [pattern or approach identified]
- **Recommendations**: [if applicable]

---

## Important Requirements

1. **Include file paths exactly as they appear** in the repository (e.g., /app/project/src/auth/handler.ts)

2. **Use code blocks** with the language specified to show evidence from the codebase

3. **For code modification tasks**: 
   - First implement changes in /app/project/
   - Then document what you changed in solution.md
   - Include before/after code snippets

4. **Be thorough but focused** - address the specific question asked

5. **The Summary section must contain key technical terms** relevant to the answer (these are used for evaluation)

## Output Path Reminder

**CRITICAL**: Write your complete solution to /logs/agent/solution.md

Do NOT write to /app/solution.md - use /logs/agent/solution.md
