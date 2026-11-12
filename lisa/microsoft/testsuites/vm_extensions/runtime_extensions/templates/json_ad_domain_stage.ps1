# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

$ErrorActionPreference = 'Stop'
$root = 'C:\lisa\ad'
New-Item -Path $root -ItemType Directory -Force | Out-Null
& icacls.exe $root /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F'
if ($LASTEXITCODE -ne 0) {
    throw 'Could not secure the DSC working directory'
}
Expand-Archive -Path (Join-Path $PSScriptRoot 'CreateADPDC.zip') -DestinationPath "$root\package" -Force
foreach ($module in @('xActiveDirectory', 'xStorage', 'xNetworking', 'xPendingReboot')) {
    Copy-Item -Path "$root\package\$module" -Destination "$env:ProgramFiles\WindowsPowerShell\Modules" -Recurse -Force
}
Copy-Item -Path (Join-Path $PSScriptRoot 'json_ad_domain_configure.ps1') -Destination $root -Force
