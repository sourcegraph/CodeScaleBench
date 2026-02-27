# Migration Guide: Envoy External Processing Filter (v1.30 → v1.31)

## Task

Generate a comprehensive migration guide for upgrading the Envoy External Processing (ext_proc) HTTP filter from **version 1.30.0 to version 1.31.0**.

## Context

The workspace contains two versions of the Envoy codebase:
- `/workspace/envoy-v1.30/` - Envoy v1.30.0 (April 2024)
- `/workspace/envoy-v1.31/` - Envoy v1.31.0 (July 2024)

## Scope

Focus specifically on the **External Processing (ext_proc) HTTP filter** configuration and implementation changes. This filter allows external services to process HTTP requests and responses.

Your migration guide should identify and document:

1. **Breaking Changes** - Incompatible configuration or behavioral changes
2. **Deprecated Features** - Fields or modes marked for future removal
3. **New Features** - Added capabilities and configuration options
4. **Configuration Updates** - Required or recommended changes to ext_proc filter configuration
5. **Behavioral Changes** - Modifications to filter behavior or runtime semantics

## Relevant Components

The ext_proc filter is primarily located in:
- Proto definitions: `api/envoy/extensions/filters/http/ext_proc/v3/`
- Implementation: `source/extensions/filters/http/ext_proc/`
- Documentation: `docs/root/configuration/http/http_filters/ext_proc_filter.rst`

## Deliverable

Write your migration guide to `/workspace/documentation.md` in Markdown format with the following sections:

1. **Overview** - Summary of the migration and major changes
2. **Breaking Changes** - Critical incompatible changes requiring action
3. **Deprecated Features** - Features marked for deprecation with migration advice
4. **New Features** - New capabilities and how to use them
5. **Migration Steps** - Step-by-step instructions for upgrading configurations
6. **Testing Recommendations** - How to validate the migration
7. **Rollback Guidance** - How to revert if issues occur

## Requirements

- Provide specific proto field names and types
- Include before/after configuration examples for each breaking change
- Explain the motivation or benefit behind major changes
- Cite specific source files where implementations changed
- Recommend best practices for adopting new features
- Identify common migration pitfalls or edge cases

## Tips

- Compare the two version directories to identify changed proto fields and implementation files
- Search for all API modifications in the ext_proc filter
- Trace configuration usage patterns across both versions
- Look for related documentation updates
