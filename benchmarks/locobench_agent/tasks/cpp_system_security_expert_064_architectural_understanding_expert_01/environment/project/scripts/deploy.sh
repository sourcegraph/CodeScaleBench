#!/usr/bin/env bash
#==============================================================================
#  FortiLedger360 - Enterprise Security Suite
#------------------------------------------------------------------------------
#  File        : scripts/deploy.sh
#  Description : Continuous-Deployment helper for FortiLedger360’s micro-
#                services stack.  The script orchestrates the entire pipeline:
#                1. Build C++ binaries
#                2. Execute unit tests
#                3. Build OCI images
#                4. Push images to registry
#                5. Deploy (or upgrade) Helm release
#                6. Rollback / Status / Cleanup utilities
#
#  Usage       : ./deploy.sh <command> [options]
#
#  Maintainer  : DevOps Team <devops@fortiledger360.io>
#  License     : MIT
#==============================================================================

set -euo pipefail
IFS=$'\n\t'

#------------------------------------------------------------------------------
# Constants & Helpers
#------------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Pretty-printing helpers ------------------------------------------------------
bold=$(tput bold || true)
green=$(tput setaf 2 || true)
red=$(tput setaf 1 || true)
yellow=$(tput setaf 3 || true)
reset=$(tput sgr0 || true)

log()  { printf "%s%s[INFO] %s%s\n"   "$bold" "$green" "$*" "$reset"; }
warn() { printf "%s%s[WARN] %s%s\n"   "$bold" "$yellow" "$*" "$reset" >&2; }
err()  { printf "%s%s[ERROR] %s%s\n"  "$bold" "$red" "$*" "$reset" >&2; }
die()  { err "$*"; exit 1; }

# Trap unexpected failures -----------------------------------------------------
trap 'err "Unexpected error at line $LINENO.  Aborting."; exit 1' ERR

#------------------------------------------------------------------------------
# Required external tools
#------------------------------------------------------------------------------
required_cmds=(docker kubectl helm make git)
for cmd in "${required_cmds[@]}"; do
    command -v "$cmd" >/dev/null 2>&1 || die "Required command '$cmd' not found."
done

#------------------------------------------------------------------------------
# Configuration (overridable via ENV)
#------------------------------------------------------------------------------
ENVIRONMENT=${ENVIRONMENT:-dev}                              # dev | staging | prod
REGISTRY=${REGISTRY:-"registry.fortiledger360.local"}        # OCI registry FQDN
NAMESPACE=${NAMESPACE:-"fortiledger360-${ENVIRONMENT}"}      # k8s namespace
COMMIT_SHA=$(git -C "$ROOT_DIR" rev-parse --short HEAD)
VERSION_TAG=${VERSION_TAG:-"${COMMIT_SHA}-${ENVIRONMENT}"}   # docker tag
PARALLEL_BUILDS=${PARALLEL_BUILDS:-"$(nproc)"}               # make -j jobs
HELM_RELEASE="fortiledger360"                                # helm release name

# Services to build/deploy -----------------------------------------------------
services=(
    "scanner"
    "metrics"
    "config_manager"
    "backup_node"
    "alert_broker"
)

#------------------------------------------------------------------------------
# Usage
#------------------------------------------------------------------------------
usage() {
cat <<EOF
FortiLedger360 Deployment Utility

Usage: $(basename "$0") <command> [options]

Commands
  build        Build all C++ binaries (make all)
  test         Run unit tests (make test)
  docker       Build Docker images for each service
  push         Push images to configured registry
  deploy       Build → Test → Docker → Push → Helm deploy (default pipeline)
  rollback     Roll back to previous Helm release revision
  status       Display rollout status of deployment
  version      Print calculated VERSION_TAG
  clean        Delete namespace and persistent volumes (DANGER)
  help         Print this help

Environment Variables
  ENVIRONMENT     Target environment (dev|staging|prod)      Default: dev
  REGISTRY        Docker registry FQDN                       Default: registry.fortiledger360.local
  VERSION_TAG     Image tag (overrides git-sha-env)          Default: <git-sha>-<env>
  NAMESPACE       Kubernetes namespace                       Default: fortiledger360-<env>
  PARALLEL_BUILDS Number of parallel 'make' jobs             Default: nproc
EOF
}

#------------------------------------------------------------------------------
# Functions
#------------------------------------------------------------------------------
build_binaries() {
    log "Building C++ binaries (jobs: ${PARALLEL_BUILDS})"
    make -C "$ROOT_DIR" -j "${PARALLEL_BUILDS}" all
}

run_tests() {
    log "Running unit tests"
    make -C "$ROOT_DIR" test
}

build_images() {
    log "Building Docker images (tag: ${VERSION_TAG})"
    for svc in "${services[@]}"; do
        svc_dir="$ROOT_DIR/services/${svc}"
        [[ -d "$svc_dir" ]] || die "Service directory not found: ${svc_dir}"
        docker build --platform linux/amd64 \
            -t "${REGISTRY}/${svc}:${VERSION_TAG}" \
            "$svc_dir"
    done
}

push_images() {
    log "Pushing images to registry '${REGISTRY}'"
    for svc in "${services[@]}"; do
        docker push "${REGISTRY}/${svc}:${VERSION_TAG}"
    done
}

create_namespace() {
    if kubectl get ns "${NAMESPACE}" >/dev/null 2>&1; then
        log "Namespace '${NAMESPACE}' already exists"
    else
        log "Creating namespace '${NAMESPACE}'"
        kubectl create namespace "${NAMESPACE}"
    fi
}

deploy_helm() {
    create_namespace
    log "Deploying Helm chart '${HELM_RELEASE}' (namespace: ${NAMESPACE})"
    helm upgrade --install "${HELM_RELEASE}" "$ROOT_DIR/helm" \
        --namespace "${NAMESPACE}" \
        --set global.imageRegistry="${REGISTRY}" \
        --set global.imageTag="${VERSION_TAG}" \
        --atomic --wait --timeout 10m
}

rollback_helm() {
    log "Rolling back Helm release '${HELM_RELEASE}'"
    helm rollback "${HELM_RELEASE}" --namespace "${NAMESPACE}" || die "Rollback failed"
}

rollout_status() {
    log "Helm release history:"
    helm history "${HELM_RELEASE}" -n "${NAMESPACE}" | tail -n 10
    echo
    log "Kubernetes deployments:"
    kubectl -n "${NAMESPACE}" get deploy
}

clean_namespace() {
    warn "This will DELETE Kubernetes namespace '${NAMESPACE}' AND all resources within."
    read -rp "Continue? (y/N): " confirm
    if [[ "${confirm,,}" == "y" ]]; then
        kubectl delete namespace "${NAMESPACE}"
        log "Namespace '${NAMESPACE}' deletion scheduled"
    else
        log "Cleanup aborted by user"
    fi
}

#------------------------------------------------------------------------------
# Dispatcher
#------------------------------------------------------------------------------
case "${1:-}" in
    build)
        build_binaries
        ;;
    test)
        run_tests
        ;;
    docker)
        build_images
        ;;
    push)
        push_images
        ;;
    deploy)
        build_binaries
        run_tests
        build_images
        push_images
        deploy_helm
        ;;
    rollback)
        rollback_helm
        ;;
    status)
        rollout_status
        ;;
    version)
        echo "${VERSION_TAG}"
        ;;
    clean)
        clean_namespace
        ;;
    help|"")
        usage
        ;;
    *)
        err "Unknown command: $1"
        echo
        usage
        exit 1
        ;;
esac

log "Operation completed successfully."
