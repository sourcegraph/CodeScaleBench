# Task: Implement GradientNoiseInjector for PyTorch

## Objective
Create a `GradientNoiseInjector` optimizer wrapper in `torch/optim/` that adds calibrated
Gaussian noise to gradients before the optimizer step, implementing the "Adding Gradient
Noise Improves Learning for Very Deep Networks" technique.

## Requirements

1. **Create `torch/optim/gradient_noise.py`** with:
   - `GradientNoiseInjector` class wrapping any base optimizer
   - `__init__(self, optimizer, eta=0.01, gamma=0.55)` — noise schedule parameters
   - `step(self, closure=None)` — injects noise then delegates to base optimizer
   - Noise variance schedule: `sigma^2 = eta / (1 + t)^gamma` where t is step count
   - Uses `torch.randn_like` for Gaussian noise generation

2. **Register in module**:
   - Add to `torch/optim/__init__.py` exports

3. **Create test file** `test/optim/test_gradient_noise.py`:
   - Test noise injection occurs
   - Test variance decay schedule
   - Test wrapping different optimizers (SGD, Adam)

## Key Reference Files
- `torch/optim/optimizer.py` — Optimizer base class
- `torch/optim/sgd.py` — simple optimizer implementation
- `torch/optim/lr_scheduler.py` — wrapper pattern with step counting
- `torch/optim/swa_utils.py` — optimizer wrapper pattern (AveragedModel)

## Success Criteria
- GradientNoiseInjector class exists in torch/optim/
- Wraps a base optimizer (composition pattern)
- Implements step() with noise injection
- Has eta and gamma parameters for noise schedule
- Test file exists
