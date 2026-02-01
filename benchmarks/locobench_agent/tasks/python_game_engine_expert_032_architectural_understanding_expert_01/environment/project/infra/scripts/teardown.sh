```python
#!/usr/bin/env python3
"""
LedgerQuest Engine – Infrastructure Teardown Utility
====================================================

This script is responsible for de-provisioning **all** AWS resources that
belong to a particular LedgerQuest Engine deployment.  It is intentionally
opinionated and *destructive*—please read the code carefully before running
it in production.

Features
--------
* Tag-driven discovery: resources are detected via a configurable tag key and
  value (default:  `Project = LedgerQuestEngine`).
* Parallel deletions with sensible limits to speed up execution without
  triggering AWS API throttling.
* Safe S3 bucket cleanup that supports versioned buckets + delete markers.
* Dry-run mode and interactive confirmation prompts to reduce “oops” moments.
* Structured logging that integrates nicely with CI platforms.
"""

from __future__ import annotations

import argparse
import concurrent.futures as _f
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from functools import partial
from typing import Iterable, List, Optional

# External deps (must be available in Lambda build image / local env)
try:
    import boto3
    from botocore.exceptions import ClientError, WaiterError
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        "ERROR: boto3 must be installed to run this script "
        "(pip install boto3 botocore)\n"
    )
    raise exc


###############################################################################
# Configuration & Constants
###############################################################################

_DEFAULT_TAG_KEY = "Project"
_DEFAULT_TAG_VAL = "LedgerQuestEngine"

# Throttle parallelism to avoid brute-forcing AWS API
_MAX_WORKERS = int(os.environ.get("LQE_TEARDOWN_MAX_WORKERS", "8"))

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_LOG = logging.getLogger("lqe.teardown")


###############################################################################
# Dataclasses
###############################################################################


@dataclass
class TeardownContext:
    session: boto3.Session
    region: str
    dry_run: bool
    tag_key: str
    tag_val: str


###############################################################################
# Helper Utilities
###############################################################################


def _confirm_or_exit(force: bool, tag_key: str, tag_val: str) -> None:
    """Ask for user confirmation before we destroy everything."""
    if force:
        _LOG.warning("Force flag detected, skipping confirmation prompt")
        return

    banner = (
        f"\nAbout to DESTROY every AWS resource tagged "
        f"{tag_key}={tag_val!r} in the current account + region.\n"
        "This action is IRREVERSIBLE.\n"
        "Type the tag *value* again to continue: "
    )
    answer = input(banner).strip()
    if answer != tag_val:
        _LOG.error("User aborted teardown – entered value did not match tag.")
        sys.exit(1)


def _handle_sigint(sig, frame):
    _LOG.warning("Teardown interrupted by user (Ctrl-C); exiting gracefully…")
    sys.exit(130)


def _log_dry_run(action: str, arn_or_name: str) -> None:
    _LOG.info("DRY-RUN: would %s %s", action, arn_or_name)


###############################################################################
# Core Deleter Class
###############################################################################


class AWSTeardown:
    """
    Discover and delete AWS resources that match a specific tag.
    """

    def __init__(self, ctx: TeardownContext) -> None:
        self.ctx = ctx
        self._session = ctx.session
        self._tag_filters = [
            {"Key": ctx.tag_key, "Values": [ctx.tag_val]},
        ]

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def run(self) -> None:
        """Execute teardown workflow."""
        stages = [
            self._delete_sfn_state_machines,
            self._delete_lambda_functions,
            self._delete_eventbridge_rules,
            self._delete_dynamodb_tables,
            self._delete_s3_buckets,
            self._delete_cloudformation_stacks,
            self._delete_ecs_clusters,
        ]

        for stage in stages:
            name = stage.__name__.replace("_delete_", "").upper()
            _LOG.info("===== Deleting %s =====", name)
            stage()
            _LOG.info("===== Done with %s =====", name)

    # --------------------------------------------------------------------- #
    # Deleters
    # --------------------------------------------------------------------- #

    def _delete_sfn_state_machines(self) -> None:
        client = self._session.client("stepfunctions", region_name=self.ctx.region)

        paginator = client.get_paginator("list_state_machines")
        to_delete: List[str] = []

        for page in paginator.paginate():
            for sm in page["stateMachines"]:
                arn = sm["stateMachineArn"]
                tags = client.list_tags_for_resource(resourceArn=arn).get("tags", [])
                if self._has_tag(tags):
                    to_delete.append(arn)

        self._execute_parallel(
            "delete",
            resources=to_delete,
            deleter=lambda arn: client.delete_state_machine(stateMachineArn=arn),
        )

    def _delete_lambda_functions(self) -> None:
        client = self._session.client("lambda", region_name=self.ctx.region)

        paginator = client.get_paginator("list_functions")
        to_delete: List[str] = []

        for page in paginator.paginate():
            for fn in page["Functions"]:
                arn = fn["FunctionArn"]
                tags = client.list_tags(Resource=arn).get("Tags", {})
                if tags.get(self.ctx.tag_key) == self.ctx.tag_val:
                    to_delete.append(arn)

        self._execute_parallel(
            "delete",
            resources=to_delete,
            deleter=lambda arn: client.delete_function(FunctionName=arn),
        )

    def _delete_eventbridge_rules(self) -> None:
        client = self._session.client("events", region_name=self.ctx.region)
        paginator = client.get_paginator("list_rules")

        rules_to_delete: List[str] = []
        for page in paginator.paginate():
            for rule in page["Rules"]:
                arn = rule["Arn"]
                tags = client.list_tags_for_resource(ResourceARN=arn).get("Tags", [])
                if self._has_tag(tags):
                    rules_to_delete.append(rule["Name"])

        def deleter(rule_name: str) -> None:
            targets = client.list_targets_by_rule(Rule=rule_name).get("Targets", [])
            if targets:
                client.remove_targets(Rule=rule_name, Ids=[t["Id"] for t in targets])
            client.delete_rule(Name=rule_name, Force=True)

        self._execute_parallel("delete", resources=rules_to_delete, deleter=deleter)

    def _delete_dynamodb_tables(self) -> None:
        client = self._session.client("dynamodb", region_name=self.ctx.region)
        paginator = client.get_paginator("list_tables")

        tables_to_delete = []
        for page in paginator.paginate():
            for table in page["TableNames"]:
                desc = client.describe_table(TableName=table)["Table"]
                tags = client.list_tags_of_resource(
                    ResourceArn=desc["TableArn"]
                ).get("Tags", [])
                if self._has_tag(tags):
                    tables_to_delete.append(table)

        self._execute_parallel(
            "delete",
            resources=tables_to_delete,
            deleter=lambda name: client.delete_table(TableName=name),
        )

    def _delete_s3_buckets(self) -> None:
        s3 = self._session.resource("s3", region_name=self.ctx.region)

        buckets_to_delete = []
        for bucket in s3.buckets.all():
            tagging = self._get_bucket_tagging(bucket)
            if tagging.get(self.ctx.tag_key) == self.ctx.tag_val:
                buckets_to_delete.append(bucket.name)

        self._execute_parallel(
            "delete", resources=buckets_to_delete, deleter=self._empty_and_delete_bucket
        )

    def _delete_cloudformation_stacks(self) -> None:
        client = self._session.client("cloudformation", region_name=self.ctx.region)
        paginator = client.get_paginator("describe_stacks")

        stacks_to_delete = []
        for page in paginator.paginate():
            for stack in page["Stacks"]:
                # Skip already deleted stacks
                if stack["StackStatus"].endswith("_COMPLETE") and stack[
                    "StackStatus"
                ].startswith("DELETE"):
                    continue
                tags = stack.get("Tags", [])
                if self._has_tag(tags):
                    stacks_to_delete.append(stack["StackName"])

        def deleter(name: str) -> None:
            client.delete_stack(StackName=name)
            waiter = client.get_waiter("stack_delete_complete")
            waiter.wait(StackName=name)

        self._execute_parallel("delete", resources=stacks_to_delete, deleter=deleter)

    def _delete_ecs_clusters(self) -> None:
        client = self._session.client("ecs", region_name=self.ctx.region)

        paginator = client.get_paginator("list_clusters")
        clusters_to_delete = []
        for page in paginator.paginate():
            for arn in page["clusterArns"]:
                tags = client.list_tags_for_resource(resourceArn=arn).get(
                    "tags", []
                )
                if self._has_tag(tags):
                    clusters_to_delete.append(arn)

        def deleter(cluster_arn: str) -> None:
            # First stop services
            services = client.list_services(cluster=cluster_arn).get(
                "serviceArns", []
            )
            for svc_arn in services:
                client.update_service(
                    cluster=cluster_arn,
                    service=svc_arn,
                    desiredCount=0,
                )
                client.delete_service(
                    cluster=cluster_arn,
                    service=svc_arn,
                    force=True,
                )
            # Then delete cluster
            client.delete_cluster(cluster=cluster_arn)

        self._execute_parallel("delete", resources=clusters_to_delete, deleter=deleter)

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _execute_parallel(
        self,
        action: str,
        resources: Iterable[str],
        deleter,
    ) -> None:
        """Execute a deleter call in parallel respecting dry-run flag."""
        resources = list(resources)
        if not resources:
            _LOG.info("No resources found")
            return

        _LOG.info("Found %d resources to %s", len(resources), action)

        if self.ctx.dry_run:
            for r in resources:
                _log_dry_run(action, r)
            return

        with _f.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as exe:
            futures = {exe.submit(self._wrap_delete, deleter, r): r for r in resources}

            for fut in _f.as_completed(futures):
                resource = futures[fut]
                try:
                    fut.result()
                    _LOG.info("Successfully %s %s", action, resource)
                except Exception as exc:  # pragma: no cover
                    _LOG.error("Failed to %s %s: %s", action, resource, exc)

    @staticmethod
    def _wrap_delete(deleter, resource: str) -> None:
        """Wrapper to catch & re-raise exceptions for ThreadPoolExecutor."""
        deleter(resource)

    def _has_tag(self, tags: List[dict]) -> bool:
        for tag in tags:
            if tag.get("Key") == self.ctx.tag_key and tag.get("Value") == self.ctx.tag_val:
                return True
        return False

    # ---------- S3 helpers ---------- #

    def _get_bucket_tagging(self, bucket) -> dict:
        try:
            tagset = bucket.Tagging().tag_set
            return {t["Key"]: t["Value"] for t in tagset}
        except ClientError as err:
            if err.response["Error"]["Code"] in ("NoSuchTagSet", "NoSuchBucket"):
                return {}
            raise

    def _empty_and_delete_bucket(self, bucket_name: str) -> None:
        s3 = self._session.resource("s3", region_name=self.ctx.region)
        bucket = s3.Bucket(bucket_name)

        _LOG.debug("Emptying bucket %s …", bucket_name)
        # Delete all object versions (if versioning enabled)
        try:
            bucket.object_versions.delete()
        except ClientError as exc:
            _LOG.warning("Error deleting object versions for %s: %s", bucket_name, exc)

        # Delete bucket itself
        _LOG.debug("Deleting bucket %s …", bucket_name)
        bucket.delete()

    # --------------------------------------------------------------------- #


###############################################################################
# CLI Parsing
###############################################################################


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Teardown all AWS resources that belong to a LedgerQuest "
        "Engine deployment."
    )
    parser.add_argument(
        "--profile",
        help="AWS named profile to use (default: use boto3's default chain)",
    )
    parser.add_argument(
        "--region",
        help="AWS region (overrides AWS_REGION / profile default)",
    )
    parser.add_argument(
        "--tag-key",
        default=_DEFAULT_TAG_KEY,
        help=f"Resource tag key used as ownership marker (default: {_DEFAULT_TAG_KEY})",
    )
    parser.add_argument(
        "--tag-value",
        default=_DEFAULT_TAG_VAL,
        help=f"Resource tag value used as ownership marker (default: {_DEFAULT_TAG_VAL})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List resources that *would* be deleted without touching them",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt",
    )
    return parser.parse_args(argv)


###############################################################################
# Entry-Point
###############################################################################


def main(argv: Optional[List[str]] = None) -> None:
    # Handle Ctrl-C gracefully
    signal.signal(signal.SIGINT, _handle_sigint)

    args = _parse_args(argv)
    session = boto3.Session(profile_name=args.profile) if args.profile else boto3

    region = args.region or session.Session().region_name or "us-east-1"
    _LOG.info("Using AWS region: %s", region)

    _confirm_or_exit(args.force, args.tag_key, args.tag_value)

    ctx = TeardownContext(
        session=session.Session() if isinstance(session, boto3) else session,
        region=region,
        dry_run=args.dry_run,
        tag_key=args.tag_key,
        tag_val=args.tag_value,
    )

    teardown = AWSTeardown(ctx)
    started_at = time.time()
    teardown.run()
    _LOG.info("Teardown completed in %.1f seconds.", time.time() - started_at)


if __name__ == "__main__":
    main()
```