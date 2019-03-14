# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
param(
    [String] $TestParams,
    [object] $AllVmData
)

$REMOTE_SCRIPT="prepare_ltpt_vm.sh"

function Main {
    param (
        $TestParams
    )

    $noClient = $true
    $noServer = $true

    foreach ($vmData in $AllVmData) {
        if ($vmData.RoleName -imatch "role-0") {
            $clientVMData = $vmData
            $resourceGroupName = $vmData.ResourceGroupName
            $noClient = $false
        }
        elseif ($vmData.RoleName -imatch "role-1") {
            $noServer = $false
            $resourceGroupName = $vmData.ResourceGroupName
            $serverVMData = $vmData
        }
    }
    if ($noClient -or $noServer) {
        Throw "Client or Server VM not defined. Be sure that the SetupType has 2 VMs defined"
    }

    Write-LogInfo "CLIENT VM details :"
    Write-LogInfo "  RoleName : $($clientVMData.RoleName)"
    Write-LogInfo "  Public IP : $($clientVMData.PublicIP)"
    Write-LogInfo "  SSH Port : $($clientVMData.SSHPort)"
    Write-LogInfo "SERVER VM details :"
    Write-LogInfo "  RoleName : $($serverVMData.RoleName)"
    Write-LogInfo "  Public IP : $($serverVMData.PublicIP)"
    Write-LogInfo "  SSH Port : $($serverVMData.SSHPort)"

    Provision-VMsForLisa -allVMData $AllVmData -installPackagesOnRoleNames "none"

    $null = Run-LinuxCmd -ip $serverVMData.PublicIP -port $serverVMData.SSHPort -username $user -password $password -runMaxAllowedTime 2000 `
        -command "bash $($REMOTE_SCRIPT) --log_dir '/root/LongPerfStressTest' --config 'server' --client_ip '$($clientVMData.InternalIP)'" -runAsSudo

    $null = Run-LinuxCmd -ip $clientVMData.PublicIP -port $clientVMData.SSHPort -username $user -password $password -runMaxAllowedTime 600 `
        -command "bash $($REMOTE_SCRIPT) --log_dir '/root/LongPerfStressTest' --config 'client' --server_ip '$($serverVMData.InternalIP)'" -runAsSudo

    Write-Output "SERVER_IP=$($serverVMData.PublicIP)" > ltpt_deployment_data.txt
    Write-Output "SERVER_PORT=$($serverVMData.SSHPort)" >> ltpt_deployment_data.txt
    Write-Output "CLIENT_IP=$($clientVMData.PublicIP)" >> ltpt_deployment_data.txt
    Write-Output "CLIENT_PORT=$($clientVMData.SSHPort)" >> ltpt_deployment_data.txt
    Write-Output "REMOTE_LOG_PATH=/root/LongPerfStressTest" >> ltpt_deployment_data.txt
    Write-Output "VM_USERNAME=$user" >> ltpt_deployment_data.txt
    Write-Output "VM_PASSWORD=$password" >> ltpt_deployment_data.txt

    Write-LogInfo "Adding resource group tag: LongPerfStressTest=yes"
    Add-ResourceGroupTag -ResourceGroup $resourceGroupName -TagName LongPerfStressTest -TagValue yes
    Add-ResourceGroupTag -ResourceGroup $resourceGroupName -TagName "Month" -TagValue "$((Get-Culture).DateTimeFormat.GetMonthName((Get-Date).Month))"

    Write-LogInfo "Adding Timer Lock on the resource group $resourceGroupName"
    New-AzureRmResourceLock -LockName "Timer Lock" -LockLevel CanNotDelete -ResourceGroupName $resourceGroupName -Force
    return "PASS"
}

Main -TestParams (ConvertFrom-StringData $TestParams.Replace(";","`n"))