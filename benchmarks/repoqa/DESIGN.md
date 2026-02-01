# RepoQA Adapter Design

## Overview

The RepoQA adapter transforms RepoQA's "Searching Needle Function" (SNF) benchmark into a tool-sensitive evaluation framework. The original RepoQA presents agents with a long code context (16K tokens) and asks them to find a function matching a natural language description.

Our derived benchmark removes the long-context memorization signal and instead tests **semantic code navigation** using Sourcegraph MCP as the primary tool for discovering code structure.

## Benchmark Transformation: SNF → 3 Task Types

### Original RepoQA (SNF)
- **Input**: Long code context (16K tokens) + function description
- **Output**: Function name (exact match)
- **Signal Measured**: Long-context needle finding
- **Problem**: Reward correlates with context window size, not tool usage

### Our Approach: Three Task Variants

#### 1. Semantic Retrieval QA (SR-QA)
**Goal**: Locate a function by behavior, not name. Tests if agents can use semantic search effectively.

**Prompt Format**:
```
You are searching a large codebase for a specific function.

Function behavior:
{behavior_description}

Constraints:
- Language: {language}
- Module scope: {module_scope} (if applicable)
- Side effects: {side_effects} (if applicable, e.g., "mutates state", "performs I/O")
- Return type: {return_type}

You MUST use Sourcegraph MCP to search for this function. Do NOT attempt to guess based on naming patterns.

Provide your answer as JSON:
{
  "function_path": "path/to/file.py",
  "function_name": "function_name",
  "justification": "Brief semantic reasoning for why this function matches"
}
```

**Verifier**:
- Exact match on `(path, function_name)`: +1.0 score
- Path correct but name wrong: +0.5 score
- Name correct but path wrong: +0.3 score
- Justification scores heuristically (keyword overlap + call graph relevance)

---

#### 2. Multi-Hop Dependency QA (MD-QA)
**Goal**: Test graph reasoning. Agents must understand call paths and data flow.

**Prompt Format**:
```
You are analyzing a large codebase.

Question:
{question}

Example:
"Which function ultimately validates user input for the login handler?
Provide a valid call path from the HTTP handler to the validation function."

You MUST use Sourcegraph MCP call graph features to trace dependencies.

Provide your answer as JSON:
{
  "root_function": "path/to/file.py::function_name",
  "dependency_path": ["path1::func1", "path2::func2", "path3::func3"]
}
```

**Verifier**:
- Root function exact match: +1.0 base score
- Each step in dependency path that's valid: +0.33 per step (max 3 steps)
- Partial credit for valid prefix: +0.5

---

#### 3. Negative/Disambiguation QA (NR-QA)
**Goal**: Resistance to false positives. Agents must distinguish similar functions.

**Prompt Format**:
```
You are searching a codebase for a function.

Function description:
{description}

The codebase contains multiple functions with similar names or behavior:
- {function_a}: {brief_description_a}
- {function_b}: {brief_description_b}  
- {function_c}: {brief_description_c}

Only ONE of these functions satisfies the description. Use semantic search to identify it.

The function you seek:
- {semantic_constraint} (e.g., "mutates the database", "throws exceptions on validation failure")

Provide your answer as JSON:
{
  "function_path": "path/to/file.py",
  "function_name": "correct_function",
  "justification": "Why this is the correct one, not the others"
}
```

**Verifier**:
- Correct selection: +1.0 score
- Incorrect selection (even if plausible): 0.0 score
- Partial credit for correct path: +0.3 score

---

## Ground Truth Generation (Offline)

For each repository and function:

```python
@dataclass
class FunctionMetadata:
    """Ground truth for a single function."""
    function_id: str              # "path/to/file.py::function_name"
    canonical_path: str           # Absolute path
    canonical_name: str           # Function name
    language: str                 # python, javascript, rust, etc.
    
    # Semantic tags
    mutates_state: bool           # Modifies globals, database, file system
    throws_errors: bool           # Raises exceptions
    performs_io: bool             # File I/O, network I/O
    is_async: bool                # async/await or callback-based
    
    # Call graph
    callers: List[str]            # Functions that call this one
    callees: List[str]            # Functions this one calls
    
    # Natural language description (from original RepoQA)
    nl_description: str           # Function behavior in English
```

### Offline Extraction Pipeline

1. **Parse codebase** with tree-sitter (handles Python, Rust, JS, Go, etc.)
2. **Extract call graphs** using scope analysis
3. **Compute semantic tags** from AST (mutations, I/O, exceptions)
4. **Store metadata** in `ground_truth.json` per repo

