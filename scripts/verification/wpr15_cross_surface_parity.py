#!/usr/bin/env python3
"""SCRUM-166 (WPR-15) — Cross-surface parity verification.

Verifies WP → ContentHub → CHT parity across the three axes the mirror covers:
categories, series, tags. Combines two checks:

  1. WP ↔ ContentHub parity: fires reconcile_drift dry-run on the
     dev projection-ops Lambda. Zero phantoms + matching counts = mirror
     matches WP REST.

  2. ContentHub ↔ CHT parity: hits the CHT catalog proxy that CHT itself
     reads from, confirms all three endpoints expose live data. Term-count
     deltas vs reconcile are explained (public endpoints exclude terms
     with zero live posts, per plan design).

Usage:
    python3 scripts/verification/wpr15_cross_surface_parity.py

Requires:
    - aws CLI (v1 or v2) with invoke permission on contenthub-dev-sync-wordpress-projection-ops
    - Network access to devapp.communityhealth.media

Any failure mode reported below pauses the WPR-16 cutover.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

CHT_PROXY = "https://devapp.communityhealth.media/api/catalog/wordpress"
LAMBDA_NAME = "contenthub-dev-sync-wordpress-projection-ops"
AWS_REGION = "us-east-1"


class FetchError(Exception):
    """Any failure while contacting the CHT proxy — network, HTTP, or non-JSON body."""


def fetch_json(path: str) -> dict:
    """Fetch and parse JSON, raising FetchError on network / HTTP / decode failures."""
    req = Request(f"{CHT_PROXY}{path}", headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=15) as r:
            raw = r.read()
    except HTTPError as e:
        raise FetchError(f"{path} — HTTP {e.code} {e.reason}") from e
    except URLError as e:
        raise FetchError(f"{path} — network: {e.reason}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        preview = raw[:120].decode("utf-8", errors="replace")
        raise FetchError(f"{path} — non-JSON body: {preview!r}") from e


def _aws_cli_major_version() -> int:
    """Return 1 or 2. Falls back to 2 (stricter default) on any parse failure."""
    try:
        out = subprocess.run(
            ["aws", "--version"], capture_output=True, text=True, check=True
        ).stdout + subprocess.run(
            ["aws", "--version"], capture_output=True, text=True, check=True
        ).stderr
        # Format: "aws-cli/2.x.y ..." or "aws-cli/1.x.y ..."
        for tok in out.split():
            if tok.startswith("aws-cli/"):
                return int(tok.split("/", 1)[1].split(".", 1)[0])
    except Exception:
        pass
    return 2


def invoke_reconcile_dry_run() -> dict:
    """Fire reconcile_drift dry-run on dev Lambda.

    Passes --cli-binary-format raw-in-base64-out only on AWS CLI v2
    (flag is unknown on v1). Also inspects invoke response for
    FunctionError which the CLI does NOT surface via exit code.
    """
    payload_fd, payload_path = tempfile.mkstemp(suffix=".json", prefix="wpr15_")
    out_fd, out_path = tempfile.mkstemp(suffix=".json", prefix="wpr15_out_")
    os.close(payload_fd)
    os.close(out_fd)
    try:
        with open(payload_path, "w") as f:
            f.write('{"op":"reconcile_drift","dry_run":true}')
        cmd = ["aws", "lambda", "invoke",
               "--function-name", LAMBDA_NAME,
               "--region", AWS_REGION]
        if _aws_cli_major_version() >= 2:
            cmd += ["--cli-binary-format", "raw-in-base64-out"]
        cmd += ["--payload", f"fileb://{payload_path}", out_path]
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if r.returncode != 0:
            return {"__error__": r.stderr.strip()[:400] or "invoke failed"}
        # CLI writes an "InvokeResult" JSON to stdout; parse to detect FunctionError.
        try:
            meta = json.loads(r.stdout) if r.stdout.strip() else {}
            if meta.get("FunctionError"):
                return {
                    "__error__": f"FunctionError={meta['FunctionError']} — handler raised"
                }
        except json.JSONDecodeError:
            pass  # older CLI may not emit metadata; rely on payload
        with open(out_path) as f:
            return json.load(f)
    finally:
        for p in (payload_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def main() -> int:
    print("=== WPR-15 Cross-Surface Parity Verification ===\n")

    # STEP 1: WP ↔ ContentHub via reconcile_drift
    print("[1/2] WP ↔ ContentHub parity (reconcile_drift dry-run)")
    result = invoke_reconcile_dry_run()
    if "__error__" in result:
        print(f"  ERROR: {result['__error__']}")
        return 1
    if result.get("status") != "ok":
        print(f"  ERROR: reconcile returned status={result.get('status')}")
        return 1
    if "post_phantoms" not in result or "term_summary" not in result:
        print(
            f"  ERROR: reconcile response missing required fields "
            f"(keys present: {sorted(result.keys())})"
        )
        return 1

    post_phantoms = result["post_phantoms"]
    terms = result["term_summary"]
    print(f"  Posts:       {post_phantoms} phantoms")

    term_axes_clean = True
    for taxonomy in ("series", "category", "post_tag"):
        row = terms.get(taxonomy)
        if not row or "wp_count" not in row or "ch_count" not in row or "phantoms" not in row:
            print(f"  ✗ {taxonomy:10s} missing required counters — reconcile shape drift")
            term_axes_clean = False
            continue
        wp_ct = row["wp_count"]
        ch_ct = row["ch_count"]
        ph = row["phantoms"]
        counts_match = wp_ct == ch_ct
        marker = "✓" if counts_match and ph == 0 else "✗"
        note = "" if counts_match else f"  ← gap (WP has {wp_ct - ch_ct} CH is missing)"
        print(f"  {marker} {taxonomy:10s} WP={wp_ct:4d}  CH={ch_ct:4d}  phantoms={ph}{note}")
        if not counts_match or ph != 0:
            term_axes_clean = False

    wp_ch_clean = post_phantoms == 0 and term_axes_clean

    # STEP 2: ContentHub ↔ CHT via public proxy
    print("\n[2/2] ContentHub ↔ CHT parity (public proxy endpoints)")

    try:
        cats = fetch_json("/categories")
        series = fetch_json("/series")
        tags = fetch_json("/tags")
    except FetchError as e:
        print(f"  ERROR fetching proxy: {e}")
        print("\n=== VERDICT: FAIL (proxy unreachable — not a data issue) ===")
        return 1

    cat_exposed = len(cats.get("items", []))
    series_exposed = len(series.get("items", []))
    tag_exposed = len(tags.get("items", []))

    ch_cat = terms.get("category", {}).get("ch_count", 0)
    ch_ser = terms.get("series", {}).get("ch_count", 0)
    ch_tag = terms.get("post_tag", {}).get("ch_count", 0)

    print(f"  Categories:  {cat_exposed}/{ch_cat} exposed  (delta = zero-post terms filtered by public endpoint)")
    print(f"  Series:      {series_exposed}/{ch_ser} exposed")
    print(f"  Tags:        {tag_exposed}/{ch_tag} exposed")

    # Tag namespacing coverage — every exposed tag must have a namespaced_tag
    ns_covered = sum(1 for t in tags.get("items", []) if t.get("namespaced_tag"))
    ns_marker = "✓" if ns_covered == tag_exposed else "✗"
    print(f"  {ns_marker} Namespaced tag coverage: {ns_covered}/{tag_exposed}")

    # Series detail integrity spot-check on top series (guarded against null post_count)
    sorted_series = sorted(
        series.get("items", []),
        key=lambda s: -(s.get("post_count") or 0),
    )
    detail_ok = True
    if sorted_series:
        top = sorted_series[0]
        try:
            detail = fetch_json(f"/series/{top['slug']}")
            if detail.get("post_count") == len(detail.get("post_ids", [])):
                print(f"  ✓ Series detail integrity: /series/{top['slug']} post_count == len(post_ids)")
            else:
                detail_ok = False
                print(f"  ✗ Series detail mismatch on {top['slug']}")
        except FetchError as e:
            detail_ok = False
            print(f"  ✗ Series detail fetch failed: {e}")

    ch_cht_clean = (
        cat_exposed >= 1
        and series_exposed >= 1
        and tag_exposed >= 1
        and ns_covered == tag_exposed
        and detail_ok
    )

    # Verdict
    print("\n=== VERDICT ===")
    overall = "PASS" if (wp_ch_clean and ch_cht_clean) else "FAIL"
    print(f"WP → CH parity:     {'✓ clean' if wp_ch_clean else '✗ drift detected'}")
    print(f"CH → CHT parity:    {'✓ clean' if ch_cht_clean else '✗ integrity issue'}")
    print(f"OVERALL:            {overall}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
