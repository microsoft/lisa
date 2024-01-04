param (
    [Parameter(Mandatory=$true)][string]$PipeName,
    [Parameter(Mandatory=$true)][string]$OutFile,
    [Parameter(Mandatory=$false)][int]$PipeReconnectMillis = 12000
)

Write-Host $PID
$oStream = New-Object System.IO.FileStream $OutFile, 'OpenOrCreate', 'Write', 'Read'
$pClient = New-Object System.IO.Pipes.NamedPipeClientStream(".", $PipeName)
$reconnect = $false
try {
    while (1) {
        $timeout = 60000
        if ($reconnect) {
            $timeout = $PipeReconnectMillis
        }
        $pClient.Connect($timeout)
        if (!$pClient.IsConnected) {
            exit
        }
        Write-Host "Connected to pipe"
        $pClient.CopyTo($oStream)
        $reconnect = $true
    }
} finally {
    Write-Host "Exiting"
    $oStream.Close()
    $pClient.Dispose()
}