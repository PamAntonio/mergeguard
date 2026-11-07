#!/usr/bin/env python3
"""Build the MergeGuard one-page site.

Reads reports/*.json (falls back to site/sample/*.json), parses the
flag codes out of verifier/rules.py, and writes ONE self-contained
HTML file to both site/index.html and docs/index.html.
No CDNs, no web fonts, no frameworks.
Run:  python3 site/build.py
"""
import base64
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = Path(__file__).resolve().parent
REPORTS_DIR = ROOT / "reports"
SAMPLE_DIR = SITE / "sample"
RULES_PY = ROOT / "verifier" / "rules.py"
OUTS = [SITE / "index.html", ROOT / "docs" / "index.html"]
GITHUB = "https://github.com/PamAntonio/mergeguard"

MEANINGS = {
    "TESTS_FAILED": "The real test run's exit code isn't 0.",
    "TEST_DELETED": "The diff removes a def test_ line or deletes a test file.",
    "TEST_EDITED": "Existing test lines were changed or removed.",
    "TEST_SKIPPED": "The diff adds skip, skipif or xfail.",
    "STUBBED": "The diff adds raise NotImplementedError in non-test code.",
    "FAKE_PASS": "The diff adds assert True, sys.exit(0) or os._exit.",
    "PROTECTED_FILE": "Changed tests/conftest.py, pytest.ini, pytest settings in pyproject.toml, or .github/**.",
    "SENSITIVE_PATH": "Changed a file whose path contains auth, payment, billing or migration.",
    "CLAIM_NO_EVIDENCE": "The claim says tests pass, but no step in the event log ran the tests.",
}

TABS = [("Honest", "task-b"), ("Cheated", "task-b-gamed"), ("Seeded", "task-b-seeded"), ("Risky", "task-c")]


def load_reports():
    files = sorted(REPORTS_DIR.glob("*.json")) if REPORTS_DIR.is_dir() else []
    source = "reports/"
    if not files:
        files = sorted(SAMPLE_DIR.glob("*.json"))
        source = "site/sample/ (no reports/*.json yet)"
    reports = []
    for f in files:
        try:
            reports.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return reports, source


def flag_codes():
    text = RULES_PY.read_text(encoding="utf-8") if RULES_PY.exists() else ""
    codes = []
    for c in re.findall(r'Flag\(\s*"([A-Z][A-Z_]+)"', text):
        if c not in codes:
            codes.append(c)
    return codes


def esc(v):
    return html.escape(str(v if v is not None else ""), quote=True)


def fmt_cost(reports):
    vals = [r["cost_usd"] for r in reports if isinstance(r.get("cost_usd"), (int, float))]
    if not vals:
        return "—"
    return f"${sum(vals) / len(vals):.2f}"


def attempts_count(r):
    a = r.get("attempts")
    if isinstance(a, (list, tuple)):
        return len(a)
    if isinstance(a, (int, float)):
        return int(a)
    detail = r.get("attempts_detail")
    return len(detail) if isinstance(detail, list) else None


def fmt_attempts(reports):
    vals = [c for c in (attempts_count(r) for r in reports) if c is not None]
    if not vals:
        return "—"
    return str(int(sum(vals)))


def original_info(r):
    """Pre-fix-loop verdict/state: `original` if present, else flags/tests vs final_*."""
    o = r.get("original")
    if isinstance(o, dict):
        return {"decision": o.get("decision") or o.get("verdict"),
                "flags": o.get("flags") or [], "tests": o.get("tests") or {}}
    if isinstance(o, str):
        return {"decision": o, "flags": r.get("flags") or [], "tests": r.get("tests") or {}}
    if "final_tests" in r or "final_flags" in r or r.get("attempts_detail"):
        return {"decision": None, "flags": r.get("flags") or [], "tests": r.get("tests") or {}}
    return None


def claim_checks(r):
    """Audit claims -> verified / contradicted / no_evidence (false with no step)."""
    out = []
    for c in (r.get("audit") or {}).get("claims", []) or []:
        steps = [s for s in (c.get("steps") or []) if isinstance(s, int)]
        v = c.get("verified")
        if v is True:
            status = "verified"
        elif v is False and steps:
            status = "contradicted"
        elif v is False:
            status = "no_evidence"
        elif not steps:
            status = "no_evidence"
        else:
            status = "unsure"
        out.append({"claim": c.get("claim") or "", "status": status,
                    "steps": steps, "note": c.get("note") or "", "verified": v})
    return out


