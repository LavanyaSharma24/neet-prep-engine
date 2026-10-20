"""Live check of the deployed Tier 2 escalation API (api/main.py).

Usage: python scripts/tier2_live_check.py https://<render-host>

Standard library only. Makes at most 3 POST /escalate calls (each one costs
2-3 Gemini requests server-side), 3 seconds apart, and stops immediately on
a 502 that mentions quota/429 rather than retrying. Needs no API key — the
Gemini key lives only on the backend.
"""
import json
import sys
import time
import urllib.error
import urllib.request

REAL_ORIGIN = "https://neet-prep-engine.web.app"
OTHER_ORIGIN = "https://example.com"

WARMUP_POLL_SECONDS = 5
WARMUP_MAX_SECONDS = 120
ESCALATE_TIMEOUT_SECONDS = 60
ESCALATE_GAP_SECONDS = 3
MAX_ESCALATE_CALLS = 3
# web/src/api.ts aborts at REQUEST_TIMEOUT_MS = 30000; flag anything close.
SLOW_FLAG_SECONDS = 25
CLIENT_TIMEOUT_SECONDS = 30
EXPECTED_LABEL = "AI-GENERATED — PENDING VERIFICATION"

# (question, expected outcome(s), "/"-separated). Fixed list — not tuned to
# force outcomes. Kept to 3 to stay within the Gemini free-tier quota.
QUESTIONS = [
    ("What is the function of ribosomes?", "ok"),
    ("Who won the 2011 cricket world cup?", "refused"),
    # Textbook figure (36-38 vs. ~30-32) varies by source, so might disagree.
    ("How many net ATP molecules are produced per glucose molecule in aerobic respiration?", "ok/disagreed"),
]


def request(method, url, body=None, headers=None, timeout=30):
    """Returns (status, headers, text). status is None on timeout/network
    failure, in which case text holds the error."""
    hdrs = {"User-Agent": "tier2-live-check/1.0"}
    hdrs.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, res.headers, res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        kind = "timeout" if "timed out" in str(reason).lower() else "network"
        return None, {}, f"{kind}: {reason}"


def warm_up(base):
    print("== a. Warm-up ==")
    start = time.monotonic()
    attempt = 0
    while True:
        attempt += 1
        remaining = WARMUP_MAX_SECONDS - (time.monotonic() - start)
        if remaining <= 0:
            break
        status, _, text = request("GET", f"{base}/healthz", timeout=max(1, min(30, remaining)))
        elapsed = time.monotonic() - start
        print(f"  attempt {attempt}: status={status} at {elapsed:.1f}s")
        if status == 200:
            print(f"  /healthz OK after {elapsed:.1f}s ({attempt} attempt(s)) body={text.strip()}")
            return elapsed
        if WARMUP_MAX_SECONDS - (time.monotonic() - start) <= WARMUP_POLL_SECONDS:
            break
        time.sleep(WARMUP_POLL_SECONDS)
    print(f"  /healthz did NOT come up within {WARMUP_MAX_SECONDS}s")
    return None


