<#
.SYNOPSIS
    This script connects to a named pipe and logs the output to a file. This script is
    intended to be used with named pipes created using Set-VMCOMPort to get the serial
    console output of a VM.

.EXAMPLE
    .\serial_console_logger.ps1 -PipeName "\\.\pipe\mypipe" -OutFile "C:\temp\output.txt"

    This example connects to the named pipe "\\.\pipe\mypipe" and logs the output to
    "C:\temp\output.txt".

.NOTES
    Copyright (c) Microsoft Corporation.
    Licensed under the MIT license.
#>
param (
    [Parameter(Mandatory=$true)][string]$PipeName,
    [Parameter(Mandatory=$true)][string]$OutFile,
    [Parameter(Mandatory=$false)][int]$PipeConnectTimeoutMillis = 60000,
    [Parameter(Mandatory=$false)][int]$PipeReconnectTimeoutMillis = 15000
)

Write-Host "PID: $PID"
Write-Host "PipeName: $PipeName"
Write-Host "OutFile: $OutFile"

$oStream = New-Object System.IO.FileStream $OutFile, 'OpenOrCreate', 'Write', 'Read'
$pClient = New-Object System.IO.Pipes.NamedPipeClientStream(".", $PipeName)
$reconnect = $false

try {
    while (1) {
        $timeout = $PipeConnectTimeoutMillis
        if ($reconnect) {
            # If we are reconnecting, we'll use a shorter timeout.
            #
            # If we got disconnected because the VM was shut down, then there
            # is no point in waiting for a long time.
            #
            # If we got disconnected because the VM was rebooted, then the pipe
            # will be opened again soon and doesn't need to wait for a long time.
            $timeout = $PipeReconnectTimeoutMillis
        }

        $pClient.Connect($timeout)
        if (!$pClient.IsConnected) {
            Write-Host "Failed to connect to pipe. Exiting..."
            exit
        }

        Write-Host "Connected to pipe"
        $pClient.CopyTo($oStream)

        # If we get here, the pipe was closed. We'll try to reconnect.
        # The pipe can be closed because:
        # 1. The VM was shut down
        # 2. The VM was rebooted
        #
        # If the VM was rebooted the pipe will be opened again, so we'll
        # reconnect and continue logging.
        #
        # It is fine to take the same path for shutdown case as well. The
        # pipe reconnection will fail and the script will exit gracefully.
        Write-Host "Disconnected from pipe. Reconnecting..."
        $reconnect = $true
    }
} finally {
    Write-Host "Cleaning up: closing pipe and file stream"
    $oStream.Close()
    $pClient.Dispose()
}