def replay_payload(reports):
    by_task = {r.get("task"): r for r in reports}
    out = []
    for label, task in TABS:
        r = by_task.get(task)
        if not r:
            continue
        steps = r.get("steps") or []
        flags = r.get("flags") or []
        flagged = sorted({f["step"] for f in flags if isinstance(f.get("step"), int)}
                         | {s["step"] for s in (r.get("audit") or {}).get("suspicious_steps", [])
                            if isinstance(s.get("step"), int)})
        task_text = ""
        if steps:
            task_text = (steps[0].get("detail") or "")[:600]
        detail = r.get("attempts_detail")
        if not isinstance(detail, list):
            detail = r["attempts"] if isinstance(r.get("attempts"), list) else []
        out.append({
            "label": label, "task": r.get("task"), "decision": r.get("decision") or "—",
            "attempts": attempts_count(r), "attemptsDetail": detail,
            "simulated": bool(r.get("simulated")), "original": original_info(r),
            "finalTests": r.get("final_tests") or {}, "finalFlags": r.get("final_flags"),
            "claimChecks": claim_checks(r),
            "flags": flags,
            "tests": r.get("tests") or {}, "risk": r.get("risk") or {},
            "claim": r.get("claim") or "", "steps": steps, "flagged": flagged,
            "taskText": task_text, "changedFiles": r.get("changed_files") or [],
            "seconds": r.get("seconds"),
        })
    # any extra reports not in the three tabs
    known = {t for _, t in TABS}
    for r in reports:
        if r.get("task") not in known:
            detail = r.get("attempts_detail")
            if not isinstance(detail, list):
                detail = r["attempts"] if isinstance(r.get("attempts"), list) else []
            out.append({"label": r.get("task"), "task": r.get("task"),
                        "decision": r.get("decision") or "—", "attempts": attempts_count(r),
                        "attemptsDetail": detail, "simulated": bool(r.get("simulated")),
                        "original": original_info(r), "finalTests": r.get("final_tests") or {},
                        "finalFlags": r.get("final_flags"), "claimChecks": claim_checks(r),
                        "flags": r.get("flags") or [], "tests": r.get("tests") or {},
                        "risk": r.get("risk") or {}, "claim": r.get("claim") or "",
                        "steps": r.get("steps") or [], "flagged": [],
                        "taskText": "", "changedFiles": r.get("changed_files") or [],
                        "seconds": r.get("seconds")})
    return out


