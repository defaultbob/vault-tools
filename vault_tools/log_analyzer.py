#!/usr/bin/env python3
"""
Vault Log Analyzer
Pulls and analyzes API logs from Veeva Vault.

Supports:
  api-usage   – Download & analyze daily API usage logs (up to 30 days back)
  multi-day   – Aggregate logs across multiple days
  audit       – Query audit trail records
  runtime     – Download SDK runtime logs

Usage:
  python vault_log_analyzer.py api-usage
  python vault_log_analyzer.py api-usage --date 2025-02-20
  python vault_log_analyzer.py multi-day --days 7
  python vault_log_analyzer.py audit --list
  python vault_log_analyzer.py audit --type login_audit_trail
  python vault_log_analyzer.py runtime --date 2025-02-20

Auth (pick one):
  Export VAULT_SESSION=<session_id>        (fastest)
  Use --session <session_id>
  Use --username <u> --password <p>        (auto-authenticates)
"""

import argparse
import csv
import io
import os
import sys
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
import prettytable

# Load .env — searches CWD then walks up the directory tree
try:
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))
except ImportError:
    pass

# ── Default Configuration ──────────────────────────────────────────────────────
VAULT_URL     = os.getenv("VAULT_URL",     "https://vern-genomics-v-e-r-n--genomics--custom-pages.veevavault.com")
VAULT_VERSION = os.getenv("VAULT_VERSION", "v25.3")
SESSION_ID    = os.getenv("VAULT_SESSION", "")
_USERNAME     = os.getenv("VAULT_USERNAME", "")
_PASSWORD     = os.getenv("VAULT_PASSWORD", "")
CLIENT_ID     = "vault-log-analyzer"
OUT_DIR       = Path("out")


# ── Markdown output ────────────────────────────────────────────────────────────

class _Capture:
    """Tees stdout to an internal buffer while still printing to the terminal."""
    def __init__(self):
        self.buf = io.StringIO()

    def __enter__(self):
        self._real = sys.stdout
        sys.stdout = self
        return self

    def __exit__(self, *_):
        sys.stdout = self._real

    def write(self, s):
        self._real.write(s)
        self.buf.write(s)

    def flush(self):
        self._real.flush()

    def getvalue(self) -> str:
        return self.buf.getvalue()


def _write_md(sections: list[tuple[str, str]], filename: str):
    """Write captured sections to out/<filename>.md as formatted markdown."""
    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / filename
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(out_path, "w") as f:
        f.write(f"# Vault Log Analysis\n\n")
        f.write(f"**Generated:** {ts}  |  **Vault:** {VAULT_URL}\n\n")
        for title, content in sections:
            f.write(f"---\n\n## {title}\n\n```\n{content.strip()}\n```\n\n")
    print(f"\n  Saved: {out_path}")


