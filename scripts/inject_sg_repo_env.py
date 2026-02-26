#!/usr/bin/env python3
"""
Inject SOURCEGRAPH_REPO_NAME (or SOURCEGRAPH_REPOS for multi-repo tasks)
into Dockerfile.sg_only files.

All repos point to pinned sg-evals mirrors for reproducibility.
See configs/mirror_creation_manifest.json for the definitive mirror list.

Usage:
    python3 scripts/inject_sg_repo_env.py [--dry-run] [--force] [--task TASK_ID]

Flags:
    --force    Replace existing SOURCEGRAPH_REPO_NAME/SOURCEGRAPH_REPOS values.
               Without --force, files that already have the env var are skipped.
    --dry-run  Print what would change without writing files.
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# 8 mirrors that failed push-protection (being fixed separately).
# The correct mirror names are still used here so they work once created.
# Failed: TensorRT-LLM--b98f3fca, kafka--0753c489, kafka--3.8.0,
#         kafka--3.9.0, kafka--e678b4b, argo-cd--206a6eec,
#         argo-cd--v2.13.2, grafana--26d36ec
#
# 2 mirrors not yet in manifest (need creation):
#   envoy--v1.33.0  (envoy-code-review-001)
#   vscode--1.96.0  (vscode-code-review-001)

# Multi-repo tasks: use SOURCEGRAPH_REPOS (comma-separated list)
# All values are pinned sg-evals mirrors.
MULTI_REPO_TASKS = {
    "envoy-grpc-server-impl-001": "sg-evals/go-control-plane--71637ad6,sg-evals/istio--2300e245,sg-evals/emissary--3bbdbe0f",
    "k8s-runtime-object-impl-001": "sg-evals/api--f32ed1d6,sg-evals/apimachinery--b2e9f88f",
    "envoy-routeconfig-dep-chain-001": "sg-evals/istio--4c1f845d,sg-evals/go-control-plane--71637ad6,sg-evals/data-plane-api--84e84367",
    "envoy-stream-aggregated-sym-001": "sg-evals/envoy--1d0ba73a,sg-evals/grpc-go--3be7e2d0",
    "k8s-sharedinformer-sym-001": "sg-evals/kubernetes--31bf3ed4,sg-evals/autoscaler--0ccfef95",
    "k8s-typemeta-dep-chain-001": "sg-evals/kubernetes--31bf3ed4,sg-evals/api--f32ed1d6,sg-evals/apimachinery--b2e9f88f",
    "kafka-flink-streaming-arch-001": "sg-evals/kafka--0753c489,sg-evals/flink--0cc95fcc",
    "terraform-provider-iface-sym-001": "sg-evals/terraform--f65c52c8,sg-evals/terraform-provider-aws--e9b4629e",
    "envoy-migration-doc-gen-001": "sg-evals/envoy--50ea83e6,sg-evals/envoy--7b8baff1",
    "terraform-arch-doc-gen-001": "sg-evals/terraform--7637a921,sg-evals/terraform--24236f4f",
    "terraform-migration-doc-gen-001": "sg-evals/terraform--7637a921,sg-evals/terraform--24236f4f",
    "grpcurl-transitive-vuln-001": "sg-evals/grpcurl--25c896aa,sg-evals/grpc-go--v1.56.2",
    "wish-transitive-vuln-001": "sg-evals/wish--v0.5.0,sg-evals/ssh--v0.3.4",
    "numpy-dtype-localize-001": "sg-evals/numpy--a639fbf5,sg-evals/scikit-learn--cb7e82dd,sg-evals/pandas--41968da5",
    "k8s-cri-containerd-reason-001": "sg-evals/containerd--317286ac,sg-evals/kubernetes--8c9c67c0",
    "python-http-class-naming-refac-001": "sg-evals/django--674eda1c,sg-evals/flask--798e006f,sg-evals/requests--421b8733",
    "etcd-grpc-api-upgrade-001": "sg-evals/etcd--d89978e8,sg-evals/kubernetes--8c9c67c0,sg-evals/containerd--317286ac",
}

# Single-repo tasks: task_id -> SOURCEGRAPH_REPO_NAME value
# All values are pinned sg-evals mirrors.
SINGLE_REPO_TASKS = {
    # --- ansible ---
    "ansible-abc-imports-fix-001": "sg-evals/ansible--379058e1",
    "ansible-module-respawn-fix-001": "sg-evals/ansible--4c5ce5a1",
    "ansible-galaxy-tar-regression-prove-001": "sg-evals/ansible--b2a289dc",
    # --- argo-cd (FAILED mirrors — pending push-protection fix) ---
    "argocd-arch-orient-001": "sg-evals/argo-cd--v2.13.2",
    "argocd-sync-reconcile-qa-001": "sg-evals/argo-cd--206a6eec",
    # --- aspnetcore ---
    "aspnetcore-code-review-001": "sg-evals/aspnetcore--87525573",
    # --- bustub ---
    "bustub-hyperloglog-impl-001": "sg-evals/bustub--d5f79431",
    # --- cal.com ---
    "calcom-code-review-001": "sg-evals/cal.com--4b99072b",
    # --- camel ---
    "camel-fix-protocol-feat-001": "sg-evals/camel--1006f047",
    "camel-routing-arch-001": "sg-evals/camel--1006f047",
    # --- cgen (dibench) ---
    "cgen-deps-install-001": "sg-evals/cgen--dibench",
    # --- cilium ---
    "cilium-api-doc-gen-001": "sg-evals/cilium--ad6b298d",
    "cilium-ebpf-datapath-handoff-001": "sg-evals/cilium--v1.16.5",
    "cilium-ebpf-fault-qa-001": "sg-evals/cilium--a2f97aa8",
    "cilium-project-orient-001": "sg-evals/cilium--v1.16.5",
    # --- codecoverage (dibench) ---
    "codecoverage-deps-install-001": "sg-evals/CodeCoverageSummary--dibench",
    # --- curl ---
    "curl-cve-triage-001": "sg-evals/curl--09e25b9d",
    "curl-security-review-001": "sg-evals/curl--09e25b9d",
    "curl-vuln-reachability-001": "sg-evals/curl--09e25b9d",
    # --- envoy ---
    "envoy-udp-proxy-cds-fix-001": "sg-evals/envoy--1ae957c1",
    "envoy-dfp-host-leak-fix-001": "sg-evals/envoy--5160151e",
    # --- django ---
    "django-admins-migration-audit-001": "sg-evals/django--e295033",
    "django-audit-trail-implement-001": "sg-evals/django--674eda1c",
    "django-composite-field-recover-001": "sg-evals/django--674eda1c",
    "django-cross-team-boundary-001": "sg-evals/django--674eda1c",
    "django-csrf-session-audit-001": "sg-evals/django--9e7cc2b6",
    "django-legacy-dep-vuln-001": "sg-evals/django--674eda1c",
    "django-modeladmin-impact-001": "sg-evals/django--674eda1c",
    "django-modelchoice-fk-fix-001": "sg-evals/django--674eda1c",
    "django-orm-query-arch-001": "sg-evals/django--6b995cff",
    "django-policy-enforcement-001": "sg-evals/django--674eda1c",
    "django-pre-validate-signal-design-001": "sg-evals/django--674eda1c",
    "django-rate-limit-design-001": "sg-evals/django--674eda1c",
    "django-repo-scoped-access-001": "sg-evals/django--674eda1c",
    "django-role-based-access-001": "sg-evals/django--674eda1c",
    "django-select-for-update-fix-001": "sg-evals/django--9e7cc2b6",
    "django-sensitive-file-exclusion-001": "sg-evals/django--674eda1c",
    "django-template-inherit-recall-001": "sg-evals/django--674eda1c",
    # --- docgen ---
    "docgen-changelog-001": "sg-evals/terraform--a3dc5711",
    "docgen-changelog-002": "sg-evals/flipt--3d5a345f",
    "docgen-inline-001": "sg-evals/django--674eda1c",
    "docgen-inline-002": "sg-evals/kafka--e678b4b",
    "docgen-onboard-001": "sg-evals/istio--f8af3cae",
    "docgen-runbook-001": "sg-evals/prometheus--v2.52.0",
    "docgen-runbook-002": "sg-evals/envoy--1d0ba73a",
    # --- dotenv-expand (dibench) ---
    "dotenv-expand-deps-install-001": "sg-evals/dotenv-expand--dibench",
    # --- dotnetkoans (dibench) ---
    "dotnetkoans-deps-install-001": "sg-evals/DotNetKoans--dibench",
    # --- envoy ---
    "envoy-arch-doc-gen-001": "sg-evals/envoy--1d0ba73a",
    "envoy-code-review-001": "sg-evals/envoy--v1.33.0",
    "envoy-contributor-workflow-001": "sg-evals/envoy--v1.32.1",
    "envoy-cve-triage-001": "sg-evals/envoy--v1.31.1",
    "envoy-duplicate-headers-debug-001": "sg-evals/envoy--25f893b4",
    "envoy-ext-authz-handoff-001": "sg-evals/envoy--v1.32.1",
    "envoy-filter-chain-qa-001": "sg-evals/envoy--d7809ba2",
    "envoy-request-routing-qa-001": "sg-evals/envoy--d7809ba2",
    "envoy-vuln-reachability-001": "sg-evals/envoy--v1.31.2",
    # --- eslint-markdown (dibench) ---
    "eslint-markdown-deps-install-001": "sg-evals/markdown--dibench",
    # --- flink ---
    "flink-checkpoint-arch-001": "sg-evals/flink--0cc95fcc",
    "flink-pricing-window-feat-001": "sg-evals/flink--0cc95fcc",
    # --- flipt ---
    "flipt-auth-cookie-regression-prove-001": "sg-evals/flipt--3d5a345f",
    "flipt-cockroachdb-backend-fix-001": "sg-evals/flipt--9f8127f2",
    "flipt-degraded-context-fix-001": "sg-evals/flipt--3d5a345f",
    "flipt-dep-refactor-001": "sg-evals/flipt--3d5a345f",
    "flipt-ecr-auth-oci-fix-001": "sg-evals/flipt--c188284f",
    "flipt-eval-latency-fix-001": "sg-evals/flipt--3d5a345f",
    "flipt-flagexists-refactor-001": "sg-evals/flipt--3d5a345f",
    "flipt-otlp-exporter-fix-001": "sg-evals/flipt--b433bd05",
    "flipt-protobuf-metadata-design-001": "sg-evals/flipt--3d5a345f",
    "flipt-repo-scoped-access-001": "sg-evals/flipt--3d5a345f",
    "flipt-trace-sampling-fix-001": "sg-evals/flipt--3d5a345f",
    "flipt-transitive-deps-001": "sg-evals/flipt--3d5a345f",
    # --- ghost ---
    "ghost-code-review-001": "sg-evals/Ghost--b43bfc85",
    # --- golang/net ---
    "golang-net-cve-triage-001": "sg-evals/net--88194ad8",
    # --- grafana (FAILED mirror — pending push-protection fix) ---
    "grafana-table-panel-regression-001": "sg-evals/grafana--26d36ec",
    # --- iamactionhunter (dibench) ---
    "iamactionhunter-deps-install-001": "sg-evals/IAMActionHunter--dibench",
    # --- istio ---
    "istio-arch-doc-gen-001": "sg-evals/istio--f8af3cae",
    "istio-xds-destrul-debug-001": "sg-evals/istio--f8c9b973",
    "istio-xds-serving-qa-001": "sg-evals/istio--44d0e58e",
    # --- kubernetes ---
    "k8s-apiserver-doc-gen-001": "sg-evals/kubernetes--8c9c67c0",
    "k8s-applyconfig-doc-gen-001": "sg-evals/kubernetes--8c9c67c0",
    "k8s-clientgo-doc-gen-001": "sg-evals/kubernetes--8c9c67c0",
    "k8s-crd-lifecycle-arch-001": "sg-evals/kubernetes--v1.30.0",
    "k8s-dra-allocation-impact-001": "sg-evals/kubernetes--2e534d6",
    "k8s-dra-scheduler-event-fix-001": "sg-evals/kubernetes--v1.30.0",
    "k8s-fairqueuing-doc-gen-001": "sg-evals/kubernetes--8c9c67c0",
    "k8s-kubelet-cm-doc-gen-001": "sg-evals/kubernetes--8c9c67c0",
    "k8s-noschedule-taint-feat-001": "sg-evals/kubernetes--v1.30.0",
    "k8s-scheduler-arch-001": "sg-evals/kubernetes--v1.30.0",
    "k8s-score-normalizer-refac-001": "sg-evals/kubernetes--v1.30.0",
    # --- kafka (multiple FAILED mirrors — pending push-protection fix) ---
    "kafka-api-doc-gen-001": "sg-evals/kafka--e678b4b",
    "kafka-batch-accumulator-refac-001": "sg-evals/kafka--0753c489",
    "kafka-build-orient-001": "sg-evals/kafka--3.9.0",
    "kafka-contributor-workflow-001": "sg-evals/kafka--3.9.0",
    "kafka-message-lifecycle-qa-001": "sg-evals/kafka--0753c489",
    "kafka-producer-bufpool-fix-001": "sg-evals/kafka--be816b82",
    "kafka-sasl-auth-audit-001": "sg-evals/kafka--0753c489",
    "kafka-security-review-001": "sg-evals/kafka--3.8.0",
    "kafka-vuln-reachability-001": "sg-evals/kafka--0cd95bc2",
    # --- linux ---
    "linux-acpi-backlight-fault-001": "sg-evals/linux--55b2af1c",
    "linux-hda-intel-suspend-fault-001": "sg-evals/linux--07c4ee00",
    "linux-iwlwifi-subdevice-fault-001": "sg-evals/linux--11a48a5a",
    "linux-nfs-inode-revalidate-fault-001": "sg-evals/linux--07cc49f6",
    "linux-ssd-trim-timeout-fault-001": "sg-evals/linux--fa5941f4",
    # --- llama.cpp ---
    "llamacpp-context-window-search-001": "sg-evals/llama.cpp--56399714",
    "llamacpp-file-modify-search-001": "sg-evals/llama.cpp--56399714",
    # --- navidrome ---
    "navidrome-windows-log-fix-001": "sg-evals/navidrome--9c3b4561",
    # --- nodebb ---
    "nodebb-notif-dropdown-fix-001": "sg-evals/NodeBB--8fd8079a",
    "nodebb-plugin-validate-fix-001": "sg-evals/nodebb--76c6e302",
    # --- numpy ---
    "numpy-array-sum-perf-001": "sg-evals/numpy--a639fbf5",
    # --- openhands ---
    "openhands-search-file-test-001": "sg-evals/OpenHands--latest",
    # --- openlibrary ---
    "openlibrary-fntocli-adapter-fix-001": "sg-evals/openlibrary--c506c1b0",
    "openlibrary-search-query-fix-001": "sg-evals/openlibrary--7f6b722a",
    "openlibrary-solr-boolean-fix-001": "sg-evals/openlibrary--92db3454",
    # --- pandas ---
    "pandas-groupby-perf-001": "sg-evals/pandas--41968da5",
    # --- pcap-parser (dibench) ---
    "pcap-parser-deps-install-001": "sg-evals/pcap-parser--dibench",
    # --- postgres ---
    "postgres-client-auth-audit-001": "sg-evals/postgres--5a461dc4",
    "postgres-query-exec-arch-001": "sg-evals/postgres--5a461dc4",
    # --- prometheus ---
    "prometheus-queue-reshard-debug-001": "sg-evals/prometheus--ba14bc4",
    # --- protonmail/webclients ---
    "protonmail-conv-testhooks-fix-001": "sg-evals/webclients--c6f65d20",
    "protonmail-dropdown-sizing-fix-001": "sg-evals/webclients--8be4f6cb",
    "protonmail-holiday-calendar-fix-001": "sg-evals/webclients--369fd37d",
    # --- pytorch ---
    "pytorch-cudnn-version-fix-001": "sg-evals/pytorch--5811a8d7",
    "pytorch-dynamo-keyerror-fix-001": "sg-evals/pytorch--cbe1a35d",
    "pytorch-release-210-fix-001": "sg-evals/pytorch--863edc78",
    "pytorch-relu-gelu-fusion-fix-001": "sg-evals/pytorch--ca246612",
    "pytorch-tracer-graph-cleanup-fix-001": "sg-evals/pytorch--d18007a1",
    # --- quantlib ---
    "quantlib-barrier-pricing-arch-001": "sg-evals/QuantLib--dbdcc14e",
    # --- qutebrowser ---
    "qutebrowser-adblock-cache-regression-prove-001": "sg-evals/qutebrowser--6dd402c0",
    "qutebrowser-darkmode-threshold-regression-prove-001": "sg-evals/qutebrowser--50efac08",
    "qutebrowser-hsv-color-regression-prove-001": "sg-evals/qutebrowser--6b320dc1",
    "qutebrowser-url-regression-prove-001": "sg-evals/qutebrowser--deeb15d6",
    # --- rust ---
    "rust-subtype-relation-refac-001": "sg-evals/rust--01f6ddf7",
    # --- servo ---
    "servo-scrollend-event-feat-001": "sg-evals/servo--be6a2f99",
    # --- similar-asserts (dibench) ---
    "similar-asserts-deps-install-001": "sg-evals/similar-asserts--dibench",
    # --- scikit-learn ---
    "sklearn-kmeans-perf-001": "sg-evals/scikit-learn--cb7e82dd",
    # --- strata ---
    "strata-cds-tranche-feat-001": "sg-evals/Strata--66225ca9",
    "strata-fx-european-refac-001": "sg-evals/Strata--66225ca9",
    # --- teleport ---
    "teleport-ssh-regression-prove-001": "sg-evals/teleport--0415e422",
    # --- tensorrt (FAILED mirror — pending push-protection fix) ---
    "tensorrt-mxfp4-quant-feat-001": "sg-evals/TensorRT-LLM--b98f3fca",
    # --- terraform ---
    "terraform-code-review-001": "sg-evals/terraform--v1.10.3",
    "terraform-phantom-update-debug-001": "sg-evals/terraform--9658f9df",
    "terraform-plan-pipeline-qa-001": "sg-evals/terraform--24236f4f",
    "terraform-state-backend-handoff-001": "sg-evals/terraform--v1.9.0",
    "terraform-plan-null-unknown-fix-001": "sg-evals/terraform--abd6b9ef",
    # --- test suites ---
    "test-coverage-gap-001": "sg-evals/envoy--1d0ba73a",
    "test-coverage-gap-002": "sg-evals/kafka--e678b4b",
    "test-integration-001": "sg-evals/flipt--3d5a345f",
    "test-integration-002": "sg-evals/navidrome--9c3b4561",
    "test-unitgen-go-001": "sg-evals/kubernetes--8c9c67c0",
    "test-unitgen-py-001": "sg-evals/django--674eda1c",
    # --- tutanota ---
    "tutanota-search-regression-prove-001": "sg-evals/tutanota--f373ac38",
    # --- vscode ---
    "vscode-api-doc-gen-001": "sg-evals/vscode--69d110f2",
    "vscode-code-review-001": "sg-evals/vscode--1.96.0",
    "vscode-ext-host-qa-001": "sg-evals/vscode--17baf841",
    "vscode-stale-diagnostics-feat-001": "sg-evals/vscode--138f619c",
    # --- vuls ---
    "vuls-oval-regression-prove-001": "sg-evals/vuls--139f3a81",
}


def inject_env_var(dockerfile_path: Path, task_id: str, dry_run: bool = False,
                   force: bool = False) -> bool:
    """
    Inject SOURCEGRAPH_REPO_NAME or SOURCEGRAPH_REPOS env var into a Dockerfile.sg_only.
    Returns True if the file was (or would be) modified.
    """
    content = dockerfile_path.read_text()

    # Determine env var name and value
    if task_id in MULTI_REPO_TASKS:
        env_var = "SOURCEGRAPH_REPOS"
        env_val = MULTI_REPO_TASKS[task_id]
    elif task_id in SINGLE_REPO_TASKS:
        env_var = "SOURCEGRAPH_REPO_NAME"
        env_val = SINGLE_REPO_TASKS[task_id]
    else:
        print(f"  WARN {task_id}: no mapping found, skipping")
        return False

    # Check if already has either env var
    has_existing = "SOURCEGRAPH_REPO_NAME" in content or "SOURCEGRAPH_REPOS" in content
    if has_existing and not force:
        print(f"  SKIP {task_id}: already has env var (use --force to replace)")
        return False

    if has_existing and force:
        # Replace existing ENV line(s)
        new_content = re.sub(
            r'\n?ENV SOURCEGRAPH_REPO(?:_NAME|S)=[^\n]*\n?',
            '',
            content,
        )
        # Now inject fresh
        content = new_content

    # Find the FROM line and insert after it
    lines = content.splitlines(keepends=True)

    # Find last FROM line
    from_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("FROM "):
            from_idx = i

    if from_idx is None:
        print(f"  ERROR {task_id}: no FROM line found in {dockerfile_path}")
        return False

    # Build the ENV line to insert
    env_line = f"\nENV {env_var}={env_val}\n"

    # Insert after FROM line
    new_lines = lines[: from_idx + 1] + [env_line] + lines[from_idx + 1 :]
    new_content = "".join(new_lines)

    if dry_run:
        action = "replace" if has_existing else "add"
        print(f"  DRY-RUN {task_id}: would {action} ENV {env_var}={env_val}")
        return True

    dockerfile_path.write_text(new_content)
    action = "REPLACED" if has_existing else "ADDED"
    print(f"  {action} {task_id}: ENV {env_var}={env_val}")
    return True


def find_all_sg_only_dockerfiles():
    """Find all Dockerfile.sg_only files across SDLC suites."""
    suites = [
        "ccb_build",
        "ccb_debug",
        "ccb_design",
        "ccb_document",
        "ccb_fix",
        "ccb_secure",
        "ccb_test",
        "ccb_understand",
    ]
    results = []
    for suite in suites:
        suite_dir = REPO_ROOT / "benchmarks" / suite
        if not suite_dir.exists():
            continue
        for df in sorted(suite_dir.glob("*/environment/Dockerfile.sg_only")):
            task_id = df.parent.parent.name
            results.append((task_id, df))
    return results


def main():
    parser = argparse.ArgumentParser(description="Inject SOURCEGRAPH_REPO_NAME into Dockerfile.sg_only files")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing files")
    parser.add_argument("--force", action="store_true", help="Replace existing env var values")
    parser.add_argument("--task", help="Process only this specific task ID")
    args = parser.parse_args()

    all_files = find_all_sg_only_dockerfiles()
    print(f"Found {len(all_files)} Dockerfile.sg_only files across SDLC suites")

    if args.task:
        all_files = [(tid, df) for tid, df in all_files if tid == args.task]
        if not all_files:
            print(f"ERROR: task {args.task} not found")
            sys.exit(1)

    modified = 0
    skipped = 0
    no_mapping = 0
    errors = 0

    for task_id, dockerfile_path in all_files:
        try:
            changed = inject_env_var(dockerfile_path, task_id, dry_run=args.dry_run,
                                     force=args.force)
            if changed:
                modified += 1
            elif task_id not in SINGLE_REPO_TASKS and task_id not in MULTI_REPO_TASKS:
                no_mapping += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  ERROR {task_id}: {e}")
            errors += 1

    print()
    print(f"Summary:")
    print(f"  Modified:        {modified}")
    print(f"  Skipped (exist): {skipped}")
    print(f"  No mapping:      {no_mapping}")
    print(f"  Errors:          {errors}")
    print(f"  Total:           {len(all_files)}")

    if errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
