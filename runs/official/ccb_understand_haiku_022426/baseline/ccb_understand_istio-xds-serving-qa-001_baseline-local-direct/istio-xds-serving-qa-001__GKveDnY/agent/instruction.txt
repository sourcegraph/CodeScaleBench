# Architecture Q&A: Istio Pilot xDS Serving

**Repository:** istio/istio
**Task Type:** Architecture Q&A (investigation only — no code changes)

## Background

Istio's Pilot component is the control plane that translates high-level Kubernetes resources (VirtualService, DestinationRule, ServiceEntry, Gateway) into low-level Envoy xDS configuration. Understanding how Pilot watches Kubernetes resources, builds an internal service model, and serves xDS responses to Envoy proxies is essential for working with the Istio codebase.

## Questions

Answer ALL of the following questions about Istio Pilot's xDS serving architecture:

### Q1: Config Ingestion Pipeline

How does Pilot watch and ingest Kubernetes custom resources (VirtualService, DestinationRule, ServiceEntry)?
- What component watches CRDs and how does it implement the `ConfigStoreController` interface?
- How are config change events queued and delivered to the xDS serving layer?
- What role does the aggregate service registry play in merging multiple service sources?

### Q2: Internal Service Model

How does Pilot translate platform-specific resources into its internal model?
- What are the key internal model types that represent services and endpoints?
- How does a Kubernetes Service get converted to the internal model, and how does a ServiceEntry differ?
- What is `PushContext` and what configuration indexes does it maintain?

### Q3: xDS Generation and Dispatch

When a configuration change occurs, how does Pilot generate and deliver xDS responses to connected Envoy proxies?
- How does `DiscoveryServer` receive config updates and debounce rapid changes?
- What is the generator architecture — how are CDS, EDS, LDS, and RDS generators registered and dispatched?
- How does `pushXds` select the correct generator for each resource type?

### Q4: Resource Translation

How do specific Istio resources map to Envoy xDS resource types?
- How does a DestinationRule's traffic policy translate into Envoy Cluster settings (CDS)?
- How does a VirtualService translate into Envoy route configuration (RDS)?
- What component builds the `ClusterLoadAssignment` for endpoint discovery (EDS)?

## Output Requirements

Write your answer to `/logs/agent/investigation.md` with the following structure:

```
# Istio Pilot xDS Serving Architecture

## Q1: Config Ingestion Pipeline
<answer with specific file paths, type names, and function references>

## Q2: Internal Service Model
<answer with specific file paths, type names, and function references>

## Q3: xDS Generation and Dispatch
<answer with specific file paths, type names, and function references>

## Q4: Resource Translation
<answer with specific file paths, type names, and function references>

## Evidence
<consolidated list of supporting file paths and line references>
```

## Constraints

- Do NOT modify any source files
- Cite specific files, types, and functions — avoid vague or speculative answers
- Focus on the `pilot/pkg/xds/`, `pilot/pkg/model/`, `pilot/pkg/config/`, and `pilot/pkg/networking/` directories
