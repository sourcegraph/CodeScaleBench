#!/usr/bin/env python3
"""
Evaluate agent-generated documentation against ground truth.

This script uses an LLM judge to compare agent-generated documentation
against ground truth documentation from the Kubernetes project.

Evaluation Signals:
  Signal 1 (LLM Judge): Senior Kubernetes documentation reviewer scoring
    - Technical Accuracy (0-100, weight 0.30)
    - Completeness (0-100, weight 0.25)
    - Style Conformance (0-100, weight 0.20)
    - Ground Truth Alignment (0-100, weight 0.25)

  Signal 2 (Jaccard Similarity): Token-level mechanical similarity metric

Usage:
    python evaluate_docs.py --generated ./agent_output.md --ground-truth ./ground_truth.md \
        --model anthropic/claude-sonnet-4-20250514 --output ./evaluation.json

    python evaluate_docs.py --generated ./agent_output.md --ground-truth ./ground_truth.md \
        --task-instructions ./instruction.md --output ./evaluation.json

Options:
    --generated         Path to agent-generated documentation
    --ground-truth      Path to ground truth documentation
    --task-instructions Path to task instruction.md (passed to judge for context)
    --model             LLM model for evaluation (default: anthropic/claude-sonnet-4-20250514)
    --output            Output path for evaluation results
    --verbose           Show detailed evaluation reasoning
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Any, Optional


# LLM Judge prompt template
JUDGE_PROMPT_TEMPLATE = """You are a senior Kubernetes documentation reviewer evaluating agent-generated \
documentation against ground truth from the official Kubernetes repository.

## Task Instructions
{task_instructions}

## Ground Truth Documentation (Official Reference)
```
{ground_truth}
```

## Agent-Generated Documentation (To Be Evaluated)
```
{generated}
```

## Evaluation Criteria

Evaluate the generated documentation on these criteria. For each, provide:
1. A score from 0-100
2. Specific reasoning with examples

### 1. Technical Accuracy (0-100)
- Are the technical details correct (APIs, data structures, behaviors)?
- Are there factual errors or misleading statements?
- Are package/path references valid and correctly described?

### 2. Completeness (0-100)
- Are all major concepts from the ground truth covered?
- Are important edge cases and limitations mentioned?
- Is the scope appropriate (not missing key information)?