CSS = """
:root{--bg:#0a0e13;--panel:#11161d;--panel2:#0d1218;--line:#26303d;--text:#e8eef4;--muted:#9fb0c0;--green:#3fb950;--red:#f85149;--amber:#e3a008;--cyan:#56c8d8;--mono:ui-monospace,'SF Mono',SFMono-Regular,Menlo,Consolas,monospace;--sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);font-size:17px;line-height:1.55}
a{color:var(--cyan)}code,pre,.mono{font-family:var(--mono)}
.wrap{max-width:1120px;margin:0 auto;padding:0 24px}
header{position:sticky;top:0;z-index:50;background:rgba(10,14,19,.96);border-bottom:1px solid var(--line)}
.bar{display:flex;align-items:center;gap:22px;max-width:1120px;margin:0 auto;padding:12px 24px;flex-wrap:wrap}
.word{font-family:var(--mono);font-weight:700;font-size:19px;color:#fff;text-decoration:none;letter-spacing:-.02em}
.word b{color:var(--green);font-weight:700}
nav{display:flex;gap:16px;flex-wrap:wrap;margin-left:8px}
nav a{color:var(--muted);text-decoration:none;font-size:14px;font-family:var(--mono)}
nav a:hover{color:#fff}
.gh{margin-left:auto;font-family:var(--mono);font-size:14px;color:#fff;text-decoration:none;border:1px solid var(--line);padding:6px 12px;border-radius:4px}
.gh:hover{border-color:var(--green)}
.hero{padding:64px 0 48px;border-bottom:1px solid var(--line)}
.hero-grid{display:grid;grid-template-columns:1.15fr .85fr;gap:36px;align-items:start}
@media(max-width:860px){.hero-grid{grid-template-columns:1fr}}
.eyebrow{font-family:var(--mono);font-size:13px;color:var(--green);letter-spacing:.06em;text-transform:uppercase}
h1{font-size:46px;line-height:1.08;letter-spacing:-.03em;margin:14px 0 16px;color:#fff}
@media(max-width:600px){h1{font-size:34px}}
.sub{font-size:19px;color:#c7d2dd;max-width:34em;margin:0 0 26px}
.btns{display:flex;gap:12px;flex-wrap:wrap}
.btn{display:inline-block;padding:11px 18px;border-radius:4px;text-decoration:none;font-family:var(--mono);font-size:15px;border:1px solid var(--line);color:#fff;background:var(--panel)}
.btn.primary{background:var(--green);color:#06130a;border-color:var(--green);font-weight:700}
.btn:hover{filter:brightness(1.15)}
.term{background:#06090d;border:1px solid var(--line);border-radius:6px;font-family:var(--mono);font-size:13.5px;overflow:hidden}
.term-h{padding:9px 14px;border-bottom:1px solid var(--line);color:var(--muted);display:flex;gap:8px;align-items:center}
.dot{width:10px;height:10px;border-radius:50%;background:#30363d;display:inline-block}
.term-b{padding:16px;white-space:pre-wrap;word-break:break-word;line-height:1.7}
.ok{color:var(--green)}.bad{color:var(--red)}.warn{color:var(--amber)}.dim{color:var(--muted)}
section{padding:52px 0;border-bottom:1px solid var(--line)}
.kicker{font-family:var(--mono);color:var(--green);font-size:13px}
h2{font-size:30px;letter-spacing:-.02em;color:#fff;margin:8px 0 10px}
.lede{color:#c7d2dd;max-width:44em}
.big{font-size:26px;line-height:1.3;color:#fff;font-weight:700;max-width:22em}
table{width:100%;border-collapse:collapse;margin-top:18px;font-size:15px}
th,td{border:1px solid var(--line);padding:10px 12px;text-align:left;vertical-align:top}
th{font-family:var(--mono);font-size:13px;color:var(--muted);background:var(--panel)}
td code{color:var(--amber);font-size:14px}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}
.tab{font-family:var(--mono);padding:9px 16px;background:var(--panel);color:var(--muted);border:1px solid var(--line);border-radius:4px;cursor:pointer;font-size:15px}
.tab[aria-selected="true"]{color:#06130a;background:var(--green);border-color:var(--green);font-weight:700}
.controls{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}
.controls button{font-family:var(--mono);padding:9px 16px;background:#fff;color:#000;border:0;border-radius:4px;cursor:pointer;font-weight:700;font-size:14px}
.controls button.ghost{background:var(--panel);color:#fff;border:1px solid var(--line)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:860px){.grid2{grid-template-columns:1fr}}
.card{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:18px}
.card h3{margin:0 0 8px;font-family:var(--mono);font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.claim{white-space:pre-wrap;word-break:break-word;font-size:14.5px;max-height:260px;overflow:auto}
.timeline{list-style:none;margin:0;padding:0;font-family:var(--mono);font-size:13.5px}
.timeline li{padding:9px 12px;border:1px solid var(--line);border-radius:4px;margin-bottom:7px;background:var(--panel2);opacity:.28}
.timeline li.shown{opacity:1}
.timeline li.flagged{border-color:var(--red);background:#2a1215;color:#ffd7d5}
.timeline .n{color:var(--cyan);display:inline-block;min-width:2.2em}
.progress{font-family:var(--mono);color:var(--muted);font-size:13px}
.badge{display:inline-block;font-family:var(--mono);font-weight:700;padding:5px 12px;border-radius:4px;font-size:14px;border:1px solid var(--line)}
.badge.MERGE,.badge.FIXED_THEN_MERGE{background:var(--green);color:#06130a;border-color:var(--green)}
.badge.BLOCK{background:var(--red);color:#1a0505;border-color:var(--red)}
.badge.NEEDS_APPROVAL{background:var(--amber);color:#1a1200;border-color:var(--amber)}
.flag{display:inline-block;font-family:var(--mono);font-size:12.5px;border:1px solid var(--red);color:#ffb4ae;padding:2px 7px;border-radius:3px;margin:2px 4px 2px 0}
.flag.med{border-color:var(--amber);color:var(--amber)}
.video{border:2px dashed var(--line);border-radius:6px;min-height:340px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;color:var(--muted);background:var(--panel2);text-align:center;padding:24px}
.play{width:64px;height:64px;border-radius:50%;border:2px solid var(--muted);display:flex;align-items:center;justify-content:center;font-size:22px;color:#fff}
ol.steps{counter-reset:s;list-style:none;padding:0;display:grid;gap:12px}
ol.steps li{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:16px 18px}
ol.steps b{color:#fff}
pre.flow{background:#06090d;border:1px solid var(--line);border-radius:6px;padding:18px;overflow:auto;font-size:13.5px;line-height:1.7;color:#c7d2dd}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:18px}
@media(max-width:760px){.stats{grid-template-columns:1fr}}
.stat{background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:22px}
.stat .num{font-family:var(--mono);font-size:52px;font-weight:700;color:#fff;line-height:1}
.stat .lab{font-family:var(--mono);color:var(--muted);font-size:13px;margin-top:8px;text-transform:uppercase;letter-spacing:.05em}
.stat .note{color:var(--muted);font-size:13px;margin-top:6px}
pre.cmd{background:#06090d;border:1px solid var(--line);border-radius:6px;padding:16px;overflow:auto;font-size:13.5px;line-height:1.7}
footer{padding:28px 0 44px}
footer .wrap{display:flex;gap:20px;flex-wrap:wrap;font-family:var(--mono);font-size:14px}
footer a{color:var(--muted);text-decoration:none}footer a:hover{color:#fff}
.src{font-family:var(--mono);font-size:12.5px;color:var(--muted)}
.sim-banner{border:2px solid var(--red);color:#ffb4ae;background:#2a1215;border-radius:6px;padding:12px 16px;font-family:var(--mono);font-weight:700;margin:0 0 16px}
.claimchecks{list-style:none;margin:8px 0 0;padding:0;font-size:14px}
.claimchecks li{padding:7px 0;border-top:1px solid var(--line)}
.cc{font-family:var(--mono);font-size:12.5px;font-weight:700;margin-right:8px}
.cc.verified{color:var(--green)}.cc.contradicted{color:var(--red)}.cc.no_evidence,.cc.unsure{color:var(--amber)}
.attempts-list{list-style:none;margin:8px 0 0;padding:0;font-family:var(--mono);font-size:13.5px}
.attempts-list li{padding:7px 0;border-top:1px solid var(--line)}
.person{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.avatar{width:96px;height:96px;border-radius:50%;object-fit:cover;border:1px solid var(--line);flex:none;background:var(--panel)}
.person-links{font-family:var(--mono);font-size:14px;margin-top:6px}
.person-links a{margin-right:14px}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
"""

