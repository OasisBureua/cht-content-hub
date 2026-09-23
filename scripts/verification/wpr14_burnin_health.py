#!/usr/bin/env python3
"""SCRUM-165 (WPR-14) — Chaos + load burn-in health monitor.

Snapshot of every burn-in health signal we care about, in one run:
  - Ingest SQS queue depth + DLQ depth (any DLQ message = investigate)
  - Lambda error count over the last 24h (any > 0 = investigate)
  - Reconcile Lambda invocation status + drift counts (0 phantoms + matching
    counts = healthy)

VERDICT: GREEN when all signals clean. INVESTIGATE otherwise.
Exit 0 on GREEN, exit 1 on INVESTIGATE — safe to gate the cutover on.

Run daily during the burn-in window. Any INVESTIGATE = pause cutover.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

AWS_REGION = "us-east-1"
INGEST_LAMBDA = "contenthub-dev-sync-wordpress-ingest"
OPS_LAMBDA = "contenthub-dev-sync-wordpress-projection-ops"
QUEUE_URL = "https://queue.amazonaws.com/233636046512/contenthub-dev-sync-wordpress-ingest-queue"
DLQ_URL = "https://queue.amazonaws.com/233636046512/contenthub-dev-sync-wordpress-ingest-dlq"


def sh(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        return f"ERROR: {r.stderr.strip()[:200]}"
    return r.stdout.strip()


def queue_depth(url: str) -> tuple[str, int, int, bool]:
    """Returns (display_str, visible_count, inflight_count, parse_ok)."""
    out = sh(
        [
            "aws", "sqs", "get-queue-attributes",
            "--region", AWS_REGION,
            "--queue-url", url,
            "--attribute-names",
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
        ]
    )
    try:
        attrs = json.loads(out).get("Attributes", {})
        visible = int(attrs.get("ApproximateNumberOfMessages", 0))
        inflight = int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0))
        return (f"visible={visible}  in-flight={inflight}", visible, inflight, True)
    except Exception:
        return (out[:100], -1, -1, False)


def lambda_error_count(fn: str, hours: int = 24) -> tuple[str, int, bool]:
    """Returns (display_str, error_count, parse_ok)."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    out = sh(
        [
            "aws", "cloudwatch", "get-metric-statistics",
            "--region", AWS_REGION,
            "--namespace", "AWS/Lambda",
            "--metric-name", "Errors",
            "--dimensions", f"Name=FunctionName,Value={fn}",
            "--start-time", start.strftime("%Y-%m-%dT%H:%M:%S"),
            "--end-time", end.strftime("%Y-%m-%dT%H:%M:%S"),
            "--period", str(hours * 3600),
            "--statistics", "Sum",
        ]
    )
    try:
        dp = json.loads(out).get("Datapoints", [])
        total = int(sum(d.get("Sum", 0) for d in dp))
        return (f"{total} errors in last {hours}h", total, True)
    except Exception:
        return (out[:100], -1, False)


def _aws_cli_major_version() -> int:
    try:
        r = subprocess.run(
            ["aws", "--version"], capture_output=True, text=True, check=False
        )
        combined = (r.stdout or "") + (r.stderr or "")
        for tok in combined.split():
            if tok.startswith("aws-cli/"):
                return int(tok.split("/", 1)[1].split(".", 1)[0])
    except Exception:
        pass
    return 2


