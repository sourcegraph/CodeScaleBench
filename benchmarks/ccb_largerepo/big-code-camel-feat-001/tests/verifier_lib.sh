#!/bin/bash
# verifier_lib.sh — Shared verifier library for ccb_largerepo tasks
#
# Provides:
#   - Solution.md parsing (extracts files from structured output)
#   - IR metrics computation (precision, recall, F1) against ground_truth.json
#   - Dependency chain accuracy scoring
#   - ir_metrics.json output generation
#   - Composite score computation
#
# Usage:
#   source /workspace/tests/verifier_lib.sh
#   parse_solution_files "/logs/agent/solution.md"
#   compute_ir_metrics "/workspace/tests/ground_truth.json"
#   write_ir_metrics "/logs/verifier/ir_metrics.json"
#   COMPOSITE=$(composite_score "$TASK_QUALITY" "$FILE_RECALL" "$FILE_PRECISION" "$DEP_ACCURACY")

# ---------------------------------------------------------------------------
# Globals (populated by functions below)
# ---------------------------------------------------------------------------
AGENT_FILES=()           # Files extracted from agent's solution.md
AGENT_DEP_CHAIN=()       # Dependency chain from agent's solution.md
GT_FILES=()              # Ground truth files from ground_truth.json
GT_DEP_CHAIN=()          # Ground truth dependency chain
GT_ROOT_CAUSE=()         # Root cause files (bug_investigation)
GT_ENTRY_POINTS=()       # Entry point files (security_analysis)
GT_DATA_FLOW=()          # Data flow files (security_analysis)
IR_PRECISION=0           # Computed precision
IR_RECALL=0              # Computed recall
IR_F1=0                  # Computed F1
DEP_ACCURACY=0           # Dependency traversal accuracy
ROOT_CAUSE_MRR=0         # MRR for root cause file ranking

# ---------------------------------------------------------------------------
# JSON helpers (pure bash + awk, no jq dependency)
# ---------------------------------------------------------------------------

