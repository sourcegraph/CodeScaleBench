# Data Flow Q&A: Envoy Request Routing

**Repository:** envoyproxy/envoy
**Task Type:** Data Flow Q&A (investigation only — no code changes)

## Background

Envoy is a high-performance proxy that routes HTTP requests from downstream clients to upstream services. Understanding the complete path from the initial TCP accept through filter processing to the final upstream connection is critical for working with Envoy's architecture.

## Task

Trace the complete path of a single HTTP request from the moment a downstream client TCP connection is accepted through filter chain processing, route resolution, upstream cluster selection, and connection establishment. Identify every key transformation point, component boundary crossing, and state change.

## Questions

Answer ALL of the following questions about Envoy's request routing flow:

### Q1: Listener Accept to Network Filter Chain

When a downstream client establishes a TCP connection to Envoy, how does the request travel from socket accept to network filter processing?

- Which component accepts the incoming TCP connection?
- How does Envoy select which network filter chain to apply based on connection properties?
- At what point does the connection get handed to the HTTP Connection Manager (HCM)?
- What triggers the initial `onData()` call when bytes arrive?

### Q2: HTTP Parsing and Filter Chain Iteration

Once bytes arrive at the HCM, how does Envoy parse HTTP and iterate through filters?

- How does the codec parse the byte stream into HTTP headers/body?
- When is the `ActiveStream` created and how does it relate to filter iteration?
- How does the `FilterManager` determine the order of decoder filter execution?
- What filter return values can stop or continue iteration?

### Q3: Route Resolution and Upstream Selection

When the router filter is invoked, how does it select the upstream destination?

- How does the router determine which route configuration to use?
- What is the sequence of operations that resolves a route entry to a specific upstream cluster?
- How does the router select a specific upstream host from the cluster?
- What triggers the creation of the upstream connection?

### Q4: Upstream Connection and Data Flow

Once an upstream host is selected, how does Envoy establish the connection and forward the request?

- How does the connection pool provide or create an upstream connection?
- What component actually writes the HTTP request to the upstream socket?
- How does the response flow back from upstream through the filter chain?
- At what points does the encoder filter chain get invoked vs. the decoder filter chain?

## Output Requirements

Write your answer to `/logs/agent/investigation.md` with the following structure:

```
# Envoy Request Routing Flow

## Q1: Listener Accept to Network Filter Chain
<answer with specific file paths, class names, and method references>

## Q2: HTTP Parsing and Filter Chain Iteration
<answer with specific file paths, class names, and method references>

## Q3: Route Resolution and Upstream Selection
<answer with specific file paths, class names, and method references>

## Q4: Upstream Connection and Data Flow
<answer with specific file paths, class names, and method references>

## Evidence
<consolidated list of supporting file paths and line references>
```

## Constraints

- Do NOT modify any source files
- Cite specific files, classes, and methods — avoid vague or speculative answers
- Focus on the core request path, not error handling or edge cases
- Trace a single successful HTTP/1.1 request without TLS termination
