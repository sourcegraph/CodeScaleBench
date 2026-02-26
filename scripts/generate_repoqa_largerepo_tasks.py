#!/usr/bin/env python3
"""
Generate large-repo RepoQA SR-QA tasks for ccb_understand (SDLC) and ccb_mcp_onboarding (MCP-unique).

Each task creates a needle-in-haystack function search challenge in a large codebase
(1M-35M LOC) where the agent must find a function from a behavioral description.

SDLC tasks go in benchmarks/ccb_understand/ (paired baseline+MCP).
MCP-unique tasks go in benchmarks/ccb_mcp_onboarding/ (artifact-only, MCP search required).

Usage:
    python3 scripts/generate_repoqa_largerepo_tasks.py           # dry-run
    python3 scripts/generate_repoqa_largerepo_tasks.py --execute  # write files
"""

import argparse
import json
import os
import textwrap
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
UNDERSTAND_DIR = ROOT / "benchmarks" / "ccb_understand"
ONBOARDING_DIR = ROOT / "benchmarks" / "ccb_mcp_onboarding"


@dataclass
class RepoQATask:
    """Specification for a single large-repo SR-QA task."""
    task_id_understand: str      # e.g. k8s-scheduler-filter-search-001
    task_id_onboarding: str      # e.g. ccx-onboard-search-201
    repo: str                    # e.g. kubernetes/kubernetes
    mirror: str                  # e.g. sg-evals/kubernetes--v1.32.0
    language: str                # e.g. go
    function_name: str
    function_path: str
    nl_description: str          # 4-part behavioral description
    difficulty: str = "hard"
    loc_estimate: int = 0