### 3. Style Conformance (0-100)
- Does it follow Go documentation conventions (// Package, copyright header, doc.go format)?
- Does it follow Kubernetes documentation style (concise, precise, references sub-packages)?
- Is it well-organized with appropriate section structure?

### 4. Ground Truth Alignment (0-100)
- How well does the generated content align with the ground truth?
- Are the same key points emphasized?
- Does it capture the essence and structure of the original documentation?

## Output Format

Respond with a JSON object in this exact format:
```json
{{
  "technical_accuracy": {{
    "score": <0-100>,
    "reasoning": "<specific examples and explanation>"
  }},
  "completeness": {{
    "score": <0-100>,
    "reasoning": "<specific examples and explanation>"
  }},
  "style_conformance": {{
    "score": <0-100>,
    "reasoning": "<specific examples and explanation>"
  }},
  "ground_truth_alignment": {{
    "score": <0-100>,
    "reasoning": "<specific examples and explanation>"
  }},
  "overall_score": <weighted average>,
  "key_strengths": ["<strength 1>", "<strength 2>"],
  "key_weaknesses": ["<weakness 1>", "<weakness 2>"],
  "summary": "<one paragraph summary of the evaluation>"
}}
```

Provide ONLY the JSON object, no additional text.
"""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Evaluate agent-generated documentation against ground truth"
    )
    parser.add_argument(
        "--generated", required=True, help="Path to agent-generated documentation"
    )
    parser.add_argument(
        "--ground-truth", required=True, help="Path to ground truth documentation"
    )
    parser.add_argument(
        "--task-instructions",
        help="Path to task instruction.md file (provides full task context to judge)",
    )
    parser.add_argument("--task-context", help="Additional context about the task")
    parser.add_argument(
        "--model",
        default="anthropic/claude-sonnet-4-20250514",
        help="LLM model for evaluation",
    )
    parser.add_argument("--output", help="Output path for evaluation results (JSON)")
    parser.add_argument(
        "--verbose", action="store_true", help="Show detailed evaluation reasoning"
    )
    parser.add_argument(
        "--api-key", help="API key for LLM provider (or set ANTHROPIC_API_KEY)"
    )
    return parser.parse_args()


def load_document(file_path: Path) -> str:
    """Load a document from file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def compute_jaccard_similarity(text_a: str, text_b: str) -> float:
    """
    Compute token-level Jaccard similarity between two texts.

    Uses word-level tokenization (lowercased, alphanumeric tokens).
    Returns a value between 0.0 and 1.0.
    """
    def tokenize(text: str) -> set:
        # Extract alphanumeric tokens, lowercased
        return set(re.findall(r'[a-z0-9]+', text.lower()))

    tokens_a = tokenize(text_a)
    tokens_b = tokenize(text_b)

    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b

    return len(intersection) / len(union)


def call_llm_judge(
    prompt: str, model: str, api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Call the LLM to evaluate documentation."""
    try:
        import anthropic
    except ImportError:
        print("Error: anthropic package not installed. Run: pip install anthropic")
        sys.exit(1)

    # Get API key
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=key)

    # Extract model name (handle provider prefix)
    model_name = model.split("/")[-1] if "/" in model else model

    # Map to Anthropic model names
    model_mapping = {
        "claude-haiku-4-5-20251001": "claude-3-5-haiku-20241022",
        "claude-sonnet-4-20250514": "claude-sonnet-4-20250514",
        "claude-3-opus-20240229": "claude-3-opus-20240229",
    }
    model_name = model_mapping.get(model_name, model_name)

    response = client.messages.create(
        model=model_name,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    # Extract JSON from response
    response_text = response.content[0].text

    # Try to parse as JSON
    try:
        # Handle markdown code blocks
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()

        return json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f"Warning: Could not parse LLM response as JSON: {e}")
        print(f"Raw response: {response_text[:500]}...")
        return {"error": "Failed to parse evaluation", "raw_response": response_text}


def calculate_weighted_score(evaluation: Dict[str, Any]) -> float:
    """Calculate weighted overall score."""
    weights = {
        "technical_accuracy": 0.30,
        "completeness": 0.25,
        "style_conformance": 0.20,
        "ground_truth_alignment": 0.25,
    }

    total = 0.0
    for criterion, weight in weights.items():
        if criterion in evaluation and isinstance(evaluation[criterion], dict):
            score = evaluation[criterion].get("score", 0)
            total += score * weight

    return round(total, 2)


def format_report(evaluation: Dict[str, Any], jaccard: float, verbose: bool = False) -> str:
    """Format evaluation results as a readable report."""
    lines = ["=" * 60, "DOCUMENTATION EVALUATION REPORT", "=" * 60, ""]

    # Overall score
    overall = evaluation.get("overall_score", calculate_weighted_score(evaluation))
    lines.append(f"Overall Score: {overall}/100")
    lines.append(f"Jaccard Similarity: {jaccard:.4f}")
    lines.append("")

    # Individual scores
    criteria = [
        ("technical_accuracy", "Technical Accuracy", 0.30),
        ("completeness", "Completeness", 0.25),
        ("style_conformance", "Style Conformance", 0.20),
        ("ground_truth_alignment", "Ground Truth Alignment", 0.25),
    ]

    for key, label, weight in criteria:
        if key in evaluation and isinstance(evaluation[key], dict):
            score = evaluation[key].get("score", "N/A")
            lines.append(f"{label} (weight {weight}): {score}/100")
            if verbose:
                reasoning = evaluation[key].get("reasoning", "")
                if reasoning:
                    lines.append(f"  Reasoning: {reasoning[:200]}...")

    lines.append("")

    # Strengths and weaknesses
    if "key_strengths" in evaluation:
        lines.append("Key Strengths:")
        for strength in evaluation["key_strengths"]:
            lines.append(f"  + {strength}")
        lines.append("")

    if "key_weaknesses" in evaluation:
        lines.append("Key Weaknesses:")
        for weakness in evaluation["key_weaknesses"]:
            lines.append(f"  - {weakness}")
        lines.append("")

    # Summary
    if "summary" in evaluation:
        lines.append("Summary:")
        lines.append(evaluation["summary"])

    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


def main():
    args = parse_args()

    # Load documents
    generated_path = Path(args.generated).resolve()
    ground_truth_path = Path(args.ground_truth).resolve()

    if not generated_path.exists():
        print(f"Error: Generated documentation not found: {generated_path}")
        return 1

    if not ground_truth_path.exists():
        print(f"Error: Ground truth documentation not found: {ground_truth_path}")
        return 1

    generated_doc = load_document(generated_path)
    ground_truth_doc = load_document(ground_truth_path)

    print(f"Generated doc: {len(generated_doc)} characters")
    print(f"Ground truth: {len(ground_truth_doc)} characters")
    print()

    # Compute Jaccard similarity (Signal 2)
    jaccard = compute_jaccard_similarity(generated_doc, ground_truth_doc)
    print(f"Jaccard similarity: {jaccard:.4f}")
    print()

    # Prepare task instructions
    task_instructions = ""
    if args.task_instructions:
        instructions_path = Path(args.task_instructions).resolve()
        if instructions_path.exists():
            task_instructions = load_document(instructions_path)
            print(f"Task instructions: {len(task_instructions)} characters")
        else:
            print(f"Warning: Task instructions not found: {instructions_path}")

    if not task_instructions:
        task_instructions = args.task_context or "Evaluate Kubernetes documentation quality"

    # No truncation — claude-sonnet-4 has 200k context.
    # Largest ground truth is ~6.7k chars, generated docs ~15-20k. Well within limits.

    # Build prompt
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        ground_truth=ground_truth_doc,
        generated=generated_doc,
        task_instructions=task_instructions,
    )

    print(f"Calling LLM judge ({args.model})...")
    print()

    # Call LLM judge (Signal 1)
    evaluation = call_llm_judge(prompt, args.model, args.api_key)

    # Ensure overall score is calculated
    if "overall_score" not in evaluation:
        evaluation["overall_score"] = calculate_weighted_score(evaluation)

    # Print report
    report = format_report(evaluation, jaccard, args.verbose)
    print(report)

    # Save results
    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "generated_file": str(generated_path),
                    "ground_truth_file": str(ground_truth_path),
                    "task_instructions_file": args.task_instructions or None,
                    "model": args.model,
                    "jaccard_similarity": jaccard,
                    "evaluation": evaluation,
                },
                f,
                indent=2,
            )

        print(f"\nEvaluation saved to: {output_path}")

    # Return exit code based on score
    overall = evaluation.get("overall_score", 0)
    if isinstance(overall, (int, float)):
        return 0 if overall >= 50 else 1
    return 0


if __name__ == "__main__":
    exit(main())
