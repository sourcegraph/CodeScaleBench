# LoCoBench-Agent Task

## Task Information

**Task ID**: typescript_system_monitoring_expert_061_cross_file_refactoring_expert_01
**Category**: cross_file_refactoring
**Difficulty**: expert
**Language**: typescript
**Context Length**: 1026021 tokens
**Files**: 75

## Task Title

Centralize Dispersed Alerting Logic into a Unified Notification Service

## Description

The PulseSphere SocialOps system has evolved organically, with different monitoring modules developed independently. This has resulted in fragmented and inconsistent alerting mechanisms. For instance, some modules use a generic email utility, others make direct API calls to specific chat services via hardcoded webhooks, and some simply log critical errors to a file with a specific tag. This technical debt makes it difficult to manage alert routing, add new notification channels (like PagerDuty), or implement global features like alert throttling or silencing. This task involves refactoring the entire codebase to use a single, centralized, and extensible notification service.

## Your Task

Your task is to refactor the disparate alerting mechanisms scattered across the PulseSphere SocialOps codebase into a new, unified Notification Service.

**Detailed Requirements:**

1.  **Identify Alerting Logic:**
    - Scan all `src/module_*.ts` files and `src/utils.ts` to locate all instances of alert generation.
    - Look for calls to the `sendLegacyEmailAlert` function in `src/utils.ts`.
    - Find any hardcoded `fetch` or `axios` calls to webhook URLs (e.g., containing 'hooks.slack.com' or 'chat.teams.microsoft.com').
    - Identify critical error logging intended as an alert, typically marked with a comment like `// ALERT: ...` or `// CRITICAL-ALERT: ...`.

2.  **Design and Implement the Notification Service:**
    - Create a new directory: `src/services`.
    - Create a new file: `src/services/notificationService.ts`.
    - In this new file, define the following:
        - An `AlertMessage` type: `{ severity: 'critical' | 'warning' | 'info'; title: string; details: Record<string, any>; sourceModule: string; }`
        - A `NotificationChannel` interface with a single method: `send(message: AlertMessage): Promise<void>;`
        - Concrete classes that implement `NotificationChannel`: `EmailChannel`, `WebhookChannel`, and `LogChannel`.
        - A primary `NotificationService` class. This class should be initialized with a list of active channels and expose a single public method: `dispatch(alert: AlertMessage): Promise<void>`. The `dispatch` method will iterate over its configured channels and call their `send` methods.
        - Export a singleton instance of the `NotificationService` for use throughout the application.

3.  **Centralize Configuration:**
    - Create a new directory: `src/config`.
    - Create a new file: `src/config/notifications.ts`.
    - Move all hardcoded configuration details (e.g., recipient email addresses, webhook URLs) from the modules and `utils.ts` into this new config file.
    - The `NotificationService` should import its configuration from this file to initialize its channels.

4.  **Refactor Existing Modules:**
    - Go through each module where you identified alerting logic.
    - Replace the old, direct implementation with a call to the new `notificationService.dispatch()` method.
    - Ensure you correctly construct the `AlertMessage` object using the context available at the call site.

5.  **Code Cleanup:**
    - Once all modules are refactored, remove the now-redundant `sendLegacyEmailAlert` function and any related helper types from `src/utils.ts`.
    - Ensure no unused imports remain in the refactored files.

## Expected Approach

An expert developer would approach this task systematically:

1.  **Discovery Phase:** Use a global search tool (like `grep` or an IDE's find-in-files feature) to search for patterns like `sendLegacyEmailAlert`, `hooks.slack.com`, `// ALERT:`, and `http.request` to create a comprehensive list of files and line numbers that need refactoring.

2.  **Abstraction Design:** Before writing code, the developer would design the new service's API. They would define the `AlertMessage` structure and the `NotificationChannel` interface first. This interface-first approach ensures a clean separation of concerns.

3.  **Bottom-Up Implementation:**
    - Create the new directory structure (`src/services`, `src/config`).
    - Implement the `src/config/notifications.ts` file first, extracting all known configuration values.
    - Implement the `src/services/notificationService.ts` file, including the interfaces, channel classes, and the main service. The service would be built to be testable, likely by allowing channel injection in its constructor, even if the exported singleton uses a default configuration.

4.  **Incremental Refactoring:**
    - The developer would not try to refactor all files at once. They would pick one module (e.g., `src/module_30.ts`), refactor it completely to use the new service, and verify the changes.
    - This first refactoring serves as a template. They would then apply the same pattern to the remaining modules one by one, ensuring consistency.

5.  **Finalization and Cleanup:**
    - After all call sites have been migrated, the developer would confidently delete the `sendLegacyEmailAlert` function from `utils.ts`.
    - A final review of all changed files (`git diff`) would be performed to catch any inconsistencies, leftover comments, or unused imports before committing.

## Evaluation Criteria

- **Correctness & Compilation:** The final code must compile successfully without any TypeScript errors.
- **Completeness of Refactoring:** All instances of legacy alerting (email, webhooks, tagged logs) must be identified and replaced with the new service call.
- **Quality of Abstraction:** The new `NotificationService` and `NotificationChannel` interface must be well-designed, extensible, and follow standard object-oriented principles.
- **Configuration Centralization:** All hardcoded configuration values (emails, URLs) must be successfully moved to `src/config/notifications.ts` and used by the service.
- **Code Removal (Cleanup):** The old `sendLegacyEmailAlert` function in `src/utils.ts` must be successfully removed. No dead code should remain.
- **Functional Equivalence:** The refactoring must not alter the core business logic of the modules. The conditions that trigger alerts should remain identical.
- **Modularity and Imports:** The agent must correctly manage imports/exports for the new services and update them in all refactored modules.

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
