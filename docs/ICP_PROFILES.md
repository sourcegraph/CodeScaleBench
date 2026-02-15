# ICP-Aligned Benchmark Profiles

## Overview

CodeContextBench supports **5 enterprise customer profiles** (ICPs) that filter benchmark results to metrics relevant to specific organizational contexts. Each profile maps to a subset of benchmarks, defines success thresholds, and generates tailored reports.

Profiles answer four questions for each customer type:
1. What problem does this customer have?
2. What operational change occurs with context infrastructure?
3. What risk is reduced?
4. What economic outcome follows?

## Profiles

### A. Legacy Enterprise Modernization ("Sleeping Giants")

**Buyer**: VP Engineering / CTO at regulated enterprise
**Suites**: LoCoBench, LargeRepo, CrossRepo, DependEval
**Report**: Modernization Readiness Report

Key thresholds:
- ≥40% reduction in dependency ambiguity
- ≥30% comprehension time reduction
- ≥50% cross-repo pass rate

### B. Platform-Mature SaaS ("Velocity Leaders")

**Buyer**: Head of Platform Engineering / Dev Productivity Lead
**Suites**: SWE-bench Pro, DIBench, K8s Docs, TAC, PyTorch
**Report**: Developer Velocity Report

Key thresholds:
- ≥20% onboarding acceleration
- ≥70% implementation pass rate
- ≥0.30 productivity per dollar

### C. Security & Compliance ("Governance First")

**Buyer**: CISO / Head of Engineering Compliance
**Suites**: Governance (ccb_governance), CrossRepo
**Report**: Governance & Risk Report

Key thresholds:
- ≥90% compliance rate
- Zero sensitive file access
- ≥95% audit trail completeness

### D. AI-Forward ("Agent Builders")

**Buyer**: Head of AI/ML Engineering
**Suites**: SWE-bench Pro, PyTorch, LoCoBench, LargeRepo, CrossRepo, SWE-Perf
**Report**: Agent Reliability Report

Key thresholds:
- ≥30% agent reliability improvement
- ≤0.50 cross-suite consistency CV
- ≥15% token efficiency improvement

### E. Platform Consolidation ("Consolidators")

**Buyer**: VP Platform / Head of Architecture
**Suites**: CrossRepo, LargeRepo, DependEval, DIBench
**Report**: Architecture Visibility Report

Key thresholds:
- ≥25% cross-repo pass rate improvement
- ≥30% dependency resolution improvement
- ≥0.60 consolidation readiness score

## Usage

```bash
# List all profiles
python3 scripts/icp_profiles.py

# Show profile details
python3 scripts/icp_profiles.py --profile legacy

# Show suite-to-profile mapping
python3 scripts/icp_profiles.py --list-suites

# Generate profile-specific enterprise report
python3 scripts/generate_enterprise_report.py --profile legacy_modernization --output-dir reports/

# Generate all profile reports
for p in legacy_modernization platform_saas security_compliance ai_forward platform_consolidation; do
  python3 scripts/generate_enterprise_report.py --profile $p --output-dir reports/$p/
done
```

## Campaign Alignment

| Campaign | Profile |
|----------|---------|
| 100 Use Cases | Platform-Mature SaaS |
| Sleeping Giants | Legacy Enterprise Modernization |
| Security/Oversight | Security & Compliance |
| AI Rollout | AI-Forward Organizations |
| Platform Consolidation | Platform Consolidation & Migrations |

## Architecture

The ICP profile system is a **filter and lens layer** — it does not generate new data. It:

1. Filters existing benchmark results to profile-relevant suites
2. Computes profile-specific metrics from the filtered data
3. Evaluates success thresholds defined per profile
4. Generates profile-tailored report output

All underlying data comes from the same sub-reports (workflow_metrics, economic_analysis, reliability_analysis, failure_analysis, governance_evaluator).
