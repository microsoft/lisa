// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

using System;
using System.Diagnostics;
using System.IO;
using System.ServiceProcess;
using System.Threading;

public sealed class RecoveryService : ServiceBase
{
    private readonly string heartbeatPath;
    private readonly int processId = Process.GetCurrentProcess().Id;
    private Timer timer;
    private int sequence;

    private RecoveryService(string name, string path)
    {
        ServiceName = name;
        heartbeatPath = path;
        CanStop = true;
        AutoLog = false;
    }

    protected override void OnStart(string[] args)
    {
        timer = new Timer(
            delegate
            {
                int current = Interlocked.Increment(ref sequence);
                File.AppendAllText(
                    heartbeatPath, processId + ":" + current + Environment.NewLine);
            },
            null, 0, 1000);
    }

    protected override void OnStop()
    {
        using (var completed = new ManualResetEvent(false))
        {
            timer.Dispose(completed);
            if (!completed.WaitOne(TimeSpan.FromSeconds(10)))
            {
                throw new System.TimeoutException("Heartbeat timer did not stop");
            }
        }
    }

    public static void Main(string[] args)
    {
        if (args.Length != 2)
        {
            throw new ArgumentException("Expected service name and heartbeat path");
        }
        ServiceBase.Run(new RecoveryService(args[0], args[1]));
    }
}
