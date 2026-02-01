#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The solution involves changes across several files, demonstrating a successful decoupling.

-   **`ledgerquest/engine/physics/interface.py` (New File):**
    ```python
    from abc import ABC, abstractmethod
    from typing import List
    from ledgerquest.engine.ecs.entity import Entity

    class AbstractPhysicsSimulator(ABC):
        @abstractmethod
        def add_body(self, entity: Entity):
            ...

        @abstractmethod
        def remove_body(self, entity_id: int):
            ...

        @abstractmethod
        def step(self, delta_time: float):
            ...

        @abstractmethod
        def get_collisions(self) -> List[tuple[Entity, Entity]]:
            ...
    ```

-   **`ledgerquest/engine/physics/simulator.py` (Modified):**
    -   `from .interface import AbstractPhysicsSimulator` is added.
    -   The class signature is changed to `class Simulator(AbstractPhysicsSimulator):`.
    -   Methods like `step`, `add_body`, etc., now implement the abstract methods from the interface.

-   **`ledgerquest/services/game_loop/physics_updater.py` (Modified):**
    -   The import `from ledgerquest.engine.physics.simulator import Simulator` is **removed**.
    -   A new import is added: `from ledgerquest.engine.physics.interface import AbstractPhysicsSimulator`.
    -   The `__init__` method is changed to accept the simulator via dependency injection: `def __init__(self, ecs_registry, physics_simulator: AbstractPhysicsSimulator):`
    -   All internal uses of `self.physics_simulator` now correctly call methods on the abstract type.

-   **`tests/unit/engine/physics/test_simulator.py` (Modified):**
    -   No functional changes to tests are expected. All tests should pass, verifying that the concrete implementation's logic is sound.

-   **Service Initialization (e.g., `ledgerquest/services/__init__.py`) (Modified):**
    -   The code that instantiates `PhysicsUpdater` is updated to first create a concrete `Simulator` and then pass it into the `PhysicsUpdater`'s constructor. This demonstrates the principle of dependency injection.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
