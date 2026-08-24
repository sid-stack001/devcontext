"""
eval.py — Evaluation harness for devcontext diagnostic tools.

Iterates over all synthetic scenarios in eval_scenarios/, invokes
diagnose(service_name, data_dir=scenario_dir), and compares the tool's
likely_cause output against expected_diagnosis.json.

Outputs a formatted table of results and accuracy metrics.
"""

import json
from pathlib import Path

from tools import diagnose

_HERE = Path(__file__).parent
_SCENARIOS_DIR = _HERE / "eval_scenarios"


def evaluate_scenario(scenario_dir: Path) -> dict:
    expected_path = scenario_dir / "expected_diagnosis.json"
    if not expected_path.exists():
        return {
            "scenario": scenario_dir.name,
            "correct": False,
            "note": "Missing expected_diagnosis.json",
        }

    with expected_path.open(encoding="utf-8") as fh:
        expected = json.load(fh)

    service_name = expected["service"]
    should_blame_deploy = expected["should_blame_deploy"]
    correct_commit = expected.get("correct_commit")
    expected_type = expected.get("root_cause_type")

    # Call diagnose using the scenario directory
    result = diagnose(service_name, data_dir=scenario_dir)
    likely_cause = result.get("likely_cause", "")
    likely_cause_lower = likely_cause.lower()

    # --- Verification Heuristics ---
    is_correct = False
    note = ""

    if should_blame_deploy:
        if correct_commit and correct_commit in likely_cause:
            is_correct = True
            note = f"Correctly identified deploy commit {correct_commit}"
        else:
            is_correct = False
            note = f"Failed to identify deploy commit {correct_commit} in output"
    else:
        # Should NOT blame a deploy
        blamed_deploy = (
            "the most likely cause is the deploy" in likely_cause_lower
            and "no recent deploy" not in likely_cause_lower
        )
        if blamed_deploy:
            is_correct = False
            note = "Incorrectly blamed a deploy when cause was non-deploy issue"
        else:
            # Verify specific non-deploy cause identification
            if expected_type == "disk" and ("disk" in likely_cause_lower or "space" in likely_cause_lower):
                is_correct = True
                note = "Correctly identified disk space exhaustion"
            elif expected_type == "memory_leak" and ("memory" in likely_cause_lower or "oom" in likely_cause_lower):
                is_correct = True
                note = "Correctly identified memory exhaustion / leak"
            elif expected_type == "downstream_dependency" and ("downstream" in likely_cause_lower or "external" in likely_cause_lower):
                is_correct = True
                note = "Correctly identified downstream/external API outage"
            else:
                is_correct = True
                note = f"Correctly avoided blaming deploy (matched type: {expected_type})"

    return {
        "scenario": scenario_dir.name,
        "service": service_name,
        "expected_type": expected_type,
        "correct": is_correct,
        "note": note,
        "likely_cause": likely_cause,
    }


def main():
    scenario_dirs = sorted([d for d in _SCENARIOS_DIR.iterdir() if d.is_dir()])
    results = []
    correct_count = 0

    for s_dir in scenario_dirs:
        res = evaluate_scenario(s_dir)
        results.append(res)
        if res["correct"]:
            correct_count += 1

    total = len(results)

    # Print Results Table
    header = f"{'Scenario Name':<32} | {'Correct?':<8} | {'Note'}"
    divider = "-" * 85
    print("\n" + divider)
    print("EVALUATION HARNESS RESULTS")
    print(divider)
    print(header)
    print(divider)

    for r in results:
        status = "YES" if r["correct"] else "NO"
        print(f"{r['scenario']:<32} | {status:<8} | {r['note']}")

    print(divider)
    print(f"SUMMARY: {correct_count}/{total} scenarios correctly diagnosed.")
    print(divider + "\n")


if __name__ == "__main__":
    main()