TASKS: List[RepoQATask] = [
    # --- Go (2) ---
    RepoQATask(
        task_id_understand="k8s-scheduler-filter-search-001",
        task_id_onboarding="ccx-onboard-search-201",
        repo="kubernetes/kubernetes",
        mirror="sg-evals/kubernetes--v1.32.0",
        language="go",
        function_name="findNodesThatPassFilters",
        function_path="pkg/scheduler/schedule_one.go",
        loc_estimate=4_000_000,
        nl_description=textwrap.dedent("""\
            1. **Purpose**: Identifies which cluster nodes satisfy all scheduling filter plugins for a given workload, enabling the scheduler to narrow down placement candidates.
            2. **Input**: Takes a context, a framework handle providing filter plugins and parallelism settings, cycle state, a pod specification, a diagnosis collector for recording filter failures, and a pre-fetched list of all node information objects.
            3. **Output**: Returns a slice of node-info objects representing feasible placement targets, plus an error if any filter plugin returned a fatal error. Also populates the diagnosis object with per-node failure reasons as a side effect.
            4. **Procedure**:
               - Computes the target number of feasible nodes to find, reducing to 1 if there are no extender filters and no scoring plugins.
               - If no filter plugins are registered, returns the first N nodes starting from a round-robin offset.
               - Otherwise, defines an inner closure that runs all filter plugins against each node in parallel, starting from the last scheduling cycle's offset to ensure fairness.
               - Uses atomic counters to track how many feasible nodes have been found; cancels the parallel search early once the target count is reached.
               - Records non-feasible node statuses into a result array under the parallel check, then copies them into the diagnosis object after all parallel work completes.
               - Measures and reports the total Filter extension point latency via deferred metrics emission."""),
    ),
    RepoQATask(
        task_id_understand="k8s-eviction-sync-search-001",
        task_id_onboarding="ccx-onboard-search-202",
        repo="kubernetes/kubernetes",
        mirror="sg-evals/kubernetes--v1.32.0",
        language="go",
        function_name="synchronize",
        function_path="pkg/kubelet/eviction/eviction_manager.go",
        loc_estimate=4_000_000,
        nl_description=textwrap.dedent("""\
            1. **Purpose**: Performs a single synchronization cycle of the node eviction manager, evaluating current resource usage against configured thresholds and, if necessary, selecting and terminating one workload to relieve resource pressure.
            2. **Input**: Operates as a method on the eviction manager, receiving a context, a list of active workloads (pods), a function to retrieve resource usage statistics, and a function to check if a pod has been cleaned up. It implicitly reads node summary statistics from the summary provider.
            3. **Output**: Returns a slice of pods that were evicted during this cycle (at most one) and an error. As side effects, it updates internal state: the set of met thresholds, node condition timestamps, and observation history.
            4. **Procedure**:
               - Refreshes memory threshold notifiers from the latest statistics summary.
               - Computes signal observations (e.g., memory available, disk available) and determines which thresholds are currently met, both ignoring and respecting grace periods.
               - Tracks when each threshold was first observed and when each node condition was last observed, applying a transition period before declaring conditions active.
               - Filters thresholds to only those whose grace periods are fully met and whose stats have been updated since the last sync.
               - Checks for local storage eviction violations first (pod-level disk usage); if any pods are evicted there, returns early.
               - Sorts remaining thresholds by eviction priority, identifies the highest-priority reclaimable resource, and first attempts node-level reclamation (e.g., garbage-collecting images or containers).
               - If node-level reclamation is insufficient, ranks all active pods using a signal-specific ranking function, then iterates through ranked pods and evicts the first one that can be killed."""),
    ),
    # --- Java (2) ---
    RepoQATask(
        task_id_understand="kafka-batch-drain-search-001",
        task_id_onboarding="ccx-onboard-search-203",
        repo="apache/kafka",
        mirror="sg-evals/kafka--0753c489",
        language="java",
        function_name="drainBatchesForOneNode",
        function_path="clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java",
        loc_estimate=1_200_000,
        nl_description=textwrap.dedent("""\
            1. **Purpose**: Collects pending record batches from the accumulator's per-partition queues for a single broker node, respecting a maximum request size, to be sent in a single produce request.
            2. **Input**: Takes a metadata snapshot (providing cluster topology and leader epoch information), a broker node object, a maximum request size in bytes, and the current timestamp in milliseconds.
            3. **Output**: Returns an ordered list of producer batch objects that are ready to be sent to the specified broker, with their combined serialized size not exceeding the maximum (except when a single batch is larger due to compression).
            4. **Procedure**:
               - Retrieves the list of partitions assigned to the given node from the metadata snapshot.
               - Uses a per-node drain index (round-robin offset) to avoid starvation by starting from where the previous drain left off.
               - Iterates through partitions in a circular fashion: skips muted partitions (those with in-flight batches), skips partitions with empty queues or batches still in backoff.
               - For each eligible partition, peeks at the head batch under a synchronized lock: updates its leader epoch, checks if adding it would exceed the max size (allowing one oversized batch when the ready list is empty).
               - Removes the batch from the queue, and if a transaction manager is present and the batch lacks a sequence number, assigns producer ID/epoch and sequence numbers for exactly-once semantics.
               - Outside the lock, closes the batch (finalizing its memory records), records its size, marks it as drained, and continues until all partitions have been visited."""),
    ),
    RepoQATask(
        task_id_understand="kafka-assign-handler-search-001",
        task_id_onboarding="ccx-onboard-search-204",
        repo="apache/kafka",
        mirror="sg-evals/kafka--0753c489",
        language="java",
        function_name="handleAssignment",
        function_path="streams/src/main/java/org/apache/kafka/streams/processor/internals/TaskManager.java",
        loc_estimate=1_200_000,
        nl_description=textwrap.dedent("""\
            1. **Purpose**: Reconciles the stream processing task manager's current task ownership with a new assignment of active and standby tasks received after a consumer group rebalance, deciding which tasks to create, recycle, resume, or close.
            2. **Input**: Takes two maps: one mapping task IDs to sets of topic partitions for active tasks, and another for standby tasks. These represent the new desired assignment from the partition assignor.
            3. **Output**: No return value; as side effects, it updates internal task registries, creates new tasks, closes tasks no longer assigned, recycles tasks that changed between active and standby roles, and resumes suspended tasks. May throw aggregated exceptions for corrupted or migrated tasks.
            4. **Procedure**:
               - Logs the delta between existing and new assignments, then registers subscribed topics from the new active partitions.
               - Prepares mutable copies of the assignment maps and empty collections for tasks to recycle and tasks to close.
               - Locks tasks that appear in both old and new assignments to prevent concurrent state modifications.
               - Iterates over all existing tasks: if a task's ID appears in the new active set and is already active, updates its input partitions and resumes it; if it's standby but needs to become active (or vice versa), marks it for recycling. Tasks not in either new map are marked for clean closure.
               - After classification, closes and recycles tasks, unlocks, aggregates any exceptions (prioritizing fatal over migrated over corrupted), and finally creates brand-new tasks for any remaining IDs in the assignment maps."""),
    ),
    # --- Rust (2) ---
    RepoQATask(
        task_id_understand="rust-type-tests-search-001",
        task_id_onboarding="ccx-onboard-search-205",
        repo="rust-lang/rust",
        mirror="sg-evals/rust--01f6ddf7",
        language="rust",
        function_name="check_type_tests",
        function_path="compiler/rustc_borrowck/src/region_infer/mod.rs",
        loc_estimate=2_200_000,
        nl_description=textwrap.dedent("""\
            1. **Purpose**: Validates whether the type-outlives relationship tests generated during type checking are satisfied by the inferred region values, and collects error reports for those that fail.
            2. **Input**: Takes an immutable reference to the region inference context, a reference to the inference context for type manipulation, an optional mutable vector for propagating outlives requirements to enclosing closures, and a mutable buffer for collecting region error reports.
            3. **Output**: No return value; populates the errors buffer with type-test failure entries for each unsatisfied test. When processing closures, may instead propagate unsatisfied requirements upward through the optional requirements vector rather than reporting an error directly.
            4. **Procedure**:
               - Maintains a deduplication set of (erased generic kind, lower bound region, span) triples to avoid reporting essentially identical errors multiple times.
               - Iterates over each registered type test (encoding constraints like T: 'a).
               - For each test, converts the generic kind to a concrete type, then evaluates its verify bound against the inferred lower-bound region. If the bound is satisfied, the test passes and is skipped.
               - If the bound is not satisfied and this is a closure, attempts to promote the type test into a closure outlives requirement. If promotion succeeds, the test is skipped.
               - If neither verification nor promotion succeeds, erases and anonymizes the generic kind's regions, checks the deduplication set, and if the error is novel, pushes a failure entry into the errors buffer."""),
    ),
    RepoQATask(
        task_id_understand="rust-liveness-gen-search-001",
        task_id_onboarding="ccx-onboard-search-206",
        repo="rust-lang/rust",
        mirror="sg-evals/rust--01f6ddf7",
        language="rust",
        function_name="generate",
        function_path="compiler/rustc_borrowck/src/type_check/liveness/mod.rs",
        loc_estimate=2_200_000,
        nl_description=textwrap.dedent("""\
            1. **Purpose**: Orchestrates the liveness analysis for the borrow checker, determining which local variables need liveness tracking and emitting the corresponding region constraints that encode which types must be live at which program points.
            2. **Input**: Takes a mutable reference to the type checker (providing access to inference context, universal regions, constraints, and the MIR body), a dense location map for the control-flow graph, and move data tracking initialization and move status of variables.
            3. **Output**: No return value; modifies the type checker's constraint sets by adding liveness constraints. As a side effect, computes and stores boring locals (those whose types contain only free regions) in the Polonius liveness context when the next-generation borrow checker is enabled.
            4. **Procedure**:
               - First computes the set of regions known to outlive free regions by building a reverse constraint graph and performing a depth-first search from all universal (free) regions.
               - If the experimental Polonius mode is enabled, partitions locals into relevant (needing liveness computation) and boring (all regions are free), stores the boring locals for later diagnostics, then resets the free-region set.
               - Partitions local variable declarations into relevant and boring based on whether their types contain any non-free regions.
               - Invokes the trace module to perform the actual liveness computation over the relevant locals using move data.
               - Finally, records regular live regions, marking regions that appear in rvalues or call arguments as live at their use points."""),
    ),
    # --- C++ (4) ---
    RepoQATask(
        task_id_understand="firefox-http-response-search-001",
        task_id_onboarding="ccx-onboard-search-207",
        repo="mozilla/gecko-dev",
        mirror="sg-evals/firefox--871325b8",
        language="cpp",
        function_name="ContinueProcessResponse1",
        function_path="netwerk/protocol/http/nsHttpChannel.cpp",
        loc_estimate=20_000_000,
        nl_description=textwrap.dedent("""\
            1. **Purpose**: Processes an HTTP response after the initial response headers have been examined by observers, handling cookie storage, security header enforcement, alternative service negotiation, authentication state management, and Clear-Site-Data directives before handing off to the next processing stage.
            2. **Input**: Takes a pointer to an HTTP connection info object describing the connection over which the response arrived. Operates as a method on the HTTP channel, which holds the response head, transaction state, and load info.
            3. **Output**: Returns a status code. As side effects, may set cookies from response headers, process Strict-Transport-Security and Public-Key-Pinning headers, register alternative services, reset authentication state, fire Clear-Site-Data observer notifications, and initiate cache invalidation.
            4. **Procedure**:
               - If the channel is suspended, defers processing by storing a resume callback and returning immediately.
               - If the request was cancelled during response examination, calls OnStartRequest directly.
               - Reads the HTTP status code from the response head.
               - If the response is not from a failed proxy CONNECT and is not a 407, processes cookies by visiting response cookie headers.
               - Processes security headers (HSTS, HPKP) and logs any failures.
               - For non-5xx responses (excluding 421 Misdirected Request), processes Alt-Svc headers to register alternative service endpoints.
               - For non-401/407 responses, disconnects and resets the authentication provider.
               - If the response contains a Clear-Site-Data header, notifies the observer service.
               - Proceeds to the next response processing stage."""),
    ),
    RepoQATask(
        task_id_understand="firefox-cache-race-search-001",
        task_id_onboarding="ccx-onboard-search-208",
        repo="mozilla/gecko-dev",
        mirror="sg-evals/firefox--871325b8",
        language="cpp",
        function_name="MaybeRaceCacheWithNetwork",
        function_path="netwerk/protocol/http/nsHttpChannel.cpp",
        loc_estimate=20_000_000,
        nl_description=textwrap.dedent("""\
            1. **Purpose**: Determines whether it is advisable to race a network request against a pending cache lookup for the same resource, and if so, computes an appropriate delay and triggers the network request to run concurrently with cache access.
            2. **Input**: Takes no explicit parameters; operates as a method on the HTTP channel, reading channel state (load flags, error status, CORS preflight requirements) and querying system services for network link type and cache performance statistics.
            3. **Output**: No return value; as a side effect, may schedule a network request to fire after a computed delay (or immediately if the cache is determined to be slow). Sets the channel's race delay field and triggers network activation via a timer.
            4. **Procedure**:
               - Queries the network link service for the current connection type.
               - Returns immediately (no racing) if the link type is metered (e.g., cellular on Android).
               - Returns immediately if load flags prohibit network access (LOAD_ONLY_FROM_CACHE or LOAD_NO_NETWORK_IO).
               - Returns immediately if the channel has a failure status or if a CORS preflight is required but not yet completed.
               - Computes the race delay: if cache performance statistics indicate the cache is slow, sets delay to zero; otherwise, sets the delay to three times the average cache entry open time.
               - Clamps the delay between configurable minimum and maximum bounds from preferences.
               - Triggers the network request with the computed delay."""),
    ),
    RepoQATask(
        task_id_understand="envoy-retry-eval-search-001",
        task_id_onboarding="ccx-onboard-search-209",
        repo="envoyproxy/envoy",
        mirror="sg-evals/envoy--v1.31.2",
        language="cpp",
        function_name="wouldRetryFromHeaders",
        function_path="source/common/router/retry_state_impl.cc",
        loc_estimate=1_500_000,
        nl_description=textwrap.dedent("""\
            1. **Purpose**: Evaluates an upstream HTTP response against the configured retry policy to determine whether the request should be retried based on the response status code, headers, or gRPC status, returning a retry decision.
            2. **Input**: Takes a constant reference to the upstream response headers, a constant reference to the original downstream request headers, and a mutable boolean reference for signaling whether early data (0-RTT) should be disabled on retry.
            3. **Output**: Returns a retry decision enum value: either no retry, retry with backoff, or retry immediately. Sets the disable-early-data output flag when retrying a 425 Too Early response.
            4. **Procedure**:
               - First checks if the response contains a rate-limited header; if so, only retries when the rate-limited retry policy is active.
               - Extracts the HTTP response status code and evaluates it against multiple configured retry-on policies in sequence: 5xx errors, gateway errors (502/503/504), retriable 4xx (specifically 409 Conflict), and custom retriable status codes.
               - For custom retriable status codes, has special handling for HTTP 425 (Too Early): only retries if the downstream request was not itself received as early data.
               - Checks for retriable response header matchers, evaluating each configured header matcher against the response.
               - Evaluates gRPC-specific retry conditions by extracting the gRPC status from response headers and matching against configured gRPC retry policies.
               - Returns no-retry if none of the configured policies matched."""),
    ),
    RepoQATask(
        task_id_understand="envoy-pool-ready-search-001",
        task_id_onboarding="ccx-onboard-search-210",
        repo="envoyproxy/envoy",
        mirror="sg-evals/envoy--v1.31.2",
        language="cpp",
        function_name="onPoolReady",
        function_path="source/common/router/upstream_request.cc",
        loc_estimate=1_500_000,
        nl_description=textwrap.dedent("""\
            1. **Purpose**: Initializes an upstream request after its connection pool has successfully provided a connection, setting up stream metadata, timing information, protocol details, watermark callbacks, stream duration limits, and host-rewrite rules before the request is forwarded upstream.
            2. **Input**: Takes ownership of a generic upstream connection via move semantics, a shared pointer to the upstream host description, a reference to the connection's address provider (local/remote addresses, SSL info), a reference to the pool's stream info, and an optional HTTP protocol version.
            3. **Output**: No return value; as side effects, configures the upstream stream with the downstream account, records connection timing metadata, sets up upstream filter state, populates upstream address information, enables half-close if configured, starts per-try and max-stream-duration timers, rewrites the Host header if auto-host-rewrite is enabled, and notifies all registered upstream callbacks.
            4. **Procedure**:
               - Records the connection pool callback latency and takes ownership of the upstream connection.
               - Reports a successful connection to the host's outlier detector.
               - Selects the upstream host and records the protocol in stream info.
               - Copies connection timing data and stream count from the pool's stream info.
               - Sets up filter state and records local/remote addresses, SSL connection info, connection ID.
               - Synchronizes upstream and downstream byte meters.
               - Defers per-try timeout setup until the downstream request completes, or starts it immediately if the downstream has already ended.
               - Registers downstream watermark callbacks for backpressure propagation.
               - Computes and starts the max stream duration timer.
               - If auto-host-rewrite is enabled and the upstream host has a non-empty hostname, updates the Authority/Host header.
               - Emits an upstream pool-ready access log entry and invokes all upstream-connection-established callbacks."""),
    ),
    # --- Python (2) ---
    RepoQATask(
        task_id_understand="sklearn-fastica-fit-search-001",
        task_id_onboarding="ccx-onboard-search-211",
        repo="scikit-learn/scikit-learn",
        mirror="",  # public repo, no custom mirror needed
        language="python",
        function_name="_fit_transform",
        function_path="sklearn/decomposition/_fastica.py",
        loc_estimate=1_200_000,
        nl_description=textwrap.dedent("""\
            1. **Purpose**: Performs the core fitting procedure for Independent Component Analysis (ICA), computing the unmixing matrix that separates observed signals into statistically independent source signals, with optional whitening as a preprocessing step.
            2. **Input**: A 2D array of shape (n_samples, n_features) containing multivariate signal observations, plus a boolean flag that controls whether to materialize the separated source matrix or only compute the rotation matrix (to save memory on large datasets).
            3. **Output**: Returns either None (when the flag is off) or an array of shape (n_samples, n_components) containing the estimated independent source signals. As a side effect, sets instance attributes for components, mixing matrix, mean, whitening matrix, unmixing, and iteration count.
            4. **Procedure**:
               - Validates and transposes input data; selects the nonlinearity function (logcosh, exp, cube, or user-supplied callable).
               - Determines number of components (clamping to min of samples and features).
               - If whitening is enabled, centers the data by subtracting the mean, then computes a whitening matrix via eigendecomposition or SVD, projecting onto a lower-dimensional space.
               - Initializes the unmixing weight matrix (random normal if not provided).
               - Delegates to either a parallel (symmetric decorrelation) or deflation (one component at a time) algorithm to iteratively refine the unmixing matrix using fixed-point iteration.
               - Computes separated sources if requested.
               - Stores the components, mixing matrix (pseudo-inverse), and whitening matrix on the instance."""),
    ),
    RepoQATask(
        task_id_understand="pandas-pivot-internal-search-001",
        task_id_onboarding="ccx-onboard-search-212",
        repo="pandas-dev/pandas",
        mirror="",  # public repo
        language="python",
        function_name="__internal_pivot_table",
        function_path="pandas/core/reshape/pivot.py",
        loc_estimate=1_500_000,
        nl_description=textwrap.dedent("""\
            1. **Purpose**: Implements the core pivot table computation for a single aggregation function. This is the internal workhorse called by the public pivot_table function after it splits list-valued aggregation arguments into individual calls.
            2. **Input**: A DataFrame, plus parameters for values (columns to aggregate), index (row grouping keys), columns (column grouping keys), a single aggregation function or callable, fill value, margins (whether to add row/column totals), dropna, margins name, observed (for categorical groupers), sort, and extra keyword arguments.
            3. **Output**: Returns a DataFrame representing the pivot table: rows correspond to unique combinations of index keys, columns correspond to unique combinations of column keys, and cell values are the result of applying the aggregation function to matching data subsets.
            4. **Procedure**:
               - Validates that value labels exist in the data; filters the DataFrame to only relevant columns.
               - Groups the data by the concatenation of index and column keys, then applies the aggregation function.
               - If dropna is set, drops all-NaN rows from the aggregated result.
               - If the result has a MultiIndex, unstacks the column-key levels to create a 2D pivot layout, using the fill value for missing combinations.
               - If dropna is false, reindexes both axes against the full Cartesian product of level values.
               - Sorts columns if requested, fills remaining NaN values, handles integer downcasting for len aggregations.
               - If margins are requested, appends row/column totals.
               - Cleans up: drops redundant top-level column headers, transposes if no row index was specified."""),
    ),
    # --- TypeScript (2) ---
    RepoQATask(
        task_id_understand="vscode-keybinding-merge-search-001",
        task_id_onboarding="ccx-onboard-search-213",
        repo="microsoft/vscode",
        mirror="",  # public repo
        language="typescript",
        function_name="computeMergeResult",
        function_path="src/vs/platform/userDataSync/common/keybindingsMerge.ts",
        loc_estimate=5_000_000,
        nl_description=textwrap.dedent("""\
            1. **Purpose**: Implements a three-way merge algorithm that determines which items were added, removed, updated, or conflicting when reconciling local, remote, and base versions of a configuration during Settings Sync.
            2. **Input**: Three compare-result objects: one for the direct diff between local and remote, one for the diff from common ancestor to local, and one for the diff from common ancestor to remote. Each contains three sets: added, removed, and updated keys.
            3. **Output**: An object with four sets: added (keys to add from remote), removed (keys to remove per remote), updated (keys to update per remote), and conflicts (keys where local and remote diverged and cannot be auto-merged).
            4. **Procedure**:
               - Iterates over keys removed locally; if any were updated in the remote, marks them as conflicts.
               - Iterates over keys removed remotely; if updated locally, marks as conflict; otherwise accepts the removal.
               - Iterates over keys added locally; if also added in remote with different values, marks as conflict.
               - Iterates over keys added remotely; if also added locally with different values, marks as conflict; otherwise accepts the addition.
               - Iterates over keys updated locally; if also updated remotely with different values, marks as conflict.
               - Iterates over keys updated remotely; if also updated locally with different values, marks as conflict; otherwise accepts the update.
               - Already-conflicted keys are skipped via guards to avoid duplicate processing."""),
    ),
    RepoQATask(
        task_id_understand="grafana-field-calcs-search-001",
        task_id_onboarding="ccx-onboard-search-214",
        repo="grafana/grafana",
        mirror="",  # public repo
        language="typescript",
        function_name="doStandardCalcs",
        function_path="packages/grafana-data/src/transformations/fieldReducer.ts",
        loc_estimate=3_000_000,
        nl_description=textwrap.dedent("""\
            1. **Purpose**: Computes a comprehensive set of aggregate statistics (min, max, mean, sum, count, delta, range, diff, first/last, logmin, etc.) for a single data field, serving as the default standard-calculations reducer used by panel visualizations and data transformations.
            2. **Input**: A field object (containing a values array and a type enum indicating whether the field is numeric, time, string, etc.), plus two boolean flags: one for whether to skip null values entirely and one for whether to treat null values as zero for calculation purposes.
            3. **Output**: A dictionary containing computed statistics: first, last, firstNotNull, lastNotNull, min, max, sum, count, nonNullCount, mean, range, diff (last minus first non-null), percentage change, delta (cumulative positive increments with counter-reset detection), step (minimum interval between consecutive non-null values), smallest positive value, and boolean flags for all-null and all-zero.
            4. **Procedure**:
               - Returns defaults immediately if the values array is empty or undefined.
               - Determines whether the field is numeric or time-typed.
               - Iterates over every value: records first/last; handles null values according to the two flags; increments count.
               - For non-null numeric values: tracks running sum, min, max, smallest positive value, non-null count; computes step as the minimum gap between consecutive non-null values; computes delta by accumulating positive increments while detecting counter resets.
               - After the loop: clamps sentinel values back to null if no real values were seen; computes mean, range, diff, and percentage change from the accumulated statistics."""),
    ),
]


