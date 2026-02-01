#!/usr/bin/env bash
# =============================================================================
# CanvasChain Symphony – Genesis Initialisation Script
#
# File:    scripts/init_genesis.sh
# Purpose: Generate a reproducible, deterministic genesis state for a new
#          CanvasChain Symphony network.  The script wraps the Rust CLI
#          binaries (`canvas-node`, `canvas-cli`) with additional safeguards
#          and convenience features such as automatic compilation, dependency
#          checks, coloured logging, and idempotent output directories.
#
# Author:  CanvasChain Core Devs <dev@canvaschain.io>
# Licence: Apache-2.0
# =============================================================================

###############################################################################
# Shell Options & Error Handling
###############################################################################
set -Eeuo pipefail

# Trap all unexpected errors.  By default, `errexit` (`-e`) only triggers on
# simple commands; this ensures that pipeline failures are handled too.
trap 'catch $? $LINENO' ERR

catch() {
    local exit_code=$1
    local line_no=$2
    log::error "Script failed at line ${line_no} with exit code ${exit_code}"
    exit "${exit_code}"
}

###############################################################################
# Logging Helpers
###############################################################################
log::info()    { printf "\e[32m[INFO] %s\e[0m\n"    "$*"; }
log::warn()    { printf "\e[33m[WARN] %s\e[0m\n"    "$*"; }
log::error()   { printf "\e[31m[ERROR] %s\e[0m\n"   "$*"; }
log::section() { printf "\n\e[34m===== %s =====\e[0m\n" "$*"; }

###############################################################################
# Constants
###############################################################################
DEFAULT_CHAIN_ID="canvas-localnet"
DEFAULT_SS58_PREFIX=99
BIN_TARGET_DIR="target/release"
NODE_BIN="${BIN_TARGET_DIR}/canvas-node"
CLI_BIN="${BIN_TARGET_DIR}/canvas-cli"

###############################################################################
# Utilities
###############################################################################
require_cmd() {
    command -v "$1" &>/dev/null || {
        log::error "Command '$1' is required but not installed. Aborting."
        exit 127
    }
}

canonical_path() { # Resolve a path to its canonical/absolute form
    python - <<'PY' "$1"
import os, sys
print(os.path.abspath(sys.argv[1]))
PY
}

###############################################################################
# Argument Parsing
###############################################################################
print_help() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Generates genesis state & chain-spec JSONs for a new CanvasChain network.

Options:
  -n, --network    Network name/identifier     (default: ${DEFAULT_CHAIN_ID})
  -o, --out        Output directory            (default: ./chain-specs)
  -k, --keys       Path to initial validator keys YAML
  -s, --ss58       SS58 address prefix         (default: ${DEFAULT_SS58_PREFIX})
  -d, --dev        Use dev (instant) consensus instead of PoI
  -h, --help       Show this message and exit

Example:
  scripts/init_genesis.sh -n canvas-testnet -k ./validator_keys.yml -o ./specs
EOF
}

NETWORK_ID="${DEFAULT_CHAIN_ID}"
OUT_DIR="chain-specs"
VALIDATOR_KEYS=""
SS58_PREFIX="${DEFAULT_SS58_PREFIX}"
DEV_MODE="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--network)      NETWORK_ID="$2"; shift 2 ;;
        -o|--out)          OUT_DIR="$2";    shift 2 ;;
        -k|--keys)         VALIDATOR_KEYS="$2"; shift 2 ;;
        -s|--ss58)         SS58_PREFIX="$2";   shift 2 ;;
        -d|--dev)          DEV_MODE="true"; shift ;;
        -h|--help)         print_help; exit 0 ;;
        *) log::error "Unknown option: $1"; print_help; exit 1 ;;
    esac
done

###############################################################################
# Pre-flight Checks
###############################################################################
log::section "Verifying prerequisites"

for cmd in cargo jq yq; do
    require_cmd "${cmd}"
done

if [[ -n "${VALIDATOR_KEYS}" && ! -f "${VALIDATOR_KEYS}" ]]; then
    log::error "Validator keys file not found: ${VALIDATOR_KEYS}"
    exit 1
fi

###############################################################################
# Build Rust Binaries (Release)
###############################################################################
log::section "Building Rust binaries (release)"
if [[ ! -x "${NODE_BIN}" || ! -x "${CLI_BIN}" ]]; then
    log::info "Compiling CanvasChain binaries with cargo"
    cargo build --release --workspace --quiet
