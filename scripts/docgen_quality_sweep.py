#!/usr/bin/env python3
"""Run a quality-variation sweep across all ccb_docgen tasks."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCGEN_DIR = ROOT / "benchmarks" / "ccb_docgen"


def check_any(patterns: list[str], text: str) -> bool:
    for p in patterns:
        try:
            if re.search(p, text, re.IGNORECASE | re.DOTALL):
                return True
        except re.error:
            if p.lower() in text.lower():
                return True
    return False


def check_all(patterns: list[str], text: str) -> bool:
    for p in patterns:
        try:
            if not re.search(p, text, re.IGNORECASE | re.DOTALL):
                return False
        except re.error:
            if p.lower() not in text.lower():
                return False
    return True


def witness_for_pattern(pattern: str) -> str:
    candidates: list[str] = []
    p = re.sub(r"\(\?[imsux-]*\)", "", pattern)
    p = p.replace("^", " ").replace("$", " ")
    candidates.append(p)
    candidates.append(p.replace("\\", ""))

    cleaned = p
    cleaned = re.sub(r"\[(.)[^]]*\]", r"\1", cleaned)
    cleaned = cleaned.replace(".*", " ")
    cleaned = cleaned.replace(".+", " ")
    cleaned = cleaned.replace("\\.", ".")
    cleaned = cleaned.replace("|", " ")
    cleaned = re.sub(r"[?*+(){}]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    candidates.append(cleaned)

    for c in candidates:
        if not c:
            continue
        try:
            if re.search(pattern, c, re.IGNORECASE | re.DOTALL):
                return c
        except re.error:
            if pattern.lower() in c.lower():
                return c

    return "documented behavior"


def text_for_any(patterns: list[str]) -> str:
    candidates: list[str] = []
    for p in patterns:
        w = witness_for_pattern(p)
        candidates.extend(
            [
                p,
                w,
                f"{w} example",
                f"#{w}",
                f"## {w}",
            ]
        )
    for c in candidates:
        if check_any(patterns, c):
            return c
    return " ".join(witness_for_pattern(p) for p in patterns)


def text_for_all(patterns: list[str]) -> str:
    parts: list[str] = []
    for p in patterns:
        cands = [p, witness_for_pattern(p), f"{witness_for_pattern(p)} detail"]
        chosen = None
        for c in cands:
            if check_any([p], c):
                chosen = c
                break
        parts.append(chosen or witness_for_pattern(p))
    return "\n".join(parts)


@dataclass
class Item:
    category: str
    weight: float
    mode: str  # any, all, path
    values: list[str]
    name: str


@dataclass
class Spec:
    task_id: str
    category_weights: dict[str, float]
    categories: dict[str, list[Item]]
    hallucination_penalty: bool

    def score(self, text: str) -> float:
        category_scores: dict[str, float] = {}
        for cat, items in self.categories.items():
            total = sum(i.weight for i in items)
            hit = 0.0
            for item in items:
                ok = False
                if item.mode == "any":
                    ok = check_any(item.values, text)
                elif item.mode == "all":
                    ok = check_all(item.values, text)
                elif item.mode == "path":
                    ok = item.values[0].lower() in text.lower()
                if ok:
                    hit += item.weight
            category_scores[cat] = (hit / total) if total > 0 else 0.0

        base = 0.0
        for cat, w in self.category_weights.items():
            base += category_scores.get(cat, 0.0) * w

        if not self.hallucination_penalty:
            return max(0.0, min(1.0, base))

        # Mirror k8s verifier behavior: penalize invalid *.go paths.
        path_candidates = set(re.findall(r"(?:staging/src|pkg|cmd|api)/[A-Za-z0-9_./-]+\.go", text))
        invalid = 0
        for p in path_candidates:
            if not (ROOT / p).exists():
                invalid += 1
        penalty = 0.0
        if path_candidates:
            invalid_ratio = invalid / len(path_candidates)
            penalty += min(0.35, invalid_ratio * 0.5)

        return max(0.0, min(1.0, base - penalty))


def parse_task(task_dir: Path) -> Spec:
    task_id = task_dir.name
    gt = json.loads((task_dir / "tests" / "ground_truth.json").read_text())

    # Architecture / k8s format
    if "weights" in gt and "required_topics" in gt:
        category_weights = {
            "required_topics": float(gt["weights"]["required_topics"]),
            "file_references": float(gt["weights"]["file_references"]),
            "data_flow": float(gt["weights"]["data_flow"]),
            "extension_points": float(gt["weights"]["extension_points"]),
        }
        categories: dict[str, list[Item]] = {k: [] for k in category_weights}

        for raw in gt["required_topics"]:
            categories["required_topics"].append(
                Item("required_topics", float(raw["weight"]), "any", raw["patterns"], raw.get("id", "topic"))
            )
        for raw in gt["file_references"]:
            categories["file_references"].append(
                Item("file_references", float(raw["weight"]), "any", raw["patterns"], raw.get("id", "ref"))
            )
        for raw in gt["data_flow"]:
            mode = "all" if raw.get("ordered") else "all"
            categories["data_flow"].append(
                Item("data_flow", float(raw["weight"]), mode, raw["patterns"], raw.get("id", "flow"))
            )
        for raw in gt["extension_points"]:
            categories["extension_points"].append(
                Item("extension_points", float(raw["weight"]), "any", raw["patterns"], raw.get("id", "ext"))
            )

        return Spec(
            task_id=task_id,
            category_weights=category_weights,
            categories=categories,
            hallucination_penalty=task_id.startswith("docgen-k8s-"),
        )

    sc = gt["scoring_categories"]

    # Architecture-category format (docgen-arch-003)
    if "required_topics" in sc and "topics" in sc["required_topics"]:
        category_weights = {
            "required_topics": float(sc["required_topics"]["weight"]),
            "file_references": float(sc["file_references"]["weight"]),
            "data_flow": float(sc["data_flow"]["weight"]),
            "extension_points": float(sc["extension_points"]["weight"]),
        }
        categories: dict[str, list[Item]] = {k: [] for k in category_weights}

        for raw in sc["required_topics"]["topics"]:
            categories["required_topics"].append(
                Item("required_topics", float(raw["weight"]), "any", raw["check_any_pattern"], raw["name"])
            )
        for raw in sc["file_references"]["files"]:
            categories["file_references"].append(
                Item("file_references", float(raw["weight"]), "path", [raw["path"]], raw["path"])
            )
        for raw in sc["data_flow"]["flows"]:
            categories["data_flow"].append(
                Item("data_flow", float(raw["weight"]), "all", raw["check_all_patterns"], raw["name"])
            )
        for raw in sc["extension_points"]["points"]:
            categories["extension_points"].append(
                Item("extension_points", float(raw["weight"]), "any", raw["check_any_pattern"], raw["name"])
            )
        return Spec(task_id=task_id, category_weights=category_weights, categories=categories, hallucination_penalty=False)

    # Generic category/items format (api + migration)
    category_weights = {k: float(v["weight"]) for k, v in sc.items()}
    categories = {}
    for cat, data in sc.items():
        categories[cat] = [
            Item(cat, float(it["weight"]), "any", it["patterns"], it.get("name", f"{cat}_item"))
            for it in data["items"]
        ]
    return Spec(task_id=task_id, category_weights=category_weights, categories=categories, hallucination_penalty=False)


def build_variant(spec: Spec, keep_ratio: float, add_hallucination: bool, irrelevant: bool = False) -> str:
    if irrelevant:
        filler = (
            "This document discusses astronomy, music theory, ocean currents, and city planning. "
            "It intentionally avoids software implementation details, code paths, and API semantics. "
        )
        return (filler * 20).strip()

    chunks: list[str] = [f"# Generated Documentation for {spec.task_id}", ""]
    for cat, items in spec.categories.items():
        chunks.append(f"## {cat.replace('_', ' ').title()}")
        keep_n = max(1, int(round(len(items) * keep_ratio)))
        for item in items[:keep_n]:
            if item.mode == "path":
                text = item.values[0]
            elif item.mode == "all":
                text = text_for_all(item.values)
            else:
                text = text_for_any(item.values) if item.values else item.name
            chunks.append(f"- {item.name}: {text}")
        chunks.append("")

    doc = "\n".join(chunks)
    if add_hallucination:
        doc += "\n\n## Additional Notes\n- Refer to pkg/imaginary/notreal_controller.go for core algorithm details.\n"

    # Keep above minimum length for verifiers with short-doc guard.
    if len(doc) < 900:
        doc += "\n" + ("Context detail sentence. " * 80)
    return doc


def sweep_task(spec: Spec) -> dict[str, float]:
    variants = {
        "canonical": build_variant(spec, keep_ratio=1.0, add_hallucination=False),
        "high": build_variant(spec, keep_ratio=0.8, add_hallucination=False),
        "medium": build_variant(spec, keep_ratio=0.55, add_hallucination=False),
        "low": build_variant(spec, keep_ratio=0.3, add_hallucination=False),
        "irrelevant": build_variant(spec, keep_ratio=0.0, add_hallucination=False, irrelevant=True),
        "high_hallucination": build_variant(spec, keep_ratio=0.8, add_hallucination=True),
    }
    return {name: round(spec.score(text), 4) for name, text in variants.items()}


def summarize(results: dict[str, dict[str, float]]) -> dict[str, int]:
    monotonic_ok = 0
    canonical_one = 0
    hallu_penalized = 0
    k8s_count = 0
    for task, r in results.items():
        if abs(r["canonical"] - 1.0) < 1e-9:
            canonical_one += 1
        if r["high"] >= r["medium"] >= r["low"] >= r["irrelevant"]:
            monotonic_ok += 1
        if task.startswith("docgen-k8s-"):
            k8s_count += 1
            if r["high_hallucination"] < r["high"]:
                hallu_penalized += 1
    return {
        "tasks_total": len(results),
        "canonical_1_0": canonical_one,
        "monotonic_pass": monotonic_ok,
        "k8s_tasks": k8s_count,
        "k8s_hallucination_penalized": hallu_penalized,
    }


def render_markdown(results: dict[str, dict[str, float]], summary: dict[str, int]) -> str:
    lines = [
        "# DocGen Quality Variation Sweep",
        "",
        f"- Tasks: {summary['tasks_total']}",
        f"- Canonical scored 1.0: {summary['canonical_1_0']}/{summary['tasks_total']}",
        f"- Monotonic quality ordering (high>=medium>=low>=irrelevant): {summary['monotonic_pass']}/{summary['tasks_total']}",
        f"- K8s hallucination penalty triggered: {summary['k8s_hallucination_penalized']}/{summary['k8s_tasks']}",
        "",
        "| Task | Canonical | High | Medium | Low | Irrelevant | High+Hallucination |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for task in sorted(results):
        r = results[task]
        lines.append(
            f"| {task} | {r['canonical']:.2f} | {r['high']:.2f} | {r['medium']:.2f} | "
            f"{r['low']:.2f} | {r['irrelevant']:.2f} | {r['high_hallucination']:.2f} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run quality variation sweep on ccb_docgen tasks.")
    parser.add_argument("--bench-dir", type=Path, default=DOCGEN_DIR, help="DocGen benchmark directory.")
    parser.add_argument("--json-out", type=Path, default=ROOT / "reports" / "docgen_quality_sweep.json")
    parser.add_argument("--md-out", type=Path, default=ROOT / "reports" / "docgen_quality_sweep.md")
    args = parser.parse_args()

    task_dirs = sorted([p for p in args.bench_dir.iterdir() if (p / "tests" / "ground_truth.json").exists()])
    results: dict[str, dict[str, float]] = {}
    for task_dir in task_dirs:
        spec = parse_task(task_dir)
        results[spec.task_id] = sweep_task(spec)

    summary = summarize(results)
    md = render_markdown(results, summary)

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps({"summary": summary, "results": results}, indent=2) + "\n")
    args.md_out.write_text(md + "\n")

    print(md)


if __name__ == "__main__":
    main()
