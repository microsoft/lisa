# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

param([string]$PackageUrl)

$ErrorActionPreference = 'Stop'
for ($attempt = 0; $attempt -lt 18; $attempt++) {
    try {
        $token = Invoke-RestMethod -Uri 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fstorage.azure.com%2F' -Headers @{Metadata = 'true'} -TimeoutSec 15
        Invoke-WebRequest -Uri $PackageUrl -Method Head -UseBasicParsing -Headers @{
            Authorization = "Bearer $($token.access_token)"
            'x-ms-version' = '2023-01-03'
        } -TimeoutSec 15 | Out-Null
        return
    } catch {
        if ($attempt -eq 17 -or !$_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 403) {
            throw
        }
        Write-Warning 'Waiting for the managed identity storage role assignment to propagate'
        Start-Sleep -Seconds 15
    }
}
