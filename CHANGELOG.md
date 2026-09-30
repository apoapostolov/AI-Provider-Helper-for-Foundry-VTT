# Changelog

## 14.1.0 — 2026-09-07

The first standalone release of AI Provider Helper. Foundry AI modules can use
one local helper for provider connections and credentials.

### Added

- Windows users can download the helper, unzip it, and start it with a batch
  file. A separate launcher supports hosted Foundry worlds.
- Command-line users can run the helper with `npx ai-provider-helper` and
  Python 3.11 or later.
- The helper keeps provider credentials on the local computer while serving
  the [AI Provider Library](https://github.com/apoapostolov/AI-Provider-Library-for-Foundry-VTT)
  and its consumer modules.

See the [README](README.md) for setup and the [server reference](docs/SERVER.md)
for the HTTP contract.
