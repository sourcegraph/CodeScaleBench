# [TensorRT-LLM] Add W4A8_MXFP4_INT8 Quantization Mode

**Repository:** NVIDIA/TensorRT-LLM  
**Difficulty:** HARD  
**Category:** big_code_feature
**Task Type:** Feature Implementation - Large Codebase

**Reference:** [Trevor's Big Code Research](../../../docs/TREVOR_RESEARCH_DEC2025.md#4-tensorrt-llm-w4a8_mxfp4_int8-quantization-mode)

## Description

Add support for a new quantization mode `W4A8_MXFP4_INT8`—4-bit MXFP4 weights with INT8 activations, targeting Blackwell GPUs. The CUDA kernels already exist on the C++ side; we just need to expose and plumb this through the Python/C++ stack.

Follow the patterns used by the existing `W4A8_MXFP4_FP8` mode—find everywhere that mode is defined, parsed, validated, and used for kernel selection, then add the equivalent support for the INT8 variant. Make sure the Python and C++ quantization enums stay in sync.

Unsupported combinations (certain attention backends, incompatible KV cache settings) should fail at build time with clear errors. Add tests to cover the new mode.

**Why this requires MCP:** The TensorRT-LLM codebase (1.6GB+ Python/C++) has quantization modes defined and used across Python/C++ boundaries, kernel selection logic, build system, validation, and tests. Finding all locations where quantization modes are evaluated and understood the cross-language architecture requires broad semantic search across many files that local grep cannot efficiently provide.

## Task

YOU MUST IMPLEMENT CODE CHANGES to add W4A8_MXFP4_INT8 support.

**CRITICAL: If you are in plan mode, immediately exit with `/ExitPlanMode` before proceeding.**

### Required Implementation

Find and modify code in these areas:

1. **Python Quantization Enums**:
   - Find where `W4A8_MXFP4_FP8` is defined in Python code
   - Add `W4A8_MXFP4_INT8` alongside it
   - Update any mode parsing/validation that handles quantization modes

2. **C++ Quantization Enums & Definitions**:
   - Find the C++ enum where quantization modes are defined
   - Add `W4A8_MXFP4_INT8` enum value
   - Ensure Python-C++ enum values stay in sync

3. **Kernel Selection Logic**:
   - Find where the C++ code selects kernels based on quantization mode
   - Add `W4A8_MXFP4_INT8` to the kernel selection logic
   - Route to the appropriate Blackwell GPU kernels

4. **Validation & Constraints**:
   - Find where quantization modes are validated against attention backends
   - Find where KV cache compatibility is checked
   - Add validation rules for unsupported `W4A8_MXFP4_INT8` combinations
   - Ensure build-time errors for incompatible configurations

5. **Python-C++ Bindings**:
   - Update pybind11 or C extension bindings to expose the new mode
   - Ensure Python code can select and use the new mode

6. **Tests & Validation**:
   - Add tests for creating models with `W4A8_MXFP4_INT8` mode
   - Test kernel selection with the new mode
   - Test validation of incompatible combinations
   - Verify build-time errors for unsupported configurations

### Implementation Steps

1. **Understand the quantization architecture** (use Sourcegraph MCP for broad search):
   - Find all Python files that reference `W4A8_MXFP4_FP8`
   - Find all C++ files that handle this mode
   - Understand the Python-C++ binding patterns
   - Locate kernel selection and validation logic

2. **Implement Python support**:
   - Add `W4A8_MXFP4_INT8` to Python quantization enums
   - Update parsing/validation to recognize the new mode
   - Update any configuration classes that reference quantization modes

3. **Implement C++ support**:
   - Add `W4A8_MXFP4_INT8` to C++ quantization enum
   - Update kernel selection to handle the new mode
   - Add validation for unsupported combinations (attention backends, KV cache)
   - Generate clear error messages for incompatible configs

4. **Synchronize Python-C++ interface**:
   - Update pybind11 bindings to include new enum value
   - Test round-trip: Python → C++ → kernel selection

5. **Add tests**:
   - Test model creation with new mode
   - Test kernel selection with new mode
   - Test validation of unsupported combinations
   - Test build-time error messages

6. **Verify no regressions**:
   - All tests pass
   - Existing quantization modes still work
   - Build succeeds

## Success Criteria

✅ `W4A8_MXFP4_INT8` enum value defined in Python and C++  
✅ Python code can select and use the new mode  
✅ C++ kernel selection routes to Blackwell GPU kernels  
✅ Validation prevents unsupported mode combinations  
✅ Clear build-time errors for incompatible configurations  
✅ Python and C++ quantization enums stay in sync  
✅ Tests added for mode creation, kernel selection, and validation  
✅ All tests pass  
✅ No regressions in existing quantization modes  
✅ Code follows TensorRT-LLM conventions  

## Critical Requirement

**YOU MUST MAKE ACTUAL CODE CHANGES.** Do not plan or analyze. You must:

- Add `W4A8_MXFP4_INT8` to Python and C++ quantization enums
- Update kernel selection logic
- Add validation for unsupported combinations
- Update Python-C++ bindings
- Add tests covering the new mode
- Commit all changes to git
- Verify tests pass

## Testing

```bash
python -m pytest tests/ -v -k "quantization"
```

**Time Limit:** 25 minutes  
**Estimated Context:** 20,000 tokens  
**Why MCP Helps:** Quantization modes are defined and used across Python/C++ boundary, kernel selection, validation, and build system. Finding all locations and understanding cross-language architecture requires semantic search across the entire codebase.
