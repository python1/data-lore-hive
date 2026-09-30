#!/usr/bin/env python3
"""Run six bounded end-to-end cases and preserve every report, including failures."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Omit to evaluate scripted mode")
    parser.add_argument("--state-dir", default="evaluation")
    args = parser.parse_args()
    root = Path(args.state_dir).resolve() / str(uuid.uuid4())
    root.mkdir(parents=True)
    results = []
    for capacity, count in [(120, 7), (37, 7), (123, 13)]:
        for inject_error in (False, True):
            case_dir = root / f"{capacity}x{count}-{'wrong' if inject_error else 'correct'}"
            command = [sys.executable, str(Path(__file__).with_name("hive.py")), "demo",
                       "--capacity", str(capacity), "--count", str(count), "--state-dir", str(case_dir)]
            if args.model:
                command += ["--model", args.model]
            if inject_error:
                command += ["--inject-error"]
            expected_status = "disputed" if inject_error else "verified"
            case = {"capacity": capacity, "count": count, "inject_error": inject_error,
                    "expected_status": expected_status}
            try:
                process = subprocess.run(command, capture_output=True, text=True, timeout=620)
                case.update(exit_code=process.returncode, stderr=process.stderr)
                reports = list(case_dir.glob("report-*.json"))
                if len(reports) != 1:
                    raise RuntimeError("Run did not produce exactly one report")
                report = json.loads(reports[0].read_text())
                case["report"] = report
                case["status"] = report["status"]
                result = next(e["payload"] for e in report["events"] if e["kind"] == "result")
                promoted = any(e["kind"] == "working_knowledge" for e in report["events"])
                case["passed"] = (
                    report["status"] == expected_status
                    and process.returncode == (2 if inject_error else 0)
                    and result["answer_litres"] == capacity * count + int(inject_error)
                    and promoted == (not inject_error))
            except (RuntimeError, subprocess.TimeoutExpired, ValueError, StopIteration) as error:
                case.update(status="error", passed=False, error=str(error))
            results.append(case)
            summary = {"model": args.model, "policy": "independent-calculation-v2",
                       "passed": sum(item["passed"] for item in results),
                       "completed": len(results), "planned": 6, "cases": results}
            (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            print(f"{case_dir.name}: {case['status']} — {'PASS' if case['passed'] else 'FAIL'}", flush=True)
    print(f"Summary: {root / 'summary.json'}", flush=True)
    return 0 if all(case["passed"] for case in results) else 1


if __name__ == "__main__":
    sys.exit(main())
