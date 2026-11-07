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


def cmd_show(args):
    path = os.path.join(REPORTS, f"{args.task}.json")
    if not os.path.exists(path):
        print(f"no saved report for {args.task} ({path})")
        return 1
    with open(path, encoding="utf-8") as fh:
        report = json.load(fh)
    print(json.dumps(report, indent=2))
    steps = report.get("steps") or []
    if steps:
        print(f"--- replay: {len(steps)} steps (saved, no API calls) ---")
        _print_steps(steps)
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

    p = sub.add_parser("show")
    p.add_argument("task")
    p.set_defaults(fn=cmd_show)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