JS = """
const DATA = __DATA__;
let idx = 0, pos = 0, timer = null;
const $ = s => document.querySelector(s);
function flaggedSet(r){ return new Set(r.flagged || []); }
function renderTabs(){
  $('#tabs').innerHTML = DATA.map((r,i)=>`<button class="tab" role="tab" aria-selected="${i===idx}" data-i="${i}">${r.label} <span style="opacity:.75">(${r.task})</span></button>`).join('');
  document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{ stop(); idx=+b.dataset.i; pos=0; render(); });
}
function stop(){ if(timer){ clearInterval(timer); timer=null; $('#playBtn').textContent='Play'; } }
function render(){
  renderTabs();
  const r = DATA[idx]; if(!r) return;
  const fl = flaggedSet(r);
  $('#taskText').textContent = r.taskText || '(no saved task text)';
  $('#claimText').textContent = r.claim || '(no claim saved)';
  $('#simBanner').innerHTML = r.simulated ? '<div class="sim-banner">SIMULATED CHEATER (made by hand)</div>' : '';
  const ccLabel = {verified:'✓ verified', contradicted:'✗ contradicted', no_evidence:'? no evidence in log', unsure:'? unsure'};
  $('#claimChecks').innerHTML = (r.claimChecks||[]).map(c=>`<li><span class="cc ${c.status}">${ccLabel[c.status]||c.status}${c.steps && c.steps.length ? ' · step ' + c.steps.join(', ') : ''}</span>${(c.claim||'').slice(0,180)}</li>`).join('') || '<li class="dim">no audited claims</li>';
  const orig = r.original;
  $('#originalLine').innerHTML = orig ? `original (before fix loop): ${orig.decision ? '<b>' + orig.decision + '</b> · ' : ''}${(orig.flags||[]).map(f=>f.code).join(', ') || 'no flags'} · tests: ${(orig.tests||{}).summary || '—'}` : '';
  $('#metaLine').innerHTML = `branch <b>${r.task}</b> &middot; changed: ${(r.changedFiles||[]).join(', ')||'—'} &middot; tests: ${r.tests.summary||'—'} &middot; risk: ${r.risk && r.risk.score!=null ? r.risk.score+' — '+(r.risk.reason||'') : '—'}`;
  $('#flagsLine').innerHTML = (r.flags||[]).map(f=>`<span class="flag ${f.severity==='medium'?'med':''}">${f.code}${f.step!=null?' · step '+f.step:''}</span>`).join('') || '<span class="dim">no flags</span>';
  $('#attemptsLine').textContent = r.attempts==null ? '—' : (r.attempts + (r.attempts===1?' attempt':' attempts') + ' · verdict after the timeline');
  $('#attemptsList').innerHTML = (r.attemptsDetail||[]).map(a=>`<li>attempt ${a.n ?? ''} · ${a.actor || 'fixer'} · ${a.ok ? 'ok' : 'failed'} · tests: ${(a.tests||{}).summary || '—'} · flags: ${(a.flags||[]).map(f=>f.code).join(', ') || 'none'}</li>`).join('');
  $('#timeline').innerHTML = (r.steps||[]).map((s,i)=>{
    const isF = fl.has(s.n);
    return `<li class="${i<pos?'shown':''} ${isF?'flagged':''}"><span class="n">${s.n}</span> [${s.kind||''}] <b>${s.tool||''}</b>: ${(s.detail||'').slice(0,220)}${s.result?' <span class="dim">-&gt; '+String(s.result).slice(0,120)+'</span>':''}${isF?' <b>[FLAGGED]</b>':''}</li>`;
  }).join('');
  const done = pos >= (r.steps||[]).length;
  $('#verdict').innerHTML = done ? `<span class="badge ${r.decision}">${r.decision}</span>` : '<span class="dim">playing… verdict at the end</span>';
  $('#progress').textContent = `step ${Math.min(pos,(r.steps||[]).length)} / ${(r.steps||[]).length}`;
}
$('#playBtn').onclick = () => {
  if(timer){ stop(); return; }
  const r = DATA[idx]; if(pos >= (r.steps||[]).length) pos = 0;
  $('#playBtn').textContent = 'Pause';
  timer = setInterval(()=>{ const rr=DATA[idx]; pos++; render(); if(pos >= (rr.steps||[]).length) stop(); }, 650);
};
$('#skipBtn').onclick = () => { stop(); pos = (DATA[idx].steps||[]).length; render(); };
$('#restartBtn').onclick = () => { stop(); pos = 0; render(); };
render();
"""


