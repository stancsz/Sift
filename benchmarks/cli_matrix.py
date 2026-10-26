"""Opt-in 27-session native acceptance matrix with bounded scoped keys."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

from benchmarks.acceptance_tasks import TASKS
from benchmarks.cli_campaign import source_hashes


def schedule(repetitions=3):
    # Interleave clients/tasks so a compatibility failure is found early.
    return [(client, task, repeat) for repeat in range(repetitions)
            for task in TASKS for client in ("codex", "claude", "opencode")]


def run(args):
    import httpx
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    master = os.environ[args.control_key_env]
    stop = threading.Event()
    lock = threading.Lock()
    records = []
    active_sessions = {}
    frozen = source_hashes()
    started = time.monotonic()

    def api(path, payload=None):
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            response = client.request("POST" if payload is not None else "GET",
                "http://127.0.0.1:4000" + path, json=payload,
                headers={"Authorization": f"Bearer {master}"})
            response.raise_for_status()
            return response.json()

    def checkpoint():
        with lock:
            receipt = {"complete": len(records) == 27 and all(r.get("accepted") for r in records),
                       "expected_sessions": 27, "accepted_sessions": sum(bool(r.get("accepted")) for r in records),
                       "terminal_sessions": len(records), "elapsed_seconds": round(time.monotonic()-started, 2),
                       "source_sha256": frozen, "records": list(records)}
            receipt["active_sessions"] = list(active_sessions.values())
            temporary = root / "matrix.tmp"
            temporary.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            temporary.replace(root / "matrix.json")

    def session(job):
        client, task, repeat = job
        name = f"{client}-{task}-{repeat+1}"
        directory = root / name
        alias = "sift-acceptance-" + uuid.uuid4().hex[:12]
        key, process = None, None
        record = {"name": name, "client": client, "task": task, "repeat": repeat+1,
                  "accepted": False, "scoped_key_alias": alias, "key_revoked": False}
        with lock:
            active_sessions[name] = {"name": name, "scoped_key_alias": alias, "receipt": f"{name}/result.json"}
        checkpoint()
        try:
            if source_hashes() != frozen:
                raise RuntimeError("Source changed before matrix session")
            payload = api("/key/generate", {"key_alias": alias, "models": [args.model],
                "duration": "20m", "budget_duration": "20m", "max_budget": .5, "max_parallel_requests": 2})
            key = payload["key"]
            del payload
            env = os.environ.copy()
            # The control credential stays in this orchestrator; session
            # runners receive only their short-lived inference credential.
            env.pop(args.control_key_env, None)
            env.pop("EXPERTS_API_KEY", None)
            env["SIFT_ACCEPTANCE_API_KEY"] = key
            command = [sys.executable, "-m", "benchmarks.cli_campaign", "--client", client,
                       "--task", task, "--seed", str(831 + repeat*100 + TASKS.index(task)*10),
                       "--model", args.model, "--output-dir", str(directory)]
            process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8", errors="replace")
            session_started = time.monotonic()
            while True:
                try:
                    stdout, stderr = process.communicate(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    if stop.is_set() or time.monotonic()-session_started > 1000:
                        if os.name == "nt":
                            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                        else:
                            process.kill()
                        stdout, stderr = process.communicate(timeout=15)
                        record["interrupted"] = True
                        break
            (root / (name + ".stdout.txt")).write_text(stdout.replace(key, "[REDACTED]"), encoding="utf-8")
            (root / (name + ".stderr.txt")).write_text(stderr.replace(key, "[REDACTED]"), encoding="utf-8")
            record["exit_code"] = process.returncode
            if (directory / "result.json").is_file():
                result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
                record.update(accepted=process.returncode == 0 and result.get("accepted") is True
                              and result.get("active_client_seconds", 0) > 180
                              and len(result.get("turns", [])) >= 6 and result.get("source_sha256") == frozen,
                              active_seconds=result.get("active_client_seconds"), turns=len(result.get("turns", [])),
                              failure=result.get("failure"), receipt=f"{name}/result.json")
        except Exception as error:
            record["failure"] = type(error).__name__ + ": " + str(error).replace(key or master, "[REDACTED]")
        finally:
            if key:
                try:
                    api("/key/delete", {"keys": [key]})
                    remaining = api("/key/list?key_alias=" + alias)
                    record["key_revoked"] = not remaining.get("keys")
                except Exception:
                    record["key_revoked"] = False
            record["accepted"] = record["accepted"] and record["key_revoked"]
        if not record["accepted"]:
            stop.set()
        with lock:
            active_sessions.pop(name, None)
            records.append(record)
        checkpoint()
        print(json.dumps(record), flush=True)
        return record

    jobs = iter(schedule())
    checkpoint()
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = {pool.submit(session, next(jobs)) for _ in range(2)}
        while pending:
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                future.result()
                if not stop.is_set():
                    job = next(jobs, None)
                    if job is not None:
                        pending.add(pool.submit(session, job))
    checkpoint()
    return len(records) == 27 and all(r["accepted"] for r in records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="default")
    parser.add_argument("--control-key-env", default="GATEWAY_MASTER_KEY")
    parser.add_argument("--create-scoped-keys", action="store_true",
                        help="Explicitly authorize one model-restricted 20-minute/$0.50 key per session")
    args = parser.parse_args()
    if not args.create_scoped_keys:
        parser.error("Supply --create-scoped-keys to opt into live inference and scoped-key creation")
    raise SystemExit(0 if run(args) else 1)


if __name__ == "__main__":
    main()
