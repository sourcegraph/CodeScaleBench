#!/bin/bash
#
# run_official_benchmark.sh
#
# Run the full Kubernetes Documentation benchmark: all 5 tasks, both baseline
# and Sourcegraph MCP variants, with LLM judge evaluation.
#
# Usage:
#   ./run_official_benchmark.sh [--dry-run] [--model MODEL] [--category CATEGORY]
#
# Prerequisites:
#   - harbor CLI installed
#   - ~/evals/.env.local with SOURCEGRAPH_ACCESS_TOKEN and SOURCEGRAPH_ENDPOINT
#   - ANTHROPIC_API_KEY set (for LLM judge) or subscription auth
#   - Run from the CodeContextBench project root
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$(dirname "$BENCHMARK_DIR")")"

# Defaults
MODEL="${MODEL:-claude-opus-4-5-20251101}"
CATEGORY="${CATEGORY:-official}"
CONCURRENCY=1
DRY_RUN=false
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RUN_NAME="k8s-docs_${CATEGORY}_${TIMESTAMP}"
RESULTS_DIR="${PROJECT_ROOT}/runs/${CATEGORY}/${RUN_NAME}"

# All 5 tasks
TASKS=(
    "pkg-doc-001"
    "client-go-doc-001"
    "applyconfig-doc-001"
    "apiserver-doc-001"
    "fairqueuing-doc-001"
)

# Ground truth mapping (task -> ground truth file relative to task dir)
declare -A GROUND_TRUTH
GROUND_TRUTH[pkg-doc-001]="ground_truth/doc.go"
GROUND_TRUTH[client-go-doc-001]="ground_truth/doc.go"
GROUND_TRUTH[applyconfig-doc-001]="ground_truth/doc.go"
GROUND_TRUTH[apiserver-doc-001]="ground_truth/doc.go"
GROUND_TRUTH[fairqueuing-doc-001]="ground_truth/doc.go"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
log_header()  { echo -e "\n${BOLD}=== $1 ===${NC}\n"; }

usage() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Run full Kubernetes Documentation benchmark (5 tasks x 2 variants).

Options:
    --model MODEL       LLM model (default: $MODEL)
    --category CAT      Run category: official|experiment|troubleshooting (default: $CATEGORY)
    --dry-run           Show what would be run without executing
    --tasks TASKS       Comma-separated subset of tasks (default: all)
    --skip-judge        Skip LLM judge evaluation
    --help              Show this help
EOF
}

# Parse arguments
SKIP_JUDGE=false
TASK_FILTER=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --model)       MODEL="$2"; shift 2 ;;
        --category)    CATEGORY="$2"; shift 2 ;;
        --dry-run)     DRY_RUN=true; shift ;;
        --tasks)       TASK_FILTER="$2"; shift 2 ;;
        --skip-judge)  SKIP_JUDGE=true; shift ;;
        --help|-h)     usage; exit 0 ;;
        *)             log_error "Unknown option: $1"; usage; exit 1 ;;
    esac
done

# Filter tasks if requested
if [[ -n "$TASK_FILTER" ]]; then
    IFS=',' read -ra FILTERED_TASKS <<< "$TASK_FILTER"
    TASKS=("${FILTERED_TASKS[@]}")
fi

# Recalculate run name with actual params
RUN_NAME="k8s-docs_${CATEGORY}_${TIMESTAMP}"
RESULTS_DIR="${PROJECT_ROOT}/runs/${CATEGORY}/${RUN_NAME}"

# ─── Pre-flight checks ───────────────────────────────────────────────

log_header "Pre-flight Checks"

# Source credentials
if [[ -f ~/evals/.env.local ]]; then
    source ~/evals/.env.local
    log_success "Loaded ~/evals/.env.local"
else
    log_error "~/evals/.env.local not found"
    exit 1
fi

export SOURCEGRAPH_ACCESS_TOKEN
export SOURCEGRAPH_URL="${SOURCEGRAPH_URL:-${SOURCEGRAPH_ENDPOINT}}"

# Check required tools
command -v harbor &>/dev/null || { log_error "harbor not found"; exit 1; }
log_success "harbor CLI found"

# Check credentials
[[ -n "$SOURCEGRAPH_ACCESS_TOKEN" ]] || { log_error "SOURCEGRAPH_ACCESS_TOKEN not set"; exit 1; }
[[ -n "$SOURCEGRAPH_URL" ]] || { log_error "SOURCEGRAPH_URL not set"; exit 1; }
log_success "Sourcegraph credentials set ($SOURCEGRAPH_URL)"