def generate_ground_truth(task: RepoQATask) -> dict:
    """Generate ground_truth.json content."""
    return {
        "function_id": f"{task.function_path}::{task.function_name}",
        "canonical_path": task.function_path,
        "canonical_name": task.function_name,
        "language": task.language,
        "nl_description": task.nl_description,
        "task_variant": "sr-qa",
    }


def generate_instruction(task: RepoQATask) -> str:
    """Generate instruction.md for an SR-QA task."""
    return textwrap.dedent(f"""\
        # RepoQA: Semantic Retrieval (SR-QA)

        ## Task: Find the Function

        You are searching a large codebase for a specific function based on its behavior.

        **Repository**: {task.repo}
        **Language**: {task.language}

        ## Function Description

        ```
        {task.nl_description}
        ```

        ## Search Strategy

        This function **cannot be found by searching for its name** because the name is not provided. You must:

        1. **Understand the behavior** described above
        2. **Search the codebase** to find functions matching this behavior
        3. **Explore the code** using call graphs and references
        4. **Narrow down** candidates until you find the exact function


        ## Output Format

        You MUST provide your answer as valid JSON and **SAVE IT TO A FILE**:

        ```json
        {{
          "function_path": "path/to/file.ext",
          "function_name": "the_function_name",
          "justification": "Why this function matches: describe the behavior you found"
        }}
        ```

        **CRITICAL**: You MUST save the JSON to `/app/solution.json`. This location is required for verification.

        **Your final step MUST be to run this exact bash command:**

        ```bash
        cat > /app/solution.json << 'JSONEOF'
        {{
          "function_path": "ACTUAL_PATH",
          "function_name": "ACTUAL_NAME",
          "justification": "ACTUAL_JUSTIFICATION_TEXT"
        }}
        JSONEOF
        ```

        ## Notes

        - The file path should be relative to repository root
        - Function names are case-sensitive
        - Provide your best match even if uncertain; explain your reasoning
        - The justification is scored on how well it explains the function's behavior

        ## Scoring

        - **Perfect** (1.0): Correct path AND name
        - **Good** (0.7-0.9): Correct path, similar name OR vice versa
        - **Partial** (0.3-0.6): Close approximation
        - **Incorrect** (0.0): Wrong function entirely
    """)


