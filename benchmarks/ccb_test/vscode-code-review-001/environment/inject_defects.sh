#!/bin/bash
# Inject defects into the VS Code codebase for code review benchmarking
# Each defect simulates a realistic bug that an AI code reviewer should catch
# 6 defects across 5 files, 3 require cross-file reasoning

set -e
cd /workspace

# ── Defect 1: Off-by-one in Range.containsPosition — > becomes >= ──
# containsPosition should be inclusive on edges (position AT endColumn is IN range).
# Changing > to >= excludes positions at the exact end column boundary.
# Breaks find-and-replace highlighting, selection containment, bracket matching, etc.
python3 -c "
path = 'src/vs/editor/common/core/range.ts'
with open(path) as f:
    content = f.read()

old = '''\t\tif (position.lineNumber === range.endLineNumber && position.column > range.endColumn) {
\t\t\treturn false;
\t\t}
\t\treturn true;
\t}'''

new = '''\t\tif (position.lineNumber === range.endLineNumber && position.column >= range.endColumn) {
\t\t\treturn false;
\t\t}
\t\treturn true;
\t}'''

content = content.replace(old, new, 1)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-1: Range.containsPosition uses >= instead of > for endColumn check')
"

# ── Defect 2: Invert matchCase flag in createRegExp ──
# Cross-file: strings.ts createRegExp is called by textModelSearch.ts SearchParams,
# richEditBrackets.ts, and search workers. Inverting the flag causes case-sensitive
# searches to be case-insensitive and vice versa.
python3 -c "
path = 'src/vs/base/common/strings.ts'
with open(path) as f:
    content = f.read()

old = '''\tif (!options.matchCase) {
\t\tmodifiers += 'i';
\t}'''

new = '''\tif (options.matchCase) {
\t\tmodifiers += 'i';
\t}'''

content = content.replace(old, new, 1)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-2: createRegExp matchCase flag inverted — case-sensitive searches become case-insensitive')
"

# ── Defect 3: Remove CharCode.W check from isMultilineRegexSource ──
# Regex patterns containing \W should be treated as multiline (since \W matches \n).
# Removing this check causes \W patterns to be searched line-by-line, producing
# incorrect results when the pattern should match across line boundaries.
python3 -c "
path = 'src/vs/editor/common/model/textModelSearch.ts'
with open(path) as f:
    content = f.read()

old = '''\t\t\tif (nextChCode === CharCode.n || nextChCode === CharCode.r || nextChCode === CharCode.W) {
\t\t\t\treturn true;
\t\t\t}'''

new = '''\t\t\tif (nextChCode === CharCode.n || nextChCode === CharCode.r) {
\t\t\t\treturn true;
\t\t\t}'''

content = content.replace(old, new, 1)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-3: removed CharCode.W from multiline regex detection')
"

# ── Defect 4: Invert sort order in _compareByScoreAndTime ──
# Cross-file: languageFeatureRegistry.ts sorts providers by score from
# languageSelector.ts. Inverting the comparison means lowest-scoring providers
# (wildcard '*' = 5) are preferred over exact language matches (= 10).
# This breaks completion, hover, diagnostics, and all language features.
python3 -c "
path = 'src/vs/editor/common/languageFeatureRegistry.ts'
with open(path) as f:
    content = f.read()

old = '''\t\tif (a._score < b._score) {
\t\t\treturn 1;
\t\t} else if (a._score > b._score) {
\t\t\treturn -1;
\t\t}'''

new = '''\t\tif (a._score < b._score) {
\t\t\treturn -1;
\t\t} else if (a._score > b._score) {
\t\t\treturn 1;
\t\t}'''

content = content.replace(old, new, 1)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-4: _compareByScoreAndTime sort order inverted — lowest score first')
"

# ── Defect 5: Off-by-one in Position.isBefore — < becomes <= ──
# isBefore should return false when positions are equal (documented contract).
# Changing < to <= makes isBefore return true for equal positions, violating
# the contract. This breaks cursor movement, selection direction, undo/redo,
# and any code distinguishing isBefore from isBeforeOrEqual.
python3 -c "
path = 'src/vs/editor/common/core/position.ts'
with open(path) as f:
    content = f.read()

old = '''\t\tif (b.lineNumber < a.lineNumber) {
\t\t\treturn false;
\t\t}
\t\treturn a.column < b.column;
\t}'''

new = '''\t\tif (b.lineNumber < a.lineNumber) {
\t\t\treturn false;
\t\t}
\t\treturn a.column <= b.column;
\t}'''

content = content.replace(old, new, 1)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-5: Position.isBefore uses <= instead of < — returns true for equal positions')
"

# ── Defect 6: Change && to || in isValidMatch ──
# Cross-file: isValidMatch requires BOTH left AND right word boundaries for
# whole-word matching. Changing to OR means a match with a boundary on only one
# side passes validation. "test" would match "testing" (left boundary only).
# The word separators come from WordCharacterClassifier in wordCharacterClassifier.ts.
python3 -c "
path = 'src/vs/editor/common/model/textModelSearch.ts'
with open(path) as f:
    content = f.read()

old = '''\treturn (
\t\tleftIsWordBounday(wordSeparators, text, textLength, matchStartIndex, matchLength)
\t\t&& rightIsWordBounday(wordSeparators, text, textLength, matchStartIndex, matchLength)
\t);'''

new = '''\treturn (
\t\tleftIsWordBounday(wordSeparators, text, textLength, matchStartIndex, matchLength)
\t\t|| rightIsWordBounday(wordSeparators, text, textLength, matchStartIndex, matchLength)
\t);'''

content = content.replace(old, new, 1)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-6: isValidMatch uses OR instead of AND — partial word boundary matches accepted')
"

echo "All 6 defects injected successfully"
