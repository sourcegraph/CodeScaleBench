# Fix: SWE-Bench-Verified__python__maintenance__bugfix__186c0af4

**Repository:** sympy/sympy
**Language:** python
**Category:** contextbench_cross_validation

## Description

Complement doesn't work when input is a mixture of Symbols and numbers
```
>>> a=FiniteSet(x,y,2)
>>> b=Interval(-10,10)
>>> Complement(a,b)
{x, y}
```
`{x, y} \ [-10,10]` is expected as output.


## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes
