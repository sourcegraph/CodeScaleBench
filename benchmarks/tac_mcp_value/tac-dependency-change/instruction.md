# Update Dependency Versions

**Repository:** OpenHands (via Wiki)  
**Difficulty:** MEDIUM  
**Category:** tac_mcp_value  
**Task Type:** Dependency Management

## Description

Navigate to the company wiki to find the OpenHands repository, clone it, and update
specific Python package versions. This tests navigation skills and understanding of
Python dependency management.

**Why this benefits from MCP:**
- Finding the correct repository from documentation
- Understanding how dependencies are used in the codebase
- Verifying version compatibility before updating
- Understanding the project structure to properly update lockfiles

## Task

1. Find the OpenHands repository from wiki http://the-agent-company.com:8929/root/doc/-/wikis
2. Clone the newly changed repository to /workspace
3. Update the dependency tree-sitter version from 0.21.3 to 0.23.2 and zope-interface 
   version from 7.0.3 to 7.1.1 in pyproject.toml
4. Update the poetry.lock file accordingly
5. Update your local poetry environment to the new package versions

## Success Criteria

✅ Correct repository identified from wiki  
✅ Repository cloned to /workspace  
✅ pyproject.toml updated with new versions  
✅ poetry.lock updated  
✅ Poetry environment updated with new packages

## Notes

- This task requires navigating company documentation
- Each checkpoint is worth 1 point (5 total)
