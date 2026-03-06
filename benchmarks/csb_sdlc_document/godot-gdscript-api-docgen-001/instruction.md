# Task: Document GDScript VM Bytecode Instruction Set

## Objective
Create internal developer documentation for the GDScript virtual machine bytecode instruction set, covering opcode definitions, operand formats, and execution semantics.

## Steps
1. Find the GDScript VM implementation in `modules/gdscript/`
2. Identify the opcode definitions (likely an enum in a header file)
3. Study the bytecode interpreter dispatch loop
4. Study the compiler that generates bytecodes
5. Create `docs/gdscript_vm_reference.md` in `/workspace/` with:
   - VM architecture overview (stack-based vs register-based)
   - Complete opcode table with categories (arithmetic, control flow, member access, calls)
   - Operand format for each instruction category
   - Function call convention (how arguments are passed)
   - Local variable and member variable access patterns
   - Type system interaction (Variant types)

## Key Reference Files
- `modules/gdscript/gdscript_vm.cpp` — VM interpreter
- `modules/gdscript/gdscript_compiler.cpp` — bytecode generation
- `modules/gdscript/gdscript_function.h` — opcode definitions

## Success Criteria
- docs/gdscript_vm_reference.md exists
- Covers opcode categories
- Documents function call convention
- References actual source files
