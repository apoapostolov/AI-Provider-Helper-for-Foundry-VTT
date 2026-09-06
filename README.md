# AI Provider Helper

The local AI helper for the [AI Provider Library](https://github.com/apoapostolov/AI-Provider-Library-for-Foundry-VTT)
Foundry VTT module. It runs on your computer, holds the key vault, speaks
HTTPS to AI providers, and listens on loopback only:

- **8090** app: health, catalog, vault, OAuth, probes, chat, vision, images
- **8091** control: start/stop/status

The Foundry tab never talks to OpenAI-class hosts directly. See
[docs/SERVER.md](docs/SERVER.md) for the full HTTP contract.

## Run it

### Most GMs: download the zip

1. Open the [latest GitHub release](https://github.com/apoapostolov/AI-Provider-Helper-for-Foundry-VTT/releases/latest).
2. Download **AI-Helper-windows.zip**.
3. Unzip it anywhere you like.
4. Double-click **AI Helper.bat** and leave the window open.

On The Forge, Molten, Foundry Server, or another host, double-click
**AI Helper (hosted).bat** instead. Details: [tools/HELPER.md](tools/HELPER.md).

### Technical users: npx

Needs Python 3.11+ on PATH (or `APL_PYTHON` pointing at it). First run
creates a venv inside the package and installs requirements:

```bash
npx ai-provider-helper
# options
npx ai-provider-helper --port 8090 --ctl-port 8091 --hosted
```

`--hosted` adds CORS for Forge-class hosts. Ctrl+C stops both servers.

### From a checkout

```bash
cd backend
uv venv && uv pip install -r requirements.txt
uv run uvicorn app.main:app --host 127.0.0.1 --port 8090
```

Linux systemd units: `dev/install-backend.sh` in the module repo, or run the
control server as a child like the npm entry does.

## Build the Windows zip

```bash
python companion/pack_windows.py
```

Produces `companion/dist/AI-Helper-windows.zip`: embeddable CPython, the
backend, and the launchers. No PATH, no venv dance for the GM.

## Tests

```bash
cd backend && pytest
```

No live provider spend.

## Safety

- Loopback bind by default. No `0.0.0.0` until v2 has a control token.
- Hosted CORS only for the explicit origin list, never `*`.
- `/v1/fetch-image` rejects localhost, `0.0.0.0`, `::1`, and `*.local`.
- Vault keys are AES-256-GCM at rest, token files are mode `0600`.
- Keys are never logged and never returned to consumers.
