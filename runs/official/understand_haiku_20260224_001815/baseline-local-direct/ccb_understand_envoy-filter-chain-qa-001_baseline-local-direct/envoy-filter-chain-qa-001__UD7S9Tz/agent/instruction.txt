# Architecture Q&A: Envoy HTTP Filter Chain

**Repository:** envoyproxy/envoy
**Task Type:** Architecture Q&A (investigation only — no code changes)

## Background

Envoy is a high-performance service proxy that processes HTTP requests through a layered filter architecture. Understanding how a request flows from initial TCP accept through to the upstream server is fundamental to working with Envoy's codebase.

## Questions

Answer ALL of the following questions about Envoy's HTTP request processing pipeline:

### Q1: Listener to Connection Manager

When a downstream client opens a TCP connection to Envoy, how does the listener hand off the connection to the HTTP connection manager? Specifically:
- What mechanism selects which network filter chain to use for an incoming connection?
- How is the HTTP connection manager (`ConnectionManagerImpl`) installed as a network filter?
- What happens in `onData()` when the first bytes arrive?

### Q2: HTTP Filter Chain Creation and Iteration

Once HTTP request headers are parsed, how does Envoy build and iterate through the HTTP filter chain?
- At what point in request processing is the HTTP filter chain created?
- In what order are decoder filters invoked vs. encoder filters?
- What return values can a filter use to control iteration (stop, continue, buffer)?

### Q3: Router and Upstream

How does the router filter (the terminal HTTP filter) forward requests to upstream servers?
- How does the router obtain the target cluster and select a specific upstream host?
- What is the role of `UpstreamRequest` and the upstream filter chain?
- How does the response flow back through the filter chain to the downstream client?

### Q4: Architectural Boundaries

Explain the distinction between these two "filter chain" concepts in Envoy:
- The network-level filter chain (managed by `FilterChainManager`)
- The HTTP-level filter chain (managed by `FilterManager`)

Why are they separate, and how do they relate to each other?

## Output Requirements

Write your answer to `/logs/agent/investigation.md` with the following structure:

```
# Envoy HTTP Filter Chain Architecture

## Q1: Listener to Connection Manager
<answer with specific file paths, class names, and function references>

## Q2: HTTP Filter Chain Creation and Iteration
<answer with specific file paths, class names, and function references>

## Q3: Router and Upstream
<answer with specific file paths, class names, and function references>

## Q4: Architectural Boundaries
<answer with specific file paths, class names, and function references>

## Evidence
<consolidated list of supporting file paths and line references>
```

## Constraints

- Do NOT modify any source files
- Cite specific files, classes, and functions — avoid vague or speculative answers
- Focus on the `source/common/http/`, `source/common/router/`, and `source/common/listener_manager/` directories
