# LoCoBench-Agent Adapter Design

Architecture and design decisions for the LoCoBench-Agent Harbor adapter.

## Design Goals

1. **Demonstrate MCP value** - Select tasks where code search tools provide measurable advantages
2. **Fast execution** - Language-specific Dockerfiles instead of multi-language images
3. **Harbor compatibility** - Follow existing adapter patterns (repoqa, dibench, swebench_pro)
4. **Extensibility** - Easy to modify selection criteria or add new task categories

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     LoCoBench-Agent Data                        │
│  ┌─────────────────┐  ┌──────────────────────────────────────┐  │
│  │ generated/      │  │ output/scenarios/*.json              │  │
│  │ (1000 projects) │  │ (8000 task scenarios)                │  │
│  └─────────────────┘  └──────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    extract_dataset.py                           │
│  - Reads all scenario JSON files                                │
│  - Normalizes fields, parses language from ID                   │
│  - Outputs locobench_dataset.jsonl                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     select_tasks.py                             │
│  - Applies minimum thresholds (context > 50K, files > 5)        │
│  - Scores tasks: 0.3*context + 0.3*files + 0.4*category_bonus   │
│  - Outputs selected_tasks.json (top 50)                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      run_adapter.py                             │
│  - CLI interface for task generation                            │
│  - Loads LoCoBenchAdapter with dataset and data paths           │
│  - Generates Harbor task directories                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       adapter.py                                │
│  ┌──────────────┐  ┌────────────────┐  ┌─────────────────────┐  │
│  │LoCoBenchTask │  │LoCoBenchLoader │  │ LoCoBenchAdapter    │  │
│  │ (dataclass)  │  │ (JSONL loader) │  │ (Harbor generator)  │  │
│  └──────────────┘  └────────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Harbor Task Directory                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │instruction.md│  │  task.toml   │  │ environment/         │   │
│  │              │  │              │  │ ├── Dockerfile       │   │
│  │              │  │              │  │ └── project/         │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ tests/                                                    │   │
│  │ ├── test.sh          (verification entry)                 │   │
│  │ ├── verify.py        (semantic scorer)                    │   │
│  │ ├── ground_truth.json                                     │   │
│  │ └── task_metadata.json                                    │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Language-Specific Dockerfiles

**Decision**: Generate Dockerfiles dynamically based on task language.

**Rationale**: The original multi-language Dockerfile installed Python, Node.js, Rust, Go, Java, .NET, and PHP - taking 5+ minutes to build. Since tasks run in isolated containers with no cross-task sharing, each task only needs its own language.

**Implementation**: `_generate_dockerfile(language)` method in adapter.py creates minimal Dockerfiles:
- Base Ubuntu + build-essential + curl/wget/git
- Language-specific toolchain only
- Python 3 for verifier (if not already Python)

**Result**: Build times reduced from ~5 minutes to ~30-60 seconds.

### 2. Complexity-Driven Task Selection

**Decision**: Select tasks by complexity metrics, not language diversity.

**Rationale**: The goal is demonstrating MCP tool value. High-complexity tasks (large context, many files, architectural reasoning) benefit most from intelligent code search.

**Implementation**: Scoring formula in select_tasks.py:
```
score = 0.3 * normalized_context + 0.3 * normalized_files + 0.4 * category_bonus
```

Category bonuses prioritize tasks requiring codebase-wide understanding.

### 3. JSONL Intermediate Format

**Decision**: Extract raw scenarios to JSONL before adapter processing.

**Rationale**:
- Separates data extraction from task generation
- JSONL is fast to scan and filter
- Enables reuse for different selection criteria
- Matches pattern used by other adapters

### 4. Keyword-Based Verification

**Decision**: Use keyword overlap scoring instead of LLM-based evaluation.

**Rationale**:
- Fast and deterministic
- No API costs or latency
- Sufficient for initial benchmarking
- Can be upgraded to LLM-judge later

**Implementation**: verify.py computes F1 score of keywords between solution and ground truth, plus bonuses for file references and code blocks.

### 5. Project File Mapping

**Decision**: Map scenario ID prefix to generated project directory.

**Rationale**: Scenarios follow naming pattern `{lang}_{domain}_{complexity}_{num}_{category}_{difficulty}_{variant}`. The prefix up to category identifies the project in `data/generated/`.

**Implementation**: `_get_project_dir()` parses ID to find matching project, copies first subdirectory (the actual codebase).

## Data Flow

```
1. Raw Data
   data/output/scenarios/python_api_001_bug_investigation_hard_01.json
   data/generated/python_api_001/MyProject/src/...

2. Extraction (extract_dataset.py)
   → locobench_dataset.jsonl (8000 normalized records)

3. Selection (select_tasks.py)
   → selected_tasks.json (top 50 with scores)

4. Generation (run_adapter.py + adapter.py)
   → tasks/python_api_001_bug_investigation_hard_01/
      ├── instruction.md (rendered from template)
      ├── task.toml (metadata populated)
      ├── environment/
      │   ├── Dockerfile (language-specific)
      │   └── project/ (copied from data/generated/)
      └── tests/
          ├── test.sh, verify.py, ground_truth.json
```

## Extension Points

### Adding New Selection Criteria

Modify `CATEGORY_BONUSES` and thresholds in select_tasks.py:

```python
CATEGORY_BONUSES = {
    "architectural_understanding": 1.0,
    "cross_file_refactoring": 0.9,
    # Add new categories or adjust weights
}
```

### Custom Verifier

Replace verify.py with LLM-based evaluation:

```python
# In verify.py, replace compute_keyword_overlap with:
def evaluate_with_llm(solution, ground_truth):
    # Call LLM API for semantic comparison
    pass
```

### New Languages

Add to `lang_installs` dict in `_generate_dockerfile()`:

```python
"kotlin": """# Install Kotlin
RUN apt-get update && apt-get install -y kotlin \\
    && rm -rf /var/lib/apt/lists/*
""",
```

## Testing

See [SMOKE_TEST_RESULTS.md](SMOKE_TEST_RESULTS.md) for validation testing:
- Adapter generates correct Harbor structure
- Tasks run without framework errors
- Identified infrastructure issues (Docker timeouts, podman compatibility)
