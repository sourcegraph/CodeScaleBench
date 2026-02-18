# big-code-trt-001: W4A8_MXFP4_INT8 Quantization Mode Support

This repository is large. Use comprehensive search strategies for broad architectural queries rather than narrow, single-directory scopes.

## TensorRT-LLM Architecture Notes

The W4A8_MXFP4_INT8 quantization mode implementation requires understanding:

1. **Python Quantization Enums**: Where quantization modes are defined in Python (likely in `tensorrt_llm/quantization/`)
2. **C++ Quantization Enums**: Where the C++ equivalents are defined (likely in `cpp/` or `tensorrt_llm/models/`)
3. **Kernel Selection Logic**: How C++ code routes to appropriate kernels based on quantization mode
4. **Python-C++ Bindings**: How pybind11 bindings expose C++ enums to Python
5. **Validation & Constraints**: Where mode validation happens (attention backends, KV cache compatibility)
6. **Tests**: How existing quantization mode tests are structured

Find `W4A8_MXFP4_FP8` references across the entire codebase—this tells you all locations where you need to add `W4A8_MXFP4_INT8` support. Critical integration points are spread across Python, C++, and build system files.
