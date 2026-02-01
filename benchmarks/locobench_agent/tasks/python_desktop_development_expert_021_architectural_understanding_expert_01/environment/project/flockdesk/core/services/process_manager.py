```python
"""
flockdesk.core.services.process_manager
=======================================

A high-level supervisor for all out-of-process UI micro-front-ends that make up
the FlockDesk desktop experience.  Every feature (chat, white-board, presence,
etc.) ships as its own executable module and is therefore started, observed,
and torn-down by the :class:`ProcessManager`.

Design goals
------------
1. Non-blocking, `asyncio`-driven life-cycle control so the GUI thread is never
   stalled.
2. Auto-restart semantics with exponential back-off to prevent crash-loops.
3. Rich event publishing so other components (status bar, telemetry, Sentry
   integration, …) are kept in-sync without tight coupling.
4. Cross-platform process launching (Windows / macOS / Linux).

The manager intentionally avoids *business* decisions (e.g. *which* services
to start) – that is delegated to a higher-level orchestrator that reads the
workspace-profile and user-prefs.

Author: FlockDesk Core Team
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
from asyncio.subprocess import Process
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Final, Optional

try:
    # Optional diagnostics
    import sentry_sdk
except ImportError:  # pragma: no cover
    sentry_sdk = None  # type: ignore

# --------------------------------------------------------------------------- #
# Internal lightweight abstractions                                            #
# --------------------------------------------------------------------------- #

class EventBus:
    """
    Very small pub/sub abstraction.  In production we use a more sophisticated
    event-driven backbone, but for the purpose of this module we only need the
    `publish` API.
    """

    def publish(self, topic: str, payload: dict) -> None:
        """Fire-and-forget event."""
        # The real implementation fans out to registered subscribers.
        logging.getLogger(__name__).debug("EventBus.publish(%s, %s)", topic, payload)


@dataclass(slots=True, frozen=True)
class ServiceConfig:
    """Immutable service definition used by :class:`ProcessManager`."""

    # Human readable identifier, must be unique within the ProcessManager.
    name: str

    # Python module path or binary to execute (depending on `is_module`).
    entry_point: str

    # Arbitrary command-line args supplied to the process.
    args: tuple[str, ...] = ()

    # Environment variables that *override* the parent env.
    env: dict[str, str] = field(default_factory=dict)

    # Working directory for the process.
    cwd: Path | None = None

    # If ``True`` we call `python -m <entry_point>`.  Otherwise we execute the
    # given path directly (useful for Rust, Node, or Go based micro-front-ends).
    is_module: bool = True

    # If the process exits unexpectedly and this flag is on, the manager will
    # attempt to restart it with exponential back-off.
    auto_restart: bool = True

    # Maximum number of restarts within `restart_window_s` seconds before giving
    # up (crash-loop prevention).
    max_restarts: int = 5

    # Sliding window (seconds) for restart counting.
    restart_window_s: int = 120


@dataclass
class _RuntimeState:
    """
    Contains *mutable* process state and statistics during runtime.  Separated
    from the frozen :class:`ServiceConfig` for clarity.
    """

    process: Process
    restarts: list[float] = field(default_factory=list)  # epoch timestamps
    manual_stop: bool = False  # True if stop was requested by API


# --------------------------------------------------------------------------- #
# Process Manager                                                              #
# --------------------------------------------------------------------------- #

class ProcessManager:
    """
    Supervises the life-cycle of all feature processes.

    NOTE: All public APIs are coroutine functions to avoid blocking the event
    loop.  The manager should be instantiated *once* (singleton-ish) by the core
    runtime and shared via dependency-injection.
    """

    _POLL_INTERVAL_S: Final[int] = 1

    def __init__(
        self,
        bus: EventBus | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._bus: EventBus = bus or EventBus()
        self._loop: asyncio.AbstractEventLoop = loop or asyncio.get_running_loop()
        self._services: dict[str, ServiceConfig] = {}
        self._runtime: dict[str, _RuntimeState] = {}
        self._monitor_task: Optional[asyncio.Task[Any]] = None
        self._log = logging.getLogger(self.__class__.__name__)
        self._log.debug("ProcessManager initialized.")

    # --------------------------------------------------------------------- #
    # Public API                                                             #
    # --------------------------------------------------------------------- #

    async def register(self, config: ServiceConfig, *, start: bool = False) -> None:
        """
        Register a service configuration (idempotent).  Optionally boot the
        service immediately.
        """
        if config.name in self._services:
            raise ValueError(f"Service '{config.name}' already registered.")

        self._services[config.name] = config
        self._log.info("Registered service %s", config.name)
        self._bus.publish("services.registered", {"name": config.name})

        if start:
            await self.start(config.name)

    async def start(self, name: str) -> None:
        """Spawn the given service if not already running."""
        if name not in self._services:
            raise KeyError(f"Service '{name}' is unknown.")

        if name in self._runtime and self._runtime[name].process.returncode is None:
            self._log.warning("Service %s already running.", name)
            return

        config = self._services[name]
        env = os.environ.copy()
        env.update(config.env)

        cmd = self._build_command(config)
        self._log.debug("Spawning %s: %s", name, " ".join(cmd))
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(config.cwd) if config.cwd else None,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            self._log.error("Failed to start %s: %s", name, exc)
            raise

        self._runtime[name] = _RuntimeState(process=process)
        self._log.info("Service %s started with PID %s", name, process.pid)
        self._bus.publish("services.started", {"name": name, "pid": process.pid})

        # lazily start monitor loop
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = self._loop.create_task(self._monitor())

    async def stop(self, name: str, *, timeout: float = 5.0) -> None:
        """Gracefully terminate a running service."""
        runtime = self._runtime.get(name)
        if not runtime or runtime.process.returncode is not None:
            self._log.info("Service %s not running.", name)
            return

        runtime.manual_stop = True
        proc = runtime.process
        self._log.info("Stopping %s (pid=%s)…", name, proc.pid)
        proc.terminate()

        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self._log.warning("Service %s did not exit in time – killing.", name)
            proc.kill()

        self._log.info("Service %s stopped (rc=%s).", name, proc.returncode)
        self._bus.publish("services.stopped", {"name": name, "returncode": proc.returncode})

    async def restart(self, name: str) -> None:
        """Shortcut combining `stop` + `start`."""
        await self.stop(name)
        await self.start(name)

    async def shutdown(self) -> None:
        """Terminate all running services and cancel monitor loop."""
        self._log.info("ProcessManager shutdown initiated.")
        await asyncio.gather(*(self.stop(name) for name in list(self._runtime.keys())))

        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        self._log.info("ProcessManager shutdown complete.")

    # --------------------------------------------------------------------- #
    # Internals                                                              #
    # --------------------------------------------------------------------- #

    def _build_command(self, cfg: ServiceConfig) -> list[str]:
        if cfg.is_module:
            return [sys.executable, "-m", cfg.entry_point, *cfg.args]
        else:
            return [cfg.entry_point, *cfg.args]

    async def _monitor(self) -> None:
        """
        Background task that polls child processes to detect unexpected exits
        and consumes their stdout/stderr asynchronously.
        """
        self._log.debug("Monitor loop started.")
        while self._runtime:
            await asyncio.sleep(self._POLL_INTERVAL_S)
            for name, state in list(self._runtime.items()):
                proc = state.process

                # Drain streams to avoid deadlocks in case buffers get full.
                await self._drain_streams(name, proc)

                if proc.returncode is None:
                    continue  # still running

                # Process exited – handle bookkeeping
                await self._handle_exit(name, state)

            # compact finished processes
            self._runtime = {n: s for n, s in self._runtime.items() if s.process.returncode is None}
        self._log.debug("Monitor loop finished – no services left to supervise.")

    async def _handle_exit(self, name: str, state: _RuntimeState) -> None:
        rc = state.process.returncode
        crashed = rc != 0 and not state.manual_stop
        self._log.warning("Service %s exited (rc=%s, pid=%s, crashed=%s).",
                          name, rc, state.process.pid, crashed)

        self._bus.publish("services.exited", {
            "name": name,
            "pid": state.process.pid,
            "returncode": rc,
            "crashed": crashed,
        })

        if crashed and self._services[name].auto_restart:
            await self._maybe_restart(name, state)
        elif crashed and sentry_sdk:
            sentry_sdk.capture_message(f"Service {name} crashed with rc={rc}")

    async def _maybe_restart(self, name: str, state: _RuntimeState) -> None:
        cfg = self._services[name]
        now = time.time()

        # keep sliding window of restart timestamps
        state.restarts = [t for t in state.restarts if now - t <= cfg.restart_window_s]
        state.restarts.append(now)

        if len(state.restarts) > cfg.max_restarts:
            self._log.error(
                "Service %s exceeded max restarts (%s) in %ss – giving up.",
                name, cfg.max_restarts, cfg.restart_window_s
            )
            if sentry_sdk:
                sentry_sdk.capture_message(f"{name} crash-loop detected ‑ giving up.")
            return

        # exponential back-off based on restart count
        delay = min(2 ** (len(state.restarts) - 1), 30)
        self._log.info("Restarting %s in %ss (attempt %s/%s).",
                       name, delay, len(state.restarts), cfg.max_restarts)
        await asyncio.sleep(delay)
        try:
            await self.start(name)
        except Exception as exc:  # pragma: no cover
            self._log.exception("Failed to restart %s: %s", name, exc)
            if sentry_sdk:
                sentry_sdk.capture_exception(exc)

    async def _drain_streams(self, name: str, proc: Process) -> None:
        """
        Non-blocking line consumption of stdout/stderr so that log buffers do
        not get saturated.  On high volume we delegate to the central logging
        collector via the internal EventBus.
        """
        async def _pump(reader: Optional[asyncio.StreamReader],
                        cb: Callable[[str], None]) -> None:
            if reader is None or reader.at_eof():
                return
            try:
                while True:
                    line = reader.readline()  # type: ignore[call-arg]
                    if line is None:
                        break
                    if not line:
                        # Not enough data available for a full line.
                        break
                    decoded = (await line).decode(errors="replace").rstrip()
                    cb(decoded)
            except asyncio.LimitOverrunError:
                pass  # ignore, resume next tick

        await asyncio.gather(
            _pump(proc.stdout, lambda l: self._log.debug("[%s][stdout] %s", name, l)),
            _pump(proc.stderr, lambda l: self._log.error("[%s][stderr] %s", name, l)),
        )


# --------------------------------------------------------------------------- #
# Convenience Singleton (optional)                                             #
# --------------------------------------------------------------------------- #

_default_manager: Optional[ProcessManager] = None


def get_process_manager() -> ProcessManager:
    """
    Lazily construct a module-level ProcessManager so that 3rd-party plugins
    can call::

        from flockdesk.core.services.process_manager import get_process_manager
        pm = get_process_manager()
        await pm.start("my-addon")
    """
    global _default_manager
    if _default_manager is None:
        _default_manager = ProcessManager()
    return _default_manager
```