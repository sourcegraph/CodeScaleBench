# Add New API Endpoint to Copilot Arena Server

**Repository:** copilot-arena-server (TheAgentCompany GitLab)  
**Difficulty:** MEDIUM  
**Category:** tac_mcp_value  
**Task Type:** API Development

## Description

Clone an API server codebase, understand the existing endpoint implementation patterns,
and add a new mock endpoint that mirrors an existing endpoint's response format.

**Why this benefits from MCP:**
- Understanding existing endpoint implementation patterns
- Finding how the `create_pair` endpoint works
- Understanding the API structure and return formats
- Navigating the codebase to find relevant files

## Task

1. Find copilot arena's API server codebase in GitLab 
   (http://the-agent-company.com:8929/root/copilot-arena-server)
2. Clone the server repository to the /workspace folder
3. Start up the API server locally
4. Install the correct requirements by running `pip install -r requirements.txt`
5. Create a new POST endpoint to the server called `mock_create_pair`
6. It should return the same JSON as `create_pair`, except with "test" as both 
   the completions, rather than actually calling any APIs
7. Start the server in the background using:
   ```
   uvicorn app:app --host 0.0.0.0 --port 5000 --workers 1 --log-config log_conf.yaml
   ```

## Success Criteria

✅ Repository cloned successfully  
✅ Server running on port 5000  
✅ mock_create_pair endpoint returns expected JSON format  
✅ Completions in response are "test" strings

## Notes

- This task tests understanding of existing API patterns
- MCP helps quickly understand the create_pair implementation
- Deterministic grading via API response validation