### Example Ground Truth
```json
{
  "function_id": "src/auth/verify_token.py::verify_jwt_token",
  "canonical_path": "src/auth/verify_token.py",
  "canonical_name": "verify_jwt_token",
  "language": "python",
  "mutates_state": false,
  "throws_errors": true,
  "performs_io": false,
  "is_async": false,
  "callers": [
    "src/handlers/login.py::handle_login",
    "src/handlers/api.py::authenticate_request"
  ],
  "callees": [
    "jwt.decode",
    "time.time"
  ],
  "nl_description": "Validates JWT tokens from HTTP Authorization headers, checking expiration and signature validity"
}
```

---

## Harbor Task Format

Each task directory contains:

```
task/
├── instruction.md           # Prompt to agent
├── task.toml                # Metadata, timeouts, resource limits
├── environment/
│   └── Dockerfile           # Lightweight env setup
├── tests/
│   ├── test.sh              # Verifier invocation script
│   └── ground_truth.json    # Offline-computed metadata
└── solution/
    └── reference.json       # Expected output (for logging)
```

### instruction.md
- Contains prompt specific to task variant (SR-QA, MD-QA, NR-QA)
- Does NOT include full code context (unlike original RepoQA)
- Directs agent to use Sourcegraph MCP
- Defines output JSON schema clearly

### task.toml
```toml
[metadata]
author_name = "RepoQA Adapter"
difficulty = "hard"
category = "semantic-code-navigation"
tags = ["repoqa", "code-search", "graph-reasoning"]
task_variant = "sr-qa"  # or "md-qa", "nr-qa"
repository = "tensorflow/tensorflow"
commit = "abc1234..."

[agent]
timeout_sec = 600.0
model_hint = "requires-mcp"

[environment]
build_timeout_sec = 300.0
cpus = 2
memory = "4G"
```

### Dockerfile
```dockerfile
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    git curl

# Clone repository at specific commit
RUN git clone https://github.com/{repo}.git /app/repo && \
    cd /app/repo && \
    git checkout {commit}

# Install Python dependencies for ground truth validation
RUN pip install -q tree-sitter==0.20.1

WORKDIR /app
```

### test.sh (Verifier)
```bash
#!/bin/bash
set -e

cd /app

# Agent's output is in /app/solution.json
# Ground truth is in /app/tests/ground_truth.json

python3 -m repoqa_verifiers \
  --task-variant sr-qa \
  --ground-truth tests/ground_truth.json \
  --solution solution.json \
  --output /logs/verifier/reward.json
```

### Verifier Output (reward.json)
```json
{
  "correct_function": 0.5,
  "correct_path": 1.0,
  "justification_score": 0.8
}
```

Harbor aggregates these metrics across tasks.

---

## Design Rationale

### Why This Is Sourcegraph-Sensitive

1. **No Long Context**: Unlike original RepoQA, we don't provide the full code context
   - Baseline agent can't find the function by scrolling/searching the prompt
   - Must use external tools

2. **Semantic Search**: Function descriptions don't contain function names
   - Grep/rg won't find it easily
   - Sourcegraph Deep Search understands semantics

3. **Graph Reasoning**: MD-QA requires understanding call paths
   - Manual exploration is tedious
   - MCP call graph queries solve it naturally

4. **Disambiguation**: NR-QA tests precision
   - Multiple plausible answers exist
   - Semantic search avoids false positives better than keyword search

### Why It's Not Comparable to Original RepoQA

1. **Different Signal**: Original rewards long-context retrieval; ours rewards tool usage
2. **Different Baseline**: Original compares models with context windows; ours compares tool access
3. **Different Metric**: Original uses BLEU similarity; ours uses semantic similarity
4. **Different Goal**: Original measures "can you find code in a big context"; ours measures "can you navigate code structure with tools"

---

## Implementation Strategy

### Phase 1: Core Components
1. `ground_truth_extractor.py` - Parse repos, extract metadata
2. `verifiers.py` - Semantic similarity scoring
3. `adapter.py` - Transform RepoQA instances to Harbor tasks
4. `run_adapter.py` - CLI tool

### Phase 2: Testing
1. Unit tests for verifiers
2. Integration test with a small repo
3. Validation of task generation

### Phase 3: Documentation
1. README explaining design choices
2. QUICKSTART for running the adapter
3. Examples of task variants

---

## Success Criteria

- [ ] Adapter generates valid Harbor tasks
- [ ] Tasks are tool-sensitive (MCP agents score higher)
- [ ] Verifiers are deterministic and reproducible
- [ ] Documentation is clear about why this differs from original RepoQA
- [ ] Tests pass on a real repository

