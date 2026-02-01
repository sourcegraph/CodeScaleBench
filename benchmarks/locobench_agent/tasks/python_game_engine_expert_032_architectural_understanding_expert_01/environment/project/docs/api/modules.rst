.. LedgerQuest Engine API Reference
   =================================
   Documentation for the public Python API exposed by *LedgerQuest Engine*.
   This section is generated automatically from the source code using
   `Sphinx <https://www.sphinx-doc.org/>`_ with the
   `autodoc <https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html>`_
   and `autosummary <https://www.sphinx-doc.org/en/master/usage/extensions/autosummary.html>`_
   extensions.  Each sub-package below is fully type-annotated, unit-tested, and
   adheres to `PEP 8 <https://peps.python.org/pep-0008/>`_ and
   `PEP 257 <https://peps.python.org/pep-0257/>`_ best practices.

   The API surface is *stable* unless otherwise noted.  Breaking changes are
   communicated through semantic-version increments and documented in *CHANGELOG.rst*.


Contents
--------

.. toctree::
   :caption: High-Level Overview
   :maxdepth: 1

   ../../README
   ../../architecture/serverless_design
   ../../architecture/ecs_pattern
   ../../architecture/security

.. toctree::
   :caption: Public Packages
   :maxdepth: 2
   :glob:

   ledgerquest_engine
   ledgerquest_engine.core*
   ledgerquest_engine.ai*
   ledgerquest_engine.physics*
   ledgerquest_engine.level_editor*
   ledgerquest_engine.scripting*
   ledgerquest_engine.assets*
   ledgerquest_engine.network*
   ledgerquest_engine.analytics*
   ledgerquest_engine.serverless*
   ledgerquest_engine.cli*
   ledgerquest_engine.testing*

.. toctree::
   :caption: CLI Commands
   :maxdepth: 1

   ../../cli_reference

.. toctree::
   :caption: Contributing & Internals
   :maxdepth: 1

   ../../CONTRIBUTING
   ../../design/adr/index
   ../../design/coding_standards
   ../../design/testing_strategy


Module Index
------------

.. autosummary::
   :toctree: modules/generated
   :recursive:
   :caption: Complete Module Listing

   ledgerquest_engine
   ledgerquest_engine.core
   ledgerquest_engine.core.entities
   ledgerquest_engine.core.systems
   ledgerquest_engine.core.components
   ledgerquest_engine.physics
   ledgerquest_engine.physics.colliders
   ledgerquest_engine.physics.integrators
   ledgerquest_engine.physics.constraints
   ledgerquest_engine.ai
   ledgerquest_engine.ai.behaviour_trees
   ledgerquest_engine.ai.pathfinding
   ledgerquest_engine.ai.navigation
   ledgerquest_engine.level_editor
   ledgerquest_engine.level_editor.backend
   ledgerquest_engine.level_editor.frontend
   ledgerquest_engine.scripting
   ledgerquest_engine.scripting.bytecode
   ledgerquest_engine.scripting.vm
   ledgerquest_engine.assets
   ledgerquest_engine.assets.loaders
   ledgerquest_engine.assets.serializers
   ledgerquest_engine.network
   ledgerquest_engine.network.websocket
   ledgerquest_engine.network.http
   ledgerquest_engine.analytics
   ledgerquest_engine.analytics.metrics
   ledgerquest_engine.serverless
   ledgerquest_engine.serverless.state_machines
   ledgerquest_engine.serverless.triggers
   ledgerquest_engine.cli
   ledgerquest_engine.testing
   ledgerquest_engine.testing.fixtures
   ledgerquest_engine.testing.integration

Indices and Tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

.. End of file