# Suite Merging Power Analysis

## Summary

This analysis evaluates the statistical power of CodeScaleBench's 20 suites
to detect a meaningful MCP effect (delta = 0.05) and proposes merges to
improve power without losing analytical granularity.

**Key finding:** Only 2 of 20 suites achieve 80% power at delta=0.05.
Merging related low-power suites improves coverage while preserving the
ability to report fine-grained results as sub-analyses.

## Current Suite Power (delta = 0.05, alpha = 0.05, two-sided)

| Suite | n | Mean Delta | Sigma | Power | N needed (80%) |
|-------|---|-----------|-------|-------|---------------|
| csb_org_domain | 20 | +0.0091 | 0.0722 | **87.2%** | 17 |
| csb_org_crossorg | 15 | +0.0292 | 0.0647 | **84.9%** | 14 |
| csb_org_crossrepo | 14 | -0.0185 | 0.0745 | 70.9% | 18 |
| csb_sdlc_document | 13 | +0.0351 | 0.0830 | 58.4% | 22 |
| csb_sdlc_debug | 18 | -0.0476 | 0.0992 | 57.0% | 31 |
| csb_org_org | 15 | +0.0267 | 0.1062 | 44.6% | 36 |
| csb_sdlc_feature | 23 | +0.0004 | 0.1323 | 44.1% | 55 |
| csb_org_platform | 18 | -0.0380 | 0.1171 | 44.1% | 44 |
| csb_org_compliance | 18 | -0.0031 | 0.1235 | 40.4% | 48 |
| csb_org_migration | 26 | +0.0014 | 0.1549 | 37.7% | 76 |
| csb_org_onboarding | 28 | +0.0463 | 0.1678 | 35.1% | 89 |
| csb_org_crossrepo_tracing | 22 | +0.0463 | 0.1546 | 32.9% | 76 |
| csb_sdlc_secure | 12 | +0.0268 | 0.1291 | 26.8% | 53 |
| csb_sdlc_fix | 26 | +0.0920 | 0.1956 | 25.6% | 121 |
| csb_sdlc_refactor | 16 | -0.0411 | 0.1559 | 24.9% | 77 |
| csb_org_security | 24 | +0.1278 | 0.2305 | 18.5% | 167 |
| csb_sdlc_design | 14 | -0.0399 | 0.1812 | 17.7% | 104 |
| csb_org_incident | 20 | +0.1076 | 0.2264 | 16.6% | 161 |
| csb_sdlc_test | 18 | +0.0218 | 0.2178 | 16.2% | 150 |
| csb_sdlc_understand | 10 | +0.1807 | 0.2321 | 10.1% | 170 |

## Power Interpretation

- **High power (>80%):** Can reliably detect delta=0.05 effects. Results are conclusive.
- **Moderate power (50-80%):** May detect effects but has meaningful false negative risk.
- **Low power (<50%):** Suite-level conclusions are unreliable. Large effects may still be visible.

High-variance suites (sigma > 0.20) like understand, security, and incident need
50-170+ tasks each to achieve 80% power. This is impractical to add — merging is the
better strategy.

## Proposed Merges

### RECOMMENDED: Cross-Org & Org Context (merged)

**Rationale:** Both require understanding organizational code structure. crossorg adds
the multi-org dimension but the core skill is the same. Merging brings csb_org_org
(currently 44.6% power) into an already-powerful grouping.

| Config | n | Sigma | Power | N needed |
|--------|---|-------|-------|----------|
| csb_org_crossorg (current) | 15 | 0.0647 | 84.9% | 14 |
| csb_org_org (current) | 15 | 0.1062 | 44.6% | 36 |
| **crossorg_merged** (merged) | **30** | **0.0864** | **88.7%** | **24** |

Power gain from merging: **+3.8%** (already above threshold, now solidly above it;
also rescues csb_org_org from 44.6% power).

### RECOMMENDED: Compliance & Platform Knowledge (merged)

**Rationale:** Both test policy/configuration understanding across codebases. Similar
variance profiles (sigma 0.12 vs 0.12) and non-overlapping repos. This is the
highest-impact merge: +26.5 percentage points of power.

| Config | n | Sigma | Power | N needed |
|--------|---|-------|-------|----------|
| csb_org_compliance (current) | 18 | 0.1235 | 40.4% | 48 |
| csb_org_platform (current) | 18 | 0.1171 | 44.1% | 44 |
| **compliance_platform** (merged) | **36** | **0.1199** | 70.6% | **46** |

Power gain from merging: **+26.5%** (from 44% to 71%, close to threshold).

### NOT RECOMMENDED: Cross-Repo Discovery (merged)

