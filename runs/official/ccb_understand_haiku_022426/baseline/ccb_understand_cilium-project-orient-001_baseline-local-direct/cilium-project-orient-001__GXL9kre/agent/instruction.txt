# Onboarding: Cilium Codebase Orientation

**Repository:** cilium/cilium
**Task Type:** Codebase Orientation (analysis only — no code changes)

## Scenario

You are a new engineer joining a team that works on Cilium, a cloud-native networking, observability, and security platform that uses eBPF. Your manager has asked you to spend your first day exploring the codebase and answering key orientation questions so you can hit the ground running.

## Your Task

Explore the Cilium codebase and answer the following questions. Write your answers to `/logs/agent/onboarding.md`.

### Questions

1. **Main Entry Point**: Where does the cilium-agent binary start execution? Identify the main function, how the CLI is initialized, and what dependency injection framework is used to wire components together.

2. **Core Packages**: Identify at least 5 core packages under `pkg/` and describe what each one is responsible for. Focus on the packages that handle networking policy, the datapath, Kubernetes integration, endpoint management, and eBPF maps.

3. **Configuration Loading**: How does the agent load its configuration? Describe the configuration pipeline: what config formats are supported, what library is used for config binding, and What modules/interfaces define the main config struct?

4. **Test Structure**: How are tests organized in this project? Describe at least 3 different testing approaches used (e.g., unit tests, integration tests, privileged tests, BPF tests). Where do end-to-end tests live?

5. **Network Policy Pipeline**: Trace the path of a CiliumNetworkPolicy from CRD definition to eBPF enforcement. Identify at least 4 stages in this pipeline and name the relevant components or packages involved at each stage (e.g., CRD types, K8s watcher, policy repository, endpoint regeneration, BPF map sync).

6. **Adding a New Network Policy Type**: If you needed to add a new type of network policy rule (e.g., a new L7 protocol filter), which packages and files would you need to modify? Describe the sequence of changes required.

## Output Requirements

Write your answers to `/logs/agent/onboarding.md` with this structure:

```
# Cilium Codebase Orientation

## 1. Main Entry Point
<Your answer>

## 2. Core Packages
<Your answer>

## 3. Configuration Loading
<Your answer>

## 4. Test Structure
<Your answer>

## 5. Network Policy Pipeline
<Your answer>

## 6. Adding a New Network Policy Type
<Your answer>
```

## Constraints

- Do NOT modify any source files
- Do NOT write any code changes
- Your job is exploration and documentation only
- Be specific — include file paths, package names, function names, and struct names where relevant
