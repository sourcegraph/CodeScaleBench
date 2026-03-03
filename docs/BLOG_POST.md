# Rethinking Coding Agent Benchmarks, Part II: CodeScaleBench

An alternate title for this post could have been 'existing benchmarks are awful at evaluating how well agents can perform development tasks, not to mention universally misinterpreted, and I mostly can't use them to evaluate development capabilities and neither can you' but that's kind of long. In my post last month, I wrote (ranted?) about my many issues with coding agent benchmarks and my research journey (here's my paper library) to try to figure out a better way to approach them.

## My Problem with Benchmarks

The short version: most are either narrow or seemingly kind of random in their task design, use small / single repos or in some cases just snippets of code, usually aren't polyglot in language distribution, have poor and sometimes gameable verification setups (we weren't immune to this either, benchmark design requires constant vigilance, see later when I talk about an agent's use of git treachery to try to undermine my experiments), don't allow for auditable results, and are widely misinterpreted and overhyped. None of them use any of the largest open-source repos available (except for LinuxFLBench which I did adapt some tasks from, thanks folks!), none that I know of are multi-repo, and very few have anything to do with measuring information retrieval in codebases (some very recent ones do include F1 measurements though like ContextBench and Qodo's Code Review benchmark).

Unfortunately it turns out there isn't anything out there that met all of my criteria.

## What I Want in a (Enterprise Software Development) Coding Agent Benchmark:

- Has at least some very large (ideally ~1M lines of code+) codebases
- Multiple coding languages (I love Python but it's really a data analysis / ML scripting language, banks aren't building their legacy codebases with dynamically typed languages like that, but the vast majority of SWE-Bench style repos just use Python)
- Has tasks that require navigating across multiple repositories
- Has tasks that cover the full software development lifecycle not just one narrow part of it (looking at you bunch of just bug fix benchmarks because issue resolution tasks are the easiest to mine from GitHub and validate)

I wanted to evaluate how coding agents perform in as close to an enterprise environment as possible on tasks covering the entire software development life cycle (SDLC), and also to identify if the ways the agent finds the information it needs to accomplish its goal (i.e., context / information retrieval approaches) impacts how successful agents are at these tasks. I could pull here and there from some places but mostly had to build this from scratch.

Anyway it took longer than I thought it would, but I did it. I made a real benchmark that's useful for me and hopefully others too. CodeScaleBench is a living benchmark (this is code for I'm still working on it and am vulnerable to scope creep) that is divided into two parts. CodeScaleBench-SDLC has 150 software engineering tasks spanning the full SDLC; it uses a patch based verifier method popularized by SWE-Bench and also has a corresponding ground_truth.json file produced by a curator agent for context retrieval metrics I'll talk about later. CodeScaleBench-Org has 220 software engineering tasks that are separated into development tasks that require organization and in many cases cross repository-wide codebase navigation and understanding; it uses what I call an 'artifact' verifier where it produces an 'answer.json' file that is compared with the curator agent's solution. I built the benchmark framework, the evaluation pipeline, the ground truth system, and the statistical analysis layer using Claude Code et al. across ~1000 conversation sessions over about a month.

Some initial findings (that'll be expanded on later): the overall impact of using the Sourcegraph MCP on the task reward outcome is **+0.014** for CSB-SDLC and **+0.032** for CSB-Org. This means across all of our benchmark tasks the MCP runs scored on average **5.4% higher** (overall delta +0.025, from 0.464 baseline to 0.489 MCP). That overall delta is statistically significant (95% bootstrap CI: [+0.008, +0.042]), but the SDLC-only delta's confidence interval spans zero, meaning for tasks where the agent already has full local source code the effect isn't conclusive. The Org delta is significant (CI: [+0.013, +0.053]), confirming that MCP tools provide measurable value when the agent needs to discover information across repositories. The MCP tasks were also overwhelmingly completed faster and cheaper. Overall MCP saves $0.21/task and cuts agent execution time by 89 seconds (−36%). Org tasks with MCP were 63 seconds faster on wall clock (−19.8%) and slightly cheaper (−$0.010/task). SDLC tasks with MCP were also cheaper overall (−$0.50/task), driven by large savings on refactor and feature tasks where semantic search replaces expensive exhaustive code traversal.

And by the way, building a benchmark for coding agents while using coding agents is a fun way to find new failure modes. We all know agents are sneaky and mysterious genies, and that's also why I think benchmark results should ship with full agent transcripts for auditing (talking about that later, I know I'm asking a lot of you but I promise if you like benchmarks this is interesting and also explains why you read this far).

Side note: I'm going to mostly call the agent runs that used the Sourcegraph MCP 'MCP'; But I want to make it clear that this isn't commentary on the impact of MCP generally, but investigating the impact of code understanding and navigation tools on software development tasks completed by coding agents.

## The Setup

The same agent (starting with Claude Code + Haiku 4.5) runs the same task under two conditions:

**Baseline:** Full local source code. Standard tools (grep, file, read, etc.). No MCP.

**Sourcegraph MCP-augmented:** Source code isn't there. The agent gets 13 Sourcegraph MCP tools (semantic search, symbol resolution, dependency tracing, cross-repo navigation, etc.) and has to use them to find what it needs. To make this work, all benchmark repos are mirrored to a GitHub organization at pinned commits (~180 mirrors), so Sourcegraph indexes the exact version each task targets.

This makes it a conservative test. In real enterprise settings, the agent wouldn't have full local access to every relevant repo or the entire tens of millions of lines of a monolithic monster. But these runs of the benchmark test whether differences in context retrieval approaches, with access to the same information, change SDLC task outcomes. A future post will cover tasks that are uniquely enabled by these tools that a baseline agent just can't do at all. Though I did also find examples where local tools were insufficient even with all of the local code available, and the tasks were only possible with these retrieval tools. Like agents without these tools getting lost in massive codebases like Kubernetes, or confused about refactoring in Java repos, etc.

CSB-SDLC tasks are organized by SDLC phase (Understand, Design, Feature, Fix, Test, Document, Refactor, Secure, Debug), and the CSB-Org tasks are organized into organizational use cases (Dependency Tracing, Vulnerability Remediation, Framework Migration, Incident Debugging, Onboarding & Comprehension, Compliance, Cross-Org Discovery, Domain Lineage, Organizational Context, Platform Knowledge, and Cross-Repo Discovery) with many tasks including 3-20 repos. They span 40+ repositories (Kubernetes, Django, Linux, VSCode, etc.) and 9 programming languages. The full methodology, evaluation layers, and information retrieval analysis pipeline are documented in a [draft technical report](technical_reports/TECHNICAL_REPORT_V2.md).

## What I Used (And What I Threw Out)

One of the first things I tried to figure out was which existing benchmarks to draw from and which to ignore entirely. I'm not looking to reinvent any wheels if I can avoid it, and if there are existing tasks out there that I can Frankenstein-patch together into some hideous benchmark then I want to find them! I selected, or mostly didn't select, from a variety of benchmarks I found listed in the table below (these are the ones I had shortlisted as most likely to contain steal-worthy candidates).

Side note: I also learned about the ContextBench benchmark fairly late and am not including it here (like, a few days ago, because it went live on arxiv in mid-Feb which was after my research frenzy phase and during my build and write phase), but that benchmark is largely complementary to my investigation. It's a collection of ~1000+ human-annotated context files for SWE-Bench Verified and includes an information retrieval metrics evaluation framework (I'll include a short section on how I used this info to support my benchmark and some results using their evaluation framework).

