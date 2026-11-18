Windows service failure recovery
===============================

The ``WindowsServiceRecovery.verify_windows_service_failure_recovery`` case
validates a background application's recovery after an unexpected process exit.
It creates a temporary service, configures Service Control Manager (SCM) to
restart it on failure, terminates only that service's verified process, and
requires a different process to produce multiple heartbeats without manually
starting the service again.

This Windows-only P1 case requires an administrator connection and Windows
PowerShell with .NET Framework's ``System.ServiceProcess`` assembly and C#
compiler available. It does not install software, require Internet access from
the guest, change firewall settings, or modify existing services. Use a disposable
test VM. The service and its files are deleted in ``finally``; cleanup failure
fails the case and marks the node dirty.

Example testcase selection in a Windows runbook:

.. code-block:: yaml

   import_builtin_tests: true
   testcase:
     - criteria:
         name: ^verify_windows_service_failure_recovery$

The test reuses the existing ``WindowsService`` Tool for starting, stopping,
querying the service PID, and configuring failure recovery.
``PowerShell.run_cmdlet`` performs Windows-specific operations with fresh
execution and explicit error handling; native ``sc.exe`` calls additionally
check ``$LASTEXITCODE``. There are no Linux commands or raw ``node.execute``
calls in the case. The small C# fixture implements a real Windows service,
rather than registering a console program that cannot communicate with SCM.

When adapting the example, use a unique test-owned service and verify its
executable and PID before injecting a fault. A ``Running`` status alone is not
proof of application recovery: verify that the replacement process resumes
useful work. This case demonstrates that principle with per-process heartbeats.
