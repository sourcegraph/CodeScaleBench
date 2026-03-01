# Data Flow Q&A: Argo CD Sync Reconciliation

**Repository:** argoproj/argo-cd
**Task Type:** Data Flow Q&A (investigation only — no code changes)

## Background

Argo CD is a declarative GitOps continuous delivery tool for Kubernetes. At its core is the sync reconciliation process, which continuously compares desired state (from Git) with live state (in the Kubernetes cluster) and applies changes to eliminate drift. Understanding this pipeline — from Git fetch through manifest generation, diff computation, and cluster synchronization — is essential for working with Argo CD's architecture.

## Task

Trace the complete data flow of how an Application resource is synchronized from initial detection of drift through to cluster state update. Identify every key transformation point, component boundary crossing, and data structure change.

## Questions

Answer ALL of the following questions about Argo CD's sync reconciliation pipeline:

### Q1: Reconciliation Triggering and Git Fetch

When the ApplicationController detects that an Application needs reconciliation, how does it request manifest generation?

- What triggers a reconciliation cycle (periodic refresh, resource change events, manual sync)?
- How does the ApplicationController communicate with the RepoServer to request manifest generation?
- What data structure is passed from controller to reposerver (request format)?
- How does the RepoServer fetch and cache the Git repository at the specified revision?

### Q2: Manifest Generation and Rendering

After the RepoServer fetches the Git repository, how are raw files transformed into Kubernetes manifests?

- How does `GenerateManifests()` identify which config management tool to use (Helm, Kustomize, CMP plugin)?
- What is the sequence of operations that renders raw manifests from the repository?
- What caching mechanisms exist for generated manifests, and what invalidates the cache?
- What data structure is returned from the RepoServer to the controller (response format)?

### Q3: Diff Computation Between Desired and Live State

Once manifests are generated, how does Argo CD compute the diff between desired (Git) and live (cluster) state?

- Which component is responsible for fetching live state from the Kubernetes cluster?
- How does the diff engine normalize resources before comparison?
- What are the different diff strategies (legacy 3-way, structured merge, server-side), and when is each used?
- What data structure represents the diff result, and how does it indicate out-of-sync resources?

### Q4: Sync Operation Execution

When out-of-sync resources are detected, how does Argo CD apply changes to the cluster?

- How are sync phases (PreSync, Sync, PostSync) and waves orchestrated?
- What is the difference between client-side apply (kubectl apply) and server-side apply in Argo CD?
- How does Argo CD determine the order in which resources are applied?
- How is sync status tracked and propagated back to the Application resource status?

## Output Requirements

Write your answer to `/logs/agent/investigation.md` with the following structure:

```
# Argo CD Sync Reconciliation Pipeline

## Q1: Reconciliation Triggering and Git Fetch
<answer with specific file paths, type/interface names, and method references>

## Q2: Manifest Generation and Rendering
<answer with specific file paths, type/interface names, and method references>

## Q3: Diff Computation Between Desired and Live State
<answer with specific file paths, type/interface names, and method references>

## Q4: Sync Operation Execution
<answer with specific file paths, type/interface names, and method references>

## Data Flow Summary
<ordered list of transformation points from Git fetch to cluster sync with data structures at each step>

## Evidence
<consolidated list of supporting file paths and line references>
```

## Constraints

- Do NOT modify any source files
- Cite specific files, packages, types, and methods — avoid vague or speculative answers
- Focus on the core sync reconciliation path, not error handling or edge cases
- Trace a standard automated sync with no special sync options or hooks