Most of CSB-SDLC and all of CSB-Org's tasks are original in the sense that they weren't lifted from an existing benchmark. However, each one is grounded in a real repository at a pinned commit, targeting a real development scenario pulled from GitHub issues, PRs, and codebase analysis. I designed the Org tasks using a custom use case registry and artifact evaluation setup for cross-repository code intelligence; check out the [technical report](technical_reports/TECHNICAL_REPORT_V2.md) for more details on the 'direct' SWE-bench style verifier mode for code modifications vs an 'artifact' answer.json approach.

I also created an agentic benchmark checklist pipeline (inspired by this paper) to audit every task before it goes into a suite. It runs automated checks across three dimensions, Task Validity, Outcome Validity, and Reporting, and flags issues as PASS/FAIL/WARN/SKIP with severity-aware grading (A-F) based on critical and important criteria. It catches many structural and verifier-quality problems; it's complementary to a separate preflight runtime validation check I put in place in my (semi-futile) attempts to eliminate all failure modes (more on that in the QA section).

## +0.025 Overall, But Single Numbers are Useless

After running all 370 canonical task pairs (each with 3+ independent runs, yielding 4,132 individual results), the headline as a single number is kinda meh: baseline mean reward 0.464, MCP mean reward 0.489, delta +0.025; so the average overall MCP effect is small.