def cors_check(base, origin):
    status, headers, text = request(
        "OPTIONS",
        f"{base}/escalate",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    allow_origin = headers.get("access-control-allow-origin") if headers else None
    allowed = status == 200 and allow_origin in (origin, "*")
    print(
        f"  Origin {origin}: HTTP {status}, access-control-allow-origin={allow_origin!r}, "
        f"allow-methods={headers.get('access-control-allow-methods') if headers else None!r}, "
        f"body={text.strip()[:80]!r} -> {'ALLOWED' if allowed else 'NOT allowed'}"
    )
    return allowed


def validation_checks(base):
    print("== c. Validation (no Gemini calls) ==")
    results = {}
    for name, question in (("empty question", ""), ("2001-char question", "a" * 2001)):
        status, _, text = request("POST", f"{base}/escalate", body={"question": question})
        results[name] = status
        verdict = "PASS" if status == 422 else "FAIL (expected 422)"
        print(f"  {name}: HTTP {status} -> {verdict}")
        if status != 422:
            print(f"    body: {text[:200]}")
    return results


def is_quota_error(status, text):
    lowered = text.lower()
    return status == 502 and ("quota" in lowered or "429" in lowered or "resource_exhausted" in lowered)


def escalation_checks(base):
    print("== d. Escalation calls ==")
    rows = []
    stopped_on_quota = False
    for index, (question, expected) in enumerate(QUESTIONS[:MAX_ESCALATE_CALLS]):
        if index:
            time.sleep(ESCALATE_GAP_SECONDS)
        start = time.monotonic()
        status, _, text = request(
            "POST", f"{base}/escalate", body={"question": question}, timeout=ESCALATE_TIMEOUT_SECONDS
        )
        seconds = time.monotonic() - start
        row = {
            "question": question, "expected": expected, "http": status,
            "seconds": seconds, "answer": None, "label": None, "detail": None,
        }
        if status is None:
            row["actual"] = "client-timeout" if text.startswith("timeout") else "network-error"
            row["detail"] = text
        elif status == 200:
            try:
                body = json.loads(text)
            except ValueError:
                body = {}
                row["detail"] = f"non-JSON body: {text[:200]}"
            row["label"] = body.get("label")
            if body.get("disagreed"):
                row["actual"] = "disagreed"
            elif body.get("refused"):
                row["actual"] = "refused"
            elif body.get("answer"):
                row["actual"] = "ok"
                row["answer"] = body["answer"]
            else:
                row["actual"] = "200-no-answer"
        else:
            row["actual"] = str(status)
            row["detail"] = text[:300]
        rows.append(row)
        http = f"HTTP {status}" if status is not None else row["actual"]
        print(f"  [{index + 1}/{len(QUESTIONS)}] {row['actual']} ({http}, {seconds:.1f}s) {question}")
        if status is not None and is_quota_error(status, text):
            stopped_on_quota = True
            print("  STOPPING: 502 mentions quota/429 (free-tier limit). Not retrying.")
            break
    return rows, stopped_on_quota


def print_table(rows):
    print("== e. Results ==")
    width = max(len(r["question"]) for r in rows)
    header = f"{'question'.ljust(width)} | expected     | actual         | HTTP           | seconds"
    print(header)
    print("-" * len(header))
    for r in rows:
        match = "" if r["actual"] in r["expected"].split("/") else "  <-- differs from expected"
        slow = ""
        if r["seconds"] > CLIENT_TIMEOUT_SECONDS:
            slow = f"  [SLOW: over the web client's {CLIENT_TIMEOUT_SECONDS}s abort]"
        elif r["seconds"] > SLOW_FLAG_SECONDS:
            slow = f"  [SLOW: over {SLOW_FLAG_SECONDS}s, client aborts at {CLIENT_TIMEOUT_SECONDS}s]"
        print(
            f"{r['question'].ljust(width)} | {r['expected'].ljust(12)} | {r['actual'].ljust(14)} | "
            f"{str(r['http'] or r['actual']).ljust(14)} | {r['seconds']:.1f}{slow}{match}"
        )
    print()
    for r in rows:
        if r["actual"] == "ok":
            print(f"OK answer — {r['question']}")
            print(f"  {r['answer'][:200]!r}")
        elif r["actual"] == "disagreed":
            print(f"DISAGREED — {r['question']} (both answers are in the server's flagged_items log)")
        elif r["detail"]:
            print(f"{r['actual']} detail — {r['question']}")
            print(f"  {r['detail']}")
        if r["http"] == 200 and r["label"] != EXPECTED_LABEL:
            print(f"  UNEXPECTED LABEL for {r['question']!r}: {r['label']!r}")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    # The label contains an em dash; don't let a cp1252 console crash the run.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    base = sys.argv[1].rstrip("/")
    print(f"Base URL: {base}")

    cold_start = warm_up(base)
    if cold_start is None:
        return 1

    print("== b. CORS preflight on /escalate ==")
    real_allowed = cors_check(base, REAL_ORIGIN)
    other_allowed = cors_check(base, OTHER_ORIGIN)
    print(f"  real origin allowed: {'PASS' if real_allowed else 'FAIL'}")
    print(f"  example.com rejected: {'PASS' if not other_allowed else 'FAIL (it was allowed)'}")

    validation_checks(base)

    rows, stopped_on_quota = escalation_checks(base)
    print_table(rows)

    print("== Summary ==")
    observed = sorted({r["actual"] for r in rows})
    slowest = max(rows, key=lambda r: r["seconds"])
    print(f"  cold start (this run): {cold_start:.1f}s")
    print(f"  escalation calls made: {len(rows)} of {len(QUESTIONS)} planned")
    print(f"  outcomes observed: {', '.join(observed)}")
    print(f"  refused seen live: {'YES' if 'refused' in observed else 'NO'}")
    print(f"  disagreed seen live: {'YES' if 'disagreed' in observed else 'NO'}")
    print(f"  slowest call: {slowest['seconds']:.1f}s ({slowest['question']})")
    over_slow = [r for r in rows if r["seconds"] > SLOW_FLAG_SECONDS]
    print(f"  calls over {SLOW_FLAG_SECONDS}s: {len(over_slow)}")
    over = [r for r in rows if r["seconds"] > CLIENT_TIMEOUT_SECONDS]
    print(f"  calls over the client's {CLIENT_TIMEOUT_SECONDS}s timeout: {len(over)}")
    if stopped_on_quota:
        print("  STOPPED EARLY on quota/429.")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
