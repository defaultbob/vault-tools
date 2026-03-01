# vault-tools

A collection of CLI tools for working with Veeva Vault, installable as a single `uv` package.

## Tools

| Command | Description |
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

### Install from Git

```bash
uv tool install "git+https://github.com/defaultbob/vault-tools"
```

### Install from a local copy

```bash
git clone https://github.com/defaultbob/vault-tools
uv tool install ./vault-tools
```

## Development

```bash
git clone https://github.com/defaultbob/vault-tools
cd vault-tools
uv sync
```

## Adding a New Tool

1. Add a module to `vault_tools/` (e.g. `vault_tools/my_tool.py`) with a `main()` entry point
2. Add a script entry to `[project.scripts]` in `pyproject.toml`:
   ```toml
   my-tool = "vault_tools.my_tool:main"
   ```
3. Add a README to a matching subdirectory `my-tool/README.md` and link it in the table above

## Credentials

Tools that connect to Vault read credentials from a `.env` file at the repo root:

```bash
VAULT_URL=https://your-vault.veevavault.com
VAULT_VERSION=v25.3
VAULT_USERNAME=you@domain.com
VAULT_PASSWORD=yourpassword
VAULT_SESSION=     # optional: pre-authenticated session ID
```

`.env` is listed in `.gitignore` and will not be committed.
