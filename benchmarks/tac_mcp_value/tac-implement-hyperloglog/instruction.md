# Implement HyperLogLog Algorithm

**Repository:** bustub (TheAgentCompany GitLab)  
**Difficulty:** HARD  
**Category:** tac_mcp_value  
**Task Type:** Algorithm Implementation

## Description

Implement the HyperLogLog probabilistic data structure for cardinality estimation in the
bustub database system. This requires understanding the existing codebase structure,
following coding conventions, and implementing the algorithm across 4 files.

**Why this benefits from MCP:** 
- bustub is a complex C++ database codebase with specific patterns
- Understanding how other "primer" exercises are implemented provides templates
- Finding similar hash-based data structures shows expected patterns
- Cross-file dependencies between headers and implementations require navigation

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

✅ Repository cloned successfully  
✅ All 4 implementation files completed  
✅ Unit tests pass (10 tests, graded by pass count)  

## Notes

- This task uses TheAgentCompany's pre-built environment
- Deterministic grading via unit tests
- Score is based on number of passing tests (each test worth 0.5 points)