def generate_task_toml(task_id: str, task: RepoQATask, category: str) -> str:
    """Generate task.toml content."""
    tags_list = f'["{category}", "{task.language}", "sr-qa", "large-repo", "repoqa"]'
    return textwrap.dedent(f"""\
        version = "1.0"

        [metadata]
        name = "{task_id}"
        description = "Find a function in {task.repo} ({task.loc_estimate // 1_000_000}M+ LOC) from a behavioral description"
        difficulty = "{task.difficulty}"
        category = "semantic-code-navigation"
        tags = {tags_list}
        language = "{task.language}"

        [task]
        id = "{task_id}"
        repo = "{task.repo}"
        category = "{category}"
        language = "{task.language}"
        difficulty = "{task.difficulty}"
        time_limit_sec = 1200

        [verification]
        type = "test"
        command = "bash /tests/test.sh"
        reward_type = "semantic_similarity"
        description = "Correct function retrieval similarity score"

        [environment]
        build_timeout_sec = 1800.0
        cpus = 2
        memory = "4G"
        storage = "10G"

        [environment.setup_scripts]
        mcp_config = \"\"\"#!/bin/bash
        if [ -n "$SOURCEGRAPH_ACCESS_TOKEN" ] && [ -n "$SOURCEGRAPH_URL" ]; then
          mkdir -p /root/.config/claude
          cat > /root/.config/claude/mcp.json << 'MCPEOF'
        {{
          "mcpServers": {{
            "sourcegraph": {{
              "command": "npx",
              "args": ["-y", "@sourcegraph/mcp-server"],
              "env": {{
                "SRC_ACCESS_TOKEN": "$SOURCEGRAPH_ACCESS_TOKEN",
                "SOURCEGRAPH_URL": "$SOURCEGRAPH_URL"
              }}
            }}
          }}
        }}
        MCPEOF
          echo "MCP configuration created"
        else
          echo "No Sourcegraph credentials provided, MCP disabled"
        fi
        exit 0
        \"\"\"
    """)


