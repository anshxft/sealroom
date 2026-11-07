"""Shared vs sealed review, as set out in PROTOCOL.md.

    python run.py          # real run: 30 reviewer calls and 10 grader calls
    python run.py --fake   # stubbed calls, checks the pipeline end to end
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

HERE = Path(__file__).parent
RESULTS = HERE / "results"
MODEL = "sonnet"
NO_TOOLS = ["Edit", "Write", "Read", "Glob", "Grep", "WebFetch",
            "WebSearch", "NotebookEdit", "Task", "Agent", "TodoWrite"]
FAKE = "--fake" in sys.argv


def reviewer_briefs():
    template = yaml.safe_load((HERE.parent / "sealroom.template.yaml").read_text(encoding="utf-8"))
    briefs = {a["name"].split("-")[-1].upper(): a["instructions"]
              for a in template["agents"] if "reviewer" in a["name"]}
    assert sorted(briefs) == ["A", "B", "C"], briefs
    return briefs


def claude(prompt, system):
    if FAKE:
        if "Known problems" in system:
            ids = re.findall(r"^- (\w+):", prompt, re.M)
            return json.dumps({i: (["A"] if n == 0 else []) for n, i in enumerate(ids)})
        return "VERDICT: BLOCK\nCONFIDENCE: 4\nREASON: fake"
    # Prompt on stdin and system prompt in a file: a Windows .cmd shim cuts
    # command-line arguments at the first newline.
    # A finished claude.exe can hold its folder for a moment on Windows.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as empty, \
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as aside:
        system_file = Path(aside) / "system.md"
        system_file.write_text(system, encoding="utf-8")
        out = subprocess.run(
            [shutil.which("claude.exe") or shutil.which("claude"), "-p", "--model", MODEL,
             "--append-system-prompt-file", str(system_file), "--no-session-persistence",
             "--strict-mcp-config", "--disallowedTools", *NO_TOOLS],
            input=prompt, cwd=empty, capture_output=True, text=True, encoding="utf-8",
            timeout=600)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"claude failed ({out.returncode}): {out.stderr[-500:]}")
    return out.stdout.strip()


def cached(path, make):
    """Each answer is saved as it arrives, so a rerun only redoes what failed."""
    if FAKE:
        return make()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(make(), encoding="utf-8")
    return path.read_text(encoding="utf-8")


def ask(diff, earlier):
    room = "".join(f"@sr-reviewer-{who.lower()}: {text}\n\n" for who, text in earlier)
    prefix = f"Earlier in this room:\n\n{room}" if room else ""
    return f"{prefix}review this change:\n{diff}"


def review(mode, change, who, prompt, brief):
    return cached(RESULTS / "raw" / mode / change["id"] / f"{who}.txt",
                  lambda: claude(prompt, brief))


def sealed(change, briefs):
    return {who: review("sealed", change, who, ask(change["diff"], []), brief)
            for who, brief in briefs.items()}


def shared(change, briefs):
    answers = []
    for who, brief in briefs.items():
        answers.append((who, review("shared", change, who, ask(change["diff"], answers), brief)))
    return dict(answers)


GRADER = """You grade code reviews against a list of known problems.
Known problems are listed in the message. A problem counts as found by a
reviewer only when that reviewer's text names that specific problem
explicitly. A vague worry does not count. Reply with only a JSON object
mapping each problem id to the list of reviewers (A, B, C) who found it."""


def grade(mode, change, reviews):
    bugs = "\n".join(f"- {bid}: {text}" for bid, text in change["bugs"].items())
    body = "\n\n".join(f"Reviewer {who}:\n{text}" for who, text in reviews.items())
    prompt = f"Change:\n{change['diff']}\n\nKnown problems:\n{bugs}\n\nReviews:\n\n{body}"
    raw = cached(RESULTS / "grades" / f"{mode}-{change['id']}.txt",
                 lambda: claude(prompt, GRADER + "\nKnown problems are given; grade only those."))
    found = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    assert set(found) == set(change["bugs"]), (change["id"], found)
    return found


def verdicts(reviews):
    return {who: (re.search(r"VERDICT:\s*(SHIP|BLOCK)", text) or [None, "?"])[1]
            for who, text in reviews.items()}


def main():
    changes = json.loads((HERE / "changes.json").read_text(encoding="utf-8"))
    briefs = reviewer_briefs()
    out = RESULTS / ("fake" if FAKE else "")
    with ThreadPoolExecutor(max_workers=5) as pool:
        runs = {(mode, c["id"]): pool.submit(fn, c, briefs)
                for c in changes for mode, fn in (("sealed", sealed), ("shared", shared))}
        reviews = {key: f.result() for key, f in runs.items()}
        graded = {key: pool.submit(grade, key[0], next(c for c in changes if c["id"] == key[1]), r)
                  for key, r in reviews.items()}
        grades = {key: f.result() for key, f in graded.items()}

    rows = []
    for (mode, cid), r in reviews.items():
        folder = out / "raw" / mode / cid
        folder.mkdir(parents=True, exist_ok=True)
        for who, text in r.items():
            (folder / f"{who}.txt").write_text(text, encoding="utf-8")
        g = grades[(mode, cid)]
        v = verdicts(r)
        rows.append({"mode": mode, "change": cid, "verdicts": v, "found": g,
                     "distinct": sum(bool(w) for w in g.values()),
                     "redundant": sum(len(w) > 1 for w in g.values()),
                     "split": len(set(v.values())) > 1})
    (out / "grades.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    lines = ["| Condition | Distinct problems found (of 10) | Found by 2+ reviewers | Split verdicts |",
             "| --- | --- | --- | --- |"]
    for mode in ("sealed", "shared"):
        mine = [r for r in rows if r["mode"] == mode]
        lines.append(f"| {mode} | {sum(r['distinct'] for r in mine)} | "
                     f"{sum(r['redundant'] for r in mine)} | {sum(r['split'] for r in mine)} of 5 |")
    lines += ["", "| Change | Problem | Sealed: found by | Shared: found by |", "| --- | --- | --- | --- |"]
    for c in changes:
        s = next(r for r in rows if r["mode"] == "sealed" and r["change"] == c["id"])
        h = next(r for r in rows if r["mode"] == "shared" and r["change"] == c["id"])
        for bid in c["bugs"]:
            lines.append(f"| {c['id']} | {bid} | {', '.join(s['found'][bid]) or '-'} | "
                         f"{', '.join(h['found'][bid]) or '-'} |")
    (out / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return rows


if __name__ == "__main__":
    rows = main()
    assert len(rows) == 10 and all(len(r["verdicts"]) == 3 for r in rows)
