```python
#!/usr/bin/env python3
"""
run_dev.sh  (Yes, it is really Python!)

This development–orchestration helper boot-straps and manages the entire
FlockDesk desktop workspace in *development mode*.  It exists in `scripts/`
and is invoked the same way a shell script would be:

    $ ./scripts/run_dev.sh [command] [options]

Why a “.sh” while written in Python?
------------------------------------
Historically our CI runners expect every helper to have a “.sh” extension.
Instead of fighting decades of shell-muscle-memory we simply kept the name but
moved the implementation to Python so we can enjoy argparse, logging, and
cross-platform path handling.

Responsibilities
----------------
1. Ensure a dedicated virtual-environment is present (./.venv)
2. Install/update project dependencies (`pip install -r requirements/dev.txt`)
3. Expose a convenient CLI to:
      • start       – Launch all micro front-ends + event-bus with live-reload
      • stop        – Stop any previously spawned dev processes
      • lint        – Run linters/formatters (ruff, black, mypy, etc.)
      • test        – Run pytest with coverage
      • clean       – Remove byte-code, dist folders, and temporary artefacts
      • hooks       – (Re)install git pre-commit hooks
4. Stream colored, prefixed logs for every child process
5. Forward Ctrl-C/SIGTERM to **all** children for graceful shutdown

This script is *self-contained*; it can be copied onto any developer machine
with nothing but Python³·9⁺ installed.

"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Dict, List

# --------------------------------------------------------------------------- #
# Configuration constants
# --------------------------------------------------------------------------- #

PYTHON_MIN = (3, 9, 0)
ROOT_DIR = Path(__file__).resolve().parent.parent
VENVS_DIR = ROOT_DIR / ".venv"
REQ_FILE = ROOT_DIR / "requirements" / "dev.txt"
PRECOMMIT_CONFIG = ROOT_DIR / ".pre-commit-config.yaml"

# Child services that can be run in dev mode along with their entry commands.
SERVICES: Dict[str, List[str]] = {
    "event-bus": ["python", "-m", "flockdesk.event_bus", "--dev"],
    "chat": ["python", "-m", "flockdesk.chat.ui", "--dev"],
    "whiteboard": ["python", "-m", "flockdesk.whiteboard.ui", "--dev"],
    "coedit": ["python", "-m", "flockdesk.coedit.ui", "--dev"],
    "presence": ["python", "-m", "flockdesk.presence.ui", "--dev"],
    # add new micro-front-ends here.
}

LOG_LEVEL_STYLES = {
    logging.DEBUG: "\033[38;5;241m",
    logging.INFO: "\033[38;5;34m",
    logging.WARNING: "\033[38;5;220m",
    logging.ERROR: "\033[38;5;196m",
    logging.CRITICAL: "\033[1;38;5;196m",
}
RESET = "\033[0m"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def colorize(level: int, message: str) -> str:
    """Return `message` wrapped in ANSI color according to log level."""
    return f"{LOG_LEVEL_STYLES.get(level, '')}{message}{RESET}"


class ProcessManager:
    """
    Manages a set of subprocesses, handling graceful shutdown and
    prefixing/logging of their output streams.
    """

    def __init__(self) -> None:
        self.children: Dict[str, subprocess.Popen[str]] = {}

    # --------------------------------------------------------------------- #
    # Child process management
    # --------------------------------------------------------------------- #
    def spawn(self, name: str, cmd: List[str]) -> None:
        """Spawn a subprocess and register it for later cleanup."""
        if name in self.children:
            logging.warning("Process '%s' already running, skipping.", name)
            return

        logging.info("Starting %s → %s", name, " ".join(cmd))
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT_DIR,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        self.children[name] = proc

    def _stream_output(self, name: str, proc: subprocess.Popen[str]) -> None:
        prefix = f"[{name:<10}] "
        if not proc.stdout:
            return
        for line in proc.stdout:
            sys.stdout.write(colorize(logging.INFO, prefix + line))

    def monitor(self) -> None:
        """
        Blocking loop that streams output from all child processes until
        interrupted (Ctrl-C) or one of the processes exits unexpectedly.
        """
        try:
            while True:
                for name, proc in list(self.children.items()):
                    if proc.poll() is not None:
                        raise RuntimeError(f"Process '{name}' exited early.")
                    self._stream_output(name, proc)
        except (KeyboardInterrupt, RuntimeError) as exc:
            logging.info("Shutting down (%s)…", exc)
            self.shutdown()

    # --------------------------------------------------------------------- #
    # Termination
    # --------------------------------------------------------------------- #
    def shutdown(self) -> None:
        """Forward SIGTERM to all child processes and wait for them to finish."""
        for name, proc in self.children.items():
            logging.debug("Terminating %s (pid %s)…", name, proc.pid)
            with suppress(Exception):
                proc.terminate()
        for proc in self.children.values():
            with suppress(Exception):
                proc.wait(10)
        self.children.clear()


# Context-manager-style suppression without importing `contextlib` explicitly
class suppress:  # noqa: N801
    def __init__(self, *exceptions) -> None:
        self.exceptions = exceptions

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc, tb):
        return exc_type and issubclass(exc_type, self.exceptions or (Exception,))


# --------------------------------------------------------------------------- #
# Core Tasks
# --------------------------------------------------------------------------- #
def ensure_python_version() -> None:
    if sys.version_info < PYTHON_MIN:
        sys.stderr.write(
            f"Python {'.'.join(map(str, PYTHON_MIN))}+ required, "
            f"but found {sys.version}.\n"
        )
        sys.exit(1)


def ensure_virtualenv() -> None:
    """Create a local virtualenv (./.venv) if it does not yet exist."""
    if VENVS_DIR.exists():
        return

    logging.info("Creating virtualenv in %s …", VENVS_DIR)
    import venv

    builder = venv.EnvBuilder(with_pip=True, clear=False, symlinks=True)
    builder.create(VENVS_DIR)

    # Re-entry shim: activate the venv automatically for subsequent invocations.
    activation_snippet = (
        f"source {VENVS_DIR}/bin/activate\n"
        "# Re-execute run_dev.sh within venv\n"
        f"exec python {Path(__file__).name} \"$@\""
    )
    activation_file = ROOT_DIR / "scripts" / "activate_dev_env.sh"
    activation_file.write_text("#!/usr/bin/env bash\n" + activation_snippet)
    activation_file.chmod(0o755)
    logging.debug("Wrote helper activation script → %s", activation_file)


def install_requirements() -> None:
    """Run pip install if requirement hashes changed or venv is new."""
    marker = VENVS_DIR / ".dev_requirements_installed"
    if marker.exists() and marker.stat().st_mtime >= REQ_FILE.stat().st_mtime:
        return

    logging.info("Installing dev requirements…")
    pip_exe = VENVS_DIR / "bin" / "pip"
    subprocess.check_call([pip_exe, "install", "-r", str(REQ_FILE)])
    marker.touch()


def run_linter(argv: List[str] | None = None) -> int:
    argv = argv or ["ruff", "src", "tests", "--fix", "--show-fixes"]
    logging.info("Running linter → %s", " ".join(argv))
    return subprocess.call(argv)


def run_tests(extra_pytest_args: List[str] | None = None) -> int:
    cmd = ["pytest", "-q", "--cov=src", "--cov-report=term-missing"]
    if extra_pytest_args:
        cmd.extend(extra_pytest_args)
    logging.info("Running tests → %s", " ".join(cmd))
    return subprocess.call(cmd)


def run_precommit_install() -> None:
    if not shutil.which("pre-commit"):
        logging.error("'pre-commit' is not installed. `pip install pre-commit`.")
        sys.exit(1)
    subprocess.check_call(["pre-commit", "install"])
    logging.info("pre-commit hooks installed.")


def clean() -> None:
    patterns = ["**/__pycache__", "**/*.py[co]", "dist", "build", ".pytest_cache"]
    removed = 0
    for pattern in patterns:
        for path in ROOT_DIR.glob(pattern):
            if path.is_file():
                path.unlink()
                removed += 1
            else:
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
    logging.info("Cleaned %s files/directories.", removed)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_dev.sh",
        description="FlockDesk development environment orchestrator.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("start", help="Launch all desktop micro-front-ends.")
    sub.add_parser("stop", help="Terminate anything started by `start`.")
    sub.add_parser("lint", help="Run static analysis & code-style checks.")
    sub.add_parser("test", help="Run unit tests with coverage.")
    sub.add_parser("clean", help="Remove build artefacts and caches.")
    sub.add_parser("hooks", help="(Re)install git pre-commit hooks.")

    return p


# --------------------------------------------------------------------------- #
# Main entry-points
# --------------------------------------------------------------------------- #
def cmd_start() -> None:
    pm = ProcessManager()
    for name, cmd in SERVICES.items():
        pm.spawn(name, cmd)
    pm.monitor()


def cmd_stop() -> None:
    # This is a best-effort approach using pidfiles. For now we only support
    # same-session termination. Future: integrate with `psutil`.
    logging.warning("`stop` is not yet fully implemented. Please Ctrl-C the session.")


def main(argv: List[str] | None = None) -> None:
    ensure_python_version()
    args = build_parser().parse_args(argv)

    # Minimal logging config with colored levels.
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname).1s %(message)s",
        datefmt="[%H:%M:%S]",
    )
    logging.addLevelName(
        logging.INFO, colorize(logging.INFO, logging.getLevelName(logging.INFO))
    )

    if args.command in {"start", "lint", "test"}:
        ensure_virtualenv()
        install_requirements()

    # --- Dispatch --------------------------------------------------------- #
    try:
        match args.command:
            case "start":
                cmd_start()
            case "stop":
                cmd_stop()
            case "lint":
                sys.exit(run_linter())
            case "test":
                sys.exit(run_tests())
            case "clean":
                clean()
            case "hooks":
                run_precommit_install()
            case _:
                raise ValueError(f"Unknown command '{args.command}'")
    except KeyboardInterrupt:
        logging.info("Interrupted by user.")


if __name__ == "__main__":
    main()
```