# ── Auth ───────────────────────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> str:
    url  = f"{VAULT_URL}/api/{VAULT_VERSION}/auth"
    resp = requests.post(
        url,
        data={"username": username, "password": password},
        headers={"X-VaultAPI-ClientID": CLIENT_ID, "Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("responseStatus") != "SUCCESS":
        raise RuntimeError(f"Auth failed: {data.get('errors', data)}")
    return data["sessionId"]


def make_headers(session: str) -> dict:
    return {
        "Authorization": session,
        "X-VaultAPI-ClientID": CLIENT_ID,
        "Accept": "application/json",
    }


def get_session(args) -> str:
    session = getattr(args, "session", None) or SESSION_ID
    if not session:
        # CLI flags take priority; fall back to .env values
        username = getattr(args, "username", None) or _USERNAME
        password = getattr(args, "password", None) or _PASSWORD
        if username and password:
            print("Authenticating...")
            session = authenticate(username, password)
            print("Authenticated.\n")
        else:
            print(
                "No session provided. Set VAULT_SESSION env var, "
                "use --session, or pass --username + --password."
            )
            sys.exit(1)
    return session


# ── API Usage Logs ─────────────────────────────────────────────────────────────

def download_api_usage(session: str, log_date: str) -> list[dict]:
    """Download API usage ZIP for a given date and return parsed CSV rows."""
    url    = f"{VAULT_URL}/api/{VAULT_VERSION}/logs/api_usage"
    params = {"date": log_date, "log_format": "csv"}
    resp   = requests.get(url, headers=make_headers(session), params=params)

    if resp.status_code == 404:
        print(f"  No log available for {log_date} (404).")
        return []
    if resp.status_code != 200:
        # Vault returns JSON errors even for binary endpoints
        try:
            err = resp.json()
            print(f"  API error: {err.get('errors', resp.text[:300])}")
        except Exception:
            print(f"  HTTP {resp.status_code}: {resp.text[:300]}")
        return []

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            names = z.namelist()
            if not names:
                print("  Empty ZIP received.")
                return []
            with z.open(names[0]) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
                return list(reader)
    except zipfile.BadZipFile:
        print("  Response was not a valid ZIP file.")
        return []


def analyze_api_usage(rows: list[dict], top_n: int = 10, label: str = ""):
    if not rows:
        print("  No data to analyze.")
        return

    total  = len(rows)
    errors = [r for r in rows if r.get("api_response_status", "SUCCESS") not in ("SUCCESS", "")]

    # Parse durations (ms)
    durations = []
    for r in rows:
        try:
            d = int(r.get("duration") or 0)
            if d > 0:
                durations.append((d, r))
        except (ValueError, TypeError):
            pass
    durations.sort(key=lambda x: x[0], reverse=True)

    endpoint_counts = Counter(r.get("endpoint", "").split("?")[0] for r in rows)
    user_counts     = Counter(r.get("username", "unknown") for r in rows)
    client_counts   = Counter(r.get("client_id", "unknown") for r in rows)
    http_codes      = Counter(r.get("http_response_status", "") for r in rows)
    error_types     = Counter(
        r.get("api_response_error_type", "") for r in errors
        if r.get("api_response_error_type")
    )

    title = f"  API USAGE ANALYSIS{f'  [{label}]' if label else ''}"
    print(f"\n{'='*64}")
    print(title)
    print(f"  Total calls: {total:,}   |   Errors: {len(errors):,} ({len(errors)/total*100:.1f}%)")
    print(f"{'='*64}")

    _print_table("TOP ENDPOINTS", ["Endpoint", "Calls"], endpoint_counts.most_common(top_n))
    _print_table("TOP USERS",     ["Username", "Calls"], user_counts.most_common(top_n))
    _print_table("TOP CLIENT IDs",["Client ID", "Calls"],client_counts.most_common(top_n))
    _print_table("HTTP STATUS CODES", ["Status", "Count"], sorted(http_codes.items()))

    if error_types:
        _print_table("ERROR TYPES", ["Error Type", "Count"], error_types.most_common(top_n))

    # Error details by endpoint
    if errors:
        err_by_ep = Counter(r.get("endpoint", "").split("?")[0] for r in errors)
        _print_table("ERRORS BY ENDPOINT", ["Endpoint", "Errors"], err_by_ep.most_common(top_n))

    # Slowest calls
    if durations:
        t = prettytable.PrettyTable(["Duration (ms)", "User", "Method", "Endpoint"])
        t.align = "l"
        for dur, r in durations[:top_n]:
            ep = r.get("endpoint", "")
            if len(ep) > 72:
                ep = ep[:69] + "..."
            t.add_row([f"{dur:,}", r.get("username", ""), r.get("http_method", ""), ep])
        print(f"\n  SLOWEST CALLS (top {top_n})")
        print(t)

        avg_dur = sum(d for d, _ in durations) / len(durations)
        print(f"  Avg duration: {avg_dur:,.0f} ms   |   Max: {durations[0][0]:,} ms")

    # Burst-limit warnings
    low_burst = []
    for r in rows:
        try:
            if int(r.get("burst_limit_remaining") or 999) < 100:
                low_burst.append(r)
        except (ValueError, TypeError):
            pass
    if low_burst:
        print(f"\n  WARNING: {len(low_burst):,} calls had burst_limit_remaining < 100")

    # SDK usage
    sdk_rows = [r for r in rows if r.get("sdk_count") and r["sdk_count"].strip() not in ("", "0")]
    if sdk_rows:
        print(f"\n  SDK invocations: {len(sdk_rows):,} calls triggered Vault Java SDK")


def _print_table(title: str, headers: list, data):
    t = prettytable.PrettyTable(headers)
    t.align = "l"
    for row in data:
        t.add_row(list(row))
    print(f"\n  {title}")
    print(t)


# ── Audit Trail ────────────────────────────────────────────────────────────────

def get_audit_types(session: str) -> list:
    url  = f"{VAULT_URL}/api/{VAULT_VERSION}/metadata/audittrail"
    resp = requests.get(url, headers=make_headers(session))
    resp.raise_for_status()
    data = resp.json()
    if data.get("responseStatus") != "SUCCESS":
        print("Error:", data)
        return []
    return data.get("audittrail", [])


def get_audit_details(
    session: str,
    audit_type: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    events: Optional[str] = None,
) -> list[dict]:
    url    = f"{VAULT_URL}/api/{VAULT_VERSION}/audittrail/{audit_type}"
    params = {}
    if start_date: params["start_date"] = start_date
    if end_date:   params["end_date"]   = end_date
    if events:     params["events"]     = events

    resp = requests.get(url, headers=make_headers(session), params=params)
    resp.raise_for_status()
    data = resp.json()
    if data.get("responseStatus") != "SUCCESS":
        print("Error:", data)
        return []
    return data.get("data", [])


def display_audit(rows: list[dict], top_n: int = 25):
    if not rows:
        print("  No audit records found.")
        return

    print(f"\n  {len(rows)} audit record(s) returned")

    PREFERRED = ["timestamp", "user_name", "full_name", "event_type",
                 "event_description", "item_type", "item_id", "item_name", "action"]
    fields     = list(rows[0].keys())
    show_fields = [f for f in PREFERRED if f in fields] or fields[:6]

    t = prettytable.PrettyTable(show_fields)
    t.align = "l"
    for row in rows[:top_n]:
        t.add_row([str(row.get(f, ""))[:55] for f in show_fields])
    print(t)

    if len(rows) > top_n:
        print(f"  ... {len(rows) - top_n} more rows not shown (increase --top to see more)")

    # Quick summary
    if "user_name" in fields:
        user_counts = Counter(r.get("user_name", "") for r in rows)
        print("\n  Top users by audit event:")
        for user, count in user_counts.most_common(5):
            print(f"    {user or '(unknown)':<40} {count:>5}")

    if "event_type" in fields:
        event_counts = Counter(r.get("event_type", "") for r in rows)
        print("\n  Top event types:")
        for ev, count in event_counts.most_common(10):
            print(f"    {ev or '(unknown)':<40} {count:>5}")


# ── SDK Runtime Log ────────────────────────────────────────────────────────────

def download_runtime_log(session: str, log_date: str) -> list[dict]:
    url    = f"{VAULT_URL}/api/{VAULT_VERSION}/logs/code/runtime"
    params = {"date": log_date, "log_format": "csv"}
    resp   = requests.get(url, headers=make_headers(session), params=params)

    if resp.status_code == 404:
        print(f"  No runtime log available for {log_date}.")
        return []
    if resp.status_code != 200:
        try:
            err = resp.json()
            print(f"  API error: {err.get('errors', resp.text[:300])}")
        except Exception:
            print(f"  HTTP {resp.status_code}: {resp.text[:300]}")
        return []

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            names = z.namelist()
            if not names:
                print("  Empty ZIP.")
                return []
            with z.open(names[0]) as f:
                reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
                return list(reader)
    except zipfile.BadZipFile:
        print("  Response was not a valid ZIP file.")
        return []


def display_runtime(rows: list[dict], top_n: int = 25):
    if not rows:
        print("  No runtime log data.")
        return

    print(f"\n  {len(rows)} runtime log entries")
    fields     = list(rows[0].keys())
    show_fields = fields[:7]

    t = prettytable.PrettyTable(show_fields)
    t.align = "l"
    for r in rows[:top_n]:
        t.add_row([str(r.get(f, ""))[:45] for f in show_fields])
    print(t)

    if len(rows) > top_n:
        print(f"  ... {len(rows) - top_n} more rows not shown")


# ── Commands ───────────────────────────────────────────────────────────────────

def cmd_api_usage(args):
    session  = get_session(args)
    log_date = args.date or (date.today() - timedelta(days=1)).isoformat()
    print(f"Downloading API Usage Log for {log_date} ...")
    rows = download_api_usage(session, log_date)
    analyze_api_usage(rows, top_n=args.top, label=log_date)

    if args.save:
        import json
        out = f"api_usage_{log_date}.json"
        with open(out, "w") as f:
            json.dump(rows, f, indent=2)
        print(f"\n  Raw data saved to {out}")


def cmd_multi_day(args):
    session = get_session(args)
    end     = date.today() - timedelta(days=1)
    start   = end - timedelta(days=args.days - 1)

    all_rows = []
    current  = start
    print(f"Fetching {args.days} days ({start} → {end}) ...")
    while current <= end:
        ds   = current.isoformat()
        rows = download_api_usage(session, ds)
        print(f"  {ds}: {len(rows):>6,} calls")
        all_rows.extend(rows)
        current += timedelta(days=1)

    print(f"\nAggregated total: {len(all_rows):,} calls over {args.days} days")
    analyze_api_usage(all_rows, top_n=args.top, label=f"last {args.days} days")


def cmd_audit(args):
    session = get_session(args)

    if args.list:
        types = get_audit_types(session)
        if not types:
            print("No audit types returned (check permissions).")
            return
        t = prettytable.PrettyTable(["Audit Type", "Label"])
        t.align = "l"
        for a in types:
            t.add_row([a.get("name", ""), a.get("label", "")])
        print(t)
        return

    audit_type = args.type or "login_audit_trail"
    print(f"Fetching audit trail: {audit_type} ...")
    rows = get_audit_details(session, audit_type, args.start_date, args.end_date, args.events)
    display_audit(rows, top_n=args.top)


def cmd_runtime(args):
    session  = get_session(args)
    log_date = args.date or (date.today() - timedelta(days=1)).isoformat()
    print(f"Downloading SDK Runtime Log for {log_date} ...")
    rows = download_runtime_log(session, log_date)
    display_runtime(rows, top_n=args.top)


# ── Entry Point ────────────────────────────────────────────────────────────────

def main():
    global VAULT_URL, VAULT_VERSION  # modified after arg parsing

    parser = argparse.ArgumentParser(
        prog="vault_log_analyzer",
        description="Veeva Vault Log Analyzer – pulls & analyzes Vault API logs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
commands:
  api-usage   download & analyze API usage log for one day
  multi-day   aggregate API usage logs over N days
  audit       list audit types or query an audit trail
  runtime     download & display SDK runtime log

examples:
  %(prog)s api-usage
  %(prog)s api-usage --date 2025-02-01 --top 20
  %(prog)s multi-day --days 14
  %(prog)s audit --list
  %(prog)s audit --type document_audit_trail --start-date 2025-01-01T00:00:00Z
  %(prog)s runtime --date 2025-02-01
        """,
    )

    # ── Global flags
    parser.add_argument("--vault-url",  default=VAULT_URL,     help="Vault base URL")
    parser.add_argument("--version",    default=VAULT_VERSION,  help="API version (default: v25.3)")
    parser.add_argument("--session",    default=SESSION_ID,     help="Session ID (or VAULT_SESSION env var)")
    parser.add_argument("--username",   help="Vault username")
    parser.add_argument("--password",   help="Vault password")
    parser.add_argument("--top", type=int, default=10, help="Rows to show per section (default: 10)")

    subs = parser.add_subparsers(dest="command")

    # api-usage
    p = subs.add_parser("api-usage", help="Download & analyze daily API usage log")
    p.add_argument("--date", help="Date YYYY-MM-DD (default: yesterday)")
    p.add_argument("--save", action="store_true", help="Save raw CSV rows to JSON file")
    p.set_defaults(func=cmd_api_usage)

    # multi-day
    p = subs.add_parser("multi-day", help="Aggregate API usage logs over multiple days")
    p.add_argument("--days", type=int, default=30, help="Number of past days (default: 30)")
    p.set_defaults(func=cmd_multi_day)

    # audit
    p = subs.add_parser("audit", help="Query audit trail")
    p.add_argument("--list",       action="store_true", help="List available audit types")
    p.add_argument("--type",       help="Audit trail type (e.g. login_audit_trail)")
    p.add_argument("--start-date", dest="start_date", help="Start date YYYY-MM-DDTHH:MM:SSZ")
    p.add_argument("--end-date",   dest="end_date",   help="End date YYYY-MM-DDTHH:MM:SSZ")
    p.add_argument("--events",     help="Comma-separated event filter (e.g. Edit,Delete)")
    p.set_defaults(func=cmd_audit)

    # runtime
    p = subs.add_parser("runtime", help="Download SDK runtime log")
    p.add_argument("--date", help="Date YYYY-MM-DD (default: yesterday)")
    p.set_defaults(func=cmd_runtime)

    args = parser.parse_args()

    # Push overrides back to globals used in URL building
    VAULT_URL     = args.vault_url
    VAULT_VERSION = args.version

    if not args.command:
        cmd_all(args)
        return

    with _Capture() as cap:
        args.func(args)
    _write_md([(args.command, cap.getvalue())],
              f"vault_logs_{args.command}_{date.today().isoformat()}.md")


def cmd_all(args):
    """Run all analyses with sensible defaults: yesterday's API log, login audit, runtime log."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    session   = get_session(args)

    # Inject defaults that individual commands normally set via their subparser
    args.date       = yesterday
    args.save       = False
    args.days       = 30
    args.list       = False
    args.type       = "login_audit_trail"
    args.start_date = None
    args.end_date   = None
    args.events     = None

    sep = "\n" + "━" * 64
    sections: list[tuple[str, str]] = []

    def _run(title: str, fn):
        print(sep)
        print(f"  {title}")
        print("━" * 64)
        with _Capture() as cap:
            fn(args)
        sections.append((title, cap.getvalue()))

    _run("[1/4] API USAGE — yesterday",    cmd_api_usage)
    _run("[2/4] API USAGE — last 30 days", cmd_multi_day)
    _run("[3/4] AUDIT TRAIL — login",      cmd_audit)
    _run("[4/4] SDK RUNTIME LOG",          cmd_runtime)

    _write_md(sections, f"vault_logs_{date.today().isoformat()}.md")


if __name__ == "__main__":
    main()