But this two and a half percentage point gain on its own isn't very informative (I mentioned this in my last post too). We need to dig deeper into the data.

## The SDLC Results

Breaking it down by SDLC element (which is how I designed this side of the benchmark):

| Suite | n | Baseline Mean | MCP Mean | Delta | 95% CI |
|-------|---|--------------|----------|-------|--------|
| understand | 10 | 0.557 | 0.735 | **+0.178** | [+0.034, +0.322] |
| fix | 26 | 0.465 | 0.557 | **+0.092** | [+0.024, +0.170] |
| document | 13 | 0.745 | 0.789 | +0.044 | [-0.021, +0.109] |
| secure | 12 | 0.608 | 0.634 | +0.026 | [-0.052, +0.110] |
| test | 18 | 0.513 | 0.503 | -0.010 | [-0.101, +0.087] |
| feature | 23 | 0.590 | 0.576 | -0.014 | [-0.069, +0.040] |
| refactor | 16 | 0.666 | 0.622 | -0.045 | [-0.126, +0.038] |
| design | 14 | 0.745 | 0.698 | -0.047 | [-0.157, +0.049] |
| debug | 18 | 0.617 | 0.552 | **-0.064** | [-0.112, -0.017] |

SDLC total: delta +0.014, though the confidence interval on that spans zero [-0.015, +0.043], which you could interpret as using these tools when you already have all the code locally doesn't materially change the outcome. But again, there's more to break down here.

## Where Sourcegraph MCP Wins

From that table above, you can see that, not too surprisingly, the strongest SDLC gain is the Understand suite (+0.178). The Fix suite also shows a significant gain (+0.092). The largest gains though come from cross-repository discovery tasks.

| Suite | n | Baseline Mean | MCP Mean | Delta | 95% CI |
|-------|---|--------------|----------|-------|--------|
| security | 24 | 0.422 | 0.535 | **+0.113** | [+0.042, +0.197] |
| incident | 20 | 0.444 | 0.552 | **+0.108** | [+0.033, +0.218] |
| crossrepo_tracing | 22 | 0.335 | 0.382 | +0.046 | [-0.000, +0.117] |
| onboarding | 28 | 0.703 | 0.746 | +0.044 | [-0.013, +0.111] |
| crossorg | 15 | 0.144 | 0.173 | +0.029 | [-0.003, +0.061] |
| org | 15 | 0.344 | 0.370 | +0.027 | [-0.026, +0.079] |
| domain | 20 | 0.322 | 0.331 | +0.009 | [-0.020, +0.042] |

Org total: Baseline mean 0.374, MCP mean 0.406, delta **+0.032** (95% CI: [+0.013, +0.053]). MCP wins on 63, loses on 37, neutral on 120 tasks. When the agent needs to find information scattered across multiple repos, MCP tools help.

The biggest effects are on security (+0.113) and incident debugging (+0.108). These are the tasks that look most like real enterprise work: tracing a vulnerability across a dozen repos, mapping error paths across microservices, figuring out mysterious (haunted?) codebases.

## Some Benchmark Highlights

**Understanding impact in a large codebase:** The baseline agent burned its 6000s timeout navigating the Kubernetes monorepo and produced nothing. MCP completed in 89s (67x faster) with reward 0.90/1.0. The agent used 8 keyword searches, 6 semantic searches, and 1 find_references call to map the DRA allocation impact chain across cross-package dependencies. Without retrieval tools, this task was infeasible.

**A refactor task:** Hard cross-file Java refactoring in the Strata finance library. Both configs took ~17 min. Baseline made minimal changes (6 lines added, 6 removed across 2 files), reward 0.32. MCP identified all affected files for a full refactoring (725 lines added) that passed all verifier tests, reward 0.80.

**Another hard cross-file refactoring:** Baseline made 96 tool calls over 84 min (including 6 backtracks) for reward 0.32. MCP used 5 MCP tool calls in 4.4 min for reward 0.68. The MCP agent searched for RecordAccumulator and related symbols, read 3 files, and was done.

