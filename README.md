# AI Provider Helper

**Give your Foundry AI modules one place to reach their models, without handing
your provider keys to each module.**

AI Provider Helper runs on your computer alongside Foundry. It keeps the keys,
connects to providers, and serves the AI tools used by modules such as
[Hex Atlas Survey](https://github.com/apoapostolov/Hex-Atlas-Survey-for-Foundry-VTT)
and [Imaginary Tiles](https://github.com/apoapostolov/Imaginary-Tiles-for-Foundry-VTT).
The [AI Provider Library](https://github.com/apoapostolov/AI-Provider-Library-for-Foundry-VTT)
connects those modules to this helper. Start it before opening their AI tools
and leave its window running while you play.

The helper listens on your computer rather than exposing your keys through the
Foundry host. It uses two local ports:

- **8090** app: health, catalog, vault, OAuth, probes, chat, vision, images
- **8091** control: start/stop/status

The Foundry tab does not contact AI providers directly. For the exact HTTP
contract and security model, see [the server reference](docs/SERVER.md).

## Get started

### Windows

1. Open the [latest GitHub release](https://github.com/apoapostolov/AI-Provider-Helper-for-Foundry-VTT/releases/latest).
2. Download **AI-Helper-windows.zip**.
3. Unzip it anywhere you like.
4. Double-click **AI Helper.bat** and leave the window open.

If Foundry is hosted on The Forge, Molten, Foundry Server, or another service,
run **AI Helper (hosted).bat** instead. The
[helper guide](tools/HELPER.md) covers that setup.

### macOS, Linux, and command-line users

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

## For contributors

Build the Windows zip with:

```bash
python companion/pack_windows.py
```

Produces `companion/dist/AI-Helper-windows.zip`: embeddable CPython, the
backend, and the launchers. No PATH, no venv dance for the GM.

Run tests with:

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
