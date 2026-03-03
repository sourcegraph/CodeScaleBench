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

Some initial findings (that'll be expanded on later): the overall impact of using the Sourcegraph MCP on the task reward outcome is **+0.014** for CSB-SDLC and **+0.032** for CSB-Org. This means across all of our benchmark tasks the MCP runs scored on average **5.4% higher** (overall delta +0.025, from 0.464 baseline to 0.489 MCP). That overall delta is statistically significant (95% bootstrap CI: [+0.008, +0.042]), but the SDLC-only delta's confidence interval spans zero, meaning for tasks where the agent already has full local source code the effect isn't conclusive. The Org delta is significant (CI: [+0.013, +0.053]), confirming that MCP tools provide measurable value when the agent needs to discover information across repositories. The MCP tasks were also overwhelmingly completed faster, and sometimes cheaper. Org tasks with MCP were 63 seconds faster on average (-19.8%) and slightly cheaper (-$0.010/task), while SDLC tasks with MCP were 23 seconds faster but cost more (+$0.075/task) because the agent uses MCP tools on top of local tools rather than instead of them.

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

## Retrieval Differences

I built an information retrieval evaluation pipeline alongside the task scoring to measure how agents find information across codebases that they then use (or don't) to complete their tasks (or not).

| Config | n | File Recall (mean) | MRR (mean) |
|--------|---|-------------------|------------|
| baseline-local-direct | 963 | 0.326 | 0.352 |
| mcp-remote-direct | 698 | 0.474 | 0.352 |

MCP agents find a higher fraction of the files that matter (file recall 0.474 vs 0.326), and a higher fraction of the files they retrieve are relevant. Mean Reciprocal Rank is unchanged; both configs find root-cause files at similar ranking positions when they find them.

But better retrieval doesn't always mean better outcomes. Still investigating this but likely finding the right files is necessary but not sufficient. The agent still has to correctly apply what it finds, and in some tasks the local code modification step is where removing local code availability from the MCP run environment hurts more than others.

## Patterns in the Retrieval-Outcome Pairing Data

**Retrieval rescue.** On some tasks, the baseline agent found zero relevant context and scored zero. MCP found it and scored well. MCP unlocked a capability the baseline agent just didn't have.

**Execution wins despite similar retrieval.** This one is kind of suspicious. On several tasks, both configs accessed the same files, but MCP still produced better outcomes. Maybe something about the MCP output (structured tool output, how search results prime the agent's reasoning, different prompt context from using tools vs. reading files) improves downstream execution even when the information retrieved is the same? Looking into it.

Could also just be plain ol' agent non-determinism. Retrieval quality alone doesn't seem to predict task success, but there are many more variables to isolate.

## The Cost Differences

Let's take a break from whatever voodoo variables control reward outcomes and talk about costs. MCP runs are slightly more expensive overall, about 5.8% higher ($0.333 vs $0.297 per task), but the costs vary by category.

| Category | n | Baseline Mean ($/task) | MCP Mean ($/task) | Delta |
|----------|---|------------------------|-------------------|-------|
| SDLC     | 103 | $0.463 | $0.539 | +$0.075 |
| Org      | 220 | $0.221 | $0.211 | -$0.010 |
| **Overall** | **323** | **$0.297** | **$0.333** | **+$0.017** |

MCP is cheaper on the Org tasks where it also improves reward: the agent using MCP tools costs less per task (-$0.010) because remote search replaces expensive local file-reading operations. It's more expensive on SDLC tasks (+$0.075), where the agent uses MCP tools on top of local tools rather than instead of them.

Where cost is mixed, speed is not. MCP is substantially faster across the board, cutting wall-clock time by 47 seconds overall (-11.6%) and agent execution time by 90 seconds (-38.1%).

| Metric | n | Baseline Mean (s) | MCP Mean (s) | Delta |
|--------|---|--------------------|--------------|-------|
| Wall clock | 369 | 403.1 | 356.2 | -46.8 |
| Agent execution | 369 | 237.1 | 146.7 | -90.4 |

On suites where MCP improves reward (Org security and incident especially), you get better results faster and cheaper. Where MCP hurts (debug), you get worse results faster and at slightly higher cost. This is useful signal for figuring out where these tools are worth using.

## MCP Tool Usage Patterns

Agents overwhelmingly default to keyword search. Deep Search was almost never invoked organically (6 tasks, 8 calls across 602 MCP runs). The agent relies on keyword search (4,813 calls) and file reading (6,324 calls) as its primary tools. Natural language search is used in ~42% of tasks but contributes only 587 calls. Agents seem to have a strong preference for exact keyword matching over semantic search, even when they are told outright about these tools.

## Auditable Results (Transcripts!)

I mentioned earlier that I think benchmark results should ship with full agent transcripts. Here's how I approached it for this benchmark framework.

Every task run in CodeScaleBench produces two artifacts beyond the score: a structured result.json with task metadata, pass/fail status, rewards, and timing, plus a full tool-usage transcript showing how the agent interacted with tools including MCPs. These transcripts are how I found the git history bypass hack, what Claude Code coined as MCP death spirals, verifier failures, and every other issue in this post. Without them, those issues could potentially still be there messing up the validity of the results.

All results described here, including full traces, tool breakdowns, and IR metrics, are published in the repo.

### The Results Explorer

In addition to being able to navigate the results via markdowns, if you clone the repo and run:

```
python3 scripts/export_official_results.py --serve
```

You get a local results explorer where you can browse every task run. It shows the full set of task runs across all suites, configs, and runs.

The Official Results Browser lets you filter by suite, task run, config, and status. Every row links to the task's repo, benchmark definition, trajectory, and audit trail.

Each task detail view has expandable sections for the tool breakdown, context metrics / IR analysis, and the complete conversation history. You can verify not just whether the agent succeeded, but how it approached the task, what tools it used, and where it went wrong or right.

## How I Built This (And What Broke)

I built CodeScaleBench almost entirely with Claude Code, the same AI coding agent I used for the benchmark runs. ~1000 conversation sessions over about a month, producing the task selection pipeline, 190+ Docker environment variants, a 3,500-line IR evaluation pipeline, a 7-function oracle scoring system, and helper skills for everything from benchmark design to pre-flight validation to results QA.

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

**Sourcegraph MCP tools provide mixed value depending on task type within the SDLC.** Sourcegraph MCP helped on understand (+0.178) and fix (+0.092), was neutral for feature (-0.014) and test (-0.010), and hurt on debugging (-0.064) and design (-0.047). Though again in this case the agent already has full source code which isn't likely to be the actual case for developers working in the largest codebases that would benefit from these tools. It was also cheaper for the task types it produced the best rewards for.

**Information retrieval quality has questionable impact on reward outcomes.** I saw scenarios where retrieval metrics were basically the same but outcomes still differ. That's either agent non-determinism or something else and I'll need to investigate it.

**Agents really don't want to use semantic / asynchronous tools.** I found that the agent overwhelmingly wanted to use keyword search and ignored Deep Search as a tool (6 tasks, 8 calls out of 602 MCP runs), and I wonder if nudging it to use more optimized tools in different scenarios would change any outcomes.

The [technical report](technical_reports/TECHNICAL_REPORT_V2.md) has the full methodology, statistical analysis, and evaluation pipeline details. My paper will have even more.

## What's Next

I have more tasks to run to measure variance and account for agent non-determinism. I'm expanding the benchmark framework to support six agent harnesses (Claude Code, Codex, Cursor, Gemini, Copilot, OpenHands); running the full suite across multiple agents will separate MCP tool effectiveness from agent-specific strengths.

I'm also planning Deep Search (this semantic synthesis/analysis layer was almost never invoked organically) and other MCP tool combination focused experiments, SCIP-indexed codebase comparisons (compiler-accurate code navigation vs. text search), and evaluations of alternative MCP providers like the GitHub MCP server. The benchmark is provider-agnostic and the MCP protocol is standardized, so swapping providers is just a config change.

If you're building or evaluating tools for agents working on software development (or just interested in that stuff) and want to check out the benchmark, the repo is public. I'd love to get feedback and welcome contributions.