# Check subscription auth
if [[ -f ~/.claude/.credentials.json ]]; then
    log_success "Subscription auth available"
else
    log_warning "No subscription credentials - will need ANTHROPIC_API_KEY"
fi

# Check task directories
for task in "${TASKS[@]}"; do
    task_dir="${BENCHMARK_DIR}/${task}"
    if [[ ! -f "${task_dir}/task.toml" ]]; then
        log_error "Task ${task} missing task.toml at ${task_dir}"
        exit 1
    fi
done
log_success "All ${#TASKS[@]} task directories verified"

# Create results directory
mkdir -p "$RESULTS_DIR"
log_success "Results directory: $RESULTS_DIR"

# ─── Summary ──────────────────────────────────────────────────────────

log_header "Benchmark Configuration"
log_info "Tasks:      ${TASKS[*]}"
log_info "Model:      $MODEL"
log_info "Category:   $CATEGORY"
log_info "Variants:   baseline, sourcegraph"
log_info "Results:    $RESULTS_DIR"
log_info "Total runs: $((${#TASKS[@]} * 2))"

if [[ "$DRY_RUN" == "true" ]]; then
    log_warning "DRY RUN - no tasks will be executed"
fi

echo ""

# ─── Run tasks ────────────────────────────────────────────────────────

cd "$PROJECT_ROOT"

run_variant() {
    local task="$1"
    local variant="$2"  # "baseline" or "sourcegraph"
    local job_name="${task}-${variant}-${TIMESTAMP}"
    local task_path="benchmarks/kubernetes_docs/${task}"

    log_info "Running ${task} [${variant}]..."

    if [[ "$variant" == "sourcegraph" ]]; then
        export BASELINE_MCP_TYPE=sourcegraph
    else
        export BASELINE_MCP_TYPE=none
    fi

    local cmd="harbor run \
        --path ${task_path} \
        --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
        -m ${MODEL} \
        -n ${CONCURRENCY} \
        -k 1 \
        --job-name ${job_name} \
        --debug"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY RUN] $cmd"
        return 0
    fi

    # Run and capture result
    local start_time=$(date +%s)
    if eval "$cmd" 2>&1 | tee "${RESULTS_DIR}/${task}_${variant}.log"; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        log_success "${task} [${variant}] completed in ${duration}s"

        # Copy job results to results directory
        local job_dir="jobs/${job_name}"
        if [[ -d "$job_dir" ]]; then
            cp "${job_dir}/result.json" "${RESULTS_DIR}/${task}_${variant}_result.json" 2>/dev/null || true

            # Extract the generated doc from the trace
            local trial_dir=$(ls -d "${job_dir}/${task}__"* 2>/dev/null | head -1)
            if [[ -n "$trial_dir" && -f "${trial_dir}/agent/claude-code.txt" ]]; then
                # Extract tool calls summary
                python3 -c "
import json, sys
path = '${trial_dir}/agent/claude-code.txt'
tool_calls = []
with open(path) as f:
    for line in f:
        try:
            obj = json.loads(line.strip())
            if obj.get('type') == 'assistant' and 'message' in obj:
                for block in obj['message'].get('content', []):
                    if isinstance(block, dict) and block.get('type') == 'tool_use':
                        tool_calls.append(block.get('name', 'unknown'))
        except: pass

mcp_calls = [t for t in tool_calls if 'mcp__' in t]
summary = {
    'task': '${task}',
    'variant': '${variant}',
    'total_tool_calls': len(tool_calls),
    'mcp_tool_calls': len(mcp_calls),
    'mcp_tools_used': list(set(mcp_calls)),
    'tool_sequence': tool_calls,
    'duration_seconds': ${duration}
}
with open('${RESULTS_DIR}/${task}_${variant}_trace.json', 'w') as f:
    json.dump(summary, f, indent=2)
print(f'  Tool calls: {len(tool_calls)} total, {len(mcp_calls)} MCP')
" 2>/dev/null || true

                # Extract generated doc file content
                python3 -c "
import json
path = '${trial_dir}/agent/claude-code.txt'
with open(path) as f:
    for line in f:
        try:
            obj = json.loads(line.strip())
            if obj.get('type') == 'assistant' and 'message' in obj:
                for block in obj['message'].get('content', []):
                    if isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('name') == 'Write':
                        inp = block.get('input', {})
                        fp = inp.get('file_path', '')
                        if fp.endswith(('doc.go', 'README.md')):
                            with open('${RESULTS_DIR}/${task}_${variant}_output.txt', 'w') as out:
                                out.write(inp.get('content', ''))
                            break
        except: pass
" 2>/dev/null || true
            fi
        fi
    else
        log_error "${task} [${variant}] FAILED"
    fi

    # Unset MCP type
    unset BASELINE_MCP_TYPE
}

