using System.Diagnostics;
using System.Globalization;
using System.Text.Json;
using NAudio.CoreAudioApi;
using NAudio.Wave;

namespace SessionCapture;

internal static class Program
{
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = false
    };

    public static async Task<int> Main(string[] args)
    {
        if (args.Length == 0 || args[0] is "-h" or "--help" or "help")
        {
            Console.Error.WriteLine("session-capture list");
            Console.Error.WriteLine("session-capture record --pid <id> --out <dir> [--mic default] [--no-mic]");
            return 2;
        }
        try
        {
            if (args[0] == "list" || args[0] == "--list")
            {
                Console.WriteLine(JsonSerializer.Serialize(ListCapture(), JsonOpts));
                return 0;
            }
            if (args[0] == "record" || args[0] == "--record")
            {
                return await RecordAsync(ParseRecord(args));
            }
            Console.Error.WriteLine("unknown command");
            return 2;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 1;
        }
    }

    private static Dictionary<string, object?> ListCapture()
    {
        using var enumerator = new MMDeviceEnumerator();
        var devices = new List<Dictionary<string, object?>>();
        var sessions = new List<Dictionary<string, object?>>();
        foreach (var flow in new[] { DataFlow.Capture, DataFlow.Render })
        {
            foreach (var device in enumerator.EnumerateAudioEndPoints(flow, DeviceState.Active))
            {
                using (device)
                {
                    var isDefault = false;
                    try
                    {
                        using var def = enumerator.GetDefaultAudioEndpoint(flow, Role.Multimedia);
                        isDefault = def.ID == device.ID;
                    }
                    catch
                    {
                        // no default endpoint for this flow
                    }
                    devices.Add(new Dictionary<string, object?>
                    {
                        ["id"] = device.ID,
                        ["name"] = device.FriendlyName,
                        ["flow"] = flow == DataFlow.Capture ? "capture" : "render",
                        ["default"] = isDefault
                    });
                    if (flow != DataFlow.Render) continue;
                    try
                    {
                        var manager = device.AudioSessionManager;
                        var collection = manager.Sessions;
                        for (var i = 0; i < collection.Count; i++)
                        {
                            using var session = collection[i];
                            uint pid = 0;
                            try { pid = session.GetProcessID; }
                            catch { continue; }
                            if (pid == 0) continue;
                            string name;
                            try { name = Process.GetProcessById((int)pid).ProcessName; }
                            catch { name = session.DisplayName; }
                            if (!name.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
                                name += ".exe";
                            float peak = 0;
                            try { peak = session.AudioMeterInformation.MasterPeakValue; }
                            catch { /* meter unavailable */ }
                            sessions.Add(new Dictionary<string, object?>
                            {
                                ["pid"] = pid,
                                ["name"] = name,
                                ["peak"] = peak,
                                ["device"] = device.FriendlyName
                            });
                        }
                    }
                    catch
                    {
                        // session manager unavailable on this endpoint
                    }
                }
            }
        }
        return new Dictionary<string, object?>
        {
            ["ok"] = true,
            ["devices"] = devices,
            ["sessions"] = sessions
        };
    }

    private sealed record RecordArgs(uint Pid, string OutDir, bool IncludeMic);

    private static RecordArgs ParseRecord(string[] args)
    {
        uint pid = 0;
        var outDir = "";
        var includeMic = true;
        for (var i = 1; i < args.Length; i++)
        {
            var key = args[i];
            string Next() => i + 1 < args.Length ? args[++i] : "";
            switch (key)
            {
                case "--pid":
                    pid = uint.Parse(Next(), CultureInfo.InvariantCulture);
                    break;
                case "--out":
                    outDir = Next();
                    break;
                case "--mic":
                    Next();
                    includeMic = true;
                    break;
                case "--no-mic":
                    includeMic = false;
                    break;
            }
        }
        if (pid == 0) throw new ArgumentException("--pid is required");
        if (string.IsNullOrWhiteSpace(outDir)) throw new ArgumentException("--out is required");
        return new RecordArgs(pid, outDir, includeMic);
    }

    private static async Task<int> RecordAsync(RecordArgs args)
    {
        Directory.CreateDirectory(args.OutDir);
        var stopPath = Path.Combine(args.OutDir, "stop");
        var statusPath = Path.Combine(args.OutDir, "status.json");
        var remotePath = Path.Combine(args.OutDir, "remote.wav");
        var micPath = Path.Combine(args.OutDir, "mic.wav");
        var started = DateTime.UtcNow;
        var peak = 0f;
        var cts = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) =>
        {
            e.Cancel = true;
            cts.Cancel();
        };

        WasapiRecorder? remote = null;
        WasapiRecorder? mic = null;
        WaveFileWriter? remoteWriter = null;
        WaveFileWriter? micWriter = null;
        try
        {
            var format = new WaveFormat(48000, 16, 1);
            try
            {
                remote = await new WasapiRecorderBuilder()
                    .WithProcessLoopback(args.Pid, ProcessLoopbackMode.IncludeTargetProcessTree)
                    .WithFormat(format)
                    .BuildAsync();
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("process loopback failed, using device loopback: " + ex.Message);
                remote = new WasapiRecorderBuilder()
                    .WithLoopbackCapture()
                    .WithFormat(format)
                    .Build();
            }
            remoteWriter = new WaveFileWriter(remotePath, remote.WaveFormat);
            remote.DataAvailable += (buffer, _, _, _) =>
            {
                lock (remoteWriter)
                {
                    remoteWriter.Write(buffer);
                }
                var sample = Peak(buffer, remote.WaveFormat);
                if (sample > peak) peak = sample;
            };
            remote.StartRecording();

            if (args.IncludeMic)
            {
                mic = new WasapiRecorderBuilder().WithFormat(format).Build();
                micWriter = new WaveFileWriter(micPath, mic.WaveFormat);
                mic.DataAvailable += (buffer, _, _, _) =>
                {
                    lock (micWriter)
                    {
                        micWriter.Write(buffer);
                    }
                };
                mic.StartRecording();
            }

            string processName;
            try { processName = Process.GetProcessById((int)args.Pid).ProcessName + ".exe"; }
            catch { processName = args.Pid.ToString(CultureInfo.InvariantCulture); }

            while (!cts.IsCancellationRequested && !File.Exists(stopPath))
            {
                var payload = new Dictionary<string, object?>
                {
                    ["ok"] = true,
                    ["pid"] = args.Pid,
                    ["process"] = processName,
                    ["elapsedMs"] = (long)(DateTime.UtcNow - started).TotalMilliseconds,
                    ["peak"] = peak
                };
                await File.WriteAllTextAsync(statusPath, JsonSerializer.Serialize(payload, JsonOpts), cts.Token).ConfigureAwait(false);
                await Task.Delay(400, cts.Token).ConfigureAwait(false);
            }
            return 0;
        }
        catch (OperationCanceledException)
        {
            return 0;
        }
        finally
        {
            try { remote?.StopRecording(); } catch { /* already stopped */ }
            try { mic?.StopRecording(); } catch { /* already stopped */ }
            remoteWriter?.Dispose();
            micWriter?.Dispose();
            remote?.Dispose();
            mic?.Dispose();
        }
    }

    private static float Peak(ReadOnlySpan<byte> buffer, WaveFormat format)
    {
        var max = 0f;
        if (format.Encoding == WaveFormatEncoding.IeeeFloat && format.BitsPerSample == 32)
        {
            var floats = System.Runtime.InteropServices.MemoryMarshal.Cast<byte, float>(buffer);
            foreach (var sample in floats)
            {
                var abs = Math.Abs(sample);
                if (abs > max) max = abs;
            }
            return max;
        }
        if (format.BitsPerSample == 16)
        {
            for (var i = 0; i + 1 < buffer.Length; i += 2)
            {
                var sample = Math.Abs(BitConverter.ToInt16(buffer.Slice(i, 2))) / 32768f;
                if (sample > max) max = sample;
            }
        }
        return max;
    }
}
