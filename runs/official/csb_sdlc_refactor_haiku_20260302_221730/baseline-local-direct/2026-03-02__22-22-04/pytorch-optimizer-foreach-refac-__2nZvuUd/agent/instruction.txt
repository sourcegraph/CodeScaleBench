# Task: Extract Shared Foreach Optimizer Step

## Objective
Extract the repeated `_multi_tensor_*` foreach optimization patterns from individual
optimizer files (sgd.py, adam.py, adamw.py, etc.) into a shared
`torch/optim/_foreach.py` module.

## Requirements

1. **Create `torch/optim/_foreach.py`**:
   - `_foreach_optimizer_step(params, grads, step_fn, **kwargs)` function
   - Common foreach/fused parameter handling logic
   - Shared gradient scaling and clipping utilities

2. **Update optimizer files** to use the shared module:
   - `torch/optim/sgd.py`
   - `torch/optim/adam.py`
   - `torch/optim/adamw.py`
   - Others that have `_multi_tensor_` functions

3. **Keep backward compatibility**: existing public APIs unchanged

## Key Reference Files
- `torch/optim/sgd.py` — `_multi_tensor_sgd` function
- `torch/optim/adam.py` — `_multi_tensor_adam` function
- `torch/optim/adamw.py` — `_multi_tensor_adamw` function
- `torch/optim/_functional.py` — functional optimizer implementations

## Success Criteria
- `torch/optim/_foreach.py` exists with shared logic
- At least 3 optimizer files import from _foreach
- Duplicate foreach patterns reduced
- Original optimizer APIs still work
