# CPA Usage Keeper

[中文说明](./README.md)

CPA Usage Keeper is a standalone CPA usage persistence and dashboard service.

It relies on [CLIProxyAPI (CPA)](https://github.com/router-for-me/CLIProxyAPI) as the backend CPA data source and adds persistent storage and statistical analysis capabilities on top of CPA. The service periodically pulls CPA data, writes normalized events to SQLite, exposes aggregation APIs, and serves a built-in web dashboard for usage, pricing, request health, and model/API statistics.

![cpa-usage-keeper-screenshot](https://images.bitskyline.com/i/2026/04/h9se9f.png)

## Features

- CPA usage persistence in SQLite
- Aggregated usage and pricing APIs
- Built-in React dashboard
- Optional password login protection
- Local SQLite database backups with retention

## Tech Stack

- **Backend**: Python 3.12+ / FastAPI / SQLAlchemy / SQLite
- **Package Manager**: uv
- **Frontend**: React + TypeScript (Vite)

## Installation

### Option 1: via uv (recommended)

```bash
uv tool install cpa-usage-keeper
```

After installation, the `cpa-usage-keeper` command is globally available. To upgrade:

```bash
uv tool upgrade cpa-usage-keeper
```

### Option 2: via pip

```bash
pip install cpa-usage-keeper
```

## Quick Start

1. Download the config template and fill in your values:

```bash
curl -fsSL https://raw.githubusercontent.com/8DE4732A/cpa-usage-keeper/main/config.example.toml -o config.toml
```

At minimum, fill in `base_url` and `management_key` under the `[cpa]` section.

2. Run from the directory containing `config.toml` (auto-loaded):

```bash
cpa-usage-keeper
```

Or specify the config file path explicitly:

```bash
cpa-usage-keeper -c /path/to/config.toml
```

3. Open your browser at `http://localhost:8080` (port is configurable).

## Project Structure

```text
src/cpa_usage_keeper/    Python backend source
  app.py                 FastAPI app factory & lifecycle
  config.py              Environment config loading
  database.py            SQLAlchemy database init
  models.py              ORM models
  cpa/                   CPA client and types
  api/                   HTTP route handlers
  service/               Sync and business services
  repository/            Database access layer
  poller/                Background sync loops
  auth/                  In-memory session auth
  redact/                Data redaction
  backup.py              SQLite backup management
  logging_config.py      Logging configuration
web/                     React + TypeScript frontend
static/                  Frontend build output (gitignored)
```

## Configuration

Copy the config template:

```bash
cp config.example.toml config.toml
```

The config file is organized into sections:

**`[cpa]`**

| Key | Required | Default | Description |
| --- | --- | --- | --- |
| `base_url` | Yes | - | CPA server URL |
| `management_key` | Yes | - | CPA management key |
| `request_timeout` | No | `30s` | CPA request timeout |

**`[app]`**

| Key | Required | Default | Description |
| --- | --- | --- | --- |
| `port` | No | `8080` | HTTP listen port |
| `base_path` | No | root path | Subpath deployment prefix, e.g. `/cpa`; empty means `/` |
| `timezone` | No | `Asia/Shanghai` | Business timezone — affects Today, daily aggregation, cleanup, and log timestamps |

**`[auth]`**

| Key | Required | Default | Description |
| --- | --- | --- | --- |
| `enabled` | No | `false` | Enable login protection |
| `password` | When auth is enabled | - | Login password |
| `session_ttl` | No | `168h` | Session lifetime |

**`[sync]`**

| Key | Required | Default | Description |
| --- | --- | --- | --- |
| `mode` | No | `auto` | Sync mode: `auto`, `redis`, `legacy_export` |
| `poll_interval` | No | `5m` | Pull interval for `legacy_export` |

**`[redis]`**

| Key | Required | Default | Description |
| --- | --- | --- | --- |
| `queue_addr` | No | `base_url` hostname + `8317` | CPA Redis/RESP TCP address |
| `queue_batch_size` | No | `1000` | Maximum queue records per pull |
| `queue_idle_interval` | No | `1s` | Empty queue check interval |

**`[storage]`**

| Key | Required | Default | Description |
| --- | --- | --- | --- |
| `work_dir` | No | `./data` | Application work directory for database, logs, and backups |
| `backup_enabled` | No | `true` | Enable SQLite database backups |
| `backup_interval` | No | `24h` | Database backup interval |
| `backup_retention_days` | No | `7` | Backup retention days |

**`[log]`**

| Key | Required | Default | Description |
| --- | --- | --- | --- |
| `level` | No | `info` | Log level |
| `file_enabled` | No | `true` | Write persistent log files |
| `retention_days` | No | `7` | Log retention days; `0` disables auto-cleanup |

## Development

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+
- npm
- A running [CLIProxyAPI (CPA)](https://github.com/router-for-me/CLIProxyAPI) instance

### Run locally

1. Create your local config:

```bash
cp config.example.toml config.toml
```

2. Edit `config.toml` with your values.

3. Install Python dependencies:

```bash
uv sync
```

4. Start the backend:

```bash
uv run python -m cpa_usage_keeper -c config.toml
```

5. In another terminal, install frontend dependencies and start the dev server:

```bash
npm --prefix ./web ci
npm --prefix ./web run dev -- --host 127.0.0.1
```

6. Build the frontend for production:

```bash
npm --prefix ./web run build
```

### Tests

Run the frontend verification baseline:

```bash
make verify
```

## Subpath reverse proxy

When serving under `/cpa`, set `base_path = "/cpa"` in config and keep the prefix in your reverse proxy:

```nginx
location /cpa/ {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

## Publishing

Push a `v*` tag to trigger the GitHub Actions workflow that builds the frontend, packages the wheel, and publishes to PyPI:

```bash
git tag v1.2.0
git push origin v1.2.0
```

Publishing uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) — no API token is stored in the repository. Configure GitHub Actions as a trusted publisher in your PyPI project settings first.
