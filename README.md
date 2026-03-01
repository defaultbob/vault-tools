# vault-tools

A collection of CLI tools for working with Veeva Vault, installable as a single `uv` package.

## Tools

| Command | Description |
|---|---|
| [vault-log-analyzer](vault-log-analyzer/README.md) | Pull and analyze API logs, audit trails, and SDK runtime logs from Veeva Vault |
| [vault-ddapi](vault-ddapi/README.md) | Sync Vault data (documents, users, objects, audit trail) to a local SQLite database via Direct Data API |

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

## Updating

### Installed from Git

```bash
uv tool upgrade vault-tools
```

### Installed from a local copy

```bash
cd vault-tools
git pull
uv tool install ./vault-tools --force
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

All tools read from a single `.env` file at the repo root. Copy the template and fill in your values:

```bash
cp .env.example .env
```

`.env` is gitignored and will never be committed. See [.env.example](.env.example) for all available keys.
