# Task: Terraform v1.9.0 to v1.10.0 Migration Guide

## Objective

Analyze the changes between Terraform v1.9.0 and v1.10.0 and produce a comprehensive migration guide for users upgrading from v1.9.0 to v1.10.0.

## Context

The workspace contains two versions of the Terraform codebase:
- **v1.9.0**: implemented in `/workspace/terraform-v1.9.0/` (commit 7637a92)
- **v1.10.0**: implemented in `/workspace/terraform-v1.10.0/` (commit 24236f4)

Your task is to identify breaking changes and behavioral changes that affect users, then document migration steps.

## Required Analysis

Your migration guide must cover:

1. **S3 Backend Changes**
   - Removal of deprecated IAM role assumption attributes
   - Migration to `assume_role` block syntax
   - New S3 native state locking support

2. **Moved Blocks Syntax Changes**
   - New requirement to prepend `resource.` identifier when referencing resources with type names matching top-level blocks/keywords
   - Impact on existing `moved` blocks in configurations

3. **Sensitive Value Handling**
   - Changes to mark propagation in conditional expressions
   - When sensitive marks are now preserved (previously lost)
   - How to use `nonsensitive()` to override when needed

4. **Ephemeral Resources and Values** (new feature with migration implications)
   - Introduction of ephemeral input variables and outputs
   - New ephemeral resource mode
   - Impact on secret handling in state files

## Expected Output

Write your migration guide to `/workspace/documentation.md` with the following structure:

1. **Overview** - Summary of the upgrade and major themes
2. **Breaking Changes** - Each breaking change with:
   - What changed and why
   - Before/after code examples
   - Step-by-step migration instructions
   - Common pitfalls to avoid
3. **New Features with Migration Impact** - Features that change how users should write Terraform
4. **Testing Your Migration** - How to validate the upgrade was successful
5. **Rollback Guidance** - How to safely rollback if needed

## Evaluation

Your review will be evaluated on detection accuracy and fix quality.

## Tips

- Compare the two version directories to identify changes in specific files
- Look for UPGRADE notes in release documentation
- Examine test files to understand behavioral changes
- Check for deprecation warnings and removed features
- Pay attention to changes in internal/backend/remote-state/s3/, internal/terraform/node_resource_abstract.go, and lang/marks/ directories

Good luck!