## Where Sourcegraph MCP Doesn't Help (or Hurts)

MCP hurt the reward outcomes on Debug (-0.064) and Design (-0.047). Refactor (-0.045) is also slightly negative. Test and Feature are flat.

| Suite | n | Baseline Mean | MCP Mean | Delta | 95% CI |
|-------|---|--------------|----------|-------|--------|
| debug | 18 | 0.617 | 0.552 | **-0.064** | [-0.112, -0.017] |
| design | 14 | 0.745 | 0.698 | -0.047 | [-0.157, +0.049] |
| refactor | 16 | 0.666 | 0.622 | -0.045 | [-0.126, +0.038] |
| feature | 23 | 0.590 | 0.576 | -0.014 | [-0.069, +0.040] |
| test | 18 | 0.513 | 0.503 | -0.010 | [-0.101, +0.087] |

The Debug result is the clearest negative signal: MCP underperforms baseline by -0.064 (95% CI: [-0.112, -0.017], excludes zero). These are local execution-and-modification workflows. Adding a remote retrieval layer doesn't seem to help the agent get to the actual code change in a way that helps the outcome.

Context retrieval isn't the bottleneck for every software development situation. Codebase size, harness, language, task type, prompt content all contribute. The [technical report](technical_reports/TECHNICAL_REPORT_V2.md) covers the full per-suite breakdown.

## MCP Value Scales With Codebase Size

One of the clearest patterns in the data: MCP's benefit increases monotonically with codebase size. We pulled repo sizes from the GitHub API for 365 of the 370 tasks and grouped them into bins:

| Repo Size | Approx LoC | n | Δ Reward | Δ Wall Clock | Δ Agent Exec | Δ $/task |
|-----------|-----------|---|----------|-------------|-------------|---------|
| <10 MB | <400K | 60 | −0.007 | −23s | −52s | +$1.39 |
| 10–50 MB | 0.4–2M | 61 | **+0.043** | **−153s** | **−137s** | **−$2.74** |
| 50–200 MB | 2–8M | 113 | +0.027 | +64s | −51s | +$0.03 |
| 200MB–1GB | 8–40M | 104 | +0.033 | −13s | −97s | +$0.02 |
| >1 GB | >40M | 27 | **+0.085** | −135s | −123s | +$0.06 |

For the smallest repos, MCP slightly hurts reward and adds cost. At 10–50 MB you hit the sweet spot: better outcomes, much faster, and $2.74/task cheaper. Above 1 GB the reward lift is largest (+0.085), which lines up with what you'd expect — massive monorepo-scale codebases like Kubernetes and Chromium are exactly where retrieval tools shine because the agent can't feasibly grep through tens of millions of lines. Agent execution time is shorter with MCP across *every* size category.

Breaking it down by difficulty: hard tasks (91% of the benchmark) show the best MCP profile — better reward (+0.023), faster (−58s wall clock, −95s agent), and cheaper (−$0.42/task). Expert tasks show a slight negative reward delta (−0.019) and much higher cost (+$3.01), suggesting that at the highest complexity tier the agent burns tokens on MCP searches that don't pay off.

By language, Go repos see the biggest cost savings (−$1.18/task, n=134), Rust sees the biggest wall-clock savings (−358s, n=12), and Python gets the best reward lift (+0.040, n=55). TypeScript is the only language where MCP hurts across all dimensions, though n=7 is too small to draw strong conclusions.

## Retrieval Differences