def invoke_reconcile_dry_run() -> dict:
    """Fire reconcile_drift dry-run. Handles CLI v1 vs v2 + FunctionError."""
    payload_fd, payload_path = tempfile.mkstemp(suffix=".json", prefix="wpr14_")
    out_fd, out_path = tempfile.mkstemp(suffix=".json", prefix="wpr14_out_")
    os.close(payload_fd)
    os.close(out_fd)
    try:
        with open(payload_path, "w") as f:
            f.write('{"op":"reconcile_drift","dry_run":true}')
        cmd = ["aws", "lambda", "invoke",
               "--function-name", OPS_LAMBDA,
               "--region", AWS_REGION]
        if _aws_cli_major_version() >= 2:
            cmd += ["--cli-binary-format", "raw-in-base64-out"]
        cmd += ["--payload", f"fileb://{payload_path}", out_path]
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if r.returncode != 0:
            return {"__error__": r.stderr.strip()[:400] or "invoke failed"}
        # Inspect invoke response for FunctionError (CLI does NOT surface via exit code).
        try:
            meta = json.loads(r.stdout) if r.stdout.strip() else {}
            if meta.get("FunctionError"):
                return {"__error__": f"FunctionError={meta['FunctionError']} — handler raised"}
        except json.JSONDecodeError:
            pass
        with open(out_path) as f:
            return json.load(f)
    finally:
        for p in (payload_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def main() -> int:
    print(f"=== WPR-14 Burn-in Health Snapshot ({datetime.now().strftime('%Y-%m-%d %H:%M %Z')}) ===\n")

    # SQS depth — captured ONCE, reused for verdict (avoid two calls disagreeing).
    main_display, main_visible, main_inflight, main_ok = queue_depth(QUEUE_URL)
    dlq_display, dlq_visible, dlq_inflight, dlq_ok = queue_depth(DLQ_URL)
    print("[SQS DEPTH]")
    print(f"  main queue:  {main_display}")
    print(f"  DLQ:         {dlq_display}")
    print()

    # Lambda error counts — captured with numeric extraction for verdict.
    ingest_display, ingest_errs, ingest_ok = lambda_error_count(INGEST_LAMBDA)
    ops_display, ops_errs, ops_ok = lambda_error_count(OPS_LAMBDA)
    print("[LAMBDA ERRORS (last 24h)]")
    print(f"  ingest:      {ingest_display}")
    print(f"  ops:         {ops_display}")
    print()

    # Reconcile drift.
    print("[RECONCILE DRIFT]")
    result = invoke_reconcile_dry_run()
    reconcile_ok = "__error__" not in result
    reconcile_clean = False

    if not reconcile_ok:
        print(f"  ERROR: {result['__error__']}")
    elif result.get("status") != "ok":
        print(f"  ERROR: reconcile returned status={result.get('status')}")
        reconcile_ok = False
    elif "post_phantoms" not in result or "term_summary" not in result:
        print(f"  ERROR: reconcile response missing required fields (keys: {sorted(result.keys())})")
        reconcile_ok = False
    else:
        post_phantoms = result["post_phantoms"]
        terms = result["term_summary"]
        print(f"  posts:       {post_phantoms} phantoms")
        term_axes_clean = True
        for tax in ("series", "category", "post_tag"):
            row = terms.get(tax)
            if not row or not all(k in row for k in ("wp_count", "ch_count", "phantoms")):
                print(f"  ✗ {tax:10s} missing counters — shape drift")
                term_axes_clean = False
                continue
            wp, ch, ph = row["wp_count"], row["ch_count"], row["phantoms"]
            mark = "✓" if wp == ch and ph == 0 else "✗"
            print(f"  {mark} {tax:10s} WP={wp:4d}  CH={ch:4d}  phantoms={ph}")
            if wp != ch or ph != 0:
                term_axes_clean = False
        reconcile_clean = post_phantoms == 0 and term_axes_clean
    print()

    # ── VERDICT ──────────────────────────────────────────────────────────
    # GREEN requires: SQS parsed cleanly + zero depth on both queues,
    # Lambda errors parsed + zero on both functions, reconcile clean.
    dlq_clean = dlq_ok and dlq_visible == 0 and dlq_inflight == 0
    main_queue_clean = main_ok and main_visible == 0 and main_inflight == 0
    ingest_clean = ingest_ok and ingest_errs == 0
    ops_clean = ops_ok and ops_errs == 0

    checks = {
        "main queue empty":   main_queue_clean,
        "DLQ empty":          dlq_clean,
        "ingest 0 errors":    ingest_clean,
        "ops 0 errors":       ops_clean,
        "reconcile clean":    reconcile_clean,
    }
    all_clean = all(checks.values())
    verdict = "GREEN" if all_clean else "INVESTIGATE"

    if not all_clean:
        failed = [k for k, v in checks.items() if not v]
        print(f"=== VERDICT: {verdict} ===")
        print(f"    failing checks: {', '.join(failed)}")
    else:
        print(f"=== VERDICT: {verdict} ===")
    return 0 if all_clean else 1


if __name__ == "__main__":
    sys.exit(main())
