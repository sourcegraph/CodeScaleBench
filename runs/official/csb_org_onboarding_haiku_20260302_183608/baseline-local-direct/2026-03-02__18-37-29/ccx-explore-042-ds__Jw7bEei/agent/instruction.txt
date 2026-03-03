# Architecture Map: Scientific Computing Data Flow

## Your Task

You are onboarding to a scientific computing team that uses the Python ML stack.
A senior engineer has asked you to produce a technical map of how data flows from
**raw array creation through scientific computation** across the three core libraries:
numpy, pandas, and scipy.

**Your question**: Map the data flow from raw array creation through scientific
computation across these repos. Your explanation must trace through all three layers:

1. **Array computation layer** — What function in `numpy/numpy` is the canonical
   entry point for array-level aggregation on raw ndarray objects?
2. **Data structure layer** — What class in `pandas-dev/pandas` wraps a NumPy ndarray
   as a pandas extension array, enabling interoperability between the two libraries?
3. **Scientific computation layer** — What function in `scipy/scipy` accepts numpy
   arrays (or pandas Series) as inputs for statistical analysis?

For each step, cite the specific repository, file path, and function/class name.

## Context

You are working with the Python ML stack in a cross-org environment:

- `scikit-learn/scikit-learn` (ML algorithms)
- `numpy/numpy` (array-computing)
- `pandas-dev/pandas` (dataframe-library)
- `scipy/scipy` (scientific-computing)

This question is specifically designed to benefit from cross-repo synthesis. The
data flow spans multiple organizations and can only be fully understood by examining
all three repos together.

## Output Format

Create a file at `/workspace/answer.json` with your findings:

```json
{
  "chain": [
    {
      "repo": "numpy/numpy",
      "path": "relative/path/to/file.py",
      "symbol": "FunctionOrClassName",
      "description": "What role this plays in the data flow"
    }
  ],
  "text": "Comprehensive narrative explaining how data flows from raw array creation through scientific computation, citing specific files and functions from each repo."
}
```

**Important**: Use the exact repo identifiers specified for this task. The oracle expects `repo` values of `numpy/numpy` (array layer), `pandas-dev/pandas` (data structure layer), and `scipy/scipy` (scientific computation layer). The `repo` field must match these exactly.
**Note**: Tool output may return repo names with a `github.com/` prefix (e.g., `github.com/sg-evals/kubernetes-client-go`). Strip this prefix in your answer — use `sg-evals/kubernetes-client-go`, NOT `github.com/sg-evals/kubernetes-client-go`.
**Provenance**: Your `text` narrative is evaluated for completeness. It must include repository names verbatim in `org/repo` format (e.g., `numpy/numpy`, `pandas-dev/pandas`, `scipy/scipy`) and file paths using slash notation (e.g., `numpy/_core/fromnumeric.py`), not Python module dot notation.

The `chain` should contain at least 3 steps representing the 3 layers described above.

## Evaluation

Your answer will be scored on:
- **Flow coverage**: Does the chain include key steps from all 3 layers (array creation → pandas integration → scipy computation)?
- **Technical accuracy**: Are the cited file paths and function/class names correct?
- **Provenance**: Does your narrative reference all three repositories with specific file paths?
- **Synthesis quality** (supplementary): Does the explanation connect the layers in a way that reveals the ecosystem architecture?
