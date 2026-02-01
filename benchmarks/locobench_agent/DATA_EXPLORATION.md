# LoCoBench-Agent Dataset Exploration

This document describes the structure and contents of the LoCoBench-Agent dataset for the Harbor adapter implementation.

## Directory Structure

```
data/
├── generated/              # 1000 synthetic code projects
│   ├── <project_id>/       # e.g., c_api_gateway_easy_009
│   │   ├── <project_name>/ # e.g., EduGate_ScholarLink (actual code files)
│   │   └── project_metadata.json
│   └── ...
│
└── output/
    ├── scenarios/          # 8000 task scenario JSON files
    │   └── <scenario_id>.json
    │
    ├── agent_scenarios/    # 8000 extended multi-turn agent scenarios
    │   └── <scenario_id>.json
    │
    └── validation/
        └── test_suites/    # 8000 test suite definitions
            └── <scenario_id>_tests.json
```

## Scenario File Format (data/output/scenarios/*.json)

Each scenario file contains a single task definition with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (e.g., `c_api_gateway_easy_009_architectural_understanding_expert_01`) |
| `task_category` | string | One of 8 categories (see below) |
| `difficulty` | string | `easy`, `medium`, `hard`, or `expert` |
| `title` | string | Human-readable task title |
| `description` | string | Detailed description of the task context and requirements |
| `context_files` | array | List of file paths in the synthetic project (uses `//` as separator) |
| `context_length` | integer | Total token count of all context files |
| `task_prompt` | string | The actual task/question for the agent to solve |
| `expected_approach` | string | How an expert would approach the task |
| `ground_truth` | string or object | Expected answer/solution (format varies by task category) |
| `evaluation_criteria` | array | List of criteria for judging responses |
| `metadata` | object | Additional info including files_count, coverage metrics, timestamp |

### Sample Scenario JSON

```json
{
  "id": "c_api_gateway_easy_009_architectural_understanding_expert_01",
  "task_category": "architectural_understanding",
  "difficulty": "expert",
  "title": "Architectural Refactoring for Dynamic Route Configuration",
  "description": "EduGate ScholarLink is an API gateway...",
  "context_files": [
    "EduGate_ScholarLink//src//main.c",
    "EduGate_ScholarLink//src//components//router.c",
    "EduGate_ScholarLink//include//edugate.h",
    ...
  ],
  "context_length": 128233,
  "task_prompt": "Your task is to analyze the existing architecture...",
  "expected_approach": "An expert developer would approach this...",
  "ground_truth": "The core of a correct solution involves...",
  "evaluation_criteria": [
    "**Analysis Correctness:** Accurately identifies...",
    "**Architectural Viability:** Proposes a sound...",
    ...
  ],
  "metadata": {
    "context_length": 128233,
    "files_count": 11,
    "information_coverage": 0.95,
    "coverage_range": [0.8, 1.0],
    "generation_timestamp": "2025-08-05T15:07:11.561371"
  }
}
```

## Task Categories (8 total)

The dataset contains 8 distinct task categories, each representing a different type of software engineering challenge:

1. **architectural_understanding** - Analyze and propose architectural changes or refactoring
2. **bug_investigation** - Identify root causes of bugs from symptoms and propose fixes
3. **code_comprehension** - Understand and explain how existing code works
4. **cross_file_refactoring** - Refactor code that spans multiple files
5. **feature_implementation** - Add new functionality to existing codebase
6. **integration_testing** - Design or implement integration tests
7. **multi_session_development** - Tasks requiring iterative development across sessions
8. **security_analysis** - Identify vulnerabilities and propose security improvements

## Programming Languages (10 total)

Tasks span 10 programming languages, identified by the prefix in the scenario ID:

- `c` - C
- `cpp` - C++
- `csharp` - C#
- `go` - Go
- `java` - Java
- `javascript` - JavaScript
- `php` - PHP
- `python` - Python
- `rust` - Rust
- `typescript` - TypeScript

## Dataset Statistics

- **Total scenarios**: 8,000 task files
- **Synthetic projects**: 1,000 generated codebases
- **Tasks per project**: 8 (one per task category)
- **Difficulty levels**: easy, medium, hard, expert
- **Context length range**: Varies from ~40K to 600K+ tokens

## ID Format Convention

Scenario IDs follow the pattern:
```
{language}_{domain}_{complexity}_{project_num}_{task_category}_{difficulty}_{variant}
```

Example: `python_api_gateway_expert_045_bug_investigation_hard_01`
- Language: `python`
- Domain: `api_gateway`
- Project complexity: `expert`
- Project number: `045`
- Task category: `bug_investigation`
- Task difficulty: `hard`
- Variant: `01`

## Extended Agent Scenarios (data/output/agent_scenarios/)

The `agent_scenarios/` folder contains extended versions of each scenario designed for multi-turn agent evaluation. These include:

- `scenario_id` - Matches the base scenario
- `conversation_phases` - Structured phases for agent interaction:
  1. **exploration** - Code exploration phase
  2. **analysis** - Deep analysis phase
  3. **implementation** - Implementation phase
  4. **documentation** - Documentation creation phase
- `dynamic_prompts` - Context-aware follow-up prompts
- `max_turns_in_phase` - Turn limits per phase

## Validation Test Suites (data/output/validation/test_suites/)

Each scenario has a corresponding test suite JSON with evaluation tests:

- **compilation** - Syntax validation, import resolution, type checking
- **unit** - Function signatures, error handling, input validation, output correctness
- **integration** - Module integration, database integration, API integration
- **performance** - Execution time, memory usage, scalability
- **security** - Injection prevention, input sanitization, access control

## Key Fields for Task Selection

For selecting high-complexity tasks that demonstrate MCP value:

1. **context_length** - Higher values indicate more complex projects requiring better context management
2. **metadata.files_count** - More files suggest cross-file reasoning requirements
3. **task_category** - Some categories inherently require more complex reasoning
4. **difficulty** - Expert/hard tasks are more challenging

## Notes for Adapter Implementation

1. **File Path Format**: Context file paths use `//` as separator, needs normalization to `/`
2. **Ground Truth Format**: Varies by task category (string for analysis tasks, object for bug investigation)
3. **Language Parsing**: Extract from ID prefix (first `_`-separated token)
4. **Project Location**: Match project from scenario ID prefix (e.g., `c_api_gateway_easy_009`) to find code in `generated/`
