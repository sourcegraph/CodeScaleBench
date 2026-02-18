#!/bin/bash
# Inject defects into the Ghost codebase for code review benchmarking
# Each defect simulates a realistic bug that an AI code reviewer should catch

set -e
cd /workspace

# ── Defect 1: Remove NotFoundError guard from getCommentLikes ──
# This causes the service to proceed with a null comment, producing
# incorrect results instead of a proper 404 error
python3 -c "
import re
path = 'ghost/core/core/server/services/comments/comments-service.js'
with open(path) as f:
    content = f.read()
# Remove the if (!comment) { throw ... } block after findOne in getCommentLikes
pattern = r'(const comment = await this\.models\.Comment\.findOne\(\{id: commentId\}\);)\s*\n\s*if \(!comment\) \{\s*\n\s*throw new errors\.NotFoundError\(\{\s*\n\s*message: tpl\(messages\.commentNotFound\)\s*\n\s*\}\);\s*\n\s*\}'
replacement = r'\1'
content = re.sub(pattern, replacement, content)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-1: removed NotFoundError guard from getCommentLikes')
"

# ── Defect 2: Change frame.options.id to frame.data.id in controller ──
# This causes commentId to be undefined, breaking the likes query
python3 -c "
path = 'ghost/core/core/server/services/comments/comments-controller.js'
with open(path) as f:
    content = f.read()
# Only replace in the getCommentLikes method context
old = 'const commentId = frame.options.id;'
# Find within getCommentLikes method
idx = content.find('async getCommentLikes(frame)')
if idx >= 0:
    after = content[idx:]
    after = after.replace(old, 'const commentId = frame.data.id;', 1)
    content = content[:idx] + after
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-2: changed frame.options.id to frame.data.id')
"

# ── Defect 3: Remove cacheInvalidate: false from browse headers ──
# GET endpoint will invalidate cache on every request (performance violation)
python3 -c "
path = 'ghost/core/core/server/api/endpoints/comment-likes.js'
with open(path) as f:
    content = f.read()
# Remove the headers block with cacheInvalidate: false
import re
pattern = r'\s*headers:\s*\{\s*\n\s*cacheInvalidate:\s*false\s*\n\s*\},?\s*\n'
content = re.sub(pattern, '\n', content)
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-3: removed cacheInvalidate: false header')
"

# ── Defect 4: Change withRelated from ['member'] to [] ──
# API response won't include member data, breaking the frontend likes display
python3 -c "
path = 'ghost/core/core/server/services/comments/comments-service.js'
with open(path) as f:
    content = f.read()
# Only replace within getCommentLikes context
idx = content.find('async getCommentLikes(')
if idx >= 0:
    after = content[idx:]
    after = after.replace(\"withRelated: ['member']\", 'withRelated: []', 1)
    content = content[:idx] + after
with open(path, 'w') as f:
    f.write(content)
print('INJECTED defect-4: changed withRelated from [member] to []')
"

echo "All 4 defects injected successfully"