def build():
    reports, source = load_reports()
    photo_path = SITE / "photo.jpg"
    photo_uri = ""
    if photo_path.exists():
        photo_uri = "data:image/jpeg;base64," + base64.b64encode(photo_path.read_bytes()).decode("ascii")
    codes = flag_codes()
    data = replay_payload(reports)
    data_json = json.dumps(data).replace("</", "<\\/")
    rules_rows = "".join(
        f'<tr><td><code>{esc(c)}</code></td><td>{esc(MEANINGS.get(c, "Flag raised by verifier/rules.py."))}</td>'
        f'<td class="mono">enforced in verifier/rules.py</td></tr>' for c in codes)
    js = JS.replace("__DATA__", data_json)
    photo_img = (f'<img class="avatar" src="{photo_uri}" alt="Pam Villalon" width="96" height="96">'
                 if photo_uri else "")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MergeGuard — Your agent says all tests pass. Prove it.</title>
<style>{CSS}</style></head>
<body id="top">
<header><div class="bar">
<a class="word" href="#top">Merge<b>Guard</b></a>
<nav>
<a href="#replay">Replay</a><a href="#how">How it works</a><a href="#rules">Rules</a>
<a href="#models">Models</a><a href="#numbers">Numbers</a><a href="#built">Built today</a><a href="#run">Run it</a>
</nav>
<a class="gh" href="{GITHUB}">GitHub &#8599;</a>
</div></header>

