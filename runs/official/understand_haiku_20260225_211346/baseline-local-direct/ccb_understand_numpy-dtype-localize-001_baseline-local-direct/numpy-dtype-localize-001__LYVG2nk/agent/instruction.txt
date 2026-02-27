Find the NumPy dtype compatibility issue when pandas nullable integers flow into scikit-learn preprocessing

When a pandas DataFrame with nullable integer types (e.g., pd.Int64Dtype) is passed to scikit-learn's StandardScaler or MinMaxScaler, the conversion to NumPy arrays can fail or produce unexpected results. Trace the data flow:

1. Find where scikit-learn preprocessing functions accept input data (in sklearn/preprocessing/_data.py)
2. Trace how input validation works (sklearn/utils/validation.py)
3. Identify where pandas nullable integer types are converted to NumPy arrays (pandas/core/arrays/masked.py)
4. Find the NumPy dtype handling that causes the incompatibility (numpy/_core/_methods.py)

Your analysis must span the numpy, pandas, and scikit-learn source trees under /ccb_crossrepo/src/.
Write your findings to BUG_ANALYSIS.md in the workspace, including the exact file and line range of the root cause.