def generate_task_dir(
    base_dir: Path,
    task_id: str,
    task: RepoQATask,
    category: str,
    dry_run: bool = True,
) -> None:
    """Generate a complete task directory."""
    task_dir = base_dir / task_id
    tests_dir = task_dir / "tests"
    env_dir = task_dir / "environment"

    if dry_run:
        print(f"  [DRY-RUN] Would create: {task_dir}/")
        return

    # Create dirs
    tests_dir.mkdir(parents=True, exist_ok=True)
    env_dir.mkdir(parents=True, exist_ok=True)

    # Write task.toml
    (task_dir / "task.toml").write_text(generate_task_toml(task_id, task, category))

    # Write instruction.md
    (task_dir / "instruction.md").write_text(generate_instruction(task))

    # Write ground_truth.json
    gt = generate_ground_truth(task)
    (tests_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2) + "\n")

    # Copy verifiers.py from archived template
    verifiers_src = ROOT / "benchmarks" / "archive" / "ccb_repoqa" / "tasks"
    # Find any existing verifiers.py in git or write inline
    verifiers_path = tests_dir / "verifiers.py"
    if not verifiers_path.exists():
        # Use the standard RepoQA verifier
        verifiers_path.write_text(_VERIFIERS_PY)

    # Copy test.sh from archived template
    test_sh_path = tests_dir / "test.sh"
    if not test_sh_path.exists():
        test_sh_path.write_text(_TEST_SH)
    os.chmod(test_sh_path, 0o755)

    # Write minimal Dockerfile
    (env_dir / "Dockerfile").write_text(textwrap.dedent(f"""\
        FROM python:3.11-slim
        RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*
        RUN pip install --no-cache-dir numpy
        WORKDIR /app
        RUN mkdir -p /logs/agent /logs/verifier
    """))

    print(f"  Created: {task_dir}/")


