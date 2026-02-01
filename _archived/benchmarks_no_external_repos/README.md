# Benchmarks Without External Repositories

These benchmarks are **self-contained** and do not clone or reference external codebases. They are not suitable for testing MCP/Deep Search value since there's no external code to index.

## Included Benchmarks

| Benchmark | Description | Why No External Repo |
|-----------|-------------|---------------------|
| **ainativebench** | AINativeBench synthetic test cases | Tasks use synthetic code snippets, not real repositories |
| **devai** | DevAI greenfield development | Tasks ask agents to build from scratch |
| **prdbench** | PRD-based implementation | Tasks implement PRDs without reference code |
| **hello_world_test** | Test harness validation | Simple test tasks |

## When to Use These

- Testing agent capabilities **without** code search tools
- Baseline comparisons of raw agent performance
- Validating harness/infrastructure

## Moving Back

If a benchmark is later updated to use external repositories, move it back:

```bash
mv benchmarks/no_external_repos/<benchmark> benchmarks/
```
