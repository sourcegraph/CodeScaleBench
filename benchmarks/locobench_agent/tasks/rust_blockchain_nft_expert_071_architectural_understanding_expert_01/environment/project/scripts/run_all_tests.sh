```bash
#!/usr/bin/env bash
#───────────────────────────────────────────────────────────────────────────────
# CanvasChain Symphony – run_all_tests.sh
#
# A convenience script used by CI pipelines and local developers to build and
# execute the full test-suite of all Rust micro-services, WASM smart-contracts,
# and auxiliary crates in the workspace.
#
# Features
#  • Auto-discovers all Cargo crates and integration-test harnesses.
#  • Supports selective execution (`--service wallet`), fail-fast mode,
#    and optional code-coverage (`--coverage`).
#  • Parallelises test runs when `cargo nextest` is available.
#  • Produces a colourised summary, suitable for CI log viewers.
#  • Respects `CARGO_PROFILE` and propagates additional cargo flags.
#  • Ensures deterministic output via `--locked` and `--offline` by default.
#───────────────────────────────────────────────────────────────────────────────
set -euo pipefail

#───────────────────────────────
# Helper: colourised output
#───────────────────────────────
bold=$(tput bold 2>/dev/null || true)
red=$(tput setaf 1 2>/dev/null || true)
green=$(tput setaf 2 2>/dev/null || true)
yellow=$(tput setaf 3 2>/dev/null || true)
reset=$(tput sgr0 2>/dev/null || true)

announce()   { printf "%s➜ %s%s\n" "${bold}${yellow}" "$*" "${reset}"; }
success()    { printf "%s✔ %s%s\n" "${green}" "$*" "${reset}"; }
failure()    { printf "%s✘ %s%s\n" "${red}" "$*" "${reset}"; }
sep()        { printf "%s──────────────────────────────────────────────%s\n" "${yellow}" "${reset}"; }

#───────────────────────────────
# Defaults & CLI parsing
#───────────────────────────────
CARGO_FLAGS="--locked --offline"
SERVICE_FILTER=""
RUN_COVERAGE=false
FAIL_FAST=false

usage() {
  cat <<EOF
CanvasChain Symphony – Test Orchestrator

Usage: $(basename "$0") [options] [-- [extra cargo args]]

Options:
  -s, --service <NAME>   Run tests only for microservice <NAME>
  -c, --coverage         Generate code coverage reports (requires cargo-tarpaulin)
  -f, --fail-fast        Abort on first test failure
  -v, --verbose          Pass --verbose to cargo
  -h, --help             Display this help

Examples:
  $ $(basename "$0") --service marketplace
  $ $(basename "$0") --coverage -- -p canvaschain-runtime
EOF
}

while [[ $# -gt 0 ]]; do
  case $1 in
    -s|--service)
      SERVICE_FILTER=$2; shift 2 ;;
    -c|--coverage)
      RUN_COVERAGE=true; shift ;;
    -f|--fail-fast)
      FAIL_FAST=true; shift ;;
    -v|--verbose)
      CARGO_FLAGS+=" --verbose"; shift ;;
    --) # pass the rest to cargo
      shift; break ;;
    -h|--help)
      usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

EXTRA_CARGO_ARGS=("$@")

#───────────────────────────────
# Environment sanity checks
#───────────────────────────────
if ! command -v cargo &>/dev/null; then
  failure "cargo is not installed or not in PATH"
  exit 127
fi

if $RUN_COVERAGE && ! command -v cargo-tarpaulin &>/dev/null; then
  failure "cargo-tarpaulin is required for coverage"
  exit 1
fi

if command -v cargo-nextest &>/dev/null; then
  TEST_RUNNER="cargo nextest run"
else
  TEST_RUNNER="cargo test"
fi

#───────────────────────────────
# Crate discovery
#───────────────────────────────
discover_crates() {
  local filter=$1
  local crates=()

  # Microservices located in ./services/<name>
  for manifest in services/*/Cargo.toml; do
    [[ -e "$manifest" ]] || continue
    local svc; svc=$(basename "$(dirname "$manifest")")
    if [[ -n $filter && $svc != "$filter" ]]; then
      continue
    fi
    crates+=("services/${svc}")
  done

  # Core workspace crates
  if [[ -z $filter ]]; then
    while IFS= read -r path; do
      crates+=("$path")
    done < <(cargo metadata --no-deps --format-version=1 |
              jq -r '.packages[].manifest_path' |
              grep -vE '^services/' |
              xargs -n1 dirname |
              sort -u)
  fi

  printf '%s\n' "${crates[@]}" | sort -u
}

CRATES=($(discover_crates "$SERVICE_FILTER"))

if [[ ${#CRATES[@]} -eq 0 ]]; then
  failure "No crates found matching filter '${SERVICE_FILTER:-<none>}'"
  exit 1
fi

#───────────────────────────────
# Test execution
#───────────────────────────────
declare -A FAILURES=()
total=0
passed=0

for crate in "${CRATES[@]}"; do
  ((total++))
  sep
  announce "Testing crate: ${crate}"
  pushd "$crate" >/dev/null

  if $RUN_COVERAGE; then
    # Coverage mode
    if cargo tarpaulin --workspace --out Xml --skip-clean --timeout 120 $CARGO_FLAGS "${EXTRA_CARGO_ARGS[@]}"; then
      success "Coverage succeeded for ${crate}"
      ((passed++))
    else
      failure "Coverage failed for ${crate}"
      FAILURES["$crate"]=1
      if $FAIL_FAST; then
        break
      fi
    fi
  else
    # Standard test execution
    if $TEST_RUNNER $CARGO_FLAGS "${EXTRA_CARGO_ARGS[@]}"; then
      success "Tests passed for ${crate}"
      ((passed++))
    else
      failure "Tests failed for ${crate}"
      FAILURES["$crate"]=1
      if $FAIL_FAST; then
        popd >/dev/null
        break
      fi
    fi
  fi
  popd >/dev/null
done

#───────────────────────────────
# Summary
#───────────────────────────────
sep
if [[ ${#FAILURES[@]} -eq 0 ]]; then
  success "✔ All ${passed}/${total} crates passed"
  exit 0
else
  failure "✘ ${#FAILURES[@]} crate(s) failed:"
  for crate in "${!FAILURES[@]}"; do
    printf "  – %s\n" "$crate"
  done
  exit 1
fi
```