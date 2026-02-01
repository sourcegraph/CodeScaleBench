# LoCoBench-Agent Task

## Task Information

**Task ID**: rust_web_social_expert_073_bug_investigation_expert_01
**Category**: bug_investigation
**Difficulty**: expert
**Language**: rust
**Context Length**: 1067411 tokens
**Files**: 86

## Task Title

Cross-User Data Leakage Under Concurrent Load in Session Initialization

## Description

EduPulse Live is a high-performance, event-driven social learning platform built in Rust. It serves thousands of concurrent users. A critical and elusive bug has been reported by the QA team and users. During peak usage times, some users have reported seeing dashboard information—such as recent activity, enrolled courses, or private messages—that belongs to another user who logged in at roughly the same time. The issue is non-deterministic and extremely difficult to reproduce, suggesting a race condition or a flaw in how concurrent request contexts are managed. The application does not crash; it simply serves incorrect, sensitive data.

## Your Task

A critical, intermittent data leakage bug has been reported in the EduPulse Live application. Users are occasionally seeing data belonging to other users on their dashboards immediately after logging in. Your task is to perform a thorough investigation of the codebase to identify the root cause of this data leakage.

Your analysis must:
1.  Identify the specific code flaw(s) responsible for the bug.
2.  Pinpoint the exact files and line numbers containing the problematic code.
3.  Provide a detailed, step-by-step explanation of the conditions (the 'race') that trigger the bug.
4.  Explain why this bug is intermittent and only manifests under concurrent load.

## Expected Approach

An expert developer would approach this problem systematically:
1.  **Hypothesis Formulation:** The symptoms (intermittent, cross-user data leakage) strongly point towards a state management issue, specifically a race condition involving a shared resource that is not properly isolated between requests or threads.
2.  **Codebase Triage for Shared State:** The first step is to search the entire codebase for patterns that indicate shared mutable state. This includes searching for global `static` variables, `lazy_static!`, and especially `Arc<Mutex<...>>` or `Arc<RwLock<...>>` that might be used to store user-specific information.
3.  **Request Lifecycle Analysis:** Trace the lifecycle of an authenticated user request. This involves identifying the primary web framework entry point, the middleware stack (especially for authentication and session management), and the final request handlers.
4.  **Identify Context Management Patterns:** Look for how user-specific context is managed. An expert would look for standard Rust async patterns like `tokio::task_local` for safely passing context. They would be highly suspicious of any user data being passed via a global `Mutex`.
5.  **Cross-Reference Findings:** The developer would cross-reference the locations of global shared state with the request lifecycle code. They would likely identify that a middleware (`module_48.txt`) modifies a global state and that a data-fetching module (`module_15.txt`) reads from it.
6.  **Root Cause Synthesis:** By connecting these pieces, the developer would synthesize the exact race condition: a middleware for Request A writes User A's context to the global state. Before Request A's handler can use it, a context switch occurs, and the middleware for Request B overwrites the global state with User B's context. When Request A's handler resumes, it reads the global state and incorrectly retrieves User B's data.
7.  **Isolate Problematic Code:** The final step is to pinpoint the exact `lock()`, `write()`, and `read()` calls in the respective files that constitute the flawed logic.

## Evaluation Criteria

- **Correctness of Root Cause Analysis:** Did the agent correctly identify the race condition caused by using a global `Arc<Mutex<...>>` for request-specific data?
- **Accuracy of File Identification:** Did the agent correctly identify `module_48.txt` and `module_15.txt` as the primary files involved in the bug?
- **Precision of Code Localization:** How accurately did the agent pinpoint the specific lines of code responsible for writing to and reading from the flawed global state?
- **Clarity of Explanation:** Was the agent's explanation of the race condition clear, logical, and did it correctly describe the sequence of events leading to the data leak?
- **Identification of Legacy Pattern:** Did the agent recognize the anti-pattern of mixing `task_local` context passing with a legacy global state approach?
- **Efficiency of Investigation:** Did the agent follow a logical debugging process (e.g., searching for shared state first) or did it use a brute-force, inefficient approach?

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
