# Fix: SWE-Bench-Verified__python__maintenance__bugfix__31d4fe9d

**Repository:** django/django
**Language:** python
**Category:** contextbench_cross_validation

## Description

urlize() does not handle html escaped string and trailing punctuation correctly
Description
	
Example:
urlize('Search for google.com/?q=1&lt! and see.')
# expected output
'Search for <a href="http://google.com/?q=1%3C">google.com/?q=1&lt</a>! and see.'
# actual output
'Search for <a href="http://google.com/?q=1%3C">google.com/?q=1&lt</a>lt! and see.'


## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes
