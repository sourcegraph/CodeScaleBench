# Dependency Inference Task

## Objective

Edit the build files to include all necessary dependency-related configurations to ensure the project builds and runs successfully.

## Task Information

**Language**: {language}
**Instance ID**: {instance_id}
**Build Files to Edit**: {build_files}

## Environment Specifications

```json
{env_specs}
```

## Instructions

You will need to:

1. **Analyze the project structure** in `/app/repo` to understand the codebase dependencies
2. **Review the source code** to identify all external libraries and packages being used
3. **Edit the build files** (listed above) to add all necessary dependency configurations
4. **Ensure completeness** - include ALL dependencies required for the project to build and run

### Important Notes

- The project may include multiple build files. Ensure you update all of them with the necessary dependency configurations.
- Only edit the files listed in the "Build Files to Edit" section above.
- Limit your edits strictly to dependency configurations within the build files.
- Do NOT skip, omit, or elide any content when editing files.

### Output Format

When you edit a file, you MUST use this exact format:

```
path/to/filename.ext
```
// entire file content ...
// ... goes in between
```
```

Every file edit MUST follow this format:
- First line: the filename with path (no extra markup, punctuation, or comments - JUST the filename with path)
- Second line: opening ```
- ... entire content of the file ...
- Final line: closing ```

**NEVER** skip content using "..." or add comments like "... rest of code..."!

## Evaluation

Your solution will be tested by running the project's CI/CD pipeline to verify that all tests pass with your dependency configurations.