# Extract a JSON array of strings from a file, given a key name.
# Outputs one path per line.
_json_string_array() {
    local file="$1" key="$2"
    if [ ! -f "$file" ]; then
        return
    fi
    # Use awk to extract array values for the given key.
    # Handles multi-line JSON arrays.
    awk -v key="\"$key\"" '
    BEGIN { in_array = 0 }
    $0 ~ key {
        in_array = 1
        # Check if array starts and ends on same line
        if (match($0, /\[.*\]/)) {
            line = substr($0, RSTART, RLENGTH)
            gsub(/[\[\]]/, "", line)
            n = split(line, parts, ",")
            for (i = 1; i <= n; i++) {
                gsub(/^[ \t]*"/, "", parts[i])
                gsub(/"[ \t]*$/, "", parts[i])
                if (parts[i] != "") print parts[i]
            }
            in_array = 0
        }
        next
    }
    in_array == 1 {
        if (/\]/) { in_array = 0; next }
        line = $0
        gsub(/^[ \t]*"/, "", line)
        gsub(/"[ \t,]*$/, "", line)
        gsub(/",?$/, "", line)
        if (line != "" && line !~ /^\[/) print line
    }
    ' "$file"
}

# ---------------------------------------------------------------------------
# Solution.md parsing
# ---------------------------------------------------------------------------

parse_solution_files() {
    local solution_file="$1"
    AGENT_FILES=()
    AGENT_DEP_CHAIN=()

    if [ ! -f "$solution_file" ]; then
        echo "WARN: Solution file not found: $solution_file"
        return 1
    fi

    # Strategy 1: Parse structured "## Files Examined" section
    local in_files=0
    local in_deps=0
    while IFS= read -r line; do
        # Detect section headers
        if echo "$line" | grep -qiE '^##\s+(Files Examined|Files Modified|Files Identified|Files Analyzed)'; then
            in_files=1; in_deps=0; continue
        fi
        if echo "$line" | grep -qiE '^##\s+(Dependency Chain|Call Chain|Traversal)'; then
            in_files=0; in_deps=1; continue
        fi
        if echo "$line" | grep -qE '^##\s'; then
            in_files=0; in_deps=0; continue
        fi

        if [ "$in_files" -eq 1 ]; then
            # Extract file path from "- path/to/file.ext — reason" or "- path/to/file.ext"
            local path
            path=$(echo "$line" | sed -n 's/^[-*]\s*`\?\([a-zA-Z0-9_/][a-zA-Z0-9_./-]*\.[a-zA-Z0-9]*\)`\?.*/\1/p')
            if [ -z "$path" ]; then
                # Try broader pattern: anything that looks like a file path
                path=$(echo "$line" | grep -oE '[a-zA-Z0-9_][a-zA-Z0-9_./-]+/[a-zA-Z0-9_./-]+\.[a-zA-Z]{1,10}' | head -1)
            fi
            if [ -n "$path" ]; then
                AGENT_FILES+=("$path")
            fi
        fi

        if [ "$in_deps" -eq 1 ]; then
            local path
            path=$(echo "$line" | grep -oE '[a-zA-Z0-9_][a-zA-Z0-9_./-]+/[a-zA-Z0-9_./-]+\.[a-zA-Z]{1,10}' | head -1)
            if [ -n "$path" ]; then
                AGENT_DEP_CHAIN+=("$path")
            fi
        fi
    done < "$solution_file"

    # Strategy 2: If structured parsing found nothing, fall back to regex extraction
    if [ ${#AGENT_FILES[@]} -eq 0 ]; then
        echo "NOTE: Structured parsing found no files, falling back to regex extraction"
        while IFS= read -r path; do
            AGENT_FILES+=("$path")
        done < <(grep -oE '[a-zA-Z0-9_][a-zA-Z0-9_./-]+/[a-zA-Z0-9_./-]+\.[a-zA-Z]{1,10}' "$solution_file" | \
            grep -v -E '(http|node_modules|\.lock$|/usr/|/bin/|/tmp/)' | \
            sort -u)
    fi

    echo "Parsed ${#AGENT_FILES[@]} files from solution.md (${#AGENT_DEP_CHAIN[@]} in dep chain)"
}

# ---------------------------------------------------------------------------
# Ground truth loading
# ---------------------------------------------------------------------------

load_ground_truth() {
    local gt_file="$1"
    GT_FILES=()
    GT_DEP_CHAIN=()
    GT_ROOT_CAUSE=()
    GT_ENTRY_POINTS=()
    GT_DATA_FLOW=()

    if [ ! -f "$gt_file" ]; then
        echo "ERROR: Ground truth file not found: $gt_file"
        return 1
    fi

    while IFS= read -r path; do
        GT_FILES+=("$path")
    done < <(_json_string_array "$gt_file" "files")

    while IFS= read -r path; do
        [ -n "$path" ] && GT_DEP_CHAIN+=("$path")
    done < <(_json_string_array "$gt_file" "dependency_chain")

    while IFS= read -r path; do
        [ -n "$path" ] && GT_ROOT_CAUSE+=("$path")
    done < <(_json_string_array "$gt_file" "root_cause_files")

    while IFS= read -r path; do
        [ -n "$path" ] && GT_ENTRY_POINTS+=("$path")
    done < <(_json_string_array "$gt_file" "entry_points")

    while IFS= read -r path; do
        [ -n "$path" ] && GT_DATA_FLOW+=("$path")
    done < <(_json_string_array "$gt_file" "data_flow")

    echo "Loaded ground truth: ${#GT_FILES[@]} files, ${#GT_DEP_CHAIN[@]} dep chain entries"
}

# ---------------------------------------------------------------------------
# IR metrics computation
# ---------------------------------------------------------------------------

# Normalize a file path for comparison:
#   - Strip leading /workspace/ or ./ or /
#   - Lowercase for case-insensitive match
_normalize_path() {
    local p="$1"
    p="${p#/workspace/}"
    p="${p#./}"
    p="${p#/}"
    echo "$p" | tr '[:upper:]' '[:lower:]'
}

compute_ir_metrics() {
    local gt_file="$1"

    # Load ground truth if not already loaded
    if [ ${#GT_FILES[@]} -eq 0 ]; then
        load_ground_truth "$gt_file"
    fi

    local gt_count=${#GT_FILES[@]}
    local agent_count=${#AGENT_FILES[@]}

    if [ "$gt_count" -eq 0 ]; then
        echo "WARN: Empty ground truth file set"
        IR_PRECISION=0; IR_RECALL=0; IR_F1=0
        return
    fi

    if [ "$agent_count" -eq 0 ]; then
        echo "WARN: Agent found no files"
        IR_PRECISION=0; IR_RECALL=0; IR_F1=0
        return
    fi

    # Build normalized ground truth set
    local -A gt_set
    for f in "${GT_FILES[@]}"; do
        gt_set[$(_normalize_path "$f")]=1
    done

    # Count true positives (agent files that match ground truth)
    local tp=0
    for f in "${AGENT_FILES[@]}"; do
        local norm
        norm=$(_normalize_path "$f")
        if [ "${gt_set[$norm]+_}" ]; then
            tp=$((tp + 1))
        fi
    done

    # Precision = tp / agent_count, Recall = tp / gt_count
    IR_PRECISION=$(awk "BEGIN {printf \"%.4f\", $tp / $agent_count}")
    IR_RECALL=$(awk "BEGIN {printf \"%.4f\", $tp / $gt_count}")

    # F1 = 2 * P * R / (P + R)
    if [ "$tp" -eq 0 ]; then
        IR_F1="0.0000"
    else
        IR_F1=$(awk "BEGIN {
            p = $tp / $agent_count
            r = $tp / $gt_count
            printf \"%.4f\", 2 * p * r / (p + r)
        }")
    fi

    echo "IR metrics: precision=$IR_PRECISION recall=$IR_RECALL F1=$IR_F1 (tp=$tp agent=$agent_count gt=$gt_count)"
}

# ---------------------------------------------------------------------------
# Dependency chain accuracy
# ---------------------------------------------------------------------------

compute_dep_accuracy() {
    # Dependency traversal accuracy: what fraction of GT dep chain
    # files appear in the agent's dep chain, in approximate order.
    local gt_count=${#GT_DEP_CHAIN[@]}
    DEP_ACCURACY="0.0000"

    if [ "$gt_count" -eq 0 ]; then
        DEP_ACCURACY="1.0000"  # No dep chain requirement = perfect
        return
    fi

    if [ ${#AGENT_DEP_CHAIN[@]} -eq 0 ]; then
        # Fall back to AGENT_FILES for ordering
        if [ ${#AGENT_FILES[@]} -eq 0 ]; then
            DEP_ACCURACY="0.0000"
            return
        fi
    fi

    # Use agent dep chain if available, else fall back to agent files
    local -a agent_chain
    if [ ${#AGENT_DEP_CHAIN[@]} -gt 0 ]; then
        agent_chain=("${AGENT_DEP_CHAIN[@]}")
    else
        agent_chain=("${AGENT_FILES[@]}")
    fi

    # Count GT dep chain files found in agent chain (order-aware)
    local found=0
    local last_idx=-1
    local in_order=0

    for gt_file in "${GT_DEP_CHAIN[@]}"; do
        local gt_norm
        gt_norm=$(_normalize_path "$gt_file")

        for idx in "${!agent_chain[@]}"; do
            local agent_norm
            agent_norm=$(_normalize_path "${agent_chain[$idx]}")
            if [ "$gt_norm" = "$agent_norm" ]; then
                found=$((found + 1))
                if [ "$idx" -gt "$last_idx" ]; then
                    in_order=$((in_order + 1))
                fi
                last_idx=$idx
                break
            fi
        done
    done

    # DTA = 0.5 * (found/gt_count) + 0.5 * (in_order/gt_count)
    DEP_ACCURACY=$(awk "BEGIN {
        coverage = $found / $gt_count
        ordering = $in_order / $gt_count
        printf \"%.4f\", 0.5 * coverage + 0.5 * ordering
    }")

    echo "Dependency accuracy: $DEP_ACCURACY (found=$found/$gt_count, in_order=$in_order/$gt_count)"
}

# ---------------------------------------------------------------------------
# Root cause MRR (for bug_investigation)
# ---------------------------------------------------------------------------

compute_root_cause_mrr() {
    ROOT_CAUSE_MRR="0.0000"

    if [ ${#GT_ROOT_CAUSE[@]} -eq 0 ]; then
        return
    fi

    if [ ${#AGENT_FILES[@]} -eq 0 ]; then
        return
    fi

    # Build root cause set
    local -A rc_set
    for f in "${GT_ROOT_CAUSE[@]}"; do
        rc_set[$(_normalize_path "$f")]=1
    done

    # Find rank of first root cause file in agent's examined files
    for idx in "${!AGENT_FILES[@]}"; do
        local norm
        norm=$(_normalize_path "${AGENT_FILES[$idx]}")
        if [ "${rc_set[$norm]+_}" ]; then
            local rank=$((idx + 1))
            ROOT_CAUSE_MRR=$(awk "BEGIN {printf \"%.4f\", 1.0 / $rank}")
            echo "Root cause MRR: $ROOT_CAUSE_MRR (found at rank $rank)"
            return
        fi
    done

    echo "Root cause MRR: 0.0 (root cause not found in agent files)"
}

# ---------------------------------------------------------------------------
# Composite score
# ---------------------------------------------------------------------------

# composite_score TASK_QUALITY FILE_RECALL FILE_PRECISION DEP_ACCURACY
# Returns: float score 0.0-1.0
# Formula: 0.4 * task_quality + 0.3 * file_recall + 0.2 * file_precision + 0.1 * dep_accuracy
composite_score() {
    local tq="${1:-0}" recall="${2:-$IR_RECALL}" precision="${3:-$IR_PRECISION}" dep="${4:-$DEP_ACCURACY}"
    awk "BEGIN {
        score = 0.4 * $tq + 0.3 * $recall + 0.2 * $precision + 0.1 * $dep
        if (score > 1.0) score = 1.0
        if (score < 0.0) score = 0.0
        printf \"%.2f\", score
    }"
}

# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

write_ir_metrics() {
    local output_file="$1"
    local output_dir
    output_dir=$(dirname "$output_file")
    mkdir -p "$output_dir"

    # Build agent files JSON array
    local agent_files_json="["
    local first=1
    for f in "${AGENT_FILES[@]}"; do
        [ "$first" -eq 0 ] && agent_files_json+=","
        agent_files_json+="\"$f\""
        first=0
    done
    agent_files_json+="]"

    # Build GT files JSON array
    local gt_files_json="["
    first=1
    for f in "${GT_FILES[@]}"; do
        [ "$first" -eq 0 ] && gt_files_json+=","
        gt_files_json+="\"$f\""
        first=0
    done
    gt_files_json+="]"

    cat > "$output_file" << IREOF
{
  "precision": $IR_PRECISION,
  "recall": $IR_RECALL,
  "f1": $IR_F1,
  "dependency_accuracy": $DEP_ACCURACY,
  "root_cause_mrr": $ROOT_CAUSE_MRR,
  "files_examined": $agent_files_json,
  "files_relevant": $gt_files_json,
  "agent_file_count": ${#AGENT_FILES[@]},
  "gt_file_count": ${#GT_FILES[@]}
}
IREOF
    echo "Wrote IR metrics to $output_file"
}

# ---------------------------------------------------------------------------
# Convenience: run full IR pipeline
# ---------------------------------------------------------------------------

# run_ir_pipeline SOLUTION_FILE GT_FILE IR_OUTPUT_FILE
# Parses solution, loads GT, computes all metrics, writes output.
# Sets IR_PRECISION, IR_RECALL, IR_F1, DEP_ACCURACY, ROOT_CAUSE_MRR.
run_ir_pipeline() {
    local solution_file="$1"
    local gt_file="$2"
    local ir_output="$3"

    parse_solution_files "$solution_file"
    load_ground_truth "$gt_file"
    compute_ir_metrics "$gt_file"
    compute_dep_accuracy
    compute_root_cause_mrr
    write_ir_metrics "$ir_output"
}