**Rationale for caution:** crossrepo_tracing (sigma=0.155) has 2x the variance of
crossrepo (sigma=0.075). Merging *increases* pooled variance enough to offset the
sample size gain, actually *decreasing* power from the better individual suite.

| Config | n | Sigma | Power | N needed |
|--------|---|-------|-------|----------|
| csb_org_crossrepo (current) | 14 | 0.0745 | **70.9%** | 18 |
| csb_org_crossrepo_tracing (current) | 22 | 0.1546 | 32.9% | 76 |
| crossrepo_merged (merged) | 36 | 0.1320 | 62.3% | 55 |

Power change: **-8.6%** (variance increase offsets sample size gain). Keep these
separate. Adding 4 tasks to csb_org_crossrepo (to reach n=18) would achieve 80% power
at its current low variance.

### NOT RECOMMENDED: Understand & Design (merged)

**Rationale for caution:** Both suites have very high variance (sigma > 0.18). Merging
to n=24 barely moves the needle because the merged sigma stays at 0.228. Would need
164 tasks for 80% power — impractical.

| Config | n | Sigma | Power | N needed |
|--------|---|-------|-------|----------|
| csb_sdlc_understand (current) | 10 | 0.2321 | 10.1% | 170 |
| csb_sdlc_design (current) | 14 | 0.1812 | 17.7% | 104 |
| understand_design (merged) | 24 | 0.2280 | 18.8% | 164 |

Power gain: **+1.1%** (negligible). These suites are better reported individually
with appropriate confidence interval caveats. Their large observed effects (+0.18
understand, -0.04 design) may be real but can't be confirmed at current sample sizes.

## Alternative Strategies

For suites where merging doesn't help (high-variance suites like understand, test,
security, incident):

1. **Accept lower detectable effect sizes:** At n=24 and sigma=0.23, the suite can
   detect delta=0.10 with 34% power, or delta=0.15 with 62% power. Security
   (delta=+0.128) and incident (delta=+0.108) have effects large enough to approach
   detection even at their current power levels.

2. **More runs per task:** Increasing from 3 to 5+ runs per task reduces the within-task
   noise component of sigma, which can modestly improve power. The Neyman decomposition
   (see `scripts/doe_variance_analysis.py`) separates task heterogeneity from agent
   stochasticity to quantify this effect.

3. **Report effect sizes with CIs:** Instead of binary significance testing, report
   the point estimate and 95% bootstrap CI. The reader can judge whether the CI is
   narrow enough for their purposes.

4. **Add tasks strategically:** csb_org_crossrepo only needs 4 more tasks (to n=18) to
   reach 80% power at its current low variance. csb_sdlc_document needs 9 more (to n=22)
   at its current variance.

## Implementation: Merged Suite View

The merge is a **reporting-layer change only**. Existing tasks, runs, and per-suite
breakdowns remain intact. The extract script gains a `SUITE_MERGE_MAP` that aggregates
paired stats under merged suite names while preserving the original suite as a sub-field.

Only two merges are recommended for the primary reporting view:

### Reporting hierarchy (with 2 recommended merges)

```
Overall (n=370)
  ├── SDLC (n=150)       [9 suites, no merges recommended]
  │   ├── debug (n=18)
  │   ├── design (n=14)
  │   ├── document (n=13)
  │   ├── feature (n=23)
  │   ├── fix (n=26)
  │   ├── refactor (n=16)
  │   ├── secure (n=12)
  │   ├── test (n=18)
  │   └── understand (n=10)
  └── Org (n=220)         [11→9 suites after 2 merges]
      ├── crossorg_merged (n=30, power 88.7%)
      │   ├── crossorg (n=15)
      │   └── org (n=15)
      ├── compliance_platform (n=36, power 70.6%)
      │   ├── compliance (n=18)
      │   └── platform (n=18)
      ├── crossrepo (n=14, power 70.9%)       [kept separate]
      ├── crossrepo_tracing (n=22)
      ├── domain (n=20, power 87.2%)
      ├── incident (n=20)
      ├── migration (n=26)
      ├── onboarding (n=28)
      └── security (n=24)
```

Result: 20 → 18 reporting suites with 4 suites above 70% power (up from 3).

### DO NOT merge

- **security (n=24):** Strongest MCP signal (+0.128), merging would dilute it
- **incident (n=20):** Second strongest MCP signal (+0.108), keep separate
- **migration (n=26):** Already large enough, distinct task profile
- **onboarding (n=28):** Already large enough, distinct task profile
- **domain (n=20):** Low variance (sigma=0.072), already at 87% power
- **crossrepo (n=14):** Low variance (sigma=0.075), only needs 4 more tasks for 80%
- **crossrepo_tracing (n=22):** High variance makes merging counterproductive
