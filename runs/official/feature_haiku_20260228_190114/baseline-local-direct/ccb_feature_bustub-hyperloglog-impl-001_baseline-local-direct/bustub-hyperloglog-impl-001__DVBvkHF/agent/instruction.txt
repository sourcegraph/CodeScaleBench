# Implement HyperLogLog Algorithm

**Repository:** bustub (TheAgentCompany GitLab)
**Difficulty:** HARD
**Category:** ccb_tac
**Task Type:** Algorithm Implementation

## Description

Implement the HyperLogLog probabilistic data structure for cardinality estimation in the
bustub database system. This requires understanding the existing codebase structure,
following coding conventions, and implementing the algorithm across 4 files.

## Task

Clone http://the-agent-company.com:8929/root/bustub to /workspace folder and complete
http://the-agent-company.com:8929/root/bustub/-/issues/759 locally.

Specifically, complete 4 files:
- `bustub/src/include/primer/hyperloglog.h`
- `bustub/src/include/primer/hyperloglog_presto.h`
- `bustub/src/primer/hyperloglog.cpp`
- `bustub/src/primer/hyperloglog_presto.cpp`

To ensure compatibility of testing across different operating systems, please change
the line `hash = ((hash << 5) ^ (hash >> 27)) ^ bytes[i];` in your local file
`src/include/common/util/hash_util.h` to:
`hash = ((hash << 5) ^ (hash >> 27)) ^ static_cast<signed char>(bytes[i]);`

## Success Criteria

[x] Repository cloned successfully
[x] All 4 implementation files completed
[x] Unit tests pass (10 tests, graded by pass count)

## Notes

- This task uses TheAgentCompany's pre-built environment
- Deterministic grading via unit tests
- Score is based on number of passing tests (each test worth 0.5 points)
