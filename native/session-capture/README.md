# session-capture

WASAPI sidecar for AI Provider Helper. Process loopback first, device loopback if that activation fails.

```
session-capture list
session-capture record --pid 1234 --out C:\path\job [--mic default|--no-mic]
```

Stop by writing `stop` in the out folder, or Ctrl+C.

Rebuild:

```
dotnet publish -c Release -r win-x64 --self-contained false -o publish
```

Needs the .NET 9 targeting pack. Runtime roll-forward accepts a newer host (this PC is .NET 10).
