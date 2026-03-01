# vault-tools

A collection of CLI tools for working with Veeva Vault, packaged as a `uv` workspace.

## Tools

| Tool | Description |
|---|---|
| [vault-log-analyzer](vault-log-analyzer/README.md) | Pull and analyze API logs, audit trails, and SDK runtime logs from Veeva Vault |

## Installation

### Install uv (one-time, per machine)

**Mac / Linux:**
```bash
brew install uv 
# or
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows:**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Install all tools from Git

```bash
uv tool install "git+<repo-url>"
```


### Install all tools from a local copy

```bash
git clone <repo-url>
cd vault-tools
uv tool install ./vault-log-analyzer
```

### Install a specific tool from Git

```bash
uv tool install "git+<repo-url>#subdirectory=vault-log-analyzer"
```

## Development

```bash
git clone <repo-url>
cd vault-tools
uv sync          # installs all workspace members into a shared .venv
```

## Adding a New Tool

1. Create a subdirectory: `my-tool/`
2. Add a `pyproject.toml` with `[project]` and `[project.scripts]`
3. Add `"my-tool"` to `members` in the root `pyproject.toml`
4. Run `uv sync`

## Credentials

Tools that connect to Vault read credentials from a `.env` file at the workspace root:

```bash
VAULT_URL=https://your-vault.veevavault.com
VAULT_VERSION=v25.3
VAULT_USERNAME=you@domain.com
VAULT_PASSWORD=yourpassword
VAULT_SESSION=     # optional: pre-authenticated session ID
```

`.env` is listed in `.gitignore` and will not be committed.
