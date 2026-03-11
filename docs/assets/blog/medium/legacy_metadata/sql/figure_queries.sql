-- Blog asset extraction queries for unified conversation DB
-- Generated: 2026-03-05T14:10:02.877208+00:00

-- fig01_activity_timeline
WITH msg_daily AS (
  SELECT substr(ts,1,10) AS day, agent, COUNT(*) AS messages
  FROM messages
  WHERE ts IS NOT NULL
  GROUP BY 1,2
),
sess_daily AS (
  SELECT substr(COALESCE(last_at, started_at),1,10) AS day, agent, COUNT(*) AS sessions
  FROM sessions
  WHERE COALESCE(last_at, started_at) IS NOT NULL
  GROUP BY 1,2
),
combined AS (
  SELECT day, agent, messages, 0 AS sessions FROM msg_daily
  UNION ALL
  SELECT day, agent, 0 AS messages, sessions FROM sess_daily
)
SELECT day, agent, SUM(messages) AS messages, SUM(sessions) AS sessions
FROM combined
GROUP BY day, agent
ORDER BY day, agent;

-- fig02_agent_mix
SELECT substr(ts,1,7) AS ym, agent, COUNT(*) AS messages
FROM messages
WHERE ts IS NOT NULL
GROUP BY 1,2
ORDER BY 1,2;

-- fig03_tool_intensity
SELECT agent, session_id, msg_count, tool_calls, error_count,
       ROUND(CAST(tool_calls AS REAL)/NULLIF(msg_count,0),4) AS tools_per_msg,
       started_at, last_at
FROM sessions
ORDER BY tool_calls DESC;

-- fig04_error_retry_pressure
WITH retry_hits AS (
  SELECT m.session_id, m.agent, COUNT(*) AS retry_mentions
  FROM messages m
  WHERE m.text IS NOT NULL
    AND (
      LOWER(m.text) LIKE '%retry%'
      OR LOWER(m.text) LIKE '%retried%'
      OR LOWER(m.text) LIKE '%backoff%'
      OR LOWER(m.text) LIKE '%timeout%'
      OR m.text LIKE '%429%'
    )
  GROUP BY 1,2
)
SELECT s.agent, s.session_id, s.error_count, s.tool_calls, s.msg_count,
       COALESCE(r.retry_mentions,0) AS retry_mentions, s.started_at, s.last_at
FROM sessions s
LEFT JOIN retry_hits r ON r.session_id=s.session_id AND r.agent=s.agent
ORDER BY s.error_count DESC, retry_mentions DESC;

-- fig05_incident_heatmap
WITH tagged AS (
  SELECT substr(m.ts,1,10) AS day, m.agent, 'infra' AS theme
  FROM messages m
  WHERE m.ts IS NOT NULL
    AND m.text IS NOT NULL
    AND (
      LOWER(m.text) LIKE '%daytona%'
      OR LOWER(m.text) LIKE '%docker%'
      OR LOWER(m.text) LIKE '%registry%'
      OR LOWER(m.text) LIKE '%network%'
      OR LOWER(m.text) LIKE '%ssh%'
    )
  UNION ALL
  SELECT substr(m.ts,1,10) AS day, m.agent, 'benchmark_ops' AS theme
  FROM messages m
  WHERE m.ts IS NOT NULL
    AND m.text IS NOT NULL
    AND (
      LOWER(m.text) LIKE '%oracle%'
      OR LOWER(m.text) LIKE '%verifier%'
      OR LOWER(m.text) LIKE '%artifact%'
      OR LOWER(m.text) LIKE '%harbor%'
    )
  UNION ALL
  SELECT substr(m.ts,1,10) AS day, m.agent, 'agent_design' AS theme
  FROM messages m
  WHERE m.ts IS NOT NULL
    AND m.text IS NOT NULL
    AND (
      LOWER(m.text) LIKE '%mcp%'
      OR LOWER(m.text) LIKE '%retrieval%'
      OR LOWER(m.text) LIKE '%context%'
    )
)
SELECT day, agent, theme, COUNT(*) AS hits
FROM tagged
GROUP BY 1,2,3
ORDER BY 1,2,3;

-- fig06_dedupe_impact
SELECT id, started_at, completed_at,
       session_count, message_count,
       json_extract(notes,'$.dedupe.input_rows')   AS dedupe_input_rows,
       json_extract(notes,'$.dedupe.kept_rows')    AS dedupe_kept_rows,
       json_extract(notes,'$.dedupe.dropped_rows') AS dedupe_dropped_rows
FROM ingest_runs
ORDER BY id;

-- fig07_cost_throughput_proxy
WITH msg AS (
  SELECT substr(ts,1,10) AS day, COUNT(*) AS messages
  FROM messages WHERE ts IS NOT NULL GROUP BY 1
),
tools AS (
  SELECT substr(COALESCE(last_at, started_at),1,10) AS day, SUM(tool_calls) AS tool_calls
  FROM sessions WHERE COALESCE(last_at, started_at) IS NOT NULL GROUP BY 1
),
combined AS (
  SELECT day, messages, 0 AS tool_calls FROM msg
  UNION ALL
  SELECT day, 0 AS messages, tool_calls FROM tools
)
SELECT day, SUM(messages) AS messages, SUM(tool_calls) AS tool_calls
FROM combined
GROUP BY day
ORDER BY day;

