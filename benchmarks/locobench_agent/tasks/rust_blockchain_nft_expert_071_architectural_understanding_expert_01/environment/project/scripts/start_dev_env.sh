```bash
#!/usr/bin/env bash
################################################################################
# CanvasChain Symphony – Development Environment Bootstrap Script
#
# File:    scripts/start_dev_env.sh
# Purpose: Spin-up the full local development stack (Docker services + Rust
#          micro-services) in a reproducible way.  Handles first-time toolchain
#          installation, dependency health-checks, clean rebuilds, and graceful
#          shutdown on SIGINT/SIGTERM.
#
# Usage:
#   ./scripts/start_dev_env.sh [options]
#
# Options:
#   -c, --clean           Remove target/ and Docker volumes before build.
#   -d, --detach          Do not attach to tmux session after start-up.
#   -s, --service <name>  Start only one micro-service (may be passed multiple
#                         times).  Default = all.
#   -h, --help            Show this help and exit.
#
# Examples:
#   # Start everything, attach to tmux panes:
#   ./scripts/start_dev_env.sh
#
#   # Start only composer_node and marketplace, detach from tmux:
#   ./scripts/start_dev_env.sh -d -s composer_node -s marketplace
#
# Dependencies:
#   • bash 4.4+              • docker & docker-compose
#   • rustup / stable toolchain   • protoc (protobuf compiler)
#   • tmux 3.1+
################################################################################
set -euo pipefail
IFS=$'\n\t'

################################################################################
# Constants & Configuration
################################################################################
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &>/dev/null && pwd )"
PROJECT_ROOT="${SCRIPT_DIR}/.."
DOCKER_COMPOSE_FILE="${PROJECT_ROOT}/ops/docker-compose.dev.yml"
TMUX_SESSION="canvaschain_dev"
PROTOC_VERSION="3.21.12"
MICROSERVICES=(
  composer_node
  conductor_gateway
  nft_minter
  marketplace
  royalty_streamer
  governance_daemon
  defi_engine
  wallet_service
  event_bus_bridge
  api_gateway
)

################################################################################
# Colour helpers (POSIX-compatible)
################################################################################
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log()          { printf "${BLUE}[canvaschain]${NC} %s\n"  "$*"; }
log_warn()     { printf "${YELLOW}[canvaschain][WARN]${NC} %s\n" "$*" >&2; }
log_error()    { printf "${RED}[canvaschain][ERROR]${NC} %s\n" "$*" >&2; }
log_success()  { printf "${GREEN}[canvaschain]${NC} %s\n"  "$*"; }

################################################################################
# Utility Functions
################################################################################
command_exists() { command -v "$1" &>/dev/null; }

die() { log_error "$1"; exit 1; }

require() {
  local cmd="$1" msg="${2:-}"
  command_exists "$cmd" || die "Required command '${cmd}' is not installed. ${msg}"
}

cleanup() {
  log "Caught interrupt – shutting down tmux & docker-compose…"
  tmux has-session -t "$TMUX_SESSION" 2>/dev/null && tmux kill-session -t "$TMUX_SESSION"
  docker compose -f "$DOCKER_COMPOSE_FILE" down --remove-orphans &>/dev/null || true
  exit 0
}

trap cleanup SIGINT SIGTERM

################################################################################
# Pre-flight Checks
################################################################################
check_prerequisites() {
  log "Verifying toolchain prerequisites…"
  require "docker"          "Install Docker: https://docs.docker.com/get-docker/"
  require "docker-compose"  "Install Docker Compose plugin."
  require "tmux"            "Install tmux 3.1+"
  require "rustup"          "Install rustup: https://rustup.rs/"
  require "protoc"          "Install protobuf compiler."
  require "cargo"           # Provided by rustup, but double-check.
}

ensure_rust_toolchain() {
  if ! rustup show active-toolchain | grep -q "stable"; then
    log "Installing stable Rust toolchain…"
    rustup install stable
  fi
  rustup component add clippy rustfmt &>/dev/null || true
}

ensure_protoc_version() {
  local current
  current="$(protoc --version | awk '{print $2}')"
  if [[ "$current" != "$PROTOC_VERSION" ]]; then
    log_warn "Protoc version ${current} detected; ${PROTOC_VERSION} is recommended."
  fi
}

################################################################################
# Docker helpers
################################################################################
docker_start() {
  log "Starting Docker dependencies (${DOCKER_COMPOSE_FILE})…"
  docker compose -f "$DOCKER_COMPOSE_FILE" pull --quiet
  docker compose -f "$DOCKER_COMPOSE_FILE" up -d # we rely on healthchecks below
  log "Waiting for Docker health checks to pass…"
  docker compose -f "$DOCKER_COMPOSE_FILE" ps --services --filter "status=running" \
    | while read -r svc; do
        until docker compose -f "$DOCKER_COMPOSE_FILE" exec "$svc" /bin/sh -c 'echo healthy' &>/dev/null; do
          printf '.'
          sleep 1
        done
      done
  log_success "All Docker services are healthy."
}

################################################################################
# Build & Start Micro-services
################################################################################
build_service() {
  local service="$1"
  log "Building ${service}…"
  pushd "${PROJECT_ROOT}/${service}" &>/dev/null
  cargo clippy --workspace --all-targets -- -D warnings
  cargo build --release
  popd &>/dev/null
}

start_service_tmux() {
  local service="$1"
  local idx="$2"
  local pane="pane_${idx}"
  tmux new-window  -t "$TMUX_SESSION" -n "$service" -d
  tmux send-keys   -t "$TMUX_SESSION:$service" "cd ${PROJECT_ROOT}/${service} && cargo run" C-m
}

build_selected_services() {
  local -a selected=("$@")
  for svc in "${selected[@]}"; do
    build_service "$svc"
  done
}

start_selected_services_tmux() {
  local -a selected=("$@")
  local idx=0
  for svc in "${selected[@]}"; do
    start_service_tmux "$svc" "$idx"
    ((idx++))
  done
}

################################################################################
# CLI Argument Parsing
################################################################################
CLEAN=0
DETACH=0
SELECTED_SERVICES=()

print_help() { grep '^#' "$0" | head -n 40 | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    -c|--clean)   CLEAN=1; shift ;;
    -d|--detach)  DETACH=1; shift ;;
    -s|--service) SELECTED_SERVICES+=("$2"); shift 2 ;;
    -h|--help)    print_help; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

if [[ ${#SELECTED_SERVICES[@]} -eq 0 ]]; then
  SELECTED_SERVICES=("${MICROSERVICES[@]}") # default: all services
fi

################################################################################
# Main
################################################################################
main() {
  check_prerequisites
  ensure_rust_toolchain
  ensure_protoc_version

  [[ $CLEAN -eq 1 ]] && {
    log "Cleaning docker volumes & cargo artifacts…"
    docker compose -f "$DOCKER_COMPOSE_FILE" down -v --remove-orphans || true
    find "$PROJECT_ROOT" -maxdepth 2 -type d -name target -exec rm -rf {} +
  }

  docker_start
  build_selected_services "${SELECTED_SERVICES[@]}"

  log "Launching micro-services inside tmux session '${TMUX_SESSION}'…"
  tmux has-session -t "$TMUX_SESSION" 2>/dev/null && tmux kill-session -t "$TMUX_SESSION"
  tmux new-session -d -s "$TMUX_SESSION" -n "bootstrap" "printf 'CanvasChain dev-env bootstrap\n'; bash"

  start_selected_services_tmux "${SELECTED_SERVICES[@]}"

  log_success "All selected micro-services are running."

  if [[ $DETACH -eq 0 ]]; then
    log "Attaching to tmux session. Exit with Ctrl-b d (detach) or Ctrl-c to shutdown."
    tmux attach -t "$TMUX_SESSION"
  else
    log "Detached mode enabled; tmux session '${TMUX_SESSION}' continues in background."
  fi
}

main "$@"
```