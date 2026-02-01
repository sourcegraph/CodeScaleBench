# LoCoBench-Agent Task

## Task Information

**Task ID**: c_api_microservice_expert_080_architectural_understanding_expert_01
**Category**: architectural_understanding
**Difficulty**: expert
**Language**: c
**Context Length**: 1102120 tokens
**Files**: 79

## Task Title

Diagnose Performance Degradation in the V2 API Endpoints

## Description

The MercuryMonolith Commerce Hub is a high-performance, mission-critical API written in C. It serves product data to various front-end clients. Recently, after the rollout of API v2, monitoring systems have detected significant performance degradation for all v2 endpoints (e.g., `/api/v2/products/...`) compared to their v1 counterparts. The latency is especially pronounced on cache misses, but is still unacceptably high even with cache hits. As the lead architect, your task is to analyze the system's architecture to identify the root cause of this performance issue.

## Your Task

Your analysis must produce a technical report in markdown format. The report should:

1.  **Identify Key Components:** Pinpoint the specific source modules (`module_XX.txt`) responsible for the following functionalities:
    *   HTTP request routing (especially the logic that differentiates v1 and v2).
    *   The core response caching mechanism.
    *   The primary business logic for handling v2 product-related requests.

2.  **Describe the Request Lifecycle:** Detail the step-by-step flow of a request to a v2 endpoint (e.g., `/api/v2/products/{id}`). Describe how the identified modules interact with each other from the moment the request is received to the moment a response is sent.

3.  **Formulate a Hypothesis:** Based on your analysis of the component interactions, formulate a precise hypothesis explaining why v2 endpoints are inherently slower than v1 endpoints. Your hypothesis must be grounded in the architectural design and the sequence of operations you've identified.

## Expected Approach

An expert developer would not attempt to read all 80+ files. They would approach this systematically:

1.  **Find the Entry Point:** Start by searching for common C web server patterns. Look for `main()` functions, socket handling (`socket`, `bind`, `listen`, `accept`), or usage of a known C HTTP library. The goal is to find the main request loop.

2.  **Locate the Router:** From the entry point, trace the code to where the HTTP request URI is parsed. Search for string functions like `strstr`, `strncmp`, or `sscanf` being used with URL paths like `"/api/v1/"` or `"/api/v2/"`. This will likely lead to a large switch statement or an if-else-if chain in a specific module that acts as the router.

3.  **Identify the Caching Module:** Search the codebase for keywords related to caching, such as `cache`, `redis`, `memcached`, `get`, `set`, `key`, `ttl`. This will isolate the module(s) responsible for the response caching feature.

4.  **Trace V1 vs. V2 Paths:** Once the router is found, trace the function calls for both a v1 and a v2 path. Note which modules are called in each case. The developer should observe that the v2 path involves an additional module or a more complex call chain before reaching the core data-fetching logic.

5.  **Analyze the Interaction:** With the key modules (router, v2 logic, caching) identified, the developer would analyze the *order of operations* for a v2 request. They would ask: "When is the cache checked? Is it before or after the expensive v2-specific operations?" By comparing the v1 and v2 call graphs, the architectural flaw will become apparent.

6.  **Synthesize the Findings:** The developer would then write up the report, clearly stating which file does what, drawing the call sequence, and articulating the core problem: that expensive processing for v2 happens *before* the cache lookup, nullifying many of its benefits and slowing down every request.

## Evaluation Criteria

- {'criterion': 'Correctly identifies the routing module.', 'metric': 'Boolean', 'expected_value': 'Agent must identify `src/module_31.txt` as the router.'}
- {'criterion': 'Correctly identifies the caching module.', 'metric': 'Boolean', 'expected_value': 'Agent must identify `src/module_62.txt` as the caching component.'}
- {'criterion': 'Correctly identifies the V2 transformation module.', 'metric': 'Boolean', 'expected_value': 'Agent must identify `src/module_50.txt` as the location of V2-specific logic.'}
- {'criterion': 'Accurately describes the request lifecycle for a V2 endpoint.', 'metric': 'Ordinal (1-5)', 'expected_value': '5 - The agent correctly sequences the key steps: routing -> data fetch -> V2 transformation -> cache interaction.'}
- {'criterion': 'Correctly identifies and explains the architectural flaw.', 'metric': 'Ordinal (1-5)', 'expected_value': '5 - The agent explicitly states that the expensive V2 transformation occurs *before* the cache lookup, which is the root cause of the performance issue.'}
- {'criterion': 'Clarity and conciseness of the final report.', 'metric': 'Ordinal (1-5)', 'expected_value': '5 - The report is well-structured, easy to understand, and directly answers all parts of the prompt.'}

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