# Inline copies of the standard RepoQA verifier and test script
_VERIFIERS_PY = '''\
"""Verifiers for RepoQA SR-QA tasks. Scores agent function retrieval."""

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict


@dataclass
class VerificationResult:
    correct_function: float
    correct_path: float
    justification_score: float
    reasoning: str = ""


class SemanticRetrievalQAVerifier:
    def __init__(self, ground_truth: Dict[str, Any]):
        self.ground_truth = ground_truth

    def verify(self, agent_output: Dict[str, Any]) -> VerificationResult:
        try:
            path = agent_output.get("function_path", "")
            name = agent_output.get("function_name", "")
            justification = agent_output.get("justification", "")
        except (KeyError, TypeError) as e:
            return VerificationResult(0.0, 0.0, 0.0, f"Invalid output: {e}")

        canonical_path = self.ground_truth.get("canonical_path", "")
        canonical_name = self.ground_truth.get("canonical_name", "")
        nl_description = self.ground_truth.get("nl_description", "")

        path_score = self._path_similarity(path, canonical_path)
        name_score = self._name_similarity(name, canonical_name)

        if path_score == 1.0 and name_score == 1.0:
            function_score = 1.0
        elif path_score == 1.0 and name_score > 0.7:
            function_score = 0.8
        elif path_score > 0.8 and name_score == 1.0:
            function_score = 0.8
        elif path_score > 0.5 and name_score > 0.5:
            function_score = 0.3
        else:
            function_score = 0.0

        justification_score = self._keyword_overlap(justification, nl_description)

        reasoning = (
            f"Path match: {path_score:.2f} (expected {canonical_path})\\n"
            f"Name match: {name_score:.2f} (expected {canonical_name})\\n"
            f"Justification keywords: {justification_score:.2f}"
        )
        return VerificationResult(function_score, path_score, justification_score, reasoning)

    @staticmethod
    def _path_similarity(p1: str, p2: str) -> float:
        p1, p2 = Path(p1).as_posix(), Path(p2).as_posix()
        return 1.0 if p1 == p2 else SequenceMatcher(None, p1, p2).ratio()

    @staticmethod
    def _name_similarity(n1: str, n2: str) -> float:
        return 1.0 if n1 == n2 else SequenceMatcher(None, n1.lower(), n2.lower()).ratio()

    @staticmethod
    def _keyword_overlap(text1: str, text2: str) -> float:
        if not text1 or not text2:
            return 0.0
        w1 = set(re.findall(r"\\w+", text1.lower()))
        w2 = set(re.findall(r"\\w+", text2.lower()))
        if not w1 or not w2:
            return 0.0
        return len(w1 & w2) / len(w1 | w2)
'''

