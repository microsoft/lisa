##############################################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
#
# Setup_AITL.ps1
<#
.SYNOPSIS
    This script is to create/update a custom role and grant to Service Principal for Partner in Production Env
.PARAMETER
    -RoleName, RoleName you want to create/update (default is "Azure Image Testing for Linux Delegator")
    -ServicePrincipalName, Service Principal Name you want to assign (default is "AzureImageTestingforLinux")
    -SubscriptionId, Subscription scope associated with Role assignment (default is account's 1st available subscription)
Documentation

.EXAMPLE
    User sample:  Setup_AITL.ps1
    Debug sample: Setup_AITL.ps1 -RoleName "AzureLSGDelegator_test" -ServicePrincipalName "AzureLinuxTestingService" -SubscriptionId "/subscriptions/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
#>
###############################################################################################

param(
    # if RoleName not exist then create, otherwise update
    [string] $RoleName = "Azure Image Testing for Linux Delegator",
    [string] $ServicePrincipalName = "AzureImageTestingforLinux",
    [string] $SubscriptionId = ""
)

Import-Module Az.Resources
$ErrorActionPreference = "Stop"

function Compare-List {
    param (
        [ System.Collections.Generic.List[string] ] $list1,
        [ System.Collections.Generic.List[string] ] $list2
    )

    if ( $list1.Count -ne $list2.Count ) {
        return $false;
    }
    $sorted_list1 = $list1 | Sort-Object;
    $sorted_list2 = $list2 | Sort-Object;

    for (($i = 0); $i -lt $sorted_list1.Count; $i++) {
        if ( $sorted_list1[$i] -ne $sorted_list2[$i] ) {
            return $false
        }
    }

    return $true
}

function Compare-RoleSetting {
    param (
        [Microsoft.Azure.Commands.Resources.Models.Authorization.PSRoleDefinition] $role1,
        [Microsoft.Azure.Commands.Resources.Models.Authorization.PSRoleDefinition] $role2
    ) 
    
    if ( ($null -eq $role1) -or ($null -eq $role2) ) {
        return $false;
    }

    $isActionsMatch = Compare-List $role1.Actions $role2.Actions
    $isDataActionsMatch = Compare-List $role1.DataActions $role2.DataActions
    $isScopesMatch = Compare-List $role1.AssignableScopes $role2.AssignableScopes

    if ( ($role1.Description -eq $role2.Description) -and
        ($role1.IsCustom -eq $role2.IsCustom) -and
        ($role1.Name -eq $role2.Name) -and
        ($isActionsMatch -eq $true) -and
        ($isDataActionsMatch -eq $true) -and
        ($isScopesMatch -eq $true)) {
        return $true
    }
    else {
        return $false
    }
}

function Wait-RolePropagate {
    param (
        [string] $RoleName,
        [string] $SubscriptionId,
        [Microsoft.Azure.Commands.Resources.Models.Authorization.PSRoleDefinition] $RoleBeforeUpdate = $null # used $null for creation wait
    )
    Write-Host "In Wait-RolePropagate: waiting for the role changes to propagate"
    $StartTime = $(get-date)

    $changeCount = 0
    $count = 0
    $max = 20
    # check until it's the same for multiple times to make sure cache is refreshed as much as possible.
    while ($changeCount -lt 6) {
        if ($count -gt $max) {
            Write-Host "Fail to detect changed custom role after $count times"
            exit 1
        }
        
        Write-Host "Checking change applied..."
        $afterUpdate = Get-AzRoleDefinition -Name $RoleName -Scope $SubscriptionId
        $isRolesMatch = Compare-RoleSetting $RoleBeforeUpdate $afterUpdate
        if ($isRolesMatch -eq $false) {
            Write-Host "Found changed results."
            $count++
            $changeCount++
        }
        else {
            $changeCount = 0
        }
        Start-Sleep -Seconds 20
    }

    $elapsedTime = $(get-date) - $StartTime
    "Role Propagation took time: {0:HH:mm:ss}" -f ([datetime]$elapsedTime.Ticks) | Write-Host
}

function Retry-Command {
    [CmdletBinding()]
    Param(
        [Parameter(Position = 0, Mandatory = $true)]
        [scriptblock]$ScriptBlock,

        [Parameter(Position = 1, Mandatory = $false)]
        [int]$Maximum = 5,

        [Parameter(Position = 2, Mandatory = $false)]
        [int]$Delay = 1000
    )

    Begin {
        $cnt = 0
    }

    Process {
        do {
            $cnt++
            try {
                $ScriptBlock.Invoke()
                return
            }
            catch {
                Write-Error $_.Exception.InnerException.Message -ErrorAction Continue
                Start-Sleep -Milliseconds $Delay
            }
        } while ($cnt -lt $Maximum)

        # Throw an error after $Maximum unsuccessful invocations. Doesn't need
        # a condition, since the function returns upon successful invocation.
        throw 'Execution failed.'
    }
}

# Main Function
# Step 1. set the default parameter for SubscriptionId, actions, dataActions
if ($SubscriptionId -eq "") {
    $SubscriptionId = "/subscriptions/" + (Get-AzContext).Subscription.id
}

$actionPermsList = @("Microsoft.Resources/subscriptions/resourceGroups/read",
    "Microsoft.Resources/subscriptions/resourceGroups/write",
    "Microsoft.Resources/subscriptions/resourceGroups/delete",
    "Microsoft.Resources/deployments/read",
    "Microsoft.Resources/deployments/write",
    "Microsoft.Resources/deployments/validate/action",
    "Microsoft.Resources/deployments/operationStatuses/read",
    "Microsoft.Compute/virtualMachines/read",
    "Microsoft.Compute/virtualMachines/write",
    "Microsoft.Compute/virtualMachines/retrieveBootDiagnosticsData/action",
    "Microsoft.Compute/availabilitySets/write",
    "Microsoft.Compute/virtualMachines/start/action",
    "Microsoft.Compute/virtualMachines/restart/action",
    "Microsoft.Compute/virtualMachines/deallocate/action",
    "Microsoft.Compute/virtualMachines/powerOff/action",
    "Microsoft.Compute/disks/read",
    "Microsoft.Compute/disks/write",
    "Microsoft.Compute/disks/delete",
    "Microsoft.Compute/virtualMachines/extensions/read",
    "Microsoft.Compute/virtualMachines/extensions/write",
    "Microsoft.Network/virtualNetworks/read",
    "Microsoft.Network/virtualNetworks/write",
    "Microsoft.Network/virtualNetworks/subnets/join/action",
    "Microsoft.Network/publicIPAddresses/read",
    "Microsoft.Network/publicIPAddresses/write",
    "Microsoft.Network/publicIPAddresses/join/action",
    "Microsoft.Network/networkInterfaces/read",
    "Microsoft.Network/networkInterfaces/write",
    "Microsoft.Network/networkInterfaces/join/action",
    "Microsoft.Network/privateEndpoints/write",
    "Microsoft.Network/privateLinkServices/PrivateEndpointConnectionsApproval/action",
    "Microsoft.SerialConsole/serialPorts/write",
    "Microsoft.Network/networkSecurityGroups/write",
    "Microsoft.Network/networkSecurityGroups/read",
    "Microsoft.Network/networkSecurityGroups/join/action",
    "Microsoft.Storage/storageAccounts/read",
    "Microsoft.Storage/storageAccounts/write",
    "Microsoft.Storage/storageAccounts/listKeys/action")
$dataActionPermsList = @("Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete",
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read",
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write",
    "Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action")


$targetRole = [Microsoft.Azure.Commands.Resources.Models.Authorization.PSRoleDefinition]::new()
$targetRole.Description = 'Custmor delegation role is to run test cases and upload logs in Prod env.'
$targetRole.IsCustom = $true
$targetRole.Name = $RoleName
$targetRole.Actions = $actionPermsList
$targetRole.DataActions = $dataActionPermsList
$targetRole.AssignableScopes = $SubscriptionId

# step 2. Create or Update Role
$existRole = Get-AzRoleDefinition -Name $RoleName -Scope $SubscriptionId
if ($null -eq $existRole) {
    # create
    Write-Host "creating new role $RoleName with Parameters:"
    $targetRole | ConvertTo-Json | Write-Host 
    New-AzRoleDefinition -Role $targetRole
    Wait-RolePropagate $RoleName $SubscriptionId $null
}
else {
    # update
    $beforeUpdate = Get-AzRoleDefinition -Name $RoleName -Scope $SubscriptionId
    Write-Host "try to update role $RoleName :"

    $isRolesMatch = Compare-RoleSetting $beforeUpdate $targetRole
    if ( $isRolesMatch -eq $true) {
        Write-Host "input Role '$RoleName' has the same setting with the existing one, won't do any update"
    }
    else {
        # only update when different.
        Write-Host "Prepare to update role: $RoleName, current Role paramaters: "
        $beforeUpdate | ConvertTo-Json | Write-Host
    
        $targetRole.Id = $beforeUpdate.Id
        Write-Host "Updating existed role: $RoleName with parameters: "
        $targetRole | ConvertTo-Json | Write-Host
        Set-AzRoleDefinition -Role $targetRole
    
        Wait-RolePropagate $RoleName $SubscriptionId $beforeUpdate
    }
}

# Step 3. assign this role to Service Principal
$ServicePrincipalId = (Get-AzADServicePrincipal -DisplayName $ServicePrincipalName).id

$roleAssign = Get-AzRoleAssignment -ObjectId $ServicePrincipalId -RoleDefinitionName $RoleName -Scope $SubscriptionId
if ($null -eq $roleAssign) {
    Write-Host "Assign role $RoleName to ServicePrincipal $ServicePrincipalName with ID: $ServicePrincipalId"

    Retry-Command -ScriptBlock {
        New-AzRoleAssignment -ObjectId $ServicePrincipalId -RoleDefinitionName $RoleName -Scope $SubscriptionId -ErrorAction 'Stop'
    } -Maximum 20 -Delay 30000
}
else {
    Write-Host "Role '$RoleName' assignment to ServicePrincipal '$ServicePrincipalName' already exists."
}
