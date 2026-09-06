# Local endpoint

Bind: `0.0.0.0:8090`. Control: `0.0.0.0:8091`.
CORS allows loopback, LAN, Tailscale, and `.local` Foundry origins.
`APL_CORS_ORIGINS` adds hosted origins such as `https://*.forge-vtt.com`.
The Foundry client uses the page host when Endpoint Host is loopback **and**
the page host is private. A Forge hostname keeps `127.0.0.1` so the helper
stays on the GM PC.

GMs start the helper from [tools/HELPER.md](../tools/HELPER.md).
Windows: GitHub Releases `AI-Helper-windows.zip`, then `AI Helper.bat`.
Hosted Foundry: `AI Helper (hosted).bat`. Binds `127.0.0.1`.

Checkout path (Windows, macOS, Linux). Leave the window open.

```bash
python3 tools/run-helper.py
python3 tools/run-helper.py --foundry-hosted
```

Linux user units stay available:

```bash
cd backend
uv venv && uv pip install -r requirements.txt
uv run uvicorn app.main:app --host 127.0.0.1 --port 8090
# or
../dev/install-backend.sh
```

Env: `APL_HOST`, `APL_PORT`, `APL_CACHE`, `APL_DEBUG`, `APL_CORS_ORIGINS`,
`APL_CTL_BACKEND` (`auto`, `child`, `systemd`),
`OPENROUTER_API_KEY`, `HF_TOKEN`, `ARTIFICIAL_ANALYSIS_API_KEY`,
`ZEROEVAL_API_KEY`.

## App routes

| Method | Path | Body / query | Result |
| --- | --- | --- | --- |
| GET | `/health` | | `{status, service, port}`. Can wait behind catalog or quota poll. |
| GET | `/v1/catalog` | `capability`, `refresh=1`, `sources=a,b` | providers + live counts + evaluation metadata |
| GET | `/v1/evaluations` | `sources=a,b` | cached model evaluations and source status |
| POST | `/v1/evaluations/refresh` | `{source, sources:[...]}` | sequential source refresh + recalculated metadata |
| POST | `/v1/query` | `QueryRequest` | taxonomy + `granted` |
| GET | `/v1/vault` | | credential metadata, no secrets |
| POST | `/v1/vault` | `VaultUpsert` | create/update key + grants + enabled state |
| DELETE | `/v1/vault/{id}` | | drop a key |
| GET | `/v1/quota` | `provider` | last snapshot |
| POST | `/v1/quota/poll` | | refresh snapshots |
| POST | `/v1/providers/probe` | `ProbeRequest` | `{ok, detail, models}` |
| GET | `/v1/providers/{id}/oauth/status` | | `{connected, expires_at?}` |
| POST | `/v1/providers/{id}/oauth/start` | | device code payload |
| POST | `/v1/providers/{id}/oauth/poll` | `{flow_id}` | `{status}` |
| GET | `/v1/providers/{id}/oauth/token` | | `{access_token, expires_at}` |
| DELETE | `/v1/providers/{id}/oauth` | | `{ok}` |
| POST | `/v1/chat/completions` | `ChatRequest` | provider JSON |
| POST | `/v1/vision/complete` | `VisionRequest` | provider JSON |
| POST | `/v1/images/generations` | `ImageRequest` | provider JSON or `{b64}` |
| POST | `/v1/images/edits` | `ImageRequest` | provider JSON |
| POST | `/v1/codex/images` | `ImageRequest` | `{b64}` |
| POST | `/v1/fetch-image` | `{url}` | image bytes |
| POST | `/v1/shutdown` | | `{ok}` then process exits |

### ProbeRequest

```json
{
  "provider": "openai",
  "endpoint": "",
  "model": "",
  "api_key": "",
  "refresh": false,
  "capability": "vision"
}
```

`api_key` is never logged (`repr=False`). Codex probe hits
`/backend-api/wham/usage` instead of `/models`.

### ChatRequest

```json
{
  "provider": "openai",
  "endpoint": "",
  "model": "gpt-4o",
  "api_key": "",
  "messages": [{ "role": "user", "content": "..." }],
  "extras": {}
}
```

### VisionRequest

```json
{
  "provider": "openai",
  "model": "gpt-4o",
  "api_key": "",
  "prompt": "Name the terrain in this crop.",
  "image": "data:image/png;base64,..."
}
```

The helper wraps the image as an OpenAI-compatible `image_url` part.

### ImageRequest

```json
{
  "provider": "openai",
  "model": "gpt-image-2",
  "api_key": "",
  "prompt": "a stone tile",
  "width": 1024,
  "height": 1024,
  "images": []
}
```

Codex ignores `api_key` if a stored OAuth session exists.

## Control routes (8091)

| Method | Path | Result |
| --- | --- | --- |
| GET | `/status` | `{ok, running, backend}` child pid or systemd unit |
| POST | `/start` | starts uvicorn (child) or the systemd unit |
| POST | `/stop` | stops that process |

`tools/run-helper.py` forces `APL_CTL_BACKEND=child`. Linux install still uses systemd when the user unit exists.
Local Endpoint Server uses `GET /status` when `GET /health` is slow.
Quota poll runs provider checks in parallel. Stop logs `ctl stop from <ip>`.
The unit uses `TimeoutStopSec=10` and `--timeout-graceful-shutdown 3`.

## Catalog refresh

`GET /v1/catalog?refresh=1` pulls:

- OpenRouter `GET https://openrouter.ai/api/v1/models`
- Hugging Face `GET https://huggingface.co/api/models?pipeline_tag=...`

Results attach to the `openrouter` and `huggingface` provider rows. Other
providers keep the static seed until a per-provider probe with
`refresh: true` returns `/models`.

## Model evaluations

`POST /v1/evaluations/refresh` accepts one source ID at a time. The client
calls checked sources in sequence so the UI can show progress and warn about a
single failed source without discarding the other sources. The Artificial
Analysis refresh may include `apiKey`, supplied by the module's world setting;
it is used only for that localhost download request and is never returned in
cache or model payloads. The optional
`sources` list controls which cached sources participate in the merged result;
disabling a source removes its cached scores from weighting until it is enabled
again. The helper stores normalized source records and derived model metadata in
`cache/evaluations.json`. There is no TTL and no background refresh. Successful
records remain cached indefinitely until a later successful manual evaluation
download replaces that source. Failed downloads preserve the previous records
and only update the attempt/error status. Source scores are normalized before weighted merging;
Models.dev supplies capabilities, context, and pricing but does not affect
intelligence ranking. CodeSOTA is annotation-only.

## Safety

- Helper binds localhost only.
- `/v1/fetch-image` rejects localhost, `0.0.0.0`, `::1`, and `*.local`.
- OAuth token files are `cache/oauth/{provider}.json` with mode `0600`.
- Never return token values from `/health` or `/v1/catalog`.
