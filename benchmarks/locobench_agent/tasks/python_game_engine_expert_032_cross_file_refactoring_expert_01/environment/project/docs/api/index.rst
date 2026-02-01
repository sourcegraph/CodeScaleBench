.. LedgerQuest Engine – API Documentation Root
   ===========================================
   SPDX-License-Identifier: Apache-2.0

LedgerQuest Engine
------------------
A Serverless Business-Grade Game Framework
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section provides the *public* Python API reference for the
`LedgerQuest Engine`_ package.  If you are new to LedgerQuest, start with
the :doc:`../getting_started/index` guide.  For architectural details see
:doc:`../architecture/index`.

.. _LedgerQuest Engine: https://github.com/ledgerquest/engine

Contents
========

.. toctree::
   :maxdepth: 2
   :caption: Package Reference

   ledgerquest_engine.core
   ledgerquest_engine.ecs
   ledgerquest_engine.ai
   ledgerquest_engine.physics
   ledgerquest_engine.rendering
   ledgerquest_engine.networking
   ledgerquest_engine.scripting
   ledgerquest_engine.data
   ledgerquest_engine.cli


Quick-Start (Python)
====================

The snippet below demonstrates how to spin-up a *headless* simulation with
physics and AI systems enabled, all without provisioning any servers.
Everything runs as *stateless* Lambda invocations locally via the
``ServerlessLocal`` test harness.

.. code-block:: python

    from ledgerquest_engine.runtime import ServerlessLocal
    from ledgerquest_engine.ecs import World
    from ledgerquest_engine.ai.behaviour_trees import SeekTarget
    from ledgerquest_engine.physics import RigidBody

    # 1) Stand-up the local, Step-Functions-compatible runtime.
    engine = ServerlessLocal().cold_start()

    # 2) Build a minimal ECS world
    world = World(name="demo-world")

    # 3) Create two entities: a seeker and a target
    seeker = world.spawn(
        "Seeker",
        components=[
            RigidBody(mass=1.2, position=[0, 0, 0]),
            SeekTarget(target_entity_id="target-1"),
        ],
    )

    target = world.spawn(
        "Target",
        entity_id="target-1",
        components=[RigidBody(mass=0.4, position=[10, 0, 0])],
    )

    # 4) Kick-off one game tick
    delta = 1.0 / 60.0  # 60 Hz
    engine.step(world, delta_time=delta)

    # 5) Persist the world state to DynamoDB via the default data-adapter
    world.save()

    print(f"Seeker new position: {seeker[RigidBody].position}")

The above will output something like:

.. code-block:: text

    Seeker new position: [0.166, 0.0, 0.0]

where the exact values depend on the default *force* parameters of the
``SeekTarget`` behaviour tree leaf.

Module Organisation
===================

The LedgerQuest package follows a *layered* folder hierarchy that mirrors
typical AAA game engines but with an added *serverless* twist:

+---------------------+----------------------------------------------+
| Sub-package         | Responsibility                               |
+=====================+==============================================+
| ``core``            | Cross-cutting utilities (config, logging,    |
|                     | error-handling, reflection utilities, etc.)  |
+---------------------+----------------------------------------------+
| ``ecs``             | Entity-Component-System implementation       |
+---------------------+----------------------------------------------+
| ``ai``              | Behaviour-trees, path-finding, decision      |
|                     | graphs, etc.                                 |
+---------------------+----------------------------------------------+
| ``physics``         | Deterministic, fixed-tick simulation of      |
|                     | rigid-bodies and kinematic constraints       |
+---------------------+----------------------------------------------+
| ``rendering``       | GPU/GLTF mesh batching, sprite atlas         |
|                     | generation via AWS Fargate burst workers     |
+---------------------+----------------------------------------------+
| ``networking``      | WebSocket and gRPC transport abstractions,   |
|                     | synchronisation protocols                   |
+---------------------+----------------------------------------------+
| ``scripting``       | Lua/Python hybrid scripting VM front-ends    |
+---------------------+----------------------------------------------+
| ``data``            | Adapters for DynamoDB, S3, Redshift Spectrum |
+---------------------+----------------------------------------------+
| ``cli``             | Developer tooling (level-editor, stress-test |
|                     | harness, deploy scripts)                     |
+---------------------+----------------------------------------------+

Versioning & Stability
======================

All public symbols documented here adhere to `Semantic Versioning 2.0`_.
Breaking API changes are announced one minor version *before* they land
and are *feature-flagged* during transition.

.. _Semantic Versioning 2.0: https://semver.org/

Contributing to the Docs
========================

If you discover inaccuracies, please:

1. Fork the repository.
2. Edit the relevant ``.rst`` or docstring.
3. Run ``make docs`` (requires Poetry & tox).
4. Submit a pull request ☺.

For style conventions we follow `PEP 257 <https://peps.python.org/pep-0257/>`_
for docstrings and `sphinx-contrib/napoleon` for *NumPy* style signatures.

Indices and Tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
