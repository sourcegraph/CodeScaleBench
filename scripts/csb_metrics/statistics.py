"""Statistical analysis utilities for CodeScaleBench A/B comparisons.

Provides hypothesis testing, effect size calculations, bootstrap confidence
intervals, and McNemar's test for paired pass/fail outcomes. Pure stdlib —
no external dependencies (math, statistics, random only).

Ported from IR-SDLC-Factory/app/ir_sdlc/comparative_analysis.py,
stripped of AgentRunner/ABComparator/ComparisonReport classes.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normal_cdf(x: float) -> float:
    """Approximate standard normal CDF via the error function."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _chi2_cdf_df1(x: float) -> float:
    """Chi-squared CDF for df=1: P(X <= x) = 2*Phi(sqrt(x)) - 1."""
    if x <= 0:
        return 0.0
    return 2 * _normal_cdf(math.sqrt(x)) - 1


# ---------------------------------------------------------------------------
# Core statistical functions
# ---------------------------------------------------------------------------

def welchs_t_test(
    a: List[float],
    b: List[float],
    alpha: float = 0.05,
) -> dict:
    """Welch's t-test for independent samples (unequal variances).

    Args:
        a: Baseline group measurements.
        b: Treatment group measurements.
        alpha: Significance level.

    Returns:
        Dict with keys: t_stat, p_value, df, n_a, n_b, is_significant,
        interpretation.
    """
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return {
            "t_stat": 0.0,
            "p_value": 1.0,
            "df": 0.0,
            "n_a": n_a,
            "n_b": n_b,
            "is_significant": False,
            "interpretation": "Insufficient sample size (need >= 2 per group)",
        }

    mean_a, mean_b = statistics.mean(a), statistics.mean(b)
    var_a, var_b = statistics.variance(a), statistics.variance(b)

    se = math.sqrt(var_a / n_a + var_b / n_b)
    if se == 0:
        return {
            "t_stat": 0.0,
            "p_value": 1.0,
            "df": 0.0,
            "n_a": n_a,
            "n_b": n_b,
            "is_significant": False,
            "interpretation": "Zero variance in both groups",
        }

    t_stat = (mean_b - mean_a) / se

    # Welch-Satterthwaite degrees of freedom
    num = (var_a / n_a + var_b / n_b) ** 2
    denom = (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
    df = num / denom if denom > 0 else 1.0

    # Two-tailed p-value (normal approximation, adequate for df > ~30)
    p_value = 2 * (1 - _normal_cdf(abs(t_stat)))

    is_sig = p_value < alpha
    direction = "higher" if t_stat > 0 else "lower"
    interpretation = (
        f"Treatment is {'significantly ' if is_sig else 'not significantly '}"
        f"{direction} than baseline "
        f"(t={t_stat:.3f}, p={p_value:.4f}, df={df:.1f})"
    )

    return {
        "t_stat": round(t_stat, 4),
        "p_value": round(p_value, 6),
        "df": round(df, 1),
        "n_a": n_a,
        "n_b": n_b,
        "is_significant": is_sig,
        "interpretation": interpretation,
    }


def cohens_d(
    a: List[float],
    b: List[float],
) -> dict:
    """Cohen's d effect size with 95 % confidence interval.

    Args:
        a: Baseline group.
        b: Treatment group.

    Returns:
        Dict with keys: d, magnitude, ci_lower, ci_upper.
    """
    n_a, n_b = len(a), len(b)
    if n_a < 1 or n_b < 1:
        return {"d": 0.0, "magnitude": "invalid", "ci_lower": 0.0, "ci_upper": 0.0}
    if n_a == 1 and n_b == 1:
        return {"d": 0.0, "magnitude": "insufficient_data", "ci_lower": 0.0, "ci_upper": 0.0}

    mean_a, mean_b = statistics.mean(a), statistics.mean(b)
    var_a = statistics.variance(a) if n_a > 1 else 0.0
    var_b = statistics.variance(b) if n_b > 1 else 0.0

    pooled_var = ((n_a - 1) * var_a + (n_b - 1) * var_b) / max(n_a + n_b - 2, 1)
    pooled_std = math.sqrt(pooled_var) if pooled_var > 0 else 1e-10

    d = (mean_b - mean_a) / pooled_std

    # Cohen's conventions
    abs_d = abs(d)
    if abs_d < 0.2:
        magnitude = "negligible"
    elif abs_d < 0.5:
        magnitude = "small"
    elif abs_d < 0.8:
        magnitude = "medium"
    else:
        magnitude = "large"

    # Hedges & Olkin (1985) approximate 95 % CI
    se = math.sqrt((n_a + n_b) / (n_a * n_b) + (d ** 2) / (2 * (n_a + n_b)))
    ci_lower = d - 1.96 * se
    ci_upper = d + 1.96 * se

    return {
        "d": round(d, 4),
        "magnitude": magnitude,
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
    }


def mcnemar_test(
    paired: List[Tuple[bool, bool]],
    alpha: float = 0.05,
) -> dict:
    """McNemar's test for paired nominal data (pass/fail per task).

    Args:
        paired: List of (baseline_passed, treatment_passed) tuples.
        alpha: Significance level.

    Returns:
        Dict with chi2, p_value, b, c, is_significant, interpretation.
    """
    if not paired:
        return {
            "chi2": 0.0,
            "p_value": 1.0,
            "b": 0,
            "c": 0,
            "n": 0,
            "is_significant": False,
            "interpretation": "Empty sample",
        }

    # b = baseline fail, treatment pass  (treatment improved)
    # c = baseline pass, treatment fail  (treatment regressed)
    b = sum(1 for bl, tr in paired if not bl and tr)
    c = sum(1 for bl, tr in paired if bl and not tr)
    n = len(paired)

    if b + c == 0:
        return {
            "chi2": 0.0,
            "p_value": 1.0,
            "b": b,
            "c": c,
            "n": n,
            "is_significant": False,
            "interpretation": "No discordant pairs — identical outcomes",
        }

    # Continuity-corrected McNemar chi-squared
    chi2 = (abs(b - c) - 1) ** 2 / (b + c)
    p_value = 1 - _chi2_cdf_df1(chi2)
    is_sig = p_value < alpha

    if b > c:
        direction = "treatment improved"
    elif c > b:
        direction = "baseline better"
    else:
        direction = "no clear direction"

    interpretation = (
        f"McNemar: {direction} "
        f"(b={b}, c={c}, chi2={chi2:.3f}, p={p_value:.4f})"
    )

    return {
        "chi2": round(chi2, 4),
        "p_value": round(p_value, 6),
        "b": b,
        "c": c,
        "n": n,
        "is_significant": is_sig,
        "interpretation": interpretation,
    }


def bootstrap_ci(
    values: List[float],
    n_bootstrap: int = 10000,
    ci: float = 0.95,
) -> Tuple[float, float, float]:
    """Percentile bootstrap confidence interval for the mean.

    Uses random.Random(42) internally for reproducibility.

    Args:
        values: Sample values.
        n_bootstrap: Number of bootstrap resamples (default: 10,000).
        ci: Confidence level.

    Returns:
        Tuple of (mean, ci_lower, ci_upper).

    >>> m, lo, hi = bootstrap_ci([0.5, 0.6, 0.7])
    >>> lo <= m <= hi
    True
    >>> abs(m - 0.6) < 0.001
    True
    >>> bootstrap_ci([])
    (0.0, 0.0, 0.0)
    >>> bootstrap_ci([0.5])
    (0.5, 0.5, 0.5)
    """
    if not values:
        return (0.0, 0.0, 0.0)

    mean_val = sum(values) / len(values)

    if len(values) == 1:
        return (mean_val, mean_val, mean_val)

    rng = random.Random(42)
    resamples: List[float] = []
    for _ in range(n_bootstrap):
        sample = rng.choices(values, k=len(values))
        resamples.append(sum(sample) / len(sample))

    resamples.sort()
    alpha = 1 - ci
    lo_idx = int(alpha / 2 * n_bootstrap)
    hi_idx = int((1 - alpha / 2) * n_bootstrap) - 1

    return (
        round(mean_val, 6),
        round(resamples[lo_idx], 6),
        round(resamples[hi_idx], 6),
    )


def bootstrap_ci_dict(
    values: List[float],
    n_bootstrap: int = 1000,
    ci: float = 0.95,
) -> dict:
    """Backwards-compatible dict wrapper around bootstrap_ci.

    Returns dict with ``estimate``, ``ci_lower``, ``ci_upper`` keys.
    Use this when callers expect a dict (legacy compatibility).
    """
    m, lo, hi = bootstrap_ci(values, n_bootstrap=n_bootstrap, ci=ci)
    return {"estimate": m, "ci_lower": lo, "ci_upper": hi}


def paired_bootstrap_delta(
    values_a: List[float],
    values_b: List[float],
    n_bootstrap: int = 10000,
    ci: float = 0.95,
) -> Tuple[float, float, float, float]:
    """Paired bootstrap test for the mean delta (b - a).

    Uses random.Random(42) internally for reproducibility.

    Args:
        values_a: Baseline measurements (paired with values_b).
        values_b: Treatment measurements (paired with values_a).
        n_bootstrap: Number of bootstrap resamples (default: 10,000).
        ci: Confidence level.

    Returns:
        Tuple of (mean_delta, ci_lower, ci_upper, p_value) where p_value
        is the proportion of bootstrap deltas crossing zero (two-tailed).

    >>> a = [0.4, 0.5, 0.6]; b = [0.5, 0.6, 0.7]
    >>> delta, lo, hi, p = paired_bootstrap_delta(a, b)
    >>> abs(delta - 0.1) < 0.001
    True
    >>> lo > 0
    True
    >>> paired_bootstrap_delta([], [])
    (0.0, 0.0, 0.0, 1.0)
    """
    if not values_a or not values_b:
        return (0.0, 0.0, 0.0, 1.0)

    n = min(len(values_a), len(values_b))
    deltas = [values_b[i] - values_a[i] for i in range(n)]
    mean_delta = sum(deltas) / len(deltas)

    if len(deltas) == 1:
        return (mean_delta, mean_delta, mean_delta, 1.0)

    rng = random.Random(42)
    boot_deltas: List[float] = []
    for _ in range(n_bootstrap):
        indices = rng.choices(range(len(deltas)), k=len(deltas))
        boot_mean = sum(deltas[i] for i in indices) / len(indices)
        boot_deltas.append(boot_mean)

    boot_deltas.sort()
    alpha = 1 - ci
    lo_idx = int(alpha / 2 * n_bootstrap)
    hi_idx = int((1 - alpha / 2) * n_bootstrap) - 1

    # Two-tailed p-value: proportion of bootstrap deltas crossing zero
    if mean_delta >= 0:
        p_one = sum(1 for d in boot_deltas if d <= 0) / n_bootstrap
    else:
        p_one = sum(1 for d in boot_deltas if d >= 0) / n_bootstrap
    p_value = min(p_one * 2, 1.0)

    return (
        round(mean_delta, 6),
        round(boot_deltas[lo_idx], 6),
        round(boot_deltas[hi_idx], 6),
        round(p_value, 6),
    )


def spearman_rank_correlation(
    x: List[float],
    y: List[float],
) -> Tuple[float, float]:
    """Spearman rank correlation coefficient and approximate p-value.

    Ranks values (handling ties via average rank), computes Pearson
    correlation on the ranks. P-value approximated via t-distribution.
    Stdlib only — no scipy/numpy.

    Args:
        x: First variable values.
        y: Second variable values (paired with x).

    Returns:
        Tuple of (rho, p_value).

    >>> x = [1.0, 2.0, 3.0, 4.0, 5.0]; y = [1.0, 2.0, 3.0, 4.0, 5.0]
    >>> rho, p = spearman_rank_correlation(x, y)
    >>> abs(rho - 1.0) < 0.001
    True
    >>> p < 0.05
    True
    >>> rho2, _ = spearman_rank_correlation([1.0, 2.0, 3.0], [3.0, 2.0, 1.0])
    >>> abs(rho2 - (-1.0)) < 0.001
    True
    >>> spearman_rank_correlation([], [])
    (0.0, 1.0)
    >>> spearman_rank_correlation([1.0], [1.0])
    (0.0, 1.0)
    """
    n = min(len(x), len(y))
    if n < 2:
        return (0.0, 1.0)

    x, y = list(x[:n]), list(y[:n])

    def _ranks(vals: List[float]) -> List[float]:
        indexed = sorted(enumerate(vals), key=lambda kv: kv[1])
        r = [0.0] * len(vals)
        i = 0
        while i < len(indexed):
            j = i
            while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[j][1]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0  # 1-indexed average rank
            for k in range(i, j + 1):
                r[indexed[k][0]] = avg_rank
            i = j + 1
        return r

    rx, ry = _ranks(x), _ranks(y)

    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    denom_x = sum((rx[i] - mx) ** 2 for i in range(n))
    denom_y = sum((ry[i] - my) ** 2 for i in range(n))
    denom = math.sqrt(denom_x * denom_y) if denom_x * denom_y > 0 else 0.0

    if denom == 0.0:
        return (0.0, 1.0)

    rho = max(-1.0, min(1.0, num / denom))

    if abs(rho) >= 1.0:
        return (round(rho, 6), 0.0)

    t = rho * math.sqrt(n - 2) / math.sqrt(1 - rho ** 2)
    p_value = 2 * (1 - _normal_cdf(abs(t)))

    return (round(rho, 6), round(p_value, 6))


def retrieval_outcome_correlation(
    ir_scores: List[float],
    rewards: List[float],
    suite_labels: List[str],
) -> dict:
    """Spearman correlation between IR retrieval quality and task reward.

    Computes overall and per-suite correlations. Effect size is mean reward
    for high-recall tasks (>= 0.8) minus mean reward for low-recall tasks
    (< 0.5).

    Args:
        ir_scores: File recall scores per task.
        rewards: Task reward scores per task (paired with ir_scores).
        suite_labels: Suite name per task (paired with ir_scores).

    Returns:
        Dict with 'overall' key and per-suite keys. Each value contains
        rho, p_value, effect_size.

    >>> ir = [0.1, 0.5, 0.8, 0.9]; r = [0.0, 0.5, 0.8, 1.0]
    >>> s = ["a", "a", "b", "b"]
    >>> res = retrieval_outcome_correlation(ir, r, s)
    >>> abs(res["overall"]["rho"] - 1.0) < 0.01
    True
    >>> retrieval_outcome_correlation([], [], [])
    {'overall': {'rho': 0.0, 'p_value': 1.0, 'effect_size': 0.0}}
    """
    if not ir_scores or not rewards:
        return {"overall": {"rho": 0.0, "p_value": 1.0, "effect_size": 0.0}}

    n = min(len(ir_scores), len(rewards), len(suite_labels))
    ir_scores = list(ir_scores[:n])
    rewards = list(rewards[:n])
    suite_labels = list(suite_labels[:n])

    rho, p = spearman_rank_correlation(ir_scores, rewards)

    high_r = [rewards[i] for i in range(n) if ir_scores[i] >= 0.8]
    low_r = [rewards[i] for i in range(n) if ir_scores[i] < 0.5]
    effect_size = (
        sum(high_r) / len(high_r) - sum(low_r) / len(low_r)
        if high_r and low_r
        else 0.0
    )

    result: dict = {
        "overall": {
            "rho": round(rho, 6),
            "p_value": round(p, 6),
            "effect_size": round(effect_size, 6),
        }
    }

    for suite in sorted(set(suite_labels)):
        idx = [i for i in range(n) if suite_labels[i] == suite]
        if len(idx) < 3:
            continue
        s_ir = [ir_scores[i] for i in idx]
        s_r = [rewards[i] for i in idx]
        s_rho, s_p = spearman_rank_correlation(s_ir, s_r)
        s_high = [s_r[j] for j, i in enumerate(idx) if ir_scores[i] >= 0.8]
        s_low = [s_r[j] for j, i in enumerate(idx) if ir_scores[i] < 0.5]
        s_effect = (
            sum(s_high) / len(s_high) - sum(s_low) / len(s_low)
            if s_high and s_low
            else 0.0
        )
        result[suite] = {
            "rho": round(s_rho, 6),
            "p_value": round(s_p, 6),
            "effect_size": round(s_effect, 6),
        }

    return result


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class MetricComparison:
    """Comparison of a single metric between baseline and treatment."""

    metric_name: str

    # Summary stats
    baseline_mean: float = 0.0
    baseline_std: float = 0.0
    baseline_n: int = 0
    treatment_mean: float = 0.0
    treatment_std: float = 0.0
    treatment_n: int = 0

    # Deltas
    absolute_diff: float = 0.0
    relative_diff_pct: float = 0.0

    # Statistical tests (populated by compute())
    t_test: Optional[dict] = None
    effect_size: Optional[dict] = None
    ci: Optional[dict] = None

    def compute(
        self,
        baseline_values: List[float],
        treatment_values: List[float],
    ) -> "MetricComparison":
        """Populate all fields from raw value lists. Returns self."""
        self.baseline_n = len(baseline_values)
        self.treatment_n = len(treatment_values)

        if baseline_values:
            self.baseline_mean = statistics.mean(baseline_values)
            self.baseline_std = (
                statistics.stdev(baseline_values) if len(baseline_values) > 1 else 0.0
            )
        if treatment_values:
            self.treatment_mean = statistics.mean(treatment_values)
            self.treatment_std = (
                statistics.stdev(treatment_values) if len(treatment_values) > 1 else 0.0
            )

        self.absolute_diff = self.treatment_mean - self.baseline_mean
        if self.baseline_mean != 0:
            self.relative_diff_pct = (self.absolute_diff / self.baseline_mean) * 100

        if self.baseline_n >= 2 and self.treatment_n >= 2:
            self.t_test = welchs_t_test(baseline_values, treatment_values)
            self.effect_size = cohens_d(baseline_values, treatment_values)

        # Bootstrap CI on the difference (when paired) or on treatment mean
        if baseline_values and treatment_values:
            min_len = min(len(baseline_values), len(treatment_values))
            diffs = [
                treatment_values[i] - baseline_values[i]
                for i in range(min_len)
            ]
            if diffs:
                self.ci = bootstrap_ci_dict(diffs)

        return self

    def to_dict(self) -> dict:
        return {
            "metric_name": self.metric_name,
            "baseline": {
                "mean": round(self.baseline_mean, 4),
                "std": round(self.baseline_std, 4),
                "n": self.baseline_n,
            },
            "treatment": {
                "mean": round(self.treatment_mean, 4),
                "std": round(self.treatment_std, 4),
                "n": self.treatment_n,
            },
            "absolute_diff": round(self.absolute_diff, 4),
            "relative_diff_pct": round(self.relative_diff_pct, 2),
            "t_test": self.t_test,
            "effect_size": self.effect_size,
            "confidence_interval": self.ci,
        }


@dataclass
class PairedComparisonReport:
    """Aggregate comparison of baseline vs treatment across multiple metrics."""

    metrics: List[MetricComparison] = field(default_factory=list)
    mcnemar: Optional[dict] = None
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "metrics": [m.to_dict() for m in self.metrics],
            "mcnemar": self.mcnemar,
            "summary": self.summary,
        }
