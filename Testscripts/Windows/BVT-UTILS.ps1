 # Copyright (c) Microsoft Corporation. All rights reserved.
 # Licensed under the Apache License.

# Check if VM supports one feature or not based on comparison of curent kernel
# version with feature supported kernel version. If the current version is 
# lower than feature supported version, return false, otherwise return true.
function Get-VMFeatureSupportStatus {
    param (
        [String] $VmIp, 
        [String] $VmPort,
        [String] $User,
        [String] $Password,
        [String] $SupportKernel
    )

    $currentKernel = .\Tools\plink.exe -C -pw $Password -P $VmPort $User@$VmIp "uname -r"
    if ($? -eq $False) {
        Write-Output "Warning: Could not get kernel version".
    }
    $sKernel = $supportKernel.split(".-")
    $cKernel = $currentKernel.split(".-")

    for ($i=0; $i -le 3; $i++) {
        if ($cKernel[$i] -lt $sKernel[$i] ) {
            $cmpResult = $false
            break;
        }
        if ($cKernel[$i] -gt $sKernel[$i] ) {
            $cmpResult = $true
            break
        }
        if ($i -eq 3) {
            $cmpResult = $True 
        }
    }
    return $cmpResult
}