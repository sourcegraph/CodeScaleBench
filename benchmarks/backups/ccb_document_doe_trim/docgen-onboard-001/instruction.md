# Task: Generate Developer Onboarding Guide for Istio Control Plane

**Repository:** istio/istio
**Output:** Write your guide to `/workspace/documentation.md`

## Objective

Produce a developer onboarding guide for Istio's control plane. This guide should help a new contributor understand how to build Istio, navigate the codebase, and make their first contribution.

## Scope

Your guide must cover all of the following:

### 1. Build Prerequisites
- Required Go version, tools, and environment variables
- How to clone the repository with all submodules
- How to build the core control plane binaries (`pilot-discovery`, `istiod`)
- How to run the test suite

### 2. Architecture Overview
- Istio's control plane components and their responsibilities (Pilot, Citadel, Galley — now merged into istiod)
- The xDS protocol and how istiod pushes configuration to Envoy proxies
- Key packages: `pilot/pkg/`, `security/pkg/`, `galley/pkg/`
- How the service registry integrates with Kubernetes

### 3. First Contribution Workflow
- How to find good first issues
- How to run linters and pre-commit checks
- How to write and run unit tests for a change
- How to submit a PR (required reviewers, CI gates)

## Quality Bar

- Reference specific Makefile targets, Go packages, or scripts
- Architecture section must explain at least one data flow end-to-end (e.g., service discovery to xDS push)
- Do not fabricate commands — verify against actual Makefile and scripts in the repo

## Anti-Requirements

- Do not simply reproduce the README
- Do not include Kubernetes operator/installation instructions (focus on developer workflow only)
