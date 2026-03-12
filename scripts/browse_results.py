#!/usr/bin/env python3
"""Local results browser — generates HTML pages matching the official results browser style.

Usage:
    python3 scripts/browse_results.py runs/staging/sourcegraph_sonnet_20260311_012119
    python3 scripts/browse_results.py runs/staging/sourcegraph_sonnet_20260311_012119 --serve

Output goes to browse/<run_name>/ (gitignored), not inside runs/.
"""

import argparse
import html as html_lib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

EVENT_LIMIT = 2000


def esc(text) -> str:
    if text is None:
        return "-"
    return html_lib.escape(str(text))


def fmt_float(v, decimals=3):
    if v is None:
        return "-"
    return f"{float(v):.{decimals}f}"


def fmt_int(v):
    if v is None:
        return "-"
    return f"{int(v):,}"


def fmt_sec(s):
    if not s:
        return "-"
    if s < 60:
        return f"{s:.1f}s"
    if s < 3600:
        return f"{s/60:.1f}m"
    return f"{s/3600:.1f}h"


def fmt_json(obj):
    if obj is None:
        return "-"
    try:
        text = json.dumps(obj, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(obj)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    return esc(text)


def truncate_text(text, limit=4000):
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def normalize_task_name(raw: str) -> str:
    name = raw
    for prefix in ("mcp_", "bl_", "sgonly_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return re.sub(r"__[A-Za-z0-9]{5,8}$", "", name)


def find_trial_dirs(run_dir: str) -> list[dict]:
    tasks = []
    for config_dir in sorted(Path(run_dir).iterdir()):
        if not config_dir.is_dir():
            continue
        for task_group in sorted(config_dir.iterdir()):
            if not task_group.is_dir():
                continue
            for trial_dir in sorted(task_group.iterdir()):
                if not trial_dir.is_dir() or not (trial_dir / "result.json").exists():
                    continue
                td = extract_task_data(trial_dir, config_dir.name)
                if td:
                    tasks.append(td)
    return tasks


def extract_task_data(trial_dir: Path, config_name: str) -> dict | None:
    try:
        result = json.loads((trial_dir / "result.json").read_text())
    except Exception:
        return None

    raw_name = result.get("task_name", trial_dir.name)
    vr = (result.get("verifier_result") or {}).get("rewards") or {}
    reward = vr.get("reward")
    ar = result.get("agent_result") or {}

    def phase_sec(key):
        p = result.get(key) or {}
        s, e = p.get("started_at"), p.get("finished_at")
        if s and e:
            try:
                return round((datetime.fromisoformat(e.replace("Z", "+00:00"))
                              - datetime.fromisoformat(s.replace("Z", "+00:00"))).total_seconds(), 1)
            except Exception:
                pass
        return None

    metrics = {}
    mf = trial_dir / "task_metrics.json"
    if mf.exists():
        try:
            metrics = json.loads(mf.read_text())
        except Exception:
            pass

    inst = ""
    inf = trial_dir / "agent" / "instruction.txt"
    if inf.exists():
        try:
            inst = inf.read_text(errors="replace")
        except OSError:
            pass

    trace = parse_transcript(trial_dir / "agent" / "claude-code.txt")

    return dict(
        task_name=normalize_task_name(raw_name), raw_name=raw_name, config=config_name,
        reward=reward, status="passed" if reward and reward > 0 else "failed",
        trial_dir=str(trial_dir),
        wall_clock_sec=phase_sec("agent_execution") or metrics.get("agent_execution_seconds"),
        env_setup_sec=phase_sec("environment_setup") or metrics.get("environment_setup_seconds"),
        started_at=result.get("started_at", ""),
        input_tokens=ar.get("n_input_tokens", 0),
        cache_tokens=ar.get("n_cache_tokens", 0),
        output_tokens=ar.get("n_output_tokens", 0),
        cost_usd=metrics.get("cost_usd"),
        tool_calls_total=metrics.get("tool_calls_total", 0),
        tool_calls_mcp=metrics.get("tool_calls_mcp", 0),
        tool_calls_by_name=metrics.get("tool_calls_by_name", {}),
        mcp_ratio=metrics.get("mcp_ratio", 0),
        files_modified=metrics.get("files_modified", 0),
        timed_out=metrics.get("timed_out", False),
        conversation_turns=metrics.get("conversation_turns", 0),
        tool_errors_total=metrics.get("tool_errors_total", 0),
        mcp_latency_p50_ms=metrics.get("mcp_latency_p50_ms"),
        context_window_peak_pct=metrics.get("context_window_peak_pct"),
        cache_hit_rate=metrics.get("cache_hit_rate"),
        exception_info=result.get("exception_info"),
        model=result.get("config", {}).get("agent", {}).get("model_name", "unknown"),
        instruction_text=inst, trace=trace,
    )


# ---------------------------------------------------------------------------
# Transcript parser (matches export_official_results.py _parse_transcript)
# ---------------------------------------------------------------------------

def _tool_result_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                bt = str(b.get("type") or "")
                if bt in ("text", "tool_result"):
                    inner = b.get("text", b.get("content", ""))
                    if isinstance(inner, str):
                        parts.append(inner)
                    elif isinstance(inner, list):
                        for ib in inner:
                            parts.append(str(ib.get("text", ib.get("content", "")) if isinstance(ib, dict) else ib))
                elif isinstance(b.get("content"), str):
                    parts.append(str(b["content"]))
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        raw = content.get("content")
        if raw is not None:
            return _tool_result_to_text(raw)
        return json.dumps(content, sort_keys=True)
    return ""


def parse_transcript(path: Path) -> dict:
    events, tool_calls, code_changes, bash_commands = [], [], [], []
    id_to_name, pending = {}, {}
    seq = 0

    if not path.is_file():
        return {"events": [], "tool_calls": [], "code_changes": [], "bash_commands": []}
    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception:
        return {"events": [], "tool_calls": [], "code_changes": [], "bash_commands": []}

    def add(mtype, sub, text=None, tool=None, payload=None, ts=None):
        nonlocal seq
        if len(events) < EVENT_LIMIT:
            events.append(dict(sequence=seq, timestamp=ts, type=mtype, subtype=sub,
                               tool=tool, text=text or "", payload=payload or {}))
        seq += 1

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            p = json.loads(raw)
        except json.JSONDecodeError:
            continue
        mt = str(p.get("type") or "")
        ts = p.get("timestamp") if isinstance(p.get("timestamp"), str) else None

        if mt == "assistant":
            msg = p.get("message")
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if isinstance(content, str):
                add("assistant", "text", content, ts=ts)
                continue
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                it = str(item.get("type") or "")
                if it == "text":
                    add("assistant", "text", str(item.get("text") or ""), ts=ts)
                elif it == "tool_use":
                    tn = str(item.get("name") or "unknown")
                    ti = item.get("input") if isinstance(item.get("input"), dict) else {}
                    cid = str(item.get("id") or "")
                    if cid:
                        id_to_name[cid] = tn
                    add("assistant", "tool_use", tool=tn, payload=ti, ts=ts)
                    if len(tool_calls) < EVENT_LIMIT:
                        cd = dict(sequence=seq - 1, timestamp=ts, tool=tn, tool_use_id=cid,
                                  input=ti, output=None, output_text="")
                        tool_calls.append(cd)
                        if cid:
                            pending[cid] = cd
                    if tn == "Edit" and len(code_changes) < EVENT_LIMIT:
                        code_changes.append(dict(sequence=seq - 1, type="edit",
                                                 file_path=str(ti.get("file_path") or ""),
                                                 old_string=str(ti.get("old_string") or ""),
                                                 new_string=str(ti.get("new_string") or "")))
                    elif tn == "Write" and len(code_changes) < EVENT_LIMIT:
                        code_changes.append(dict(sequence=seq - 1, type="write",
                                                 file_path=str(ti.get("file_path") or ""),
                                                 content=str(ti.get("content") or "")))
                    elif tn == "Bash":
                        cmd = str(ti.get("command") or "")
                        if cmd and len(bash_commands) < EVENT_LIMIT:
                            bash_commands.append(dict(sequence=seq - 1, command=cmd))

        elif mt == "user":
            msg = p.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            top = p.get("tool_use_result") or p.get("toolUseResult")
            if isinstance(content, list):
                blocks = [b for b in content if isinstance(b, dict) and str(b.get("type") or "") == "tool_result"]
                if blocks:
                    for b in blocks:
                        uid = str(b.get("tool_use_id") or b.get("toolUseId") or "")
                        mapped = id_to_name.get(uid)
                        bt = _tool_result_to_text(b.get("content"))
                        op = top if top is not None and len(blocks) == 1 else b.get("content")
                        if not bt and op is not None:
                            bt = _tool_result_to_text(op)
                        add("user", "tool_result", bt, tool=mapped,
                            payload=op if isinstance(op, dict) else None, ts=ts)
                        if uid in pending:
                            pending[uid]["output"] = op
                            pending[uid]["output_text"] = bt
                    continue
            if isinstance(top, dict):
                add("user", "tool_result", _tool_result_to_text(top.get("content")), payload=top, ts=ts)
                continue
            if isinstance(content, str):
                add("user", "text", content, ts=ts)
            elif isinstance(content, list):
                parts = [str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                add("user", "text", "\n".join(parts), ts=ts)

        elif mt == "system":
            add("system", str(p.get("subtype") or "init"), ts=ts)

    return {"events": events, "tool_calls": tool_calls, "code_changes": code_changes, "bash_commands": bash_commands}


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

STYLE = """\
:root { --bg:#0b1117; --panel:#131d27; --border:#2a3a4a; --text:#e9f0f6; --muted:#9fb1c2; --accent:#4fd39b; }
body { margin:0; font-family: ui-sans-serif,system-ui,-apple-system,sans-serif; background:linear-gradient(180deg,#0b1117,#0f1720); color:var(--text); }
.wrap { max-width:1200px; margin:0 auto; padding:20px; }
h1,h2,h3,h4 { margin:0 0 10px; }
.panel { background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:14px; margin-bottom:14px; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; }
.metric { background:#0f1821; border:1px solid var(--border); border-radius:10px; padding:10px; }
.metric .k { color:var(--muted); font-size:12px; }
.metric .v { font-size:20px; margin-top:4px; }
.meta { color:var(--muted); font-size:13px; }
table { width:100%; border-collapse:collapse; }
th,td { border-bottom:1px solid var(--border); padding:8px; text-align:left; vertical-align:top; font-size:13px; }
th { color:var(--muted); cursor:pointer; }
code,pre { font-family: ui-monospace,SFMono-Regular,Menlo,monospace; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; background:#0d151d; border:1px solid var(--border); border-radius:8px; padding:8px; margin:8px 0; }
details { border:1px solid var(--border); border-radius:10px; padding:8px 10px; margin:8px 0; background:#0f1821; }
summary { cursor:pointer; color:var(--accent); }
a { color:var(--accent); text-decoration:none; }
.split { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.pill { padding:2px 8px; border-radius:999px; font-size:12px; display:inline-block; }
.passed { background: rgba(71,209,140,0.2); color:var(--accent); }
.failed { background: rgba(255,204,102,0.2); color:#ffcc66; }
.num { text-align:right; font-variant-numeric:tabular-nums; }
.mono { font-family: ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }
button { background:transparent; color:var(--text); border:1px solid var(--border); border-radius:8px; padding:8px 10px; cursor:pointer; }
select,input { background:var(--panel); color:var(--text); border:1px solid var(--border); border-radius:8px; padding:8px; }
.controls { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:14px; }
@media (max-width: 900px) { .split { grid-template-columns:1fr; } }
"""


def task_slug(t):
    return f"{t['config']}--{t['task_name']}".replace("/", "-")


def generate_index(run_name, tasks):
    rows_json = json.dumps([
        dict(task_name=t["task_name"], config=t["config"], reward=t["reward"],
             status=t["status"], wall_clock_sec=t["wall_clock_sec"],
             tool_calls_total=t["tool_calls_total"], mcp_ratio=t["mcp_ratio"],
             cost_usd=t["cost_usd"], slug=task_slug(t))
        for t in tasks
    ])
    configs = sorted(set(t["config"] for t in tasks))
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta http-equiv='Cache-Control' content='no-cache,no-store,must-revalidate'>"
        f"<title>Results Browser — {esc(run_name)}</title>"
        f"<style>{STYLE}</style></head><body><div class='wrap'>"
        f"<h1>Results Browser</h1>"
        f"<p class='meta'>{esc(run_name)} — {len(tasks)} trials, {len(configs)} configs</p>"
        "<div class='controls'>"
        "<select id='cf'><option value=''>All configs</option></select>"
        "<select id='sf'><option value=''>All statuses</option><option>passed</option><option>failed</option></select>"
        "<input id='q' placeholder='Search task' /><button id='clr'>Clear</button></div>"
        "<div id='st' class='meta'></div>"
        "<table><thead><tr><th>Config</th><th>Task</th><th>Status</th><th class='num'>Reward</th>"
        "<th class='num'>MCP ratio</th><th class='num'>Tools</th><th class='num'>Time</th><th class='num'>Cost</th>"
        "</tr></thead><tbody id='r'></tbody></table></div>"
        f"<script>var T={rows_json};"
        "var cf=document.getElementById('cf'),sf=document.getElementById('sf'),"
        "q=document.getElementById('q'),r=document.getElementById('r'),st=document.getElementById('st');"
        "function fs(s){if(!s)return'-';if(s<60)return s.toFixed(1)+'s';if(s<3600)return(s/60).toFixed(1)+'m';return(s/3600).toFixed(1)+'h'}"
        "function fm(v,d){return(v===null||v===undefined)?'-':Number(v).toFixed(d||3)}"
        "[...new Set(T.map(function(t){return t.config}))].sort().forEach(function(c){cf.add(new Option(c,c))});"
        "function render(){var c=cf.value,s=sf.value,k=q.value.trim().toLowerCase();"
        "var f=T.filter(function(t){return(!c||t.config===c)&&(!s||t.status===s)&&(!k||t.task_name.toLowerCase().indexOf(k)>=0)});"
        "r.innerHTML=f.map(function(t){return '<tr>'"
        "+'<td class=\"mono\">'+t.config+'</td>'"
        "+'<td><a href=\"'+t.slug+'.html\">'+t.task_name+'</a></td>'"
        "+'<td><span class=\"pill '+t.status+'\">'+t.status+'</span></td>'"
        "+'<td class=\"num\">'+fm(t.reward)+'</td>'"
        "+'<td class=\"num\">'+fm(t.mcp_ratio)+'</td>'"
        "+'<td class=\"num\">'+(t.tool_calls_total||'-')+'</td>'"
        "+'<td class=\"num\">'+fs(t.wall_clock_sec)+'</td>'"
        "+'<td class=\"num\">'+(t.cost_usd?'$'+t.cost_usd.toFixed(2):'-')+'</td></tr>'}).join('');"
        "st.textContent='Showing '+f.length+' of '+T.length+' trials'}"
        "cf.onchange=sf.onchange=render;q.oninput=render;"
        "document.getElementById('clr').onclick=function(){cf.value='';sf.value='';q.value='';render()};"
        "render();</script></body></html>"
    )


def generate_detail_page(run_name, t):
    trace = t.get("trace") or {}
    tevs = trace.get("events", [])
    ttc = trace.get("tool_calls", [])
    tcc = trace.get("code_changes", [])
    tbc = trace.get("bash_commands", [])

    mg = "".join(
        f"<div class='metric'><div class='k'>{esc(k)}</div><div class='v'>{esc(v)}</div></div>"
        for k, v in [
            ("Reward", fmt_float(t["reward"], 4)), ("Status", t["status"]),
            ("Config", t["config"]), ("Model", t["model"]),
            ("Agent Time", fmt_sec(t["wall_clock_sec"])), ("Env Setup", fmt_sec(t["env_setup_sec"])),
            ("Input Tokens", fmt_int(t["input_tokens"])), ("Output Tokens", fmt_int(t["output_tokens"])),
            ("Cache Tokens", fmt_int(t["cache_tokens"])),
            ("Cost", f"${t['cost_usd']:.2f}" if t["cost_usd"] else "-"),
            ("Tool Calls", f"{t['tool_calls_total']} ({t['tool_calls_mcp']} MCP)"),
            ("MCP Ratio", fmt_float(t["mcp_ratio"], 3)),
            ("Context Peak", f"{t['context_window_peak_pct']:.0%}" if t["context_window_peak_pct"] else "-"),
            ("Cache Hit", f"{t['cache_hit_rate']:.0%}" if t["cache_hit_rate"] else "-"),
            ("Turns", str(t["conversation_turns"])), ("Timed Out", "Yes" if t["timed_out"] else "No"),
        ])

    tr_ = "".join(
        f"<tr><td><code>{esc(n)}</code></td><td>{int(c)}</td></tr>"
        for n, c in sorted((t["tool_calls_by_name"] or {}).items(), key=lambda x: -x[1])
    ) or "<tr><td colspan='2'>-</td></tr>"

    cr = "".join(
        f"<tr><td>{i}</td><td>{esc(e.get('timestamp') or '-')}</td>"
        f"<td>{esc(e.get('type') or '-')}</td><td>{esc(e.get('subtype') or '-')}</td>"
        f"<td><code>{esc(e.get('tool') or '-')}</code></td>"
        f"<td><pre>{esc(truncate_text(str(e.get('text') or '')))}</pre></td></tr>"
        for i, e in enumerate(tevs[:EVENT_LIMIT], 1)
    ) or "<tr><td colspan='6'>No events</td></tr>"

    tc = "".join(
        f"<details><summary>{i}. <code>{esc(c.get('tool') or '?')}</code> @ {esc(c.get('timestamp') or '-')}</summary>"
        f"<h4>Input</h4><pre>{fmt_json(c.get('input'))}</pre>"
        + (f"<h4>Output</h4><pre>{fmt_json(c.get('output') or c.get('output_text') or None)}</pre>"
           if (c.get("output") is not None or c.get("output_text")) else "")
        + "</details>"
        for i, c in enumerate(ttc[:EVENT_LIMIT], 1)
    ) or "<p>No tool call payloads.</p>"

    cc = "".join(
        f"<details><summary>{i}. {esc(str(ch.get('type','')).upper())} <code>{esc(ch.get('file_path',''))}</code></summary>"
        + ("<div class='split'>"
           f"<div><h4>Before</h4><pre>{esc(truncate_text(str(ch.get('old_string',''))))}</pre></div>"
           f"<div><h4>After</h4><pre>{esc(truncate_text(str(ch.get('new_string',''))))}</pre></div></div>"
           if ch.get("type") == "edit"
           else f"<pre>{esc(truncate_text(str(ch.get('content',''))))}</pre>")
        + "</details>"
        for i, ch in enumerate(tcc[:EVENT_LIMIT], 1)
    ) or "<p>No code changes.</p>"

    bc = "".join(
        f"<pre>{i}. $ {esc(str(b.get('command','')))}</pre>"
        for i, b in enumerate(tbc[:EVENT_LIMIT], 1)
    ) or "<p>No bash commands.</p>"

    ex = ""
    if t["exception_info"]:
        ex = f"<div class='panel'><h2>Exception</h2><pre style='color:#ffcc66'>{esc(json.dumps(t['exception_info'], indent=2))}</pre></div>"

    cp = "passed" if "mcp" in t["config"] else ""

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{esc(t['task_name'])} — {esc(t['config'])}</title>"
        f"<style>{STYLE}</style></head><body><div class='wrap'>"
        f"<p><a href='index.html'>&larr; Back to results</a></p>"
        f"<h1>{esc(t['task_name'])}</h1>"
        f"<p class='meta'><span class='pill {cp}'>{esc(t['config'])}</span>"
        f" | Score: <strong>{fmt_float(t['reward'], 4)}</strong> | {esc(run_name)}</p>"
        f"<div class='panel'><h2>Task Information</h2>"
        f"<details open><summary>Task instruction sent to agent</summary>"
        f"<pre>{esc(t['instruction_text'])}</pre></details></div>"
        f"<div class='panel'><h2>Execution Metrics</h2><div class='grid'>{mg}</div>"
        f"<details><summary>Tool Breakdown</summary>"
        f"<table><thead><tr><th>Tool</th><th>Calls</th></tr></thead><tbody>{tr_}</tbody></table></details></div>"
        f"{ex}"
        f"<div class='panel'><h2>Agent Trace</h2>"
        f"<details open><summary>Conversation History ({len(tevs)})</summary>"
        f"<table><thead><tr><th>#</th><th>Timestamp</th><th>Type</th><th>Subtype</th><th>Tool</th><th>Text</th></tr></thead>"
        f"<tbody>{cr}</tbody></table></details>"
        f"<details><summary>Tool Calls ({len(ttc)})</summary>{tc}</details>"
        f"<details><summary>Code Changes ({len(tcc)})</summary>{cc}</details>"
        f"<details><summary>Bash Commands ({len(tbc)})</summary>{bc}</details></div>"
        f"<div class='panel'><h2>File Paths</h2><pre>Trial: {esc(t['trial_dir'])}</pre></div>"
        "</div></body></html>"
    )


def main():
    ap = argparse.ArgumentParser(description="Generate HTML results browser (official style)")
    ap.add_argument("run_dir")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    run_dir = os.path.abspath(args.run_dir)
    if not os.path.isdir(run_dir):
        print(f"ERROR: not a directory: {run_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {run_dir}...")
    tasks = find_trial_dirs(run_dir)
    if not tasks:
        print("No trials found.", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(tasks)} trial(s)")

    run_name = os.path.basename(run_dir)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    browse_dir = os.path.join(repo_root, "browse", run_name)
    os.makedirs(browse_dir, exist_ok=True)

    with open(os.path.join(browse_dir, "index.html"), "w") as f:
        f.write(generate_index(run_name, tasks))
    for t in tasks:
        with open(os.path.join(browse_dir, f"{task_slug(t)}.html"), "w") as f:
            f.write(generate_detail_page(run_name, t))
    print(f"  {len(tasks) + 1} pages in {browse_dir}/")

    if args.serve:
        import http.server, functools
        h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=browse_dir)
        s = http.server.HTTPServer(("0.0.0.0", args.port), h)
        print(f"Serving at http://localhost:{args.port}/index.html")
        try:
            s.serve_forever()
        except KeyboardInterrupt:
            pass
    else:
        print(f"  python3 scripts/browse_results.py {args.run_dir} --serve")


if __name__ == "__main__":
    main()
