# AI Helper

Chat, images, and live model lists need a small program on **your** computer.
The Foundry hosting company cannot run it for you.

You download it. You double-click it. You leave the window open while you play.
You close the window when you are done.

## Windows

1. Open the [latest GitHub release](https://github.com/apoapostolov/AI-Provider-Helper-for-Foundry-VTT/releases/latest).
2. Download **AI-Helper-windows.zip**.
3. Unzip it anywhere you like.
4. Double-click **AI Helper.bat**.
5. Leave that window open.

If you play on The Forge, Molten, Foundry Server, or another host, double-click
**AI Helper (hosted).bat** instead.

Do this the first time on this PC, and again if the helper window is not
already open.

## Mac and Linux

Open a terminal and run one command:

```text
npx ai-provider-helper
```

You need Python 3.11 or newer installed. Hosted Foundry: add `--hosted`.

```text
npx ai-provider-helper --hosted
```

Press Ctrl+C to stop the helper.

## If it still will not connect

Pause the ad blocker on the Foundry tab, then reload the world.

### uBlock Origin

1. Open Foundry.
2. Click the uBlock Origin icon.
3. Click the large power button so the toolbar icon goes gray.
4. Or add this Foundry site under **Trusted sites**.

### uBlock Origin Lite

Disable filtering on this site in the popup, then reload.

### Adblock Plus

**Allowlisted websites**, add the Foundry URL. Smart allowlisting drops a site
after seven days if you do not visit it.

### AdBlock, AdGuard, Privacy Badger, Brave Shields

Pause or allowlist the Foundry tab the same way you would for a site that
needs to talk to something on this computer.

Safari will not let a hosted Foundry page talk to a helper on this computer.
Use Chrome, Edge, Firefox, or the Foundry desktop app.

## What to leave alone in Foundry

Leave **Endpoint Host** on the default. Do not type a public IP.

If the browser asks to allow access to your local network, click **Allow**.
