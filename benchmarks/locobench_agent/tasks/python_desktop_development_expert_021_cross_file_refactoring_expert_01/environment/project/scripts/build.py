```python
#!/usr/bin/env python3
"""
FlockDesk – Social Workspace Orchestrator
scripts/build.py

Build orchestration script for desktop micro-front-ends.

This script offers a single entry-point for developers and CI pipelines to
compile, package, and validate every independently deployable micro-UI that
makes up the FlockDesk desktop client.

Features
--------
• Auto-discovers micro-front-ends under `frontend/*`
• Generates Qt resource binaries (`.qrc` → `_rc.py`)
• Produces standalone executables via PyInstaller
• Concurrent builds with rich progress bars
• Version + build-metadata injection
• Clean and dist-size reporting utilities
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as _dt
import json
import os
import platform
import shutil
import subprocess
import sys
from functools import cached_property
from pathlib import Path
from typing import Dict, Iterable, List, Optional

try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
    from rich.table import Table
except ImportError as exc:  # pragma: no cover
    print("Missing dev dependency 'rich'; install with `pip install rich`", file=sys.stderr)
    raise

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


class BuildError(RuntimeError):
    """Raised when a build step fails."""


class MicroFrontendBuilder:
    """
    Builds a single micro-front-end.

    Each micro-front-end has the following structure::

        frontend/
          chat/
            pyproject.toml
            src/
              flockdesk_chat/
                __init__.py
                main.py
            resources/
              icons.qrc

    Parameters
    ----------
    name:
        Logical name of the micro-front-end (folder name).
    root:
        Path to the `frontend/<name>` directory.
    build_dir:
        Common build directory (e.g. project_root / "build").
    dist_dir:
        Common distribution directory (e.g. project_root / "dist").

    Notes
    -----
    • Each front-end *may* ship a custom `build.py` to override steps – if found,
      `python build.py --build-dir ...` will be delegated to that script.
    • If no custom build is present we fall back to a default PyInstaller call.
    """

    DEFAULT_ENTRY = "main.py"

    def __init__(self, name: str, root: Path, build_dir: Path, dist_dir: Path, console: Console):
        self.name = name
        self.root = root
        self.build_dir = build_dir / name
        self.dist_dir = dist_dir / name
        self.console = console

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def build(self, clean: bool = False) -> None:
        """High-level build routine (idempotent)."""
        if clean:
            self._clean()

        self.build_dir.mkdir(parents=True, exist_ok=True)
        self.dist_dir.mkdir(parents=True, exist_ok=True)

        self._inject_version_metadata()
        self._compile_qt_resources()
        self._delegate_or_pyinstall()

    def size(self) -> int:
        """Returns distribution size in bytes."""
        if not self.dist_dir.exists():
            return 0
        return sum(p.stat().st_size for p in self.dist_dir.rglob("*") if p.is_file())

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #

    def _clean(self) -> None:
        """Delete build + dist directories for this front-end."""
        for folder in [self.build_dir, self.dist_dir]:
            if folder.exists():
                shutil.rmtree(folder, ignore_errors=True)

    def _inject_version_metadata(self) -> None:
        """
        Write a `_build.json` file next to the package's `__init__.py`
        containing Git commit hash, build time, and platform info.
        """
        pkg_name = self._package_name_from_pyproject()
        pkg_root = self.root / "src" / pkg_name
        if not pkg_root.exists():
            return  # Nothing to do

        metadata = {
            "frontend": self.name,
            "build_time": _dt.datetime.utcnow().isoformat() + "Z",
            "git_commit": self._git_commit_hash(),
            "platform": platform.platform(aliased=True, terse=True),
            "python": platform.python_version(),
        }

        with (pkg_root / "_build.json").open("w", encoding="utf-8") as fp:
            json.dump(metadata, fp, indent=2)

    def _compile_qt_resources(self) -> None:
        """
        Compile every `.qrc` file found under `root/resources` into
        `*_rc.py` files using `pyside6-rcc`.
        """
        qrc_dir = self.root / "resources"
        if not qrc_dir.exists():
            return

        for qrc_file in qrc_dir.glob("*.qrc"):
            py_file = qrc_file.with_suffix("_rc.py")
            cmd = ["pyside6-rcc", str(qrc_file), "-o", str(py_file)]
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as exc:
                raise BuildError(f"Qt resource compilation failed: {qrc_file}") from exc

    def _delegate_or_pyinstall(self) -> None:
        """
        If the front-end contains its own `build.py`, delegate to it.
        Otherwise fall back to a standard PyInstaller build.
        """
        custom_build_script = self.root / "build.py"
        if custom_build_script.exists():
            cmd = [
                sys.executable,
                str(custom_build_script),
                "--build-dir",
                str(self.build_dir),
                "--dist-dir",
                str(self.dist_dir),
            ]
            self._run_subprocess(cmd, cwd=self.root)
            return

        # Fallback: generic PyInstaller build
        entry = self._find_entry_script()
        spec_path = self.build_dir / f"{self.name}.spec"
        cmd = [
            "pyinstaller",
            "--noconfirm",
            "--clean",
            "--name",
            self.name,
            "--distpath",
            str(self.dist_dir),
            "--workpath",
            str(self.build_dir),
            "--specpath",
            str(self.build_dir),
            str(entry),
        ]
        self._run_subprocess(cmd, cwd=self.root)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _run_subprocess(self, cmd: List[str], cwd: Path) -> None:
        """Run `cmd` and stream output; raise on non-zero exit."""
        self.console.log(f"[grey50]$ {' '.join(cmd)}[/]")

        process = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        for line in iter(process.stdout.readline, ""):
            self.console.print(f"[dim]{line.rstrip()}[/]")

        process.wait()

        if process.returncode != 0:
            raise BuildError(f"Command {' '.join(cmd)} failed with exit code {process.returncode}")

    def _find_entry_script(self) -> Path:
        """
        Attempt to locate an entry-point script.

        1. If `pyproject.toml` defines `[project.scripts]`, use the first entry.
        2. Else fall back to `<package>/main.py`.
        """
        pyproject = self._load_pyproject()
        scripts: Dict[str, str] = pyproject.get("project", {}).get("scripts", {})  # type: ignore[assignment]

        if scripts:
            module_expr = next(iter(scripts.values()))
            module_path = module_expr.split(":")[0].replace(".", "/") + ".py"
            candidate = self.root / "src" / module_path
            if candidate.exists():
                return candidate

        # Fallback
        pkg_name = self._package_name_from_pyproject()
        candidate = self.root / "src" / pkg_name / self.DEFAULT_ENTRY

        if not candidate.exists():
            raise BuildError(f"Cannot locate entry script for {self.name}")

        return candidate

    def _load_pyproject(self) -> Dict[str, object]:
        fp = self.root / "pyproject.toml"
        if not fp.exists():
            raise BuildError(f"{self.name} missing pyproject.toml")
        with fp.open("rb") as fh:
            return tomllib.load(fh)

    def _package_name_from_pyproject(self) -> str:
        pyproject = self._load_pyproject()
        project_section = pyproject.get("project") or pyproject.get("tool", {}).get("poetry")
        if not project_section:
            raise BuildError(f"Could not find project metadata in {self.name}/pyproject.toml")

        name: str = project_section["name"]  # type: ignore[index]
        return name.replace("-", "_")

    @staticmethod
    def _git_commit_hash() -> str:
        try:
            out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL)
            return out.decode().strip()
        except Exception:
            return "unknown"


class BuildManager:
    """
    Coordinates builds across all micro-front-ends.
    """

    FRONTEND_ROOT = Path(__file__).resolve().parent.parent / "frontend"
    BUILD_DIR = Path(__file__).resolve().parent.parent / "build"
    DIST_DIR = Path(__file__).resolve().parent.parent / "dist"

    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()
        self.console.log("[bold cyan]FlockDesk Build Manager[/]")

    # ------------------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------------------ #

    @cached_property
    def micro_frontends(self) -> List[MicroFrontendBuilder]:
        """Discover and cache builders for all front-ends."""
        if not self.FRONTEND_ROOT.exists():
            self.console.print(f"[red]Error:[/] frontend root {self.FRONTEND_ROOT} does not exist.")
            sys.exit(1)

        builders: List[MicroFrontendBuilder] = []
        for child in self.FRONTEND_ROOT.iterdir():
            if not child.is_dir():
                continue
            builders.append(MicroFrontendBuilder(
                name=child.name,
                root=child,
                build_dir=self.BUILD_DIR,
                dist_dir=self.DIST_DIR,
                console=self.console,
            ))
        return builders

    # ------------------------------------------------------------------ #
    # Public
    # ------------------------------------------------------------------ #

    def build_all(self, clean: bool = False, parallel: bool = True) -> None:
        """
        Build every front-end.

        Parameters
        ----------
        clean:
            Remove previous artifacts for each front-end before building.
        parallel:
            Use a ThreadPool to parallelise compilations.
        """
        self.console.print(f"Building [bold]{len(self.micro_frontends)}[/] micro-front-ends...")
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=self.console,
        )

        with progress:
            task_id = progress.add_task("Overall", total=len(self.micro_frontends))

            build_fn = lambda fb: self._build_single(progress, task_id, fb, clean)

            if parallel:
                with cf.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
                    futures = [pool.submit(build_fn, fb) for fb in self.micro_frontends]
                    for fut in cf.as_completed(futures):
                        exc = fut.exception()
                        if exc:
                            raise exc
            else:
                for fb in self.micro_frontends:
                    build_fn(fb)

    def report_dist_sizes(self) -> None:
        """Print dist folder sizes for each front-end."""
        table = Table(title="Distribution Footprint", show_lines=True)
        table.add_column("Frontend")
        table.add_column("Size (MB)", justify="right")

        total = 0
        for fb in sorted(self.micro_frontends, key=lambda x: x.name):
            size = fb.size()
            total += size
            table.add_row(fb.name, f"{size / 1024 ** 2:.2f}")

        table.add_row("[bold]TOTAL", f"[bold]{total / 1024 ** 2:.2f}")
        self.console.print(table)

    def clean_all(self) -> None:
        """Delete the shared build + dist directories."""
        for folder in [self.BUILD_DIR, self.DIST_DIR]:
            if folder.exists():
                self.console.log(f"[yellow]Removing {folder}[/]")
                shutil.rmtree(folder, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # Private
    # ------------------------------------------------------------------ #

    def _build_single(
        self,
        progress: Progress,
        task_id: int,
        fb: MicroFrontendBuilder,
        clean: bool,
    ) -> None:
        progress.console.log(f"[blue]⏳ Building {fb.name}[/]")
        try:
            fb.build(clean=clean)
            progress.console.log(f"[green]✔ Built {fb.name}[/]")
        except BuildError as exc:
            progress.console.log(f"[red]✖ Failed {fb.name}: {exc}[/]")
            raise
        finally:
            progress.advance(task_id)

    # ------------------------------------------------------------------ #
    # CLI handling
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description="FlockDesk build orchestrator")
        sub = parser.add_subparsers(dest="command", required=True)

        b_all = sub.add_parser("build", help="Build every micro-front-end")
        b_all.add_argument("--no-clean", action="store_true", help="Do not clean before build")
        b_all.add_argument("--serial", action="store_true", help="Disable parallel build")

        sub.add_parser("sizes", help="Show dist folder sizes")

        sub.add_parser("clean", help="Remove build + dist directories")

        return parser.parse_args(argv)

    # ------------------------------------------------------------------ #
    # Main entry
    # ------------------------------------------------------------------ #

    def main(self, argv: Optional[Iterable[str]] = None) -> None:
        ns = self._parse_args(argv)
        if ns.command == "build":
            self.build_all(clean=not ns.no_clean, parallel=not ns.serial)
        elif ns.command == "sizes":
            self.report_dist_sizes()
        elif ns.command == "clean":
            self.clean_all()


def entry_point() -> None:  # pragma: no cover
    """Console-script entry."""
    BuildManager().main()


if __name__ == "__main__":  # pragma: no cover
    entry_point()
```