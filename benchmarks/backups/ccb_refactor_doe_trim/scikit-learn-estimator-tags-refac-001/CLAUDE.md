# scikit-learn-estimator-tags-refac-001: Rename _get_tags

## Task Type: Cross-File Refactoring (Rename)

Rename _get_tags → _estimator_tags across scikit-learn.

## Key Reference Files
- `sklearn/base.py` — BaseEstimator definition
- `sklearn/utils/estimator_checks.py` — tag checking
- `sklearn/utils/_tags.py` — tag utilities

## Search Strategy
- Search for `_get_tags` across sklearn/ for all references
- Search for `def _get_tags` for overrides
