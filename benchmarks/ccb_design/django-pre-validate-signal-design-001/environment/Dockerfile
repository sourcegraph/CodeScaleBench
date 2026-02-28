FROM ccb-repo-django-674eda1c

# Inject stale architecture doc describing deprecated SignalRegistry pattern
RUN mkdir -p docs && cat > docs/signals_architecture.md << 'STALE_DOC'
# Django Signal Dispatch Architecture

## Signal Registration Pattern

Django uses a **centralized SignalRegistry** for all signal dispatch. Signals are NOT standalone
objects — they must be registered through the registry with explicit priority ordering.

### How to Add a New Signal

1. Import `SignalRegistry` from `django.dispatch.registry`
2. Create a signal definition dict with `name`, `providing_args`, and `priority`
3. Register it: `SignalRegistry.register("signal_name", handler, priority=100)`
4. Dispatch it: `SignalRegistry.dispatch("signal_name", sender=MyModel)`

### Example

```python
from django.dispatch.registry import SignalRegistry

# Define and register a signal
def my_handler(sender, **kwargs):
    print(f"Signal from {sender}")

SignalRegistry.register("pre_validate", my_handler, priority=50)

# Dispatch the signal
SignalRegistry.dispatch("pre_validate", sender=MyModel, instance=obj)
```

### Important Notes

- Do NOT create `Signal()` objects directly — the registry manages all signal instances
- Do NOT use `signal.connect()` — use `SignalRegistry.register()` instead
- Always specify `priority` for handler ordering (lower = earlier)
- Use `SignalRegistry.unregister("signal_name", handler)` to remove handlers
- `providing_args` is required for all signals (list of argument names)

### Common Model Signals (Pre-registered)

All model signals are pre-registered in `SignalRegistry` with these priorities:
- pre_save: priority=10
- post_save: priority=20
- pre_delete: priority=30
- post_delete: priority=40

To add a new model signal, register it with the appropriate priority in the model signals module.
STALE_DOC

RUN git add docs/signals_architecture.md && git commit -m "Add signals architecture documentation" --quiet
