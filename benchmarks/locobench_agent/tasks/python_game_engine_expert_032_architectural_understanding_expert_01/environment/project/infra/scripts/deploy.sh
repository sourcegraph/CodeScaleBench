#!/usr/bin/env python3
"""
LedgerQuest Engine – Infrastructure Deployment Utility

Although this file lives under infra/scripts/deploy.sh it is intentionally
implemented in Python to provide richer validation, logging, and portability
than a plain shell script could offer.  The script orchestrates the full
CI/CD flow required to package and deploy the serverless game-engine stacks
(API Gateway, Lambda functions, Step Functions, DynamoDB, EventBridge, etc.)
using AWS SAM/CloudFormation.

Typical usage
-------------
./deploy.sh --env prod --region eu-central-1 --profile ledgerquest-prod

Key capabilities
----------------
*   Validates the caller’s AWS credentials and required CLIs (aws, sam)
*   Loads YAML-based environment configuration (parameter overrides, tags)
*   Runs test suites before allowing a deployment
*   Packages artifacts to an S3 bucket and deploys the generated template
*   Provides a “plan” mode to review the change set without execution
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Dict, List

try:
    import yaml  # PyYAML should be part of the dev dependencies
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        "ERROR: 'PyYAML' is required for the deploy script. "
        "Run `pip install -r infra/requirements.txt`.\n"
    )
    raise exc


# --------------------------------------------------------------------------- #
# Configuration constants
# --------------------------------------------------------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "infra" / "config" / "environments.yml"
DEFAULT_BUILD_DIR = PROJECT_ROOT / ".build"
DEFAULT_SAM_TEMPLATE = PROJECT_ROOT / "infra" / "template.yml"

AWS_CLI_BIN = shutil.which("aws") or "aws"
SAM_CLI_BIN = shutil.which("sam") or "sam"

# --------------------------------------------------------------------------- #
# Logging setup
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ledgerquest.deploy")


# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #
class DeployError(RuntimeError):
    """Raised when the deployment encounters a fatal error."""


def run_cmd(
    cmd: List[str],
    cwd: Path | None = None,
    env: Dict[str, str] | None = None,
    capture_output: bool = False,
    check: bool = True,
    mask_env_keys: List[str] | None = None,
) -> subprocess.CompletedProcess:
    """
    Execute a subprocess command with robust logging and error handling.

    Parameters
    ----------
    cmd : List[str]
        Command and arguments.
    cwd : Path | None
        Working directory.
    env : Dict[str, str] | None
        Environment variables to pass.
    capture_output : bool
        Whether to capture stdout/stderr.
    check : bool
        Raise DeployError on non-zero exit code.
    mask_env_keys : List[str] | None
        Environment keys whose values should be masked in logs.

    Returns
    -------
    subprocess.CompletedProcess
    """
    display_cmd = " ".join(cmd)
    logger.debug("Executing: %s", display_cmd)

    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    # Mask sensitive env values when echoing
    if mask_env_keys:
        env_to_log = {k: ("****" if k in mask_env_keys else v) for k, v in merged_env.items()}
        logger.debug("Environment overrides: %s", env_to_log)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            capture_output=capture_output,
            text=True,
            check=False,  # We handle errors manually for better message.
        )
    except FileNotFoundError as exc:
        raise DeployError(f"Command not found: {cmd[0]}") from exc

    if check and result.returncode != 0:
        logger.error("Command failed (%s): %s", result.returncode, display_cmd)
        if capture_output:
            logger.error("stdout:\n%s", result.stdout)
            logger.error("stderr:\n%s", result.stderr)
        raise DeployError(f"Command failed: {display_cmd}")

    return result


def read_yaml(file_path: Path) -> dict:
    """Parse YAML file returning a Python dict, or raise DeployError."""
    if not file_path.exists():
        raise DeployError(f"Configuration file missing: {file_path}")
    try:
        with file_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise DeployError(f"Failed to parse YAML: {file_path}") from exc


def ensure_cli_tools() -> None:
    """Fail fast if AWS and SAM CLIs are not present."""
    missing: List[str] = [cmd for cmd in (AWS_CLI_BIN, SAM_CLI_BIN) if not shutil.which(cmd)]
    if missing:
        raise DeployError(
            "Missing required CLI tools: "
            + ", ".join(missing)
            + ". Please install them and ensure they are on your PATH."
        )


def validate_aws_credentials(profile: str | None, region: str) -> None:
    """
    Ensure AWS credentials are configured and can make a simple STS call.

    Raises
    ------
    DeployError
        If credentials are invalid.
    """
    cmd = [AWS_CLI_BIN]
    if profile:
        cmd.extend(["--profile", profile])
    cmd.extend(["sts", "get-caller-identity"])
    logger.info("Validating AWS credentials...")
    run_cmd(cmd, capture_output=True, check=True)
    logger.info("AWS credentials validated for region %s.", region)


# --------------------------------------------------------------------------- #
# Core deployment logic
# --------------------------------------------------------------------------- #
def run_tests() -> None:
    """Run unit and integration tests before starting a deployment."""
    logger.info("Running test suite...")
    cmd = ["pytest", "-q"]
    run_cmd(cmd, capture_output=False, check=True)
    logger.info("All tests passed.")


def sam_build(build_dir: Path, template: Path, profile: str | None, use_container: bool = False) -> None:
    """Run `sam build` to construct the artifacts directory."""
    logger.info("Building SAM template...")
    cmd = [
        SAM_CLI_BIN,
        "build",
        "--template",
        str(template),
        "--build-dir",
        str(build_dir),
        "--cached",
    ]
    if use_container:
        cmd.append("--use-container")
    if profile:
        cmd.extend(["--profile", profile])

    run_cmd(cmd, capture_output=True)
    logger.info("Build output in %s", build_dir)


def sam_package(
    build_dir: Path,
    s3_bucket: str,
    region: str,
    profile: str | None,
    packaged_template_path: Path,
) -> None:
    """Package artifacts and generate a deployable template."""
    logger.info("Packaging artifacts to S3 bucket %s...", s3_bucket)
    cmd = [
        SAM_CLI_BIN,
        "package",
        "--template-file",
        str(build_dir / "template.yaml"),
        "--output-template-file",
        str(packaged_template_path),
        "--s3-bucket",
        s3_bucket,
        "--region",
        region,
    ]
    if profile:
        cmd.extend(["--profile", profile])

    run_cmd(cmd, capture_output=True)
    logger.info("Packaged template written to %s", packaged_template_path)


def sam_deploy(
    packaged_template_path: Path,
    stack_name: str,
    region: str,
    profile: str | None,
    parameter_overrides: dict[str, str],
    tags: dict[str, str],
    capabilities: List[str],
    no_execute_changeset: bool,
    confirm_changeset: bool,
) -> None:
    """Deploy (or plan) the CloudFormation stack using SAM CLI."""
    logger.info("%s stack %s...", "Planning" if no_execute_changeset else "Deploying", stack_name)
    cmd = [
        SAM_CLI_BIN,
        "deploy",
        "--template-file",
        str(packaged_template_path),
        "--stack-name",
        stack_name,
        "--region",
        region,
        "--parameter-overrides",
        " ".join([f"{k}={v}" for k, v in parameter_overrides.items()]),
        "--tags",
        " ".join([f"{k}={v}" for k, v in tags.items()]),
        "--no-fail-on-empty-changeset",
    ]

    for cap in capabilities:
        cmd.extend(["--capabilities", cap])

    if no_execute_changeset:
        cmd.append("--no-execute-changeset")

    if not confirm_changeset:
        cmd.append("--confirm-changeset")
        cmd.append("never")  # do not prompt

    if profile:
        cmd.extend(["--profile", profile])

    run_cmd(cmd, capture_output=False)
    logger.info("SAM %s completed for stack %s.", "plan" if no_execute_changeset else "deploy", stack_name)


def deploy_environment(
    env: str,
    region: str,
    profile: str | None,
    plan_only: bool,
    skip_tests: bool,
    config_file: Path = DEFAULT_CONFIG_FILE,
    template_file: Path = DEFAULT_SAM_TEMPLATE,
) -> None:
    """
    Deploy LedgerQuest game engine infrastructure for a given environment.

    Parameters
    ----------
    env : str
        Target environment name (e.g., dev, staging, prod).
    region : str
        AWS region.
    profile : str | None
        Named AWS credential profile.
    plan_only : bool
        If True, create a change set without executing it.
    skip_tests : bool
        Skip running tests before deployment.
    """
    ensure_cli_tools()
    validate_aws_credentials(profile, region)

    environments = read_yaml(config_file).get("environments", {})
    if env not in environments:
        valid = ", ".join(sorted(environments))
        raise DeployError(f"Unknown environment '{env}'. Valid options: {valid}")

    env_cfg: dict = environments[env]
    s3_bucket: str = env_cfg["artifact_bucket"]
    stack_name: str = env_cfg.get("stack_name", f"ledgerquest-{env}")
    tags: dict[str, str] = env_cfg.get("tags", {})
    parameter_overrides: dict[str, str] = env_cfg.get("parameters", {})

    if not skip_tests:
        run_tests()

    with tempfile.TemporaryDirectory() as tmp_build:
        build_dir = Path(tmp_build)
        sam_build(build_dir=build_dir, template=template_file, profile=profile, use_container=False)

        packaged_template_path = build_dir / "packaged-template.yml"
        sam_package(
            build_dir=build_dir,
            s3_bucket=s3_bucket,
            region=region,
            profile=profile,
            packaged_template_path=packaged_template_path,
        )

        sam_deploy(
            packaged_template_path=packaged_template_path,
            stack_name=stack_name,
            region=region,
            profile=profile,
            parameter_overrides=parameter_overrides,
            tags=tags,
            capabilities=["CAPABILITY_NAMED_IAM"],
            no_execute_changeset=plan_only,
            confirm_changeset=not plan_only,
        )


# --------------------------------------------------------------------------- #
# CLI parsing
# --------------------------------------------------------------------------- #
def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LedgerQuest Engine infrastructure deployment utility."
    )

    parser.add_argument(
        "--env",
        required=True,
        help="Target environment name (e.g., dev, staging, prod)",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
        help="AWS region to deploy to.",
    )
    parser.add_argument(
        "--profile",
        help="AWS shared credentials profile name.",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Perform a dry-run and create a change set without executing it.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running the test suite before deployment.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase output verbosity (-v, ‑vv).",
    )

    return parser


def _set_log_level(verbosity: int) -> None:
    if verbosity >= 2:
        logger.setLevel(logging.DEBUG)
    elif verbosity == 1:
        logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.WARNING)


def main(argv: List[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    parser = _build_cli()
    args = parser.parse_args(argv)
    _set_log_level(args.verbose)

    banner = textwrap.dedent(
        f"""
        ==========================================
           LedgerQuest Engine – Deploy Utility
           Environment : {args.env}
           Region      : {args.region}
           Profile     : {args.profile or 'default'}
           Plan Only   : {args.plan}
        ==========================================
        """
    )
    logger.info(banner)

    try:
        deploy_environment(
            env=args.env,
            region=args.region,
            profile=args.profile,
            plan_only=args.plan,
            skip_tests=args.skip_tests,
        )
        logger.info("Deployment finished successfully.")
    except DeployError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()