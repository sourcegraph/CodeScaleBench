```python
"""
crowdpay_connect/infra/terraform/variables.tf (Python source)

This module programmatically generates (or updates) the Terraform
`variables.tf` file that is required to provision CrowdPay Connect’s
cloud resources.  Centralising the source-of-truth for variables in
Python avoids drift between infrastructure code, CI/CD pipelines, and
runtime configuration.

Usage
-----
$ python -m crowdpay_connect.infra.terraform.variables \
        --output ./crowdpay_connect/infra/terraform/variables.tf

The script is idempotent and safe to rerun within CI jobs.

Why Python?
-----------
Although Terraform files are declarative HCL, maintaining large,
parameterised infrastructure via hand-edited `.tf` files quickly becomes
error-prone (typos, missing defaults, inconsistent metadata, etc.).  
Using Python provides:

* Strong typing & validation
* Re-use across environments (dev/staging/prod)
* Easier conditional logic
* Testability

The rendered `variables.tf` remains 100 % Terraform-compatible.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Union

# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #


class VariableRenderError(RuntimeError):
    """Raised when a TerraformVariable cannot be rendered to HCL."""


# --------------------------------------------------------------------------- #
# Data Model                                                                   #
# --------------------------------------------------------------------------- #


Json = Union[str, int, float, bool, List[Any], Mapping[str, Any], None]


@dataclass(slots=True, frozen=True)
class TerraformVariable:
    """
    Represents a Terraform variable block.

    Attributes
    ----------
    name:
        Identifier used in Terraform (snake_case).
    type_:
        Terraform‐compatible type, e.g. "string", "bool", "number",
        "list(string)", "map(any)", etc.
    description:
        Human-readable description.  Displayed in `terraform plan`.
    default:
        Optional default value.  When `None`, the variable is required.
    sensitive:
        Mark variable as `sensitive = true` so value is redacted in logs.
    """

    name: str
    type_: str
    description: str
    default: Optional[Json] = None
    sensitive: bool = False
    _INDENT: str = field(init=False, default="  ")

    # ------------------------- #
    # Public Rendering Helpers  #
    # ------------------------- #

    def render(self) -> str:
        """
        Convert this variable specification into a Terraform/HCL block.

        Returns
        -------
        str
            A Terraform variable definition block.

        Raises
        ------
        VariableRenderError
            If default value cannot be serialised to HCL.
        """
        try:
            lines = [f'variable "{self.name}" {{']
            lines.append(f"{self._INDENT}type        = {self.type_!s}")
            # Wrap description in quotes; escape contained quotes
            safe_desc = self.description.replace('"', '\\"')
            lines.append(f'{self._INDENT}description = "{safe_desc}"')

            if self.default is not None:
                rendered = self._render_default(self.default)
                lines.append(f"{self._INDENT}default     = {rendered}")

            if self.sensitive:
                lines.append(f"{self._INDENT}sensitive   = true")

            lines.append("}")
            return "\n".join(lines)
        except Exception as exc:  # pragma: no cover
            # Re-raise with more context
            raise VariableRenderError(
                f"Failed to render variable '{self.name}': {exc}"
            ) from exc

    # ------------------------- #
    # Internal Helpers          #
    # ------------------------- #

    @classmethod
    def _render_default(cls, value: Json) -> str:  # noqa: C901 (complexity)
        """
        Render Python JSON-like data into HCL for default assignment.

        This is intentionally simple—Terraform can parse JSON for complex
        literals, so we defer to `json.dumps` where possible.

        NB: HCL and JSON are compatible for most literals (string, bool,
        number, list, map).

        Raises
        ------
        VariableRenderError
            If value cannot be serialised.
        """
        if isinstance(value, str):
            return json.dumps(value)  # Adds wrapping quotes, escapes chars
        if isinstance(value, (bool, int, float)):
            return str(value).lower() if isinstance(value, bool) else str(value)
        if value is None:
            return "null"
        if isinstance(value, (list, dict)):
            return json.dumps(value, separators=(",", ":"))
        raise VariableRenderError(
            f"Unsupported default type {type(value).__name__}: {value!r}"
        )


# --------------------------------------------------------------------------- #
# Variable Catalogue                                                          #
# --------------------------------------------------------------------------- #


def build_variables() -> List[TerraformVariable]:
    """
    Create the catalogue of variables used by CrowdPay Connect.

    Returns
    -------
    List[TerraformVariable]
    """
    return [
        TerraformVariable(
            name="environment",
            type_="string",
            description="Deployment environment (dev|staging|prod)",
            default="dev",
        ),
        TerraformVariable(
            name="aws_region",
            type_="string",
            description="AWS region to deploy resources in",
            default="us-east-1",
        ),
        TerraformVariable(
            name="project_name",
            type_="string",
            description="Name prefix for tagged resources",
            default="crowdpay-connect",
        ),
        TerraformVariable(
            name="enable_multi_currency",
            type_="bool",
            description="Toggle multi-currency support",
            default=True,
        ),
        TerraformVariable(
            name="enable_kyc_verification",
            type_="bool",
            description="Enable KYC micro-service",
            default=True,
        ),
        TerraformVariable(
            name="enable_risk_assessment",
            type_="bool",
            description="Enable real-time risk assessment engine",
            default=True,
        ),
        TerraformVariable(
            name="db_password",
            type_="string",
            description="RDS/PostgreSQL master password",
            sensitive=True,
        ),
        TerraformVariable(
            name="allowed_ip_ranges",
            type_='list(string)',
            description="CIDR blocks permitted to access private API Gateway",
            default=["10.0.0.0/8"],
        ),
        TerraformVariable(
            name="default_currency",
            type_="string",
            description="Default fiat currency for settlements",
            default="USD",
        ),
        TerraformVariable(
            name="supported_currencies",
            type_='list(string)',
            description="Whitelisted currencies for CrowdPods",
            default=["USD", "EUR", "GBP", "JPY"],
        ),
    ]


# --------------------------------------------------------------------------- #
# File Generation                                                             #
# --------------------------------------------------------------------------- #


def generate_variables_tf(
    variables: Iterable[TerraformVariable],
    output_path: Path,
    overwrite: bool = True,
) -> Path:
    """
    Render the provided variables to `output_path`.

    Parameters
    ----------
    variables:
        Collection of `TerraformVariable` instances to render.
    output_path:
        Destination `.tf` file.
    overwrite:
        Overwrite existing file.  If `False` and the file exists,
        `FileExistsError` will be raised.

    Returns
    -------
    Path
        The resolved, written file location.

    Raises
    ------
    FileExistsError
        If `overwrite` is `False` and `output_path` already exists.
    IOError
        On underlying I/O failures.
    """
    output_path = output_path.expanduser().resolve()
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"{output_path} already exists and overwrite=False")

    # Ensure parent directories exist
    output_path.parent.mkdir(parents=True, exist_ok=True)

    hcl_blocks = [var.render() for var in variables]
    content = (
        "# ------------------------------------------------------------------\n"
        "# AUTO-GENERATED FILE — DO NOT EDIT                                  \n"
        "# This file is maintained by `crowdpay_connect.infra.terraform`      \n"
        "# ------------------------------------------------------------------\n\n"
    )
    content += "\n\n".join(hcl_blocks) + "\n"

    try:
        output_path.write_text(content, encoding="utf-8")
    except OSError as exc:  # pragma: no cover
        raise IOError(f"Failed to write {output_path}: {exc}") from exc

    return output_path


# --------------------------------------------------------------------------- #
# CLI Entry-Point                                                             #
# --------------------------------------------------------------------------- #


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Terraform variables.tf for CrowdPay Connect"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(__file__).with_suffix(""),
        help="Path to write variables.tf (default: module path)",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Abort if the target file already exists",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:  # pragma: no cover
    args = _parse_args(argv)
    variables = build_variables()
    output_file = generate_variables_tf(
        variables,
        output_path=args.output,
        overwrite=not args.no_overwrite,
    )
    print(f"Wrote {len(variables)} Terraform variables to {output_file}")


# Expose data model for importing modules/tests
__all__ = [
    "TerraformVariable",
    "build_variables",
    "generate_variables_tf",
]

if __name__ == "__main__":  # pragma: no cover
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("⏹  Aborted by user")
```