# Run all tasks
for task in "${TASKS[@]}"; do
    log_header "Task: ${task}"

    # Baseline first
    run_variant "$task" "baseline"
    echo ""

    # Then MCP
    run_variant "$task" "sourcegraph"
    echo ""
done

# ─── LLM Judge Evaluation ────────────────────────────────────────────

if [[ "$SKIP_JUDGE" == "true" || "$DRY_RUN" == "true" ]]; then
    log_info "Skipping LLM judge evaluation"
else
    log_header "LLM Judge Evaluation"

    EVAL_SCRIPT="${BENCHMARK_DIR}/scripts/evaluate_docs.py"
    JUDGE_MODEL="anthropic/claude-sonnet-4-20250514"

    for task in "${TASKS[@]}"; do
        gt_file="${BENCHMARK_DIR}/${task}/${GROUND_TRUTH[$task]}"

        if [[ ! -f "$gt_file" ]]; then
            log_warning "No ground truth for ${task}, skipping judge"
            continue
        fi

        for variant in baseline sourcegraph; do
            output_file="${RESULTS_DIR}/${task}_${variant}_output.txt"
            if [[ ! -f "$output_file" ]]; then
                log_warning "No output for ${task} [${variant}], skipping judge"
                continue
            fi

            log_info "Judging ${task} [${variant}]..."
            instructions_file="${BENCHMARK_DIR}/${task}/instruction.md"
            judge_args=(
                --generated "$output_file"
                --ground-truth "$gt_file"
                --model "$JUDGE_MODEL"
                --output "${RESULTS_DIR}/${task}_${variant}_eval.json"
            )
            if [[ -f "$instructions_file" ]]; then
                judge_args+=(--task-instructions "$instructions_file")
            else
                judge_args+=(--task-context "Kubernetes documentation task: ${task} (${variant} agent)")
            fi
            python3 "$EVAL_SCRIPT" "${judge_args[@]}" \
                2>&1 | tee -a "${RESULTS_DIR}/judge.log" || log_warning "Judge failed for ${task} [${variant}]"
            echo ""
        done
    done
fi

# ─── Summary Report ──────────────────────────────────────────────────

log_header "Results Summary"

python3 -c "
import json, os, glob

results_dir = '${RESULTS_DIR}'
tasks = '${TASKS[*]}'.split()

print(f'{'Task':<18} {'Variant':<14} {'Reward':>8} {'Tools':>8} {'MCP':>6} {'Judge':>8}')
print('-' * 70)

for task in tasks:
    for variant in ['baseline', 'sourcegraph']:
        reward = '-'
        tools = '-'
        mcp = '-'
        judge = '-'

        # Get reward from harbor result
        result_file = os.path.join(results_dir, f'{task}_{variant}_result.json')
        if os.path.exists(result_file):
            try:
                with open(result_file) as f:
                    data = json.load(f)
                reward = str(data.get('mean_reward', data.get('mean', '-')))
            except: pass

        # Get trace info
        trace_file = os.path.join(results_dir, f'{task}_{variant}_trace.json')
        if os.path.exists(trace_file):
            try:
                with open(trace_file) as f:
                    data = json.load(f)
                tools = str(data.get('total_tool_calls', '-'))
                mcp = str(data.get('mcp_tool_calls', '-'))
            except: pass

        # Get judge score
        eval_file = os.path.join(results_dir, f'{task}_{variant}_eval.json')
        if os.path.exists(eval_file):
            try:
                with open(eval_file) as f:
                    data = json.load(f)
                score = data.get('evaluation', {}).get('overall_score', '-')
                judge = str(score)
            except: pass

        print(f'{task:<18} {variant:<14} {reward:>8} {tools:>8} {mcp:>6} {judge:>8}')

print()
print(f'Results saved to: {results_dir}')
" 2>/dev/null || log_warning "Could not generate summary table"

log_success "Benchmark complete: $RESULTS_DIR"
