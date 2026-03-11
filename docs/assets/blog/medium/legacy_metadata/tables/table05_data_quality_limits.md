# Data Quality and Limits

## Session Timestamp Coverage

| Agent | Sessions | Started Present | Last Present |
|---|---:|---:|---:|
| claude | 1034 | 1034 | 1034 |
| external_transcript_memory | 891 | 56 | 56 |
| external_claude_archive | 287 | 287 | 287 |
| codex | 77 | 77 | 77 |
| copilot | 52 | 52 | 52 |
| external_codex | 20 | 20 | 20 |
| cursor | 18 | 0 | 0 |
| gemini | 7 | 7 | 7 |
| external_cursor | 1 | 0 | 0 |

## Message Timestamp Coverage

| Agent | Messages | ts Present |
|---|---:|---:|
| claude | 638783 | 638783 |
| external_transcript_memory | 90423 | 90423 |
| external_claude_archive | 45574 | 45574 |
| codex | 5103 | 5103 |
| external_codex | 2328 | 2328 |
| cursor | 570 | 0 |
| external_cursor | 70 | 0 |
| copilot | 52 | 52 |
| gemini | 46 | 46 |

## Known Caveats

- Cursor transcripts in this DB currently have null message timestamps.
- Copilot rows are session-state metadata pseudo-messages, not full transcripts.
- External sources may include mirrored historical material despite dedupe safeguards.
- Alias history (CodeContextBench/CodeScaleBench + dashboard siblings) is intentionally included.
