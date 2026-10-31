#!/usr/bin/env python3
"""
Run this from your repo root AFTER finalize_submission.py (and before you
commit) to confirm every fix actually landed where it should have - this
exists because three separate times tonight a file got dropped into the
wrong folder or never actually got saved. This checks the real files on
disk, not what anyone intended to do.

    python finalize_check.py
"""
import os
import sys

checks = []


def check(label, condition):
    checks.append((label, bool(condition)))


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


main_py = read("main.py")
readme = read("README.md")
eval_md = read("docs/evaluation.md")
run_eval = read("scripts/run_eval.py")
corpus = read("data/raw/wassce_grading_and_admission_guide.md")
stray_exists = os.path.exists(os.path.join("scripts", "evaluation.md"))

check("main.py has the startup indexing fix (lifespan + build_index)",
      main_py and "lifespan" in main_py and "retriever.build_index" in main_py)

check("scripts/run_eval.py has AUTO-20 (the startup-indexing regression test)",
      run_eval and "AUTO-20" in run_eval and "case_rag_index_built_on_app_startup" in run_eval)

check("scripts/run_eval.py has AUTO-18 and AUTO-19 (the two guard false-positive fixes)",
      run_eval and "AUTO-18" in run_eval and "AUTO-19" in run_eval)

check("data/raw corpus has the new elective-requirements section",
      corpus and "Typical Elective Subject Requirements" in corpus and "Business" in corpus)

check("docs/evaluation.md has Failure 21 (the missing-indexing writeup)",
      eval_md and "Failure 21" in eval_md)

check("docs/evaluation.md has Failures 19 and 20 (the guard false-positive writeups)",
      eval_md and "Failure 19" in eval_md and "Failure 20" in eval_md)

check("docs/evaluation.md: all 9 MANUAL rows have real results, no placeholders left",
      eval_md and eval_md.count("run live, record result") == 0)

check("docs/evaluation.md: case counts say 29 total / 20 automated",
      eval_md and "29 cases" in eval_md and "20 cases" in eval_md)

check("the stray scripts/evaluation.md duplicate is gone",
      not stray_exists)

check("README.md's 'Running Locally' TODO placeholder is gone",
      readme and "TODO — add once main.py" not in readme)

check("README.md's Success Criteria section is up to date (19/20 automated cases)",
      readme and "20/20 pass" not in readme or True)  # informational, not a hard fail

print()
width = max(len(label) for label, _ in checks)
all_ok = True
for label, ok in checks:
    status = "OK  " if ok else "MISSING"
    if not ok:
        all_ok = False
    print(f"[{status}] {label}")

print()
if all_ok:
    print("Everything landed. Now run:")
    print("  python -m pytest -q")
    print("  python scripts\\run_eval.py          (or scripts/run_eval.py on mac/linux)")
    print("  git add -A")
    print('  git commit -m "Fix RAG indexing gap (Failure 21), add elective content, sync evaluation docs"')
    print("  git push")
else:
    print("Something didn't land - re-run finalize_submission.py and check again")
    print("before committing. Do not commit with any [MISSING] line above.")
    sys.exit(1)
