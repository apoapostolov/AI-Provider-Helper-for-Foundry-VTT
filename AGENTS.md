# AI Provider Helper

The local helper (proxy) for AI Provider Library, split out of the module
repo. Phase A of `dev/HELPER-SPLIT.md` in the module repo: backend is
verbatim, the npm entry is a wrapper, GMs keep the zip.

- Follow the module repo `AGENTS.md` conventions where they apply here.
- App is 8090. Control is 8091. Never a second port pair.
- Do not change HTTP routes without bumping the contract version and
  updating the module repo `docs/SERVER.md` in the same release train.
- Loopback bind default. No `0.0.0.0`. Hosted CORS only via the explicit
  origin list in `bin/cli.js` and `companion/launch.py`.
- Keys never logged. Vault files 0600.
- Keep `companion/pack_windows.py` as the only zip builder. Do not
  hand-roll zip commands.
- Tests: `cd backend && pytest` before any push. No live provider spend.
- Do not commit, push, release, or change visibility unless asked.
