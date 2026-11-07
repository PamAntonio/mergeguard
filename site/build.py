#!/usr/bin/env python3
"""Build the MergeGuard one-page site (minimalist redesign).

Reads reports/*.json (falls back to site/sample/*.json) and writes ONE
self-contained HTML file to both site/index.html and docs/index.html.
No CDNs, no web fonts, no frameworks.
Run:  python3 site/build.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = Path(__file__).resolve().parent
REPORTS_DIR = ROOT / "reports"
SAMPLE_DIR = SITE / "sample"
OUTS = [SITE / "index.html", ROOT / "docs" / "index.html"]
GITHUB = "https://github.com/PamAntonio/mergeguard"
TABS = [("Honest", "task-b"), ("Cheated", "task-b-gamed"), ("Risky", "task-c")]


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


def replay_payload(reports):
    by_task = {r.get("task"): r for r in reports}
    out = []
    for label, task in TABS:
        r = by_task.get(task)
        if not r:
            continue
        steps = r.get("steps") or []
        flags = r.get("flags") or []
        reasons = {}
        for f in flags:
            if isinstance(f.get("step"), int):
                reasons[str(f["step"])] = f"{f.get('code', 'FLAGGED')} — {f.get('detail', '')}".strip(" —")
        for s in (r.get("audit") or {}).get("suspicious_steps", []):
            if isinstance(s.get("step"), int):
                reasons.setdefault(str(s["step"]),
                                   s.get("detail") or s.get("what") or "Suspicious step")
        task_text = (steps[0].get("detail") or "")[:600] if steps else ""
        out.append({
            "label": label, "task": r.get("task"),
            "decision": r.get("decision") or "—",
            "attempts": r.get("attempts"), "flags": flags,
            "tests": r.get("tests") or {}, "risk": r.get("risk") or {},
            "claim": r.get("claim") or "", "steps": steps,
            "flagged": sorted(int(k) for k in reasons), "reasons": reasons,
            "taskText": task_text,
        })
    return out


CSS = """
:root{--bg:#FAFAF7;--text:#1F2328;--muted:#6B7280;--line:#E5E7EB;--accent:#2563EB;--green:#16A34A;--red:#DC2626;--amber:#D97706}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:18px;line-height:1.6}
.col{max-width:820px;margin:0 auto;padding:0 24px}
a{color:var(--accent)}
.mono,code,pre{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
header{padding:28px 0 0}
.wordmark{font-size:15px;font-weight:600;letter-spacing:.01em}
.hero{padding:48px 0 0}
h1{font-size:42px;line-height:1.15;font-weight:700;margin:0 0 16px;letter-spacing:-.02em}
@media(max-width:600px){h1{font-size:32px}}
.hero p{margin:0 0 24px;max-width:36em}
.btn{display:inline-block;padding:10px 20px;border:1px solid var(--accent);border-radius:6px;text-decoration:none;font-size:16px;margin-right:10px;background:transparent;color:var(--accent)}
.btn.primary{background:var(--accent);color:#fff}
.btn:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.muted{color:var(--muted)}
.hero .muted{font-size:16px;margin-top:4px}
section{margin-top:64px}
h2{font-size:24px;font-weight:700;margin:0 0 16px}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}
.tab{padding:8px 16px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--text);font:inherit;font-size:16px;cursor:pointer}
.tab[aria-selected="true"]{border-color:var(--accent);color:var(--accent);font-weight:600}
.quote{border:1px solid var(--line);border-radius:6px;background:#fff;padding:16px 20px;margin-bottom:20px}
.quote p{margin:0 0 12px;white-space:pre-wrap;word-break:break-word}
.quote p:last-child{margin-bottom:0}
.quote .qlabel{font-size:14px;color:var(--muted);margin-bottom:4px}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:16px}
.controls button{padding:8px 18px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--text);font:inherit;font-size:16px;cursor:pointer}
.controls button#playBtn{border-color:var(--accent);color:var(--accent);font-weight:600}
.progress{color:var(--muted);font-size:15px}
.timeline{list-style:none;margin:0;padding:0}
.timeline li{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:14px;line-height:1.5;padding:8px 12px;border:1px solid var(--line);border-radius:6px;background:#fff;margin-bottom:6px;word-break:break-word}
.timeline li.flagged{border-color:var(--red)}
.timeline .reason{display:block;color:var(--red);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:15px;margin-top:4px}
.attempts{margin:16px 0 0}
.badge{display:inline-block;font-size:22px;font-weight:700;padding:8px 18px;border:2px solid var(--text);border-radius:6px;margin-top:16px}
.badge.MERGE,.badge.FIXED_THEN_MERGE{color:var(--green);border-color:var(--green)}
.badge.BLOCK{color:var(--red);border-color:var(--red)}
.badge.NEEDS_APPROVAL{color:var(--amber);border-color:var(--amber)}
ol.plain{margin:0;padding-left:24px}
ol.plain li{margin-bottom:8px}
.codeblock{position:relative;margin:8px 0 20px}
.codeblock pre{background:#fff;border:1px solid var(--line);border-radius:6px;padding:16px;overflow:auto;font-size:14px;line-height:1.6;margin:0;white-space:pre-wrap;word-break:break-word}
.copy{position:absolute;top:8px;right:8px;padding:4px 12px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--accent);font:inherit;font-size:14px;cursor:pointer}
.stepnum{font-weight:700}
footer{margin:64px 0 48px;padding-top:24px;border-top:1px solid var(--line);color:var(--muted);font-size:16px}
footer a{text-decoration:none}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
"""

JS = """
const DATA = __DATA__;
const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let idx = 0, pos = 0, timer = null;
const $ = s => document.querySelector(s);
function stop(){ if(timer){ clearInterval(timer); timer = null; $("#playBtn").textContent = "Play"; } }
function renderTabs(){
  $("#tabs").innerHTML = DATA.map((r,i) =>
    `<button class="tab" role="tab" id="tab-${i}" aria-selected="${i===idx}" aria-controls="replayPanel" tabindex="${i===idx?0:-1}" data-i="${i}">${r.label}</button>`).join("");
  document.querySelectorAll(".tab").forEach(b => {
    b.addEventListener("click", () => select(+b.dataset.i, true));
    b.addEventListener("keydown", e => {
      let n = null;
      if(e.key === "ArrowRight") n = (idx + 1) % DATA.length;
      if(e.key === "ArrowLeft") n = (idx - 1 + DATA.length) % DATA.length;
      if(e.key === "Home") n = 0;
      if(e.key === "End") n = DATA.length - 1;
      if(n !== null){ e.preventDefault(); select(n, true); }
    });
  });
}
function select(i, focus){
  stop(); idx = i; pos = 0; render();
  if(focus){ const t = document.getElementById("tab-" + i); if(t) t.focus(); }
}
function render(){
  renderTabs();
  const r = DATA[idx]; if(!r) return;
  const flagged = new Set(r.flagged || []);
  $("#taskText").textContent = r.taskText || "(no saved task text)";
  $("#claimText").textContent = r.claim || "(no claim saved)";
  $("#timeline").innerHTML = (r.steps || []).slice(0, pos).map(s => {
    const isF = flagged.has(s.n);
    const reason = isF ? `<span class="reason">Flagged: ${(r.reasons || {})[s.n] || "flagged step"}</span>` : "";
    const detail = String(s.detail || "").slice(0, 220);
    const result = s.result ? " -> " + String(s.result).slice(0, 120) : "";
    return `<li class="${isF ? "flagged" : ""}">${s.n} [${s.kind || ""}] ${s.tool || ""}: ${detail}${result}${reason}</li>`;
  }).join("");
  const total = (r.steps || []).length, done = pos >= total;
  $("#progress").textContent = total ? `Step ${Math.min(pos, total)} of ${total}` : "";
  $("#attemptsLine").textContent = done
    ? (r.attempts == null ? "Fix attempts: —" : `Fix attempts: ${r.attempts}`) : "";
  $("#verdict").innerHTML = done ? `<span class="badge ${r.decision}">${r.decision}</span>` : "";
}
$("#playBtn").addEventListener("click", () => {
  if(timer){ stop(); return; }
  const r = DATA[idx]; if(!r) return;
  if(pos >= (r.steps || []).length) pos = 0;
  if(REDUCED){ pos = (r.steps || []).length; render(); return; }
  $("#playBtn").textContent = "Pause";
  timer = setInterval(() => {
    pos++; render();
    if(pos >= (DATA[idx].steps || []).length) stop();
  }, 600);
});
$("#stepBtn").addEventListener("click", () => {
  stop();
  const r = DATA[idx];
  if(pos < (r.steps || []).length){ pos++; render(); }
});
$("#resetBtn").addEventListener("click", () => { stop(); pos = 0; render(); });
document.querySelectorAll(".copy").forEach(b => b.addEventListener("click", async () => {
  const pre = document.getElementById(b.dataset.target);
  const text = pre ? pre.innerText : "";
  try { await navigator.clipboard.writeText(text); }
  catch(e){
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove();
  }
  b.textContent = "Copied"; setTimeout(() => { b.textContent = "Copy"; }, 1600);
}));
render();
"""


def build():
    reports, source = load_reports()
    data = replay_payload(reports)
    data_json = json.dumps(data).replace("</", "<\\/")
    js = JS.replace("__DATA__", data_json)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MergeGuard — Your agent says all tests pass. Prove it.</title>
<style>{CSS}</style></head>
<body id="top">
<div class="col">
<header><div class="wordmark">MergeGuard</div></header>

<div class="hero">
<h1>Your agent says all tests pass. Prove it.</h1>
<p>MergeGuard reads a coding agent's step-by-step log, finds the exact step where it cut a corner, and sends it back until the fix is real.</p>
<p>
<a class="btn primary" href="#replay">Try the replay</a>
<a class="btn" href="{GITHUB}">GitHub</a>
</p>
<p class="muted">Muse Code writes the code. Muse Spark audits it. Real tests decide.</p>
</div>

<main>
<section id="replay" aria-labelledby="replay-h">
<h2 id="replay-h">Replay</h2>
<div class="tabs" id="tabs" role="tablist" aria-label="Saved runs"></div>
<div id="replayPanel" role="tabpanel">
<div class="quote">
<div class="qlabel">Task</div>
<p id="taskText"></p>
<div class="qlabel">The agent's claim</div>
<p id="claimText"></p>
</div>
<div class="controls">
<button id="playBtn" type="button">Play</button>
<button id="stepBtn" type="button">Step</button>
<button id="resetBtn" type="button">Reset</button>
<span class="progress" id="progress" aria-live="polite"></span>
</div>
<ol class="timeline" id="timeline"></ol>
<p class="attempts" id="attemptsLine"></p>
<div id="verdict" aria-live="polite"></div>
</div>
<p class="muted" style="font-size:15px">Saved runs from {source} — no API calls. Rebuild with <span class="mono">python3 site/build.py</span>.</p>
</section>

<section aria-labelledby="how-h">
<h2 id="how-h">How it works</h2>
<ol class="plain">
<li><b>Evidence.</b> Gather the diff, run the tests for real, and read the agent's step-by-step log.</li>
<li><b>Hard rules.</b> Plain checks, no AI: did the tests pass, and were any tests deleted, skipped, or edited?</li>
<li><b>Audit the log.</b> Muse Spark points to the exact step where something went wrong.</li>
<li><b>Send it back.</b> Hand the agent the evidence and a fix ticket. Check again, up to 3 tries.</li>
<li><b>Human approval.</b> Risky changes wait for a person to approve them.</li>
</ol>
</section>

<section id="run" aria-labelledby="run-h">
<h2 id="run-h">Run it</h2>

<p><span class="stepnum">1. Install</span></p>
<div class="codeblock"><button class="copy" type="button" data-target="code-install">Copy</button>
<pre id="code-install">git clone {GITHUB}
cd mergeguard/verifier
python3 -m venv .venv &amp;&amp; source .venv/bin/activate
pip install -r requirements.txt</pre></div>

<p><span class="stepnum">2. Add your Meta Model API key to .env</span></p>
<div class="codeblock"><button class="copy" type="button" data-target="code-env">Copy</button>
<pre id="code-env">cp .env.example .env
# then edit .env and set:
META_API_KEY=your-key-here
META_BASE_URL=
AUDITOR_MODEL=muse-spark-1.3</pre></div>

<p><span class="stepnum">3. Run the commands</span></p>
<div class="codeblock"><button class="copy" type="button" data-target="code-run">Copy</button>
<pre id="code-run"># numbered steps from a session log
python -m verifier steps --log &lt;path&gt; [--task &lt;task&gt;] [--json]

# evidence + hard rules only, no AI
python -m verifier rules --repo ../demo-shop --branch task-b --base bug-base --claims ../demo-shop/.claims/task-b.md --log &lt;path&gt;

# full check
python -m verifier verify --repo ../demo-shop --branch task-b --base bug-base --claims ../demo-shop/.claims/task-b.md --log &lt;path&gt;

# send it back (fix loop, up to 3 attempts)
python -m verifier fix --repo ../demo-shop --branch task-b --base bug-base --claims ../demo-shop/.claims/task-b.md --log &lt;path&gt;

# saved report + replay, no API calls
python -m verifier show task-b</pre></div>
</section>

<section aria-labelledby="built-h">
<h2 id="built-h">Built today</h2>
<p>Built by Pam Villalon, solo, during the hackathon. The verifier was built during the event, mostly by Muse Code; the design spec was written the night before; the demo-shop test app was generated with Claude at 10:41 AM; and the README was drafted with Claude.</p>
</section>
</main>

<footer>
<a href="{GITHUB}">GitHub</a> &middot; <a href="#top">Back to top</a>
</footer>
</div>
<script>{js}</script>
</body></html>
"""
    for out in OUTS:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
        print(f"wrote {out} ({len(page)} bytes) from {source}, {len(data)} replay runs")


if __name__ == "__main__":
    build()


