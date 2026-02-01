#!/bin/bash
#
# run_kubernetes_docs_benchmark.sh
#
# Run the Kubernetes documentation benchmark comparing baseline Claude
# vs Claude + Sourcegraph MCP tools.
#
# Usage:
#   ./run_kubernetes_docs_benchmark.sh <task-id> [options]
#
# Examples:
#   ./run_kubernetes_docs_benchmark.sh pkg-doc-001
#   ./run_kubernetes_docs_benchmark.sh sched-doc-001 --agents baseline,aggressive
#   ./run_kubernetes_docs_benchmark.sh all --model anthropic/claude-haiku-4-5-20251001

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$(dirname "$BENCHMARK_DIR")")"

# Default settings
MODEL="${MODEL:-anthropic/claude-haiku-4-5-20251001}"
AGENTS="${AGENTS:-baseline,deep-search}"  # Use doc benchmark agents by default
OUTPUT_DIR="${OUTPUT_DIR:-$PROJECT_ROOT/jobs}"
KUBERNETES_REPO="${KUBERNETES_REPO:-}"
KUBERNETES_ENHANCEMENTS_REPO="${KUBERNETES_ENHANCEMENTS_REPO:-}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

usage() {
    cat << EOF
Usage: $(basename "$0") <task-id> [options]

Run Kubernetes documentation benchmark tasks.

Arguments:
    task-id     Task to run (e.g., pkg-doc-001, sched-doc-001, or 'all')

Options:
    --model MODEL           LLM model to use (default: $MODEL)
    --agents AGENTS         Comma-separated agent list (default: $AGENTS)
    --output DIR            Output directory (default: $OUTPUT_DIR)
    --k8s-repo PATH         Path to kubernetes/kubernetes clone
    --keps-repo PATH        Path to kubernetes/enhancements clone
    --dry-run               Show what would be run without executing
    --help                  Show this help message

Available Tasks:
    pkg-doc-001    Container Manager package documentation
    pkg-doc-002    Scheduler Framework package documentation
    sched-doc-001  PodTopologySpread plugin documentation
    sched-doc-002  Default Pod Topology Spread
    ctrl-doc-001   Garbage Collector controller
    kubelet-doc-001 Topology Manager
    api-doc-001    Server-Side Apply

Agent Options (Documentation Benchmark - with query filtering):
    baseline       DocBenchmarkBaselineAgent (no MCP, local files only)
    deep-search    DocBenchmarkDeepSearchAgent (Deep Search + doc filtering)
    keyword-only   DocBenchmarkKeywordOnlyAgent (keyword search + doc filtering)

Agent Options (Standard - NO filtering, for comparison only):
    aggressive     DeepSearchFocusedAgent (unfiltered Deep Search)
    nodeep         MCPNonDeepSearchAgent (unfiltered keyword search)
    full-toolkit   FullToolkitAgent (all tools, unfiltered)

Examples:
    # Run single task with default agents
    $(basename "$0") pkg-doc-001

    # Run all tasks with specific agents
    $(basename "$0") all --agents baseline,aggressive,nodeep

    # Dry run to see commands
    $(basename "$0") sched-doc-001 --dry-run
EOF
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Parse arguments
TASK_ID=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --model)
            MODEL="$2"
            shift 2
            ;;
        --agents)
            AGENTS="$2"
            shift 2
            ;;
        --output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --k8s-repo)
            KUBERNETES_REPO="$2"
            shift 2
            ;;
        --keps-repo)
            KUBERNETES_ENHANCEMENTS_REPO="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        -*)
            log_error "Unknown option: $1"
            usage
            exit 1
            ;;
        *)
            TASK_ID="$1"
            shift
            ;;
    esac
done

if [[ -z "$TASK_ID" ]]; then
    log_error "Task ID is required"
    usage
    exit 1
fi

# Get list of tasks
get_tasks() {
    if [[ "$TASK_ID" == "all" ]]; then
        find "$BENCHMARK_DIR" -maxdepth 1 -type d -name '*-doc-*' -exec basename {} \; | sort
    else
        echo "$TASK_ID"
    fi
}

