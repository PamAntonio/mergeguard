"""Evidence gathering: diff, real test run, event-log reader (SPEC 6/13)."""

import json
import os
import re
import subprocess
import sys

IGNORED_PATH_SEGMENTS = frozenset({".claims"})
_EDIT_TOOLS = {"write_file", "edit_file", "apply_patch"}
_FILE_RE = re.compile(r"[\w./-]+\.(?:py|md|ini|toml|json)")


def is_ignored_path(path):
    parts = [p for p in str(path).replace("\\", "/").split("/") if p not in ("", ".")]
    return any(part in IGNORED_PATH_SEGMENTS for part in parts)


def exclude_ignored(paths):
    return [p for p in paths if not is_ignored_path(p)]


def _records(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            children = rec.get("children")
            if isinstance(children, list) and "record_json" in str(children)[:200]:
                for child in children:
                    raw = child.get("record_json") if isinstance(child, dict) else None
                    if raw:
                        try:
                            yield json.loads(raw)
                        except json.JSONDecodeError:
                            pass
            else:
                yield rec


def _args_detail(args_raw):
    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
    except json.JSONDecodeError:
        return str(args_raw)[:200], []
    if not isinstance(args, dict):
        return str(args)[:200], []
    detail = (args.get("command") or args.get("description")
              or args.get("path") or args.get("pattern") or "")
    files = []
    for key in ("path", "workdir"):
        if args.get(key):
            files.append(str(args[key]))
    files += [f for f in _FILE_RE.findall(str(detail)) if "/" in f or f.startswith("test")]
    return str(detail)[:240], sorted(set(files))


def parse_steps(log_path):
    """Turn a Muse session.jsonl into numbered steps (SPEC section 6)."""
    steps = []
    by_call = {}
    for rec in _records(log_path):
        payload = rec.get("payload") or {}
        event = payload.get("event") or {}
        kind = event.get("kind")
        if payload.get("kind") != "run":
            continue
        if kind == "started" and event.get("prompt"):
            steps.append({"n": len(steps) + 1, "kind": "other", "tool": "user",
                          "detail": str(event["prompt"])[:240], "files": [],
                          "result": "", "ok": True})
        elif kind == "assistant_tool_calls_committed":
            for call in event.get("tool_calls") or []:
                detail, files = _args_detail(call.get("args"))
                name = call.get("name", "tool")
                step = {"n": len(steps) + 1,
                        "kind": "edit" if name in _EDIT_TOOLS else "tool_call",
                        "tool": name, "detail": detail, "files": files,
                        "result": "", "ok": True}
                steps.append(step)
                if call.get("call_id"):
                    by_call[call["call_id"]] = step
        elif kind == "tool_result_batch_committed":
            for res in event.get("results") or []:
                step = by_call.get(res.get("tool_call_id"))
                if step is None:
                    continue
                text = str(res.get("text", ""))
                ok, summary = True, text[:160].replace("\n", " ")
                try:
                    data = json.loads(text)
                    out = str(data.get("output", "")).strip().splitlines()
                    summary = (f"exit={data.get('exit_code')} "
                               + (out[0][:140] if out else ""))[:200]
                    ok = data.get("exit_code") in (0, None) and data.get("terminal_status") != "failed"
                except (json.JSONDecodeError, AttributeError):
                    pass
                step["result"] = summary
                step["ok"] = bool(ok)
        elif kind == "assistant_message_committed" and event.get("text"):
            steps.append({"n": len(steps) + 1, "kind": "model_call", "tool": "model",
                          "detail": str(event["text"])[:240], "files": [],
                          "result": "", "ok": True})
    return steps


def slice_task_steps(steps, branch):
    """Steps from the prompt that starts `branch`'s task to the next prompt."""
    if not branch:
        return steps
    markers = (f".claims/{branch}.md", f"checkout -b {branch} ", f"checkout -b {branch}\n",
               f"checkout {branch} ", f"checkout {branch}\n", f"branch {branch} ")
    start = None
    for i, step in enumerate(steps):
        if step.get("tool") != "user":
            continue
        detail = str(step.get("detail", ""))
        if any(m in detail for m in markers):
            start = i
            break
    if start is None:
        return steps
    out = []
    for step in steps[start:]:
        if out and step.get("tool") == "user":
            break
        out.append(step)
    for i, step in enumerate(out, 1):
        step = dict(step)
        step["n"] = i
        out[i - 1] = step
    return out


def default_log_root():
    override = os.environ.get("MUSE_CODE_LOG_DIR", "").strip()
    if override:
        return override
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    base = xdg or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "muse", "sessions")


def find_task_logs(branches):
    """Map each branch to the session.jsonl whose prompts ran its task."""
    root = default_log_root()
    found = {}
    candidates = []
    for dirpath, _dirs, files in os.walk(root):
        if "session.jsonl" in files and "subagent" not in dirpath:
            candidates.append(os.path.join(dirpath, "session.jsonl"))
    for path in sorted(candidates):
        try:
            steps = parse_steps(path)
        except OSError:
            continue
        prompts = " ".join(s["detail"] for s in steps if s.get("tool") == "user")
        if "demo-shop" not in prompts and "claims" not in prompts:
            continue
        for branch in branches:
            if branch not in found and branch in prompts:
                found[branch] = path
    return found


def git(repo, *args, timeout=120):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=timeout)


def ensure_worktree(repo, branch, work_root):
    """Detached worktree for `branch`; never touches repo's checkout."""
    dest = os.path.join(str(work_root), branch)
    if os.path.exists(os.path.join(dest, ".git")) or os.path.exists(dest):
        if os.path.isdir(dest):
            return dest
    os.makedirs(work_root, exist_ok=True)
    git(repo, "worktree", "prune")
    res = git(repo, "worktree", "add", "--detach", dest, branch)
    if res.returncode != 0:
        raise RuntimeError(f"worktree failed for {branch}: {res.stderr.strip()}")
    return dest


def get_diff(repo, base, branch):
    res = git(repo, "diff", f"{base}...{branch}")
    return res.stdout if res.returncode == 0 else ""


def changed_files(repo, base, branch):
    res = git(repo, "diff", "--name-only", f"{base}...{branch}")
    if res.returncode != 0:
        return []
    return exclude_ignored([l for l in res.stdout.splitlines() if l.strip()])


def run_tests(worktree, repo):
    exe = os.path.join(os.path.abspath(str(repo)), ".venv", "bin", "python")
    if not os.path.exists(exe):
        exe = sys.executable
    try:
        res = subprocess.run([exe, "-m", "pytest", "-q"], cwd=worktree,
                             capture_output=True, text=True, timeout=120)
        out = (res.stdout + res.stderr).strip()
        summary = out.splitlines()[-1] if out else ""
        return {"exit_code": res.returncode, "summary": summary, "output": out[-3000:]}
    except subprocess.TimeoutExpired:
        return {"exit_code": 124, "summary": "timeout after 120s", "output": "timeout"}
