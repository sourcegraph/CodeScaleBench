# Task: Rename NodeAbstractResourceInstance to NodeResourceInstanceBase

## Objective
Rename `NodeAbstractResourceInstance` to `NodeResourceInstanceBase` in Terraform's
internal graph node hierarchy to follow Go naming conventions (avoiding "Abstract").

## Requirements

1. **Rename the struct** in `internal/terraform/node_resource_abstract_instance.go`:
   - `type NodeAbstractResourceInstance struct` → `type NodeResourceInstanceBase struct`
   - Rename the file to `node_resource_instance_base.go` (optional)

2. **Update all references** (10+ call sites):
   - Embedding in other node types
   - Method receivers
   - Type assertions and casts
   - Graph builder functions

3. **Update receiver methods** on the struct

## Key Reference Files
- `internal/terraform/node_resource_abstract_instance.go` — struct definition
- `internal/terraform/node_resource_apply_instance.go` — embeds the struct
- `internal/terraform/node_resource_plan_instance.go` — embeds the struct
- `internal/terraform/node_resource_destroy.go` — references

## Success Criteria
- `NodeAbstractResourceInstance` no longer used as struct name
- `NodeResourceInstanceBase` used instead
- Embedding sites updated
- Method receivers updated
