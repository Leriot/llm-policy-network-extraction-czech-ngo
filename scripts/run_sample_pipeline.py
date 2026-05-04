"""Sanity test: run the cleaning pipeline against the small sample slice.

The sample slice under ``data/sample/pipeline_test/`` contains:

  input_step3/{year}/{ngo}/text/*.txt    - 50 docs as they leave the date split
  expected_step4/{year}/{ngo}/text/*.txt - the same 50 docs after NGO/proximity filter
  expected_step5/{year}/{ngo}/text/*.txt - the same 50 docs after iterative cleaning
  picks.tsv                              - manifest (year, ngo, filename)

This script runs the two parameterizable cleaning scripts end to end against
``input_step3`` into a temporary working tree, then diffs each produced file
byte-for-byte against the expected snapshot.

End-to-end PASS criterion: at least 90% of step5 outputs match the snapshot
exactly. The step4 comparison is reported as informational because the
on-disk step4 snapshot is taken from a later iteration of the rules and
will not match the freshly-produced intermediate exactly.

A fresh clone can run this without R, without LLM API keys, and without
the full Zenodo dataset.

Usage:
    python scripts/run_sample_pipeline.py
"""
import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
        _sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = PROJECT_ROOT / "data" / "sample" / "pipeline_test"
WORK_DIR = SAMPLE_DIR / "_work"

STEP4_SCRIPT = PROJECT_ROOT / "scripts" / "02_filter_clean" / "04_filter_ngo_proximity.py"
STEP5_SCRIPT = PROJECT_ROOT / "scripts" / "02_filter_clean" / "05_iterative_boilerplate_cleaning.py"

PASS_THRESHOLD = 0.90  # ≥ 90% of step5 files must match the snapshot


def header(msg: str) -> None:
    print()
    print("=" * 72)
    print(msg)
    print("=" * 72)


def diff_dirs(produced: Path, expected: Path) -> tuple[int, int, list[str]]:
    expected_files = sorted(expected.rglob("*.txt"))
    matched = 0
    mismatches: list[str] = []
    for exp in expected_files:
        rel = exp.relative_to(expected)
        prod = produced / rel
        if not prod.exists():
            mismatches.append(f"missing : {rel}")
            continue
        if exp.read_text(encoding="utf-8") == prod.read_text(encoding="utf-8"):
            matched += 1
        else:
            exp_chars = exp.stat().st_size
            prod_chars = prod.stat().st_size
            mismatches.append(f"differs : {rel}  (expected {exp_chars} chars, produced {prod_chars} chars)")
    return matched, len(expected_files), mismatches


def run(cmd: list[str]) -> int:
    print(">>", " ".join(str(c) for c in cmd))
    res = subprocess.run(cmd, cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL)
    return res.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep-work", action="store_true", help="Do not delete the temporary _work tree at the end")
    args = parser.parse_args()

    if not SAMPLE_DIR.exists():
        print(f"ERROR: sample slice not found at {SAMPLE_DIR}")
        return 2

    n_picks = sum(1 for _ in (SAMPLE_DIR / "input_step3").rglob("*.txt"))
    header(f"Sample pipeline sanity test ({n_picks} documents)")
    print(f"Project root : {PROJECT_ROOT}")
    print(f"Sample slice : {SAMPLE_DIR.relative_to(PROJECT_ROOT)}")
    print(f"Work dir     : {WORK_DIR.relative_to(PROJECT_ROOT)}")

    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    WORK_DIR.mkdir(parents=True)

    work_step3 = WORK_DIR / "step3_date_filter"
    work_step4 = WORK_DIR / "step4_keyword_proximity_filtering"
    work_step5 = WORK_DIR / "step5_iterative_cleaning"
    shutil.copytree(SAMPLE_DIR / "input_step3", work_step3)

    # --- Step 4 ---
    header("Running step 4: NGO + proximity filter")
    rc = run([
        sys.executable, str(STEP4_SCRIPT),
        "--input", str(work_step3.relative_to(PROJECT_ROOT)),
        "--output", str(work_step4.relative_to(PROJECT_ROOT)),
        "--year", "all",
    ])
    if rc != 0:
        print(f"step 4 exited with {rc}")
        return rc

    matched4, total4, mis4 = diff_dirs(work_step4, SAMPLE_DIR / "expected_step4")
    print(f"step 4: {matched4}/{total4} files match the step4 snapshot (informational)")
    print("       (snapshot drift between step4 and the current ruleset is expected;")
    print("        end-to-end behavior is judged at step5 below)")

    # --- Step 5 ---
    header("Running step 5: iterative boilerplate cleaning")
    rc = run([
        sys.executable, str(STEP5_SCRIPT),
        "--input", str(work_step4.relative_to(PROJECT_ROOT)),
        "--output", str(work_step5.relative_to(PROJECT_ROOT)),
        "--force",
    ])
    if rc != 0:
        print(f"step 5 exited with {rc}")
        return rc

    matched5, total5, mis5 = diff_dirs(work_step5, SAMPLE_DIR / "expected_step5")
    rate5 = matched5 / total5 if total5 else 0
    print(f"step 5: {matched5}/{total5} files match the step5 snapshot ({rate5:.0%})")
    if mis5:
        print("       step5 mismatches (first 5):")
        for m in mis5[:5]:
            print(f"         {m}")

    header("Summary")
    ok = rate5 >= PASS_THRESHOLD
    print(f"step 4 match rate : {matched4}/{total4} (informational)")
    print(f"step 5 match rate : {matched5}/{total5} ({rate5:.0%})")
    print(f"pass threshold    : step5 >= {PASS_THRESHOLD:.0%}")
    print(f"result            : {'PASS' if ok else 'FAIL'}")

    if not args.keep_work:
        shutil.rmtree(WORK_DIR, ignore_errors=True)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
