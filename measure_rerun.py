#!/usr/bin/env python3
"""Measurement-only wrapper. Runs an unchanged evaluator and records per-answer
wall-clock time and sampled peak RSS (evaluator process tree + Ollama runner).

usage: measure.py support|prose OUT.json -- <evaluator argv...>
"""
import json
import os
import subprocess
import sys
import threading
import time

REPO = os.getcwd()
sys.path.insert(0, REPO)

samples = []  # (t, tree_rss_kb, ollama_rss_kb)
stop = threading.Event()


def sample():
    me = os.getpid()
    while not stop.is_set():
        out = subprocess.run(["ps", "-axo", "pid=,ppid=,rss=,comm="], capture_output=True, text=True).stdout
        procs = {}
        for line in out.splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4:
                procs[int(parts[0])] = (int(parts[1]), int(parts[2]), parts[3])
        tree, frontier = {me}, [me]
        while frontier:
            p = frontier.pop()
            for pid, (ppid, _, _) in procs.items():
                if ppid == p and pid not in tree:
                    tree.add(pid); frontier.append(pid)
        tree_rss = sum(procs[p][1] for p in tree if p in procs)
        ollama_rss = sum(rss for _, rss, comm in procs.values() if "ollama" in comm or "llama-server" in comm)
        samples.append((time.time(), tree_rss, ollama_rss))
        stop.wait(0.2)


def peaks(t0, t1):
    window = [s for s in samples if t0 <= s[0] <= t1] or samples[-1:]
    return {"peak_tree_rss_mb": round(max(s[1] for s in window) / 1024, 1),
            "peak_ollama_rss_mb": round(max(s[2] for s in window) / 1024, 1),
            "rss_samples": len(window)}


def main():
    mode, out = sys.argv[1], sys.argv[2]
    argv = sys.argv[sys.argv.index("--") + 1:]
    timings = []
    threading.Thread(target=sample, daemon=True).start()
    if mode == "support":
        import evaluate_support as ev
        real_run = ev.subprocess.run

        def timed_run(command, *a, **k):
            t0 = time.time(); start = time.perf_counter()
            try:
                return real_run(command, *a, **k)
            finally:
                t1 = time.time()
                if any(str(c).endswith("knowledge.py") for c in command):
                    q = command[command.index("ask") + 1]
                    seed = int(command[command.index("--seed") + 1])
                    timings.append({"seed": seed, "question": q, "wall_clock_s": round(time.perf_counter() - start, 3),
                                    "started": t0, "ended": t1, **peaks(t0, t1)})
        ev.subprocess.run = timed_run
        sys.argv = ["evaluate_support.py", *argv]
        target = ev.main
    else:
        import knowledge
        import evaluate_prose_policy as ev
        real_answer = knowledge.answer_question

        def timed_answer(db, question, model, seed=None, temperature=0):
            t0 = time.time(); start = time.perf_counter()
            try:
                return real_answer(db, question, model, seed, temperature)
            finally:
                t1 = time.time()
                timings.append({"seed": seed, "question": question, "wall_clock_s": round(time.perf_counter() - start, 3),
                                "started": t0, "ended": t1, **peaks(t0, t1)})
        knowledge.answer_question = timed_answer
        sys.argv = ["evaluate_prose_policy.py", *argv]
        target = ev.main
    t_start = time.time()
    try:
        code = target()
    finally:
        stop.set(); time.sleep(0.3)
        with open(out, "w") as f:
            json.dump({"mode": mode, "argv": argv, "total_wall_clock_s": round(time.time() - t_start, 3),
                       "sampling_interval_s": 0.2, "answers": timings,
                       "overall": peaks(t_start, time.time())}, f, indent=2)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