I built an information retrieval evaluation pipeline alongside the task scoring to measure how agents find information across codebases that they then use (or don't) to complete their tasks (or not).

| Config | n | File Recall | Precision@1 | F1@5 | MRR |
|--------|---|------------|-------------|------|-----|
| baseline-local-direct | 963 | 0.326 | 0.312 | 0.185 | 0.357 |
| mcp-remote-direct | 698 | 0.474 | 0.282 | 0.174 | 0.343 |

MCP agents find a substantially higher fraction of the files that matter (file recall 0.474 vs 0.326, +0.148), but there's a recall-precision trade-off: precision is slightly lower (P@1: 0.282 vs 0.312) and F1@5 is roughly flat (0.174 vs 0.185). MCP casts a wider net — it retrieves more relevant files but also more irrelevant ones. Mean Reciprocal Rank is essentially unchanged; both configs find root-cause files at similar ranking positions when they find them.

But better retrieval doesn't always mean better outcomes. Still investigating this but likely finding the right files is necessary but not sufficient. The agent still has to correctly apply what it finds, and in some tasks the local code modification step is where removing local code availability from the MCP run environment hurts more than others.

## Patterns in the Retrieval-Outcome Pairing Data

**Retrieval rescue.** On some tasks, the baseline agent found zero relevant context and scored zero. MCP found it and scored well. MCP unlocked a capability the baseline agent just didn't have.

**Execution wins despite similar retrieval.** This one is kind of suspicious. On several tasks, both configs accessed the same files, but MCP still produced better outcomes. Maybe something about the MCP output (structured tool output, how search results prime the agent's reasoning, different prompt context from using tools vs. reading files) improves downstream execution even when the information retrieved is the same? Looking into it.

Could also just be plain ol' agent non-determinism. Retrieval quality alone doesn't seem to predict task success, but there are many more variables to isolate.

## The Cost and Speed Differences

Let's take a break from whatever voodoo variables control reward outcomes and talk about costs and timing. Overall MCP is actually cheaper — $0.801 vs $1.008 per task (−$0.210) — and faster, cutting agent execution time by 89 seconds (−36%).

| Category | n | Baseline Mean ($/task) | MCP Mean ($/task) | Delta |
|----------|---|------------------------|-------------------|-------|
| SDLC     | 149 | $2.176 | $1.672 | −$0.504 |
| Org      | 220 | $0.221 | $0.211 | −$0.010 |
| **Overall** | **369** | **$1.008** | **$0.801** | **−$0.210** |

MCP is cheaper on Org tasks because remote search replaces expensive local file-reading operations. It's also cheaper on SDLC overall, driven by large savings on refactor (−$4.24/task) and feature (−$1.55/task) suites where MCP's semantic search replaces expensive exhaustive code traversal. Design tasks are the main exception (+$1.55/task), where MCP adds overhead without replacing local analysis.

Speed tells an even cleaner story:

| Metric | n | Baseline Mean (s) | MCP Mean (s) | Delta |
|--------|---|--------------------|--------------|-------|
| Wall clock | 370 | 411.1 | 375.2 | −36.0 |
| Agent execution | 370 | 243.7 | 155.1 | −88.6 |

Agent execution time is the cleaner metric (it excludes Docker build and verification overhead): the agent's problem-solving phase is 36% shorter with MCP. Org tasks see the biggest wall-clock speedup (−63 seconds, −19.8%). The per-suite variation is large — MCP cuts design task wall clock by 415 seconds but adds 360 seconds to fix tasks. But agent execution time is shorter with MCP on *every single suite* except refactor (+5s, flat) and fix (−1s, flat).

On suites where MCP improves reward (Org security and incident especially), you also get better results faster and cheaper. Security tasks: +0.122 reward, −269s wall clock, −$0.002/task. Incident tasks: +0.108 reward, −92s wall clock, −$0.021/task. Where MCP hurts reward (debug: −0.064), you still get faster agent execution but at slightly higher cost. This is useful signal for figuring out where these tools are worth deploying.

## MCP Tool Usage Patterns

Agents overwhelmingly default to keyword search. Deep Search was almost never invoked organically (6 tasks, 8 calls across 602 MCP runs). The agent relies on keyword search (4,813 calls) and file reading (6,324 calls) as its primary MCP tools. Natural language search is used in ~42% of tasks but contributes only 587 calls vs 4,813 for keyword search. The search strategy breakdown: the vast majority of tasks use keyword-only or keyword-dominant approaches, with natural language search as a secondary fallback, and Deep Search effectively ignored. Agents seem to have a strong preference for exact keyword matching over semantic search, even when they are told outright about these tools.

## Auditable Results (Transcripts!)

I mentioned earlier that I think benchmark results should ship with full agent transcripts. Here's how I approached it for this benchmark framework.

Every task run in CodeScaleBench produces two artifacts beyond the score: a structured result.json with task metadata, pass/fail status, rewards, and timing, plus a full tool-usage transcript showing how the agent interacted with tools including MCPs. These transcripts are how I found the git history bypass hack, what Claude Code coined as MCP death spirals, verifier failures, and every other issue in this post. Without them, those issues could potentially still be there messing up the validity of the results.

All results described here, including full traces, tool breakdowns, and IR metrics, are published in the repo.

### The Results Explorer

In addition to being able to navigate the results via markdowns, if you clone the repo and run:

```
python3 scripts/export_official_results.py --serve
```

You get a local results explorer where you can browse every task run. It shows 4,132 total task evaluations across all suites, configs, and runs.

The Official Results Browser lets you filter by suite, task run, config, and status. Every row links to the task's repo, benchmark definition, trajectory, and audit trail.

Drilling into a specific task, here's a baseline run of bustub-hyperloglog-impl-001 in the feature suite. You can see it took 2269 seconds (nearly 38 minutes), made 175 tool calls, consumed 28.5M input tokens, and scored a reward of 0.167. The full conversation history (388 messages) is right there for inspection.

And an example MCP-augmented run: mcp_CCX-compliance-124 in the compliance suite. 115 seconds total, 20 tool calls, MCP ratio of 0.950, reward of 0.7419. The agent trace starts with "I'll help you audit the CSP enforcement infrastructure in Firefox" and immediately goes to the relevant dom/security/ directory via Sourcegraph MCP tools.

Each task detail view has expandable sections for the tool breakdown, context metrics / IR analysis, and the complete conversation history. You can verify not just whether the agent succeeded, but how it approached the task, what tools it used, and where it went wrong or right.

## How I Built This (And What Broke)

I built CodeScaleBench almost entirely with Claude Code, the same AI coding agent I used for the initial benchmark runs. ~600 conversation sessions over about a month, producing the task selection pipeline, 190+ Docker environment variants, a 3,500-line IR evaluation pipeline, a 7-function oracle scoring system, and helper skills for everything from benchmark design to pre-flight validation to results QA.

The process taught me a lot about where AI-assisted development works well and where issues pop up.

**What worked well:** Generating Dockerfiles, writing evaluation scripts, building metrics pipelines, implementing statistical tests. Well-structured, pattern-heavy work where you describe what you want and validate the output deterministically. Claude Code was great at this.

**What broke, repeatedly:** The preamble. This is the instruction text prepended to each task telling the MCP agent about its tools. I went through five iterations:

V1 and V2 were too subtle. The agent had MCP tools available but never called them. Zero Sourcegraph tool calls across the board. V3 overcorrected with "MANDATORY" triple reinforcement, which got 90%+ adoption but caused what Claude Code coined the "MCP death spiral": when a mirror was broken or a repo name was wrong, the agent would spend its entire context window retrying failed MCP queries, scoring 0.0 on tasks where the baseline scored 1.0. V4 swung back to "soft guidance" and adoption dropped to 40%. V5 finally landed it by leading with the constraint "these files are not present locally, you must use MCP tools to access source code", which finally forced adoption without mandating a specific workflow.

**Git Treachery:** Then there was the git history bypass bug. I discovered that 5 of my first 9 test tasks were Claude being sneaky gaming the truncation I had set up in the MCP docker environments: the agent figured out it could `git show HEAD:filename` to recover the full source from git history, completely defeating the experimental setup. The fix (recommitting the truncated state as a new commit so `git show HEAD:` returns empty files) was straightforward, but finding it required actually reading agent transcripts. Just a reminder that systematic QA on AI-generated infrastructure is non-negotiable.

## Benchmark QA is SUPER IMPORTANT

Speaking of QA, that has taken (and continues to take) the majority of the benchmark creation time. One of my first QA audits found nearly 30 issues in the benchmark infrastructure: broken verifiers, instruction contamination (a bunch of task instructions had Sourcegraph references leaking into the baseline config), silent scoring failures. Our PyTorch verification checks were accidentally ineffective because of a name collision that caused make to skip the verifier commands, and more. Just a bunch of infrastructure whack-a-mole.

To mitigate some of this I had Claude make some QA and other benchmark-helper skills and built an agentic benchmark checklist pipeline (the one I mentioned earlier that is inspired by this paper). Every run goes through automated validation across six dimensions before it can be promoted to official status. It catches instruction contamination, broken verifiers, reproducibility issues, ghost runs, error misclassification, and tool effectiveness problems. I have the run outputs go to a staging directory and promote the runs to official once they pass several quality gates.

The six dimensions:

1. Task Validity -- instruction quality, Dockerfile correctness, task metadata
2. Outcome Validity -- verifier soundness, scoring accuracy, fail2pass checks
3. Reporting -- result.json completeness, metrics extraction, audit trail
4. Reproducibility -- deterministic environments, pinned commits, verifier idempotence
5. Tool Effectiveness -- MCP adoption rates, zero-tool detection, death spiral flagging
6. Statistical Validity -- sufficient sample size, paired comparison integrity, CI coverage

Iterative, borderline paranoid QA is a benchmark requirement. If you want to try to do it right anyway.

## What I Don't Know Yet

These are results from one agent (Claude Code), one code navigation MCP provider (Sourcegraph), running Haiku 4.5. The sample sizes are meaningful (370 tasks, 4,132 individual results with 3+ runs per task) and the overall effect is statistically significant, but individual sub-suite confidence intervals are wide enough that some suite-level conclusions could shift with more data.

The weak correlations between retrieval quality and task outcomes also need more exploration. If better retrieval doesn't predict better outcomes, what does? Is it the structure of the tool output? The harness? The codebase? The way search-first workflows shape the agent's reasoning? Some interaction between retrieval strategy and the agent's existing capabilities? I don't know yet, but I think figuring this out is important for how we build code intelligence tools and design coding agent workflows.

## The Signal

I started this project because I wanted to be able to measure the impact of code context retrieval on coding agent software development task outcomes. I couldn't use many tasks in existing benchmarks because they're not measuring what matters for developers and agents working in large codebases, or only do so in narrow ways.

Here's what the data from my benchmark says so far:

**Sourcegraph MCP provides measurable value on cross-repository discovery tasks.** The Org tasks show a +0.032 gain over the baseline rewards (95% CI: [+0.013, +0.053]), with security (+0.113) and incident debugging (+0.108) showing the largest effects. The agent with the MCP tools also finishes its tasks faster and cheaper in many cases. This is something I want to explore further.

**MCP's value scales with codebase size.** The reward lift increases monotonically from −0.007 on <10 MB repos to +0.085 on >1 GB repos. The cost-efficiency sweet spot is 10–50 MB codebases (−$2.74/task, −153s wall clock, +0.043 reward). Agent execution time is shorter with MCP across every size category.

**Sourcegraph MCP tools provide mixed value depending on task type within the SDLC.** Sourcegraph MCP helped on understand (+0.178) and fix (+0.092), was neutral for feature (-0.014) and test (-0.010), and hurt on debugging (-0.064) and design (-0.047). Though again in this case the agent already has full source code which isn't likely to be the actual case for developers working in the largest codebases that would benefit from these tools. It was also cheaper for the task types it produced the best rewards for.

**Information retrieval quality has questionable impact on reward outcomes.** I saw scenarios where retrieval metrics were basically the same but outcomes still differ. That's either agent non-determinism or something else and I'll need to investigate it.

**Agents really don't want to use semantic / asynchronous tools.** I found that the agent overwhelmingly wanted to use keyword search and ignored Deep Search as a tool (6 tasks, 8 calls out of 602 MCP runs), and I wonder if nudging it to use more optimized tools in different scenarios would change any outcomes.

The [technical report](technical_reports/TECHNICAL_REPORT_V2.md) has the full methodology, statistical analysis, and evaluation pipeline details. My paper will have even more.

## What's Next

I have more tasks to run to measure variance and account for agent non-determinism. I'm expanding the benchmark framework to support six agent harnesses (Claude Code, Codex, Cursor, Gemini, Copilot, OpenHands); running the full suite across multiple agents will separate MCP tool effectiveness from agent-specific strengths.

I'm also planning Deep Search (this semantic synthesis/analysis layer was almost never invoked organically) and other MCP tool combination focused experiments, SCIP-indexed codebase comparisons (compiler-accurate code navigation vs. text search), and evaluations of alternative MCP providers like the GitHub MCP server. The benchmark is provider-agnostic and the MCP protocol is standardized, so swapping providers is just a config change.

If you're building or evaluating tools for agents working on software development (or just interested in that stuff) and want to check out the benchmark, the repo is public. I'd love to get feedback and welcome contributions.
