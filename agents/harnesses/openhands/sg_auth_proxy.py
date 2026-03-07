#!/usr/bin/env python3
"""HTTP auth proxy for Sourcegraph MCP.

OpenHands sends 'Authorization: Bearer <token>', but Sourcegraph requires
'Authorization: token <token>'. This proxy listens on localhost and forwards
requests to Sourcegraph with the correct auth header.

Runs as a background daemon inside the container. OpenHands SHTTP config
points at http://localhost:<port> with no api_key; this proxy adds auth.

Deepsearch filtering: deepsearch/deepsearch_read tool calls are intercepted
and rejected with a helpful error because OpenHands' MCP client has a ~30s
internal HTTP timeout that kills long-running deepsearch requests.

Usage:
    SG_MCP_URL=https://sourcegraph.sourcegraph.com/.api/mcp \
    SG_MCP_TOKEN=sgp_... \
    python3 sg_auth_proxy.py [--port 18973]

Writes the actual listen port to /tmp/sg_proxy_port on startup.
"""

import argparse
import json
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import urllib.error

SG_URL = os.environ.get("SG_MCP_URL", "https://sourcegraph.sourcegraph.com/.api/mcp")
SG_TOKEN = os.environ.get("SG_MCP_TOKEN", "")

# Tools that require long-running async calls and will hit OpenHands' ~30s
# internal HTTP timeout, crashing the agent.
_BLOCKED_TOOLS = {"deepsearch", "deepsearch_read"}

# Max retries for upstream 5xx errors
_MAX_RETRIES = 2
_RETRY_DELAY = 2  # seconds


def _is_blocked_tool_call(body: bytes) -> tuple[bool, str]:
    """Check if a JSON-RPC request is calling a blocked tool."""
    try:
        req = json.loads(body)
        if req.get("method") == "tools/call":
            tool_name = req.get("params", {}).get("name", "")
            if tool_name in _BLOCKED_TOOLS:
                return True, tool_name
    except (json.JSONDecodeError, AttributeError):
        pass
    return False, ""


def _make_tool_error_response(body: bytes, tool_name: str) -> bytes:
    """Return a JSON-RPC error response for a blocked tool call."""
    try:
        req = json.loads(body)
        req_id = req.get("id")
    except (json.JSONDecodeError, AttributeError):
        req_id = None
    resp = {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Error: '{tool_name}' is unavailable in this environment "
                        f"due to timeout constraints. Use 'keyword_search' or "
                        f"'nls_search' instead for code discovery."
                    ),
                }
            ],
            "isError": True,
        },
    }
    return json.dumps(resp).encode()


def _forward_request(url, body, headers, method, retries=_MAX_RETRIES):
    """Forward a request to upstream with retry on 5xx errors."""
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    last_exc = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                resp_body = resp.read()
                return resp.status, resp.getheaders(), resp_body
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt < retries:
                last_exc = e
                time.sleep(_RETRY_DELAY)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                last_exc = e
                time.sleep(_RETRY_DELAY)
                continue
            raise
    raise last_exc


class ProxyHandler(BaseHTTPRequestHandler):
    def _build_fwd_headers(self):
        fwd_headers = {}
        for key, val in self.headers.items():
            lower = key.lower()
            if lower in ("host", "authorization", "s", "x-session-api-key"):
                continue
            fwd_headers[key] = val
        if SG_TOKEN:
            fwd_headers["Authorization"] = f"token {SG_TOKEN}"
        fwd_headers["Host"] = urllib.request.urlparse(SG_URL).netloc
        return fwd_headers

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length else b""

        # Block deepsearch tools that will timeout
        blocked, tool_name = _is_blocked_tool_call(body)
        if blocked:
            error_body = _make_tool_error_response(body, tool_name)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(error_body)))
            self.end_headers()
            self.wfile.write(error_body)
            return

        fwd_headers = self._build_fwd_headers()

        try:
            status, resp_headers, resp_body = _forward_request(
                SG_URL, body, fwd_headers, "POST"
            )
            self.send_response(status)
            for key, val in resp_headers:
                if key.lower() not in ("transfer-encoding", "connection"):
                    self.send_header(key, val)
            self.end_headers()
            self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            err_body = e.read() if e.fp else b""
            self.wfile.write(err_body)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(str(e).encode())

    def do_GET(self):
        fwd_headers = self._build_fwd_headers()

        try:
            status, resp_headers, resp_body = _forward_request(
                SG_URL, None, fwd_headers, "GET"
            )
            self.send_response(status)
            for key, val in resp_headers:
                if key.lower() not in ("transfer-encoding", "connection"):
                    self.send_header(key, val)
            self.end_headers()
            self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            self.wfile.write(e.read() if e.fp else b"")
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def log_message(self, format, *args):
        # Suppress request logging to keep container logs clean
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18973)
    args = parser.parse_args()

    server = HTTPServer(("127.0.0.1", args.port), ProxyHandler)
    port = server.server_address[1]

    # Write port for config discovery
    with open("/tmp/sg_proxy_port", "w") as f:
        f.write(str(port))

    print(f"SG auth proxy listening on 127.0.0.1:{port} -> {SG_URL}", flush=True)
    if _BLOCKED_TOOLS:
        print(f"  Blocked tools: {', '.join(sorted(_BLOCKED_TOOLS))}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
