# Add New API Endpoint to Copilot Arena Server

**Repository:** copilot-arena-server (TheAgentCompany GitLab)  
**Difficulty:** MEDIUM  
**Category:** ccb_tac  
**Task Type:** API Development

## Description

Clone an API server codebase, understand the existing endpoint implementation patterns,
and add a new mock endpoint that mirrors an existing endpoint's response format.


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

[x] Repository cloned successfully  
[x] Server running on port 5000  
[x] mock_create_pair endpoint returns expected JSON format  
[x] Completions in response are "test" strings

## Notes

- This task tests understanding of existing API patterns
- Deterministic grading via API response validation