# Map agent short names to import paths
get_agent_import_path() {
    local agent="$1"
    case "$agent" in
        # Documentation benchmark specialized agents (with query filtering)
        baseline)
            echo "benchmarks.kubernetes_docs.agents:DocBenchmarkBaselineAgent"
            ;;
        deep-search)
            echo "benchmarks.kubernetes_docs.agents:DocBenchmarkDeepSearchAgent"
            ;;
        keyword-only)
            echo "benchmarks.kubernetes_docs.agents:DocBenchmarkKeywordOnlyAgent"
            ;;
        # Legacy/standard agents (for comparison - NOT filtered)
        aggressive)
            echo "agents.mcp_variants:DeepSearchFocusedAgent"
            ;;
        nodeep)
            echo "agents.mcp_variants:MCPNonDeepSearchAgent"
            ;;
        full-toolkit)
            echo "agents.mcp_variants:FullToolkitAgent"
            ;;
        *)
            log_error "Unknown agent: $agent"
            exit 1
            ;;
    esac
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check for harbor
    if ! command -v harbor &> /dev/null; then
        log_error "harbor command not found. Activate the harbor venv:"
        echo "  source harbor/bin/activate"
        exit 1
    fi

    # Check for required environment variables
    if [[ -z "$ANTHROPIC_API_KEY" ]]; then
        log_warning "ANTHROPIC_API_KEY not set. Source .env.local and export it:"
        echo "  source .env.local && export ANTHROPIC_API_KEY"
    fi

    # Check for Kubernetes repo if needed
    if [[ -z "$KUBERNETES_REPO" ]]; then
        log_warning "KUBERNETES_REPO not set. Set --k8s-repo for ground truth extraction."
    fi

    log_success "Prerequisites check complete"
}

# Run a single task with a single agent
run_task() {
    local task="$1"
    local agent="$2"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local experiment_name="k8s-docs-${task}-${agent}-${timestamp}"
    local task_dir="$BENCHMARK_DIR/$task"
    local output_path="$OUTPUT_DIR/$experiment_name"

    if [[ ! -d "$task_dir" ]]; then
        log_error "Task directory not found: $task_dir"
        return 1
    fi

    log_info "Running task: $task with agent: $agent"
    log_info "Output: $output_path"

    local agent_import=$(get_agent_import_path "$agent")

    local cmd="harbor run \
        --path $task_dir \
        --agent-import-path $agent_import \
        --model $MODEL \
        -n 1"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY RUN] Would execute:"
        echo "  $cmd"
        return 0
    fi

    # Create output directory
    mkdir -p "$output_path"

    # Run the task
    log_info "Executing: $cmd"
    eval "$cmd" 2>&1 | tee "$output_path/run.log"

    log_success "Task $task completed with agent $agent"
}

# Run evaluation
run_evaluation() {
    local task="$1"
    local agent="$2"
    local generated_output="$3"
    local ground_truth="$BENCHMARK_DIR/$task/ground_truth"

    log_info "Evaluating $task output from $agent"

    if [[ ! -d "$ground_truth" ]]; then
        log_warning "No ground truth found for $task, skipping evaluation"
        return 0
    fi

    # Find the ground truth file
    local gt_file=$(find "$ground_truth" -type f \( -name "*.md" -o -name "*.go" \) | head -1)

    if [[ -z "$gt_file" ]]; then
        log_warning "No ground truth file found in $ground_truth"
        return 0
    fi

    # Find the generated output file
    local gen_file=$(find "$generated_output" -type f \( -name "*.md" -o -name "*.go" -o -name "doc.go" \) | head -1)

    if [[ -z "$gen_file" ]]; then
        log_warning "No generated output found for evaluation"
        return 0
    fi

    local eval_output="$generated_output/evaluation.json"

    local cmd="python3 $SCRIPT_DIR/evaluate_docs.py \
        --generated $gen_file \
        --ground-truth $gt_file \
        --model $MODEL \
        --output $eval_output \
        --task-context 'Kubernetes documentation task: $task'"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY RUN] Would evaluate:"
        echo "  $cmd"
        return 0
    fi

    log_info "Executing evaluation..."
    eval "$cmd"

    log_success "Evaluation complete: $eval_output"
}

# Main execution
main() {
    log_info "Kubernetes Documentation Benchmark Runner"
    log_info "========================================="

    check_prerequisites

    local tasks=$(get_tasks)
    local agents_array=(${AGENTS//,/ })

    log_info "Tasks to run: $(echo $tasks | tr '\n' ' ')"
    log_info "Agents: ${agents_array[*]}"
    log_info "Model: $MODEL"

    echo ""

    local total_runs=0
    local successful_runs=0

    for task in $tasks; do
        for agent in "${agents_array[@]}"; do
            ((total_runs++))

            if run_task "$task" "$agent"; then
                ((successful_runs++))
            fi

            echo ""
        done
    done

    echo ""
    log_info "========================================="
    log_info "Benchmark Complete"
    log_info "Successful: $successful_runs / $total_runs"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_warning "This was a dry run. No tasks were actually executed."
    fi
}

main