else
    log::info "Binaries already built – skipping compilation"
fi

###############################################################################
# Prepare Output Directory
###############################################################################
OUT_DIR=$(canonical_path "${OUT_DIR}")
mkdir -p "${OUT_DIR}"

RAW_SPEC="${OUT_DIR}/${NETWORK_ID}-raw.json"
PLAIN_SPEC="${OUT_DIR}/${NETWORK_ID}.json"
GENESIS_STATE="${OUT_DIR}/genesis_state.bin"
GENESIS_WASM="${OUT_DIR}/genesis_wasm.compact"

###############################################################################
# Generate Chain Specification
###############################################################################
log::section "Generating chain-spec"

if [[ "${DEV_MODE}" == "true" ]]; then
    "${NODE_BIN}" build-spec --dev --disable-default-bootnode                                          \
                             --chain-id "${NETWORK_ID}"                                                \
                             --chain-name "${NETWORK_ID}"                                              \
                             --ss58-format "${SS58_PREFIX}"                                            \
                             > "${PLAIN_SPEC}"
else
    "${NODE_BIN}" build-spec --chain-id "${NETWORK_ID}"                                                \
                             --chain-name "${NETWORK_ID}"                                              \
                             --para-id 0                                                               \
                             --ss58-format "${SS58_PREFIX}"                                            \
                             --disable-default-bootnode                                                \
                             > "${PLAIN_SPEC}"
fi

cp "${PLAIN_SPEC}" "${RAW_SPEC}"

###############################################################################
# Inject Validator Keys (if provided)
###############################################################################
if [[ -n "${VALIDATOR_KEYS}" ]]; then
    log::section "Injecting initial authority keys"
    # The YAML is expected to contain an array of objects with the form:
    # - stash: 5Fx...
    #   controller: 5Gx...
    #   grandpa: 0x...
    #   babe: 0x...
    #   im_online: 0x...
    tmp="$(mktemp)"
    yq -c '.[]' "${VALIDATOR_KEYS}" | while read -r val; do
        STASH=$(echo "${val}" | jq -r '.stash')
        CONTROLLER=$(echo "${val}" | jq -r '.controller')
        GRANDPA=$(echo "${val}" | jq -r '.grandpa')
        BABE=$(echo "${val}" | jq -r '.babe')
        IMONLINE=$(echo "${val}" | jq -r '.im_online')

        jq --arg stash "${STASH}"                                                                      \
           --arg controller "${CONTROLLER}"                                                            \
           --arg grandpa "${GRANDPA}"                                                                  \
           --arg babe "${BABE}"                                                                        \
           --arg im_online "${IMONLINE}"                                                               \
           '
           (.genesis.runtime.staking.stakers) += [
               [$stash, $controller, 1000000000000000000, "Validator"]
           ] |
           (.genesis.runtime.session.keys) += [
               [$stash,
                $stash,
                {
                  "grandpa":  $grandpa,
                  "babe":     $babe,
                  "im_online": $im_online
                }
               ]
           ]
           ' "${RAW_SPEC}" > "${tmp}" && mv "${tmp}" "${RAW_SPEC}"
    done
fi

###############################################################################
# Build Raw Specialist ChainSpec (again) after modifications
###############################################################################
log::section "Converting to raw chain-spec"
"${NODE_BIN}" build-spec --chain "${RAW_SPEC}" --raw > "${RAW_SPEC}.tmp" && mv "${RAW_SPEC}.tmp" "${RAW_SPEC}"

###############################################################################
# Generate Genesis State & WASM
###############################################################################
log::section "Extracting genesis state artifacts"

"${CLI_BIN}" export-genesis-state --chain "${RAW_SPEC}" > "${GENESIS_STATE}"
"${CLI_BIN}" export-genesis-wasm   --chain "${RAW_SPEC}" > "${GENESIS_WASM}"

log::info "Genesis files generated:"
log::info "  Chain spec (plain): ${PLAIN_SPEC}"
log::info "  Chain spec (raw)  : ${RAW_SPEC}"
log::info "  Genesis state     : ${GENESIS_STATE}"
log::info "  Genesis WASM      : ${GENESIS_WASM}"
log::section "Genesis initialisation completed ✅"
