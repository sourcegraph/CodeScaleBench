# LoCoBench-Agent Task Selection Criteria

This document defines the criteria for selecting high-complexity tasks from the LoCoBench-Agent dataset that best demonstrate the value of MCP (Model Context Protocol) tools.

## Selection Philosophy

**Selection is complexity-driven, not language-driven.** We select tasks based on their inherent complexity and the potential for MCP tools to provide measurable benefits, regardless of the programming language. This ensures a diverse, representative sample that truly tests agent capabilities across challenging scenarios.

## Quantitative Metrics

### Minimum Thresholds

Tasks must meet these minimum requirements to be considered:

| Metric | Minimum Value | Rationale |
|--------|--------------|-----------|
| `context_length` | >50,000 tokens | Tasks with substantial context benefit most from intelligent retrieval |
| `files_count` | >5 files | Multi-file tasks require cross-file reasoning |

Tasks below these thresholds are excluded from selection as they don't sufficiently demonstrate MCP value.

## Scoring Formula

Each task is scored using a weighted combination of normalized metrics and category bonuses:

```
score = (context_weight * context_score) + (files_weight * files_score) + (category_weight * category_bonus)
```

### Scoring Weights

| Factor | Weight | Description |
|--------|--------|-------------|
| `context_length` | 0.3 | Normalized context length (relative to max in dataset) |
| `files_count` | 0.3 | Normalized file count (relative to max in dataset) |
| `task_category_bonus` | 0.4 | Category-specific bonus based on MCP value potential |

### Normalization

- `context_score = context_length / max_context_length` (scaled 0-1)
- `files_score = files_count / max_files_count` (scaled 0-1)

## Task Category Bonuses

Not all task categories equally demonstrate MCP value. Categories requiring extensive codebase navigation and cross-file analysis receive higher bonuses:

| Task Category | Bonus | Rationale |
|---------------|-------|-----------|
| `architectural_understanding` | 1.0 | Maximum MCP value - requires understanding system-wide structure, dependencies, and design patterns |
| `cross_file_refactoring` | 0.9 | High MCP value - changes propagate across many files, benefit from intelligent navigation |
| `bug_investigation` | 0.8 | Strong MCP value - requires tracing execution paths, finding related code |
| `security_analysis` | 0.7 | Good MCP value - requires understanding data flow and identifying vulnerable patterns |
| `feature_implementation` | 0.5 | Moderate MCP value - may be localized or span multiple files |
| `code_comprehension` | 0.4 | Lower MCP value - often focused on specific code sections |
| `integration_testing` | 0.3 | Lower MCP value - typically focused on specific integration points |
| `multi_session_development` | 0.3 | Lower MCP value for single evaluation - designed for multi-turn scenarios |

## Selection Process

1. **Filter**: Exclude tasks below minimum thresholds
2. **Score**: Calculate composite score for each remaining task
3. **Rank**: Sort tasks by score descending
4. **Select**: Take top 50 tasks
5. **Verify**: Ensure reasonable distribution across categories and languages (as a sanity check, not as a selection criterion)

## Expected Outcome

The top 50 tasks should:
- Have high context complexity (average >75K tokens)
- Span multiple files (average >8 files)
- Be weighted toward categories that benefit most from MCP tools
- Naturally include a variety of languages due to complexity-driven selection

## Usage

This criteria is implemented in `select_tasks.py`, which:
1. Reads tasks from `locobench_dataset.jsonl`
2. Applies minimum thresholds
3. Calculates scores using the formula above
4. Outputs ranked results to `selected_tasks.json`
