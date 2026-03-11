-- Engineering diary extraction seed query (message-level)
SELECT m.id, m.ts, m.session_id, m.agent, m.role, s.source_path, s.project_key, m.text
FROM messages m
JOIN sessions s ON s.session_id=m.session_id AND s.agent=m.agent
WHERE m.ts IS NOT NULL
  AND m.role IN ('user','assistant')
  AND m.text IS NOT NULL
  AND m.agent NOT LIKE 'external_%'
  AND (s.project_key LIKE '%CodeScaleBench%' OR s.project_key LIKE '%CodeContextBench%')
ORDER BY m.ts;
