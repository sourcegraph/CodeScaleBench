# big-code-trt-001: W4A8_MXFP4_INT8 Quantization Mode Support

This repository is large. If a search spans more than a narrow, well-defined set of directories, you **MUST** use Sourcegraph MCP search tools:

- ✅ Use `sg_keyword_search`, `sg_nls_search`, or `sg_deepsearch` for broad architectural queries
- ✅ Use MCP to find all references across the codebase quickly
- ✅ Use MCP to understand patterns and conventions at scale
- ❌ Do NOT use local `grep` or `rg` for cross-module searches
- ❌ Local tools only for narrow, single-directory scopes

## TensorRT-LLM Architecture Notes

The W4A8_MXFP4_INT8 quantization mode implementation requires understanding:

1. **Python Quantization Enums**: Where quantization modes are defined in Python (likely in `tensorrt_llm/quantization/`)
2. **C++ Quantization Enums**: Where the C++ equivalents are defined (likely in `cpp/` or `tensorrt_llm/models/`)
3. **Kernel Selection Logic**: How C++ code routes to appropriate kernels based on quantization mode
4. **Python-C++ Bindings**: How pybind11 bindings expose C++ enums to Python
5. **Validation & Constraints**: Where mode validation happens (attention backends, KV cache compatibility)
6. **Tests**: How existing quantization mode tests are structured

Use MCP to find `W4A8_MXFP4_FP8` references across the entire codebase—this tells you all locations where you need to add `W4A8_MXFP4_INT8` support. Local tools would require multiple targeted searches and might miss critical integration points.
