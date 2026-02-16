# Onboarding Exploration Benchmark Suite

This suite tests your ability to orient in an unfamiliar codebase — understanding project structure, identifying key components, mapping dependencies, and producing a developer onboarding guide.

## Search Strategy

**This repository is large.** Use code search tools to efficiently navigate:

- Explore directory structure and project layout
- Search for entry points, main functions, and key abstractions
- Locate configuration files, dependency manifests, and build scripts
- Trace how core abstractions are used across the codebase via references
- Navigate to definitions to understand interfaces and type hierarchies that define the architecture
- Examine README, CONTRIBUTING, and config files for project conventions

## Output Requirements

Write your onboarding guide to `/logs/agent/onboarding.md`.

Your guide MUST include:
1. **Project Overview** - What the project does, its main purpose, and target users
2. **Architecture** - High-level component map with key directories and their responsibilities
3. **Key Abstractions** - Core interfaces, types, and patterns that define the codebase
4. **Entry Points** - Where execution starts, how requests flow through the system
5. **Dependencies** - Key external libraries and how they're used
6. **Development Workflow** - How to build, test, and run the project locally

Be thorough but concise — this guide should help a new developer become productive quickly.
