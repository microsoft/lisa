##############################################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script will create Azure Active Directory application, and Service Principal that can access Azure resources
# It will return clientID, tenantID, client secret that can be used for LISAv2 test on Azure
##############################################################################################
function Write-Prompt($Message) {
    Write-Host $Message -ForegroundColor Yellow
}
function New-ServicePrincipal() {
    $ErrorActionPreference = "Stop"
    Connect-AzAccount
    $subscription = Get-AzSubscription

    $subCount = 1
    if ($subscription.Count) {
        $subCount = $subscription.Count
    }
    if ($subCount -gt 1) {
        Write-Host "There are $subCount subscriptions in your account:`n"
        foreach ($sub in $subscription) {
            Write-Host "Id   : $($sub.Id)"
            Write-Host "Name : $($sub.Name)`n"
        }
        Write-Prompt "Copy and paste the ID of the subscription that you want to create Service Principal with:"
        $InputId = Read-Host
        $subscription = Get-AzSubscription -SubscriptionId $InputId
        Select-AzSubscription -Subscription $InputId
    }
    Write-Host "Use subscription $($subscription.Name)..."

    # get identifier for Service Principal
    $defaultIdentifier = "LISAv2" + [guid]::NewGuid()
    $identifier = "1"
    while (("$identifier".length -gt 0 -and "$identifier".length -lt 8) -or ("$identifier".contains(" "))) {
        Write-Prompt "Please input identifier for your Service Principal with`n(1) MINIMUM length of 8`n(2) NO space`n[press Enter to use default identifier $DefaultIdentifier]:"
        $identifier = Read-Host
    }
    if (!$identifier) {
        $identifier = $defaultIdentifier
    }
    Write-Host "Use $identifier as identifier..."
    $tenantId = $subscription.TenantId
    Write-Host "Create Active Directory application..."
    $application = New-AzADApplication -DisplayName $identifier
    $objectId = $application.Id
    $ClientId = $application.AppId
    if ( -not $objectId ) {
        $objectId = $application.ObjectId
    }
    if ( -not $ClientId ) {
        $ClientId = $application.ApplicationId
    }
    $ErrorActionPreference = "Continue"

    while ($true) {
        Start-Sleep -Seconds 10
        $appCheck = Get-AzADApplication -ApplicationId $ClientId
        if ($appCheck) {
          break
        }
    }

    $ErrorActionPreference = "Stop"
    $context = Get-AzContext
    Connect-AzureAD -TenantId $context.Tenant.TenantId -AccountId $context.Account.Id
    $secretStartDate = Get-Date
    $secretEndDate = $secretStartDate.AddYears(10)
    $clientSecret = New-AzureADApplicationPasswordCredential -ObjectId $objectId -CustomKeyIdentifier "GraphClientSecret" -StartDate $secretStartDate -EndDate $secretEndDate

    Write-Host "Create Service Principal..."
    New-AzADServicePrincipal -ApplicationId $ClientId

    $ErrorActionPreference = "Continue"

    while ($true) {
        Start-Sleep -Seconds 10
        $spCheck = Get-AzADServicePrincipal -ApplicationId $ClientId
        if ($spCheck) {
          break
        }
    }

    $ErrorActionPreference = "Stop"

    # let user choose what kind of role they need
    Write-Prompt "What kind of privileges do you want to assign to the Service Principal?"
    Write-Prompt "1) Contributor (Default)"
    Write-Prompt "2) Owner"
    Write-Prompt "Please choose by entering 1 or 2:"
    $Privilege = Read-Host
    Write-Host "Assign roles to Service Principal..."
    try {
        if ($Privilege -eq 2) {
            $role = "Owner"
        } else {
            $role = "Contributor"
        }
        $subscriptionId = $context.Subscription.Id
        $spRoleAssignment = @{
                      ObjectId = $spCheck.id;
                      RoleDefinitionName = $role;
                      Scope = "/subscriptions/$subscriptionId"
        }
        New-AzRoleAssignment @spRoleAssignment
        Write-Host "Successfully created Service Principal and assigned role...`n"
    } catch {
        $line = $_.InvocationInfo.ScriptLineNumber
        $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
        Write-Host -ForegroundColor Red "Exception in New-ServicePrincipal."
        Write-Host -ForegroundColor Red "Source : Line $line in script $script_name."

        $currentSignInAccount = Get-AzContext | Select-Object Account
        $role = Get-AzRoleAssignment -SignInName $currentSignInAccount.Account.id | Select-Object RoleDefinitionName
        # https://docs.microsoft.com/en-us/powershell/azure/create-azure-service-principal-azureps?view=azps-2.5.0#manage-service-principal-roles
        if ($_ -match "does not have authorization to perform action 'Microsoft.Authorization/roleAssignments/write' over scope") {
            Write-Host "You are the $($role.RoleDefinitionName) of subscription $($subscription.Name) - $($subscription.Id), don't have enough permission to assign a role."
            $confirmation = Read-Host "Do you want to delete the service principal $identifier just created? [y/n]"
            if($confirmation -eq "y") {
                Remove-AzADApplication -ApplicationId $ClientId -Force
                Write-Host "Delete $identifier successfully..."
                return
            } else {
                Write-Prompt "Successfully created Service Principal but assigned role failed..."
                Write-Prompt "You can use command 'Remove-AzADApplication -ApplicationId $ClientId -Force' to remove it manually..."
            }
        }
    }

    Write-Host "==============Created Serivce Principal=============="
    Write-Host "SUBSCRIPTION_ID:" $subscription.Id
    Write-Host "CLIENT_ID:      " $clientId
    Write-Host "TENANT_ID:      " $tenantId
    Write-Host "CLIENT_SECRET:  " $clientSecret.Value
}

New-ServicePrincipal
