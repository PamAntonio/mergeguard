"""Command-line commands (SPEC section 13)."""

import argparse
import json
import os
import sys
import time

from verifier import evidence, rules

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK_ROOT = os.path.join(HERE, ".work")
REPORTS = os.path.join(HERE, "reports")


def _print_steps(steps):
    for s in steps:
        files = f" files={','.join(s['files'])}" if s.get("files") else ""
        result = f" -> {s['result']}" if s.get("result") else ""
        print(f"{s['n']:>3} [{s['kind']}] {s['tool']}: {s['detail']}{files}{result}")


def cmd_steps(args):
    steps = evidence.parse_steps(args.log)
    steps = evidence.slice_task_steps(steps, args.task)
    if args.json:
        print(json.dumps(steps, indent=2))
    else:
        _print_steps(steps)
    return 0


def gather(repo, branch, base, claims_path, log_path, task=None):
    """Evidence + hard rules for one task branch. No AI calls."""
    worktree = evidence.ensure_worktree(repo, branch, WORK_ROOT)
    diff = evidence.get_diff(repo, base, branch)
    files = evidence.changed_files(repo, base, branch)
    tests = evidence.run_tests(worktree, repo)
    claim = ""
    if claims_path and os.path.exists(claims_path):
        with open(claims_path, encoding="utf-8") as fh:
            claim = fh.read()
    steps = evidence.slice_task_steps(evidence.parse_steps(log_path), task or branch) if log_path else []
    flags = rules.evaluate(diff_text=diff, changed_files=files,
                           test_exit_code=tests["exit_code"],
                           claim_text=claim, steps=steps)
    return {"worktree": worktree, "diff": diff, "files": files, "tests": tests,
            "claim": claim, "steps": steps, "flags": flags}


def cmd_rules(args):
    data = gather(args.repo, args.branch, args.base, args.claims, args.log, args.task)
    out = {"task": args.task or args.branch, "branch": args.branch, "base": args.base,
           "tests": {"exit_code": data["tests"]["exit_code"],
                     "summary": data["tests"]["summary"]},
           "flags": [f.to_dict() for f in data["flags"]],
           "decision_preview": rules.decide(data["flags"])}
    print(json.dumps(out, indent=2))
    return 0


def build_report(task, branch, data, audit_result=None, audit_flags=None,
                 risk=None, attempts=0, fix_loop_ran=False, seconds=0.0):
    from verifier import rules as _rules
    flags = list(data["flags"]) + list(audit_flags or [])
    preview = _rules.decide(flags, attempts=attempts, fix_loop_ran=fix_loop_ran)
    decision = "BLOCK" if preview == "FIX_LOOP" else preview
    if risk and risk.get("score") is not None and risk["score"] >= 7 and decision == "MERGE":
        decision = "NEEDS_APPROVAL"
    return {
        "task": task, "branch": branch, "decision": decision, "attempts": attempts,
        "flags": [f.to_dict() for f in flags],
        "tests": {"exit_code": data["tests"]["exit_code"],
                  "summary": data["tests"]["summary"]},
        "risk": risk or {"score": None, "reason": "", "areas": []},
        "audit": audit_result or {"claims": [], "suspicious_steps": []},
        "claim": data["claim"], "changed_files": data["files"],
        "steps": data["steps"], "seconds": round(seconds, 2), "cost_usd": None,
    }


def save_report(report):
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, f"{report['task']}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    return path


def cmd_verify(args):
    from verifier import audit as audit_mod
    from verifier import risk as risk_mod
    started = time.time()
    task = args.task or args.branch
    data = gather(args.repo, args.branch, args.base, args.claims, args.log, task)
    audit_result, audit_flags, _usage = audit_mod.audit_task(
        data["steps"], data["diff"], data["tests"]["output"], data["claim"])
    risk = None
    codes = {f.code for f in data["flags"]}
    if "SENSITIVE_PATH" in codes:
        risk = risk_mod.risk_reason(data["diff"], data["files"])
    report = build_report(task, args.branch, data, audit_result, audit_flags,
                          risk, seconds=time.time() - started)
    report["attempts_detail"] = []
    report["final_tests"] = report["tests"]
    path = save_report(report)
    print(json.dumps({k: report[k] for k in
                      ("task", "decision", "attempts", "flags", "tests", "risk", "audit")},
                     indent=2))
    print(f"saved {path}")
    return 0


