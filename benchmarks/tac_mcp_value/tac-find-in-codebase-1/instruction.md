# Find Answer in Codebase - Context Window PR

**Repository:** llama.cpp (TheAgentCompany GitLab)  
**Difficulty:** MEDIUM  
**Category:** tac_mcp_value  
**Task Type:** Code Navigation & Search

## Description

Search the llama.cpp repository to find which pull request improved the context window
for llama3.1 series models. This is a pure code search/navigation task - exactly what
Sourcegraph MCP excels at.

**Why this benefits from MCP:**
- **This is a PERFECT test case for code search value**
- Requires searching through PR history and code changes
- Semantic understanding of "context window improvements" needed
- Local grep for keywords may miss semantic matches
- Deep Search can understand the intent and find related PRs

## Task

Your colleague Chen Xinyi wants to know which pull requests in llama.cpp 
(http://the-agent-company.com:8929/root/llama.cpp) improves the context window of 
llama3.1 series models. 

Find the most recent related merged pull request number (starting with #) and send 
the number to Chen Xinyi. You can find her on RocketChat (http://the-agent-company.com:3000/).

## Success Criteria

✅ Correct PR number (#8676) found and communicated to Chen Xinyi via RocketChat

## Notes

- This task explicitly tests code navigation and search capabilities
- Strong MCP advantage expected - Deep Search understands semantic queries
- Requires RocketChat interaction to complete