_TEST_SH = '''\
#!/bin/bash
# RepoQA SR-QA Verification Script
echo "Starting RepoQA verifier..." 1>&2
cd /app || { echo "ERROR: Cannot cd to /app"; exit 1; }
mkdir -p /logs/verifier

if [ ! -f /tests/ground_truth.json ]; then
    echo "ERROR: No ground_truth.json found at /tests/ground_truth.json"
    echo \'{"score": 0.0}\' > /logs/verifier/reward.json
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

SOLUTION_FILE="/app/solution.json"
if [ ! -f "$SOLUTION_FILE" ]; then
    echo "ERROR: Agent did not create solution.json in /app/"
    echo \'{"score": 0.0}\' > /logs/verifier/reward.json
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

cat > /tmp/verify.py << \'PYEOF\'
import json, sys, re
sys.path.insert(0, "/tests")
from verifiers import SemanticRetrievalQAVerifier

try:
    with open("/tests/ground_truth.json") as f:
        ground_truth = json.load(f)
    with open("/app/solution.json") as f:
        raw = f.read()
    matches = re.findall(r"```(?:json)?\\s*\\n(.*?)```", raw, re.DOTALL)
    if matches:
        raw = matches[-1].strip()
    agent_output = json.loads(raw)

    verifier = SemanticRetrievalQAVerifier(ground_truth)
    result = verifier.verify(agent_output)
    reward = {"score": float(result.correct_function)}

    print(f"Correct Function: {result.correct_function:.2f}")
    print(f"Correct Path: {result.correct_path:.2f}")
    print(f"Justification: {result.justification_score:.2f}")
    print(f"Details: {result.reasoning}")

    with open("/logs/verifier/reward.json", "w") as f:
        json.dump(reward, f, indent=2)
    with open("/logs/verifier/reward.txt", "w") as f:
        f.write(str(reward["score"]))
except Exception as e:
    import traceback
    print(f"ERROR: {e}")
    traceback.print_exc()
    with open("/logs/verifier/reward.json", "w") as f:
        json.dump({"score": 0.0}, f)
    with open("/logs/verifier/reward.txt", "w") as f:
        f.write("0.0")
PYEOF

python3 /tmp/verify.py 2>&1 | tee /logs/verifier/verify-debug.log
exit 0
'''


def main():
    parser = argparse.ArgumentParser(description="Generate large-repo RepoQA SR-QA tasks")
    parser.add_argument("--execute", action="store_true", help="Write files (default: dry-run)")
    args = parser.parse_args()

    dry_run = not args.execute
    mode = "DRY-RUN" if dry_run else "EXECUTE"
    print(f"=== RepoQA Large-Repo Task Generator ({mode}) ===")
    print(f"Tasks: {len(TASKS)}")
    print()

    print(f"--- ccb_understand (SDLC paired) ---")
    for task in TASKS:
        generate_task_dir(UNDERSTAND_DIR, task.task_id_understand, task, "ccb_understand", dry_run)

    print()
    print(f"--- ccb_mcp_onboarding (MCP-unique) ---")
    for task in TASKS:
        generate_task_dir(ONBOARDING_DIR, task.task_id_onboarding, task, "ccb_mcp_onboarding", dry_run)

    print()
    total = len(TASKS) * 2
    print(f"Total: {total} task directories ({'would be ' if dry_run else ''}created)")
    if dry_run:
        print("Run with --execute to write files.")


if __name__ == "__main__":
    main()
