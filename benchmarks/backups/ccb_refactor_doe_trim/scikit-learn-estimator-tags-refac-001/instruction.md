# Task: Rename _get_tags to _estimator_tags

## Objective
Rename `_get_tags` method to `_estimator_tags` across the scikit-learn estimator hierarchy
to better describe the method's purpose and avoid confusion with generic getter patterns.

## Requirements

1. **Rename in base estimator** `sklearn/base.py`:
   - `def _get_tags(self)` → `def _estimator_tags(self)`

2. **Update ALL overrides** across estimator hierarchy (50+ references):
   - `sklearn/linear_model/` — LinearRegression, LogisticRegression, etc.
   - `sklearn/tree/` — DecisionTreeClassifier, etc.
   - `sklearn/ensemble/` — RandomForestClassifier, etc.
   - `sklearn/svm/` — SVC, SVR, etc.
   - `sklearn/utils/estimator_checks.py` — tag checking utilities
   - Test files

3. **Update tag checking utilities** that call `_get_tags()`

## Key Reference Files
- `sklearn/base.py` — BaseEstimator._get_tags()
- `sklearn/utils/estimator_checks.py` — uses _get_tags extensively
- `sklearn/utils/_tags.py` — tag-related utilities

## Success Criteria
- `_get_tags` no longer used as method name in BaseEstimator
- `_estimator_tags` used instead
- 80%+ of 50+ overrides and call sites updated