def cmd_fix(args):
    from verifier import audit as audit_mod
    from verifier import fixer
    from verifier import rules as _rules
    started = time.time()
    task = args.task or args.branch
    orig = fixer.ensure_orig_branch(args.repo, args.branch)
    print(f"preserved original as {orig}")
    # ORIGINAL verdict: evidence + audit on the untouched branch first.
    orig_data = gather(args.repo, args.branch, args.base, args.claims, args.log, task)
    audit_result, audit_flags, _u = audit_mod.audit_task(
        orig_data["steps"], orig_data["diff"], orig_data["tests"]["output"],
        orig_data["claim"])
    worktree = fixer.branch_worktree(args.repo, args.branch, WORK_ROOT)
    attempts = 0
    attempts_detail = []
    data = orig_data
    while attempts < 3 and _rules.decide(data["flags"], attempts=attempts) == "FIX_LOOP":
        attempts += 1
        ticket = fixer.build_ticket(data["flags"], data["tests"], args.branch)
        print(f"--- attempt {attempts} ---\n{ticket}")
        ok, detail = fixer.try_muse_code_fix(worktree, ticket)
        actor = "Muse Code via muse exec"
        if not ok:
            print(f"muse exec unavailable/failed ({detail[-200:]}); using Spark patch")
            ok, detail = fixer.spark_patch_fix(worktree, ticket)
            actor = "Muse Spark patch + git apply"
        print(f"fix via {actor}: ok={ok} {detail[-200:]}")
        fixer.commit_if_dirty(worktree, f"fix attempt {attempts} for {args.branch}")
        data = gather(args.repo, args.branch, args.base, args.claims, args.log, task)
        attempts_detail.append({
            "n": attempts, "actor": actor, "ok": bool(ok),
            "flags": [f.to_dict() for f in data["flags"]],
            "tests": {"exit_code": data["tests"]["exit_code"],
                      "summary": data["tests"]["summary"]},
        })
    moved = evidence.git(args.repo, "rev-parse", args.branch).stdout.strip()
    orig_ref = evidence.git(args.repo, "rev-parse", orig).stdout.strip()
    fix_ran = attempts > 0 or (moved and orig_ref and moved != orig_ref)
    report = build_report(task, args.branch, orig_data, audit_result, audit_flags,
                          attempts=attempts, fix_loop_ran=fix_ran,
                          seconds=time.time() - started)
    report["attempts_detail"] = attempts_detail
    report["final_tests"] = {"exit_code": data["tests"]["exit_code"],
                             "summary": data["tests"]["summary"]}
    report["final_flags"] = [f.to_dict() for f in data["flags"]]
    rule_codes = {f.code for f in data["flags"]}
    blocking = rule_codes & (_rules.FIX_LOOP_CODES - {"CLAIM_NO_EVIDENCE"})
    if fix_ran and data["tests"]["exit_code"] == 0 and not blocking:
        report["decision"] = "FIXED_THEN_MERGE"
    if getattr(args, "simulated", False):
        report["simulated"] = True
    report["orig_branch"] = orig
    path = save_report(report)
    print(json.dumps({k: report[k] for k in
                      ("task", "decision", "attempts", "flags", "tests")}, indent=2))
    print(f"saved {path}")
    return 0


def cmd_show(args):
    path = os.path.join(REPORTS, f"{args.task}.json")
    if not os.path.exists(path):
        print(f"no saved report for {args.task} ({path})")
        return 1
    with open(path, encoding="utf-8") as fh:
        report = json.load(fh)
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
        if report.get("steps"):
            print(f"--- replay: {len(report['steps'])} steps (saved, no API calls) ---")
            _print_steps(report["steps"])
        return 0
    from rich.console import Console
    from rich.text import Text
    console = Console(width=100)
    if report.get("simulated"):
        console.print(Text("SIMULATED CHEATER (made by hand)", style="bold white on red"))
    style = {"MERGE": "bold green", "FIXED_THEN_MERGE": "bold green",
             "NEEDS_APPROVAL": "bold yellow", "BLOCK": "bold red"}.get(
                 report.get("decision"), "bold")
    console.print(Text(f"{report.get('task')}  [{report.get('decision')}]", style=style))
    claim = " ".join(str(report.get("claim") or "").split())[:110]
    console.print(f"Claim: {claim}")
    console.print("Original flags:")
    seen = set()
    shown = 0
    for flag in report.get("flags") or []:
        key = (flag.get("code"), flag.get("detail"))
        if key in seen:
            continue
        seen.add(key)
        shown += 1
        step = f" step {flag['step']}" if flag.get("step") else ""
        console.print(
            f"  - ({flag.get('source')}) {flag.get('code')}{step}: "
            f"{str(flag.get('detail'))[:80]}", markup=False)
    if not shown:
        console.print("  - none")
    for item in (report.get("audit") or {}).get("claims") or []:
        verdict = item.get("verified")
        mark = "\u2713 verified" if verdict is True else (
            "\u2717 false" if verdict is False else "? no evidence")
        console.print(f"  {mark}: {str(item.get('claim'))[:80]}")
    for att in report.get("attempts_detail") or []:
        codes = [f.get("code") for f in att.get("flags") or []]
        summary = (att.get("tests") or {}).get("summary", "")
        console.print(f"attempt {att.get('n')}: {att.get('actor')} \u2192 "
                      f"{summary}, flags: {','.join(codes) if codes else 'no flags'}")
    risk = report.get("risk") or {}
    if risk.get("score") is not None or risk.get("reason"):
        console.print(f"Risk: {risk.get('score')}/10 \u2014 {str(risk.get('reason'))[:110]}")
    console.print(Text(f"FINAL: {report.get('decision')}", style=style))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="verifier")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("steps")
    p.add_argument("--log", required=True)
    p.add_argument("--task")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_steps)

    p = sub.add_parser("rules")
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--claims")
    p.add_argument("--log")
    p.add_argument("--task")
    p.set_defaults(fn=cmd_rules)

    p = sub.add_parser("verify")
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--claims")
    p.add_argument("--log")
    p.add_argument("--task")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("fix")
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--claims")
    p.add_argument("--log")
    p.add_argument("--task")
    p.add_argument("--simulated", action="store_true")
    p.set_defaults(fn=cmd_fix)

    p = sub.add_parser("show")
    p.add_argument("task")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_show)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