<div class="hero"><div class="wrap"><div class="hero-grid">
<div>
<div class="eyebrow">AIE Code Summit Hackathon &middot; Trust but Verify</div>
<h1>Your agent says all tests pass. Prove it.</h1>
<p class="sub">MergeGuard reads a coding agent's step-by-step log, finds the exact step where it cut a corner, and sends it back until the fix is real.</p>
<div class="btns">
<a class="btn primary" href="{GITHUB}">GitHub</a>
<a class="btn" href="#video">Demo video</a>
<a class="btn" href="#replay">Try the replay</a>
</div></div>
<div class="term" aria-label="Mock terminal verdict">
<div class="term-h"><span class="dot"></span><span class="dot"></span><span class="dot"></span> mergeguard &middot; verdict</div>
<div class="term-b"><span class="dim">$</span> python -m verifier show task-b-gamed
<span class="bad">task-b-gamed &middot; step 13 &middot; TEST_EDITED &middot; sent back</span>
<span class="dim">attempt 2 &middot;</span> <span class="ok">8 passed</span> <span class="dim">&middot;</span> <span class="ok">MERGE</span>
<span class="dim"># mock terminal — live numbers below come from reports/*.json</span></div>
</div>
</div></div></div>

<main>
<section id="replay"><div class="wrap">
<div class="kicker">01 &middot; Replay</div><h2>Replay a saved run</h2>
<p class="lede">Three saved runs, played back step by step from <span class="mono">reports/*.json</span>. No API calls. The flagged step is shown in red when a flag carries a step number.</p>
<p class="src">data source: {esc(source)}</p>
<div class="tabs" id="tabs" role="tablist"></div>
<div id="simBanner"></div>
<div class="controls">
<button id="playBtn">Play</button>
<button id="skipBtn" class="ghost">Skip to verdict</button>
<button id="restartBtn" class="ghost">Restart</button>
<span class="progress" id="progress"></span>
</div>
<div class="grid2">
<div class="card"><h3>The task</h3><div class="claim" id="taskText"></div>
<h3 style="margin-top:16px">The agent's claim</h3><div class="claim" id="claimText"></div>
<h3 style="margin-top:16px">Claim check</h3><ul class="claimchecks" id="claimChecks"></ul></div>
<div class="card"><h3>Run</h3>
<p class="mono" id="metaLine" style="font-size:13.5px"></p>
<p class="mono" id="originalLine" style="font-size:13.5px"></p>
<p id="flagsLine"></p>
<p class="mono" id="attemptsLine"></p>
<ul class="attempts-list" id="attemptsList"></ul>
<p>Verdict: <span id="verdict"></span></p></div>
</div>
<div class="card" style="margin-top:18px"><h3>Step timeline</h3><ol class="timeline" id="timeline"></ol></div>
</div></section>

<section id="video"><div class="wrap">
<div class="kicker">02 &middot; Watch it</div><h2>Watch it</h2>
<div class="video"><div class="play">&#9654;</div>
<div><b style="color:#fff">Demo video — placeholder</b><br>Video not embedded yet. This box is where the 3-minute demo will go.</div>
<div class="mono" style="font-size:13px">id="video" &middot; replace this placeholder with the recording</div></div>
</div></section>

<section id="how"><div class="wrap">
<div class="kicker">03 &middot; How it works</div><h2>How it works</h2>
<ol class="steps">
<li><b>1. Evidence.</b> Gather what changed (the diff), run the tests for real, and read the agent's step-by-step event log.</li>
<li><b>2. Hard rules.</b> Simple checks with no AI involved. Did the tests actually pass? Were tests deleted, skipped or edited? Were protected files touched?</li>
<li><b>3. Audit the log.</b> An AI auditor goes through the event log and points to the exact step where something went wrong.</li>
<li><b>4. Send it back.</b> Hand the agent the evidence and a fix ticket. Check again, up to 3 tries. Still flagged after 3 tries &rarr; BLOCK.</li>
<li><b>5. Human approval.</b> Risky changes — anything touching sensitive paths or scoring high on risk — wait for a human to approve.</li>
</ol>
<pre class="flow">agent log + diff + real test run
        |
        v
  [1 Evidence] -&gt; [2 Hard rules] -&gt; [3 Audit the log]
        |               |                    |
        +---------------+--------------------+
                        v
                flagged? --no--&gt; risky? --no--&gt; MERGE
                   |               |
                  yes             yes
                   |               |
                   v               v
            [4 Send it back]  [5 Human approval]
              (up to 3 tries)   NEEDS_APPROVAL
                   |
                still flagged --&gt; BLOCK</pre>
</div></section>

<section id="rules"><div class="wrap">
<div class="kicker">04 &middot; Rules</div><h2>Rules</h2>
<p class="big">Real tests decide, not the AI. The AI can add a block, never remove one.</p>
<table><thead><tr><th>Flag code</th><th>What it means</th><th>Enforced</th></tr></thead>
<tbody>{rules_rows}</tbody></table>
<p class="src">{len(codes)} flag codes parsed from verifier/rules.py at build time.</p>
</div></section>

<section id="models"><div class="wrap">
<div class="kicker">05 &middot; Models</div><h2>Models</h2>
<table><thead><tr><th>Model</th><th>Role in MergeGuard</th></tr></thead><tbody>
<tr><td><b>Muse Code</b></td><td>The agent being checked — and it built most of MergeGuard.</td></tr>
<tr><td><b>Muse Spark</b> <span class="dim">(Meta Model API)</span></td><td>Audits the log, writes fix tickets, gives risk reasons.</td></tr>
</tbody></table>
</div></section>

<section id="numbers"><div class="wrap">
<div class="kicker">06 &middot; Numbers</div><h2>Numbers</h2>
<p class="lede">Filled from the report JSON at build time. Missing values show —, never a guess.</p>
<div class="stats">
<div class="stat"><div class="num">{len(codes) if codes else "—"}</div><div class="lab">Hard rules</div><div class="note">flag codes in verifier/rules.py</div></div>
<div class="stat"><div class="num">{fmt_attempts(reports)}</div><div class="lab">Attempts to fix</div><div class="note">total attempts across saved reports ({len(reports)} runs)</div></div>
<div class="stat"><div class="num">{fmt_cost(reports)}</div><div class="lab">Cost per check</div><div class="note">mean cost_usd across saved reports</div></div>
</div>
<p class="src">source: {esc(source)} &middot; rebuild with: python3 site/build.py</p>
</div></section>

<section id="built"><div class="wrap">
<div class="kicker">07 &middot; Built during the hackathon</div><h2>Built during the hackathon</h2>
<div class="person">{photo_img}<div><p class="big" style="margin:0">Pam Villalon, solo.</p>
<div class="person-links"><a href="https://linkedin.com/in/pama8">LinkedIn</a><a href="https://github.com/PamAntonio">GitHub</a></div></div></div>
</div></section>

<section id="run"><div class="wrap">
<div class="kicker">08 &middot; Run it</div><h2>Run it</h2>
<h3 class="mono" style="color:#fff">Setup</h3>
<pre class="cmd">git clone {GITHUB}
cd mergeguard/verifier
python3 -m venv .venv &amp;&amp; source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your keys — never commit .env</pre>
<h3 class="mono" style="color:#fff">Commands (from verifier/cli.py)</h3>
<pre class="cmd"># print a session's numbered steps
python -m verifier steps --log &lt;path&gt; [--task &lt;task&gt;] [--json]

# evidence + hard rules only, no AI calls
python -m verifier rules --repo ../demo-shop --branch task-b --base bug-base \\
                         --claims ../demo-shop/.claims/task-b.md --log &lt;path&gt;

# full check: rules + audit (+ risk reason on sensitive paths)
python -m verifier verify --repo ../demo-shop --branch task-b --base bug-base \\
                          --claims ../demo-shop/.claims/task-b.md --log &lt;path&gt;

# send it back: fix loop, up to 3 attempts
python -m verifier fix --repo ../demo-shop --branch task-b --base bug-base \\
                       --claims ../demo-shop/.claims/task-b.md --log &lt;path&gt;

# show a saved report + replay its steps (no API calls)
python -m verifier show task-b

# rebuild this page from reports/*.json
python3 site/build.py</pre>
</div></section>
</main>

<footer><div class="wrap">
<a href="{GITHUB}">Repo</a><a href="#video">Video</a><a href="#top">Back to top</a>
<span class="dim">MergeGuard &middot; AIE Code Summit Hackathon</span>
</div></footer>
<script>{js}</script>
</body></html>
"""
    for out in OUTS:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
        print(f"wrote {out} ({len(page)} bytes) from {source}, {len(data)} replay runs, {len(codes)} rules")


if __name__ == "__main__":
    build()
