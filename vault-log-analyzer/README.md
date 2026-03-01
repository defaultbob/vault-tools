# Vault Log Analyzer

A CLI tool that pulls and analyzes API logs from Veeva Vault using the Vault REST API (v25.3).

---

## Distribution (uv / uvx)

The tool is packaged for cross-platform distribution via [uv](https://docs.astral.sh/uv/).
No Python installation or admin rights required on the target machine.

### Install uv (one-time, per machine)

**Mac / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows:**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Install from Git

```bash
uv tool install "git+<repo-url>#subdirectory=vault-log-analyzer"
vault-log-analyzer
```

### Install from a local copy

```bash
# From the workspace root:
uv tool install ./vault-log-analyzer
vault-log-analyzer
```

> Replace `<repo-url>` with your internal GitHub/GitLab URL.

---

## Local Development Setup

### 1. Install dependencies

From the workspace root:

```bash
uv sync
```

### 2. Configure credentials

Create a `.env` file at the workspace root:

```bash
VAULT_URL=https://your-vault.veevavault.com
VAULT_VERSION=v25.3
VAULT_USERNAME=you@domain.com
VAULT_PASSWORD=yourpassword
VAULT_SESSION=           # optional: pre-authenticated session ID
```

The tool loads `.env` automatically. You can also override any value at runtime with CLI flags.

> `.env` is listed in `.gitignore` and will not be committed.

---

## Commands

### `api-usage` — Daily API Usage Log

Downloads the daily API usage log for one day (up to 30 days back) and prints a full analysis.

```bash
python vault_log_analyzer.py api-usage                   # yesterday
python vault_log_analyzer.py api-usage --date 2025-02-01
python vault_log_analyzer.py api-usage --date 2025-02-01 --top 20
python vault_log_analyzer.py api-usage --save            # also writes raw rows to JSON
```

**Analysis sections:**
| Section | Description |
|---|---|
| Top Endpoints | Most-called API endpoints |
| Top Users | Users generating the most calls |
| Top Client IDs | Integration clients by volume |
| HTTP Status Codes | Distribution of 200/400/500 responses |
| Error Types | `INSUFFICIENT_ACCESS`, `INVALID_DATA`, etc. |
| Errors by Endpoint | Which endpoints are failing most |
| Slowest Calls | Sorted by duration (ms) |
| Burst Limit Warning | Flags calls where remaining limit < 100 |
| SDK Invocations | Count of calls that triggered Vault Java SDK |

---

### `multi-day` — Multi-Day Aggregate Analysis

Fetches and aggregates logs across N consecutive days (ending yesterday).

```bash
python vault_log_analyzer.py multi-day                   # last 30 days (default)
python vault_log_analyzer.py multi-day --days 14
python vault_log_analyzer.py multi-day --days 7 --top 15
```

Same analysis sections as `api-usage`, applied to the combined dataset.

---

### `audit` — Audit Trail

Query Vault audit trails: login activity, document changes, object changes, and more.

```bash
# List available audit types (login_audit_trail, document_audit_trail, etc.)
python vault_log_analyzer.py audit --list

# Query the login audit trail (default)
python vault_log_analyzer.py audit

# Query a specific type
python vault_log_analyzer.py audit --type document_audit_trail
python vault_log_analyzer.py audit --type object_audit_trail

# Filter by date range (ISO 8601, UTC)
python vault_log_analyzer.py audit --type login_audit_trail \
  --start-date 2025-02-01T00:00:00Z \
  --end-date   2025-02-28T23:59:59Z

# Filter by event type
python vault_log_analyzer.py audit --type document_audit_trail \
  --events "Edit,Delete,CheckOut"
```

**Common audit types:**

| Type | What it tracks |
|---|---|
| `login_audit_trail` | User logins and logouts |
| `document_audit_trail` | Document edits, approvals, deletions |
| `object_audit_trail` | Object record changes |
| `system_audit_trail` | Admin/system-level changes |

> Audit data is limited to the past 30 days per API call (unless using `all_dates=true` with CSV export).

---

### `runtime` — SDK Runtime Log

Downloads the Vault Java SDK runtime log for a given day.

```bash
python vault_log_analyzer.py runtime                     # yesterday
python vault_log_analyzer.py runtime --date 2025-02-01
```

> Requires **Admin: Logs: Vault Java SDK Logs** permission.
> Runtime logs are available ~15 minutes after the SDK transaction completes.

---

## Global Options

All commands accept these flags:

| Flag | Description |
|---|---|
| `--vault-url <url>` | Override the Vault base URL |
| `--version <ver>` | Override API version (default: `v25.3`) |
| `--session <id>` | Use a specific session ID |
| `--username <u>` | Vault username (auto-authenticates) |
| `--password <p>` | Vault password |
| `--top <n>` | Number of rows to show per section (default: 10) |

---

## Auth Priority

The script resolves credentials in this order:

1. `--session` flag
2. `VAULT_SESSION` in `.env`
3. `--username` + `--password` flags
4. `VAULT_USERNAME` + `VAULT_PASSWORD` in `.env`

---

## Required Permissions

| Command | Required Vault Permission |
|---|---|
| `api-usage` | Admin: Logs: API Usage Logs |
| `audit` | Admin: Logs: (varies by audit type) |
| `runtime` | Admin: Logs: Vault Java SDK Logs |

---

## API Reference

Endpoints used (Vault API v25.3):

| Endpoint | Purpose |
|---|---|
| `POST /api/{v}/auth` | Authenticate (username + password) |
| `GET /api/{v}/logs/api_usage` | Download daily API usage log (ZIP/CSV) |
| `GET /api/{v}/logs/code/runtime` | Download SDK runtime log (ZIP/CSV) |
| `GET /api/{v}/metadata/audittrail` | List available audit types |
| `GET /api/{v}/audittrail/{type}` | Query an audit trail |

Full spec: [Vault API v25.3](https://developer.veevavault.com/api/25.3/)
