##############################################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

# This script will create Azure Active Directory application, and Service Principal that can access Azure resources
# It will return clientID, tenantID, client secret that can be used for LISAv2 test on Azure
##############################################################################################

# https://gallery.technet.microsoft.com/Generate-a-random-and-5c879ed5
function New-SWRandomPassword {
    <#
    .Synopsis
        Generates one or more complex passwords designed to fulfill the requirements for Active Directory
    .DESCRIPTION
        Generates one or more complex passwords designed to fulfill the requirements for Active Directory
    .EXAMPLE
        New-SWRandomPassword
        C&3SX6Kn

        Will generate one password with a length between 8 and 12 chars.
    .EXAMPLE
        New-SWRandomPassword -MinPasswordLength 8 -MaxPasswordLength 12 -Count 4
        7d&5cnaB
        !Bh776T"Fw
        9"C"RxKcY
        %mtM7#9LQ9h

       Will generate four passwords, each with a length of between 8 and 12 chars.
    .EXAMPLE
        New-SWRandomPassword -InputStrings abc, ABC, 123 -PasswordLength 4
        3ABa

        Generates a password with a length of 4 containing at least one char from each InputString
    .EXAMPLE
        New-SWRandomPassword -InputStrings abc, ABC, 123 -PasswordLength 4 -FirstChar abcdefghijkmnpqrstuvwxyzABCEFGHJKLMNPQRSTUVWXYZ
        3ABa

        Generates a password with a length of 4 containing at least one char from each InputString that will start with a letter from
        the string specified with the parameter FirstChar
    .OUTPUTS
        [String]
    .NOTES
        Written by Simon Wahlin, blog.simonw.se
        I take no responsibility for any issues caused by this script.
    .FUNCTIONALITY
        Generates random passwords
    #>
    [CmdletBinding(DefaultParameterSetName='FixedLength',ConfirmImpact='None')]
    [OutputType([String])]
    Param
    (
        # Specifies minimum password length
        [Parameter(Mandatory=$false,
                   ParameterSetName='RandomLength')]
        [ValidateScript({$_ -gt 0})]
        [Alias('Min')]
        [int]$MinPasswordLength = 8,

        # Specifies maximum password length
        [Parameter(Mandatory=$false,
                   ParameterSetName='RandomLength')]
        [ValidateScript({
                if($_ -ge $MinPasswordLength){$true}
                else{Throw 'Max value cannot be lesser than min value.'}})]
        [Alias('Max')]
        [int]$MaxPasswordLength = 12,

        # Specifies a fixed password length
        [Parameter(Mandatory=$false, ParameterSetName='FixedLength')]
        [ValidateRange(1,2147483647)]
        [int]$PasswordLength = 8,

        # Specifies an array of strings containing character groups from which the password will be generated.
        # At least one char from each group (string) will be used.
        [String[]]$InputStrings = @('abcdefghijkmnpqrstuvwxyz', 'ABCEFGHJKLMNPQRSTUVWXYZ', '23456789', '!#%=_'),

        # Specifies a string containing a character group from which the first character in the password will be generated.
        # Useful for systems which requires first char in password to be alphabetic.
        [String] $FirstChar,

        # Specifies number of passwords to generate.
        [ValidateRange(1,2147483647)]
        [int]$Count = 1
    )
    Begin {
        Function Get-Seed{
            # Generate a seed for randomization
            $RandomBytes = New-Object -TypeName 'System.Byte[]' 4
            $Random = New-Object -TypeName 'System.Security.Cryptography.RNGCryptoServiceProvider'
            $Random.GetBytes($RandomBytes)
            [BitConverter]::ToUInt32($RandomBytes, 0)
        }
    }
    Process {
        For($iteration = 1;$iteration -le $Count; $iteration++){
            $Password = @{}
            # Create char arrays containing groups of possible chars
            [char[][]]$CharGroups = $InputStrings

            # Create char array containing all chars
            $AllChars = $CharGroups | ForEach-Object {[Char[]]$_}

            # Set password length
            if($PSCmdlet.ParameterSetName -eq 'RandomLength')
            {
                if($MinPasswordLength -eq $MaxPasswordLength) {
                    # If password length is set, use set length
                    $PasswordLength = $MinPasswordLength
                }
                else {
                    # Otherwise randomize password length
                    $PasswordLength = ((Get-Seed) % ($MaxPasswordLength + 1 - $MinPasswordLength)) + $MinPasswordLength
                }
            }

            # If FirstChar is defined, randomize first char in password from that string.
            if($PSBoundParameters.ContainsKey('FirstChar')){
                $Password.Add(0,$FirstChar[((Get-Seed) % $FirstChar.Length)])
            }
            # Randomize one char from each group
            Foreach($Group in $CharGroups) {
                if($Password.Count -lt $PasswordLength) {
                    $Index = Get-Seed
                    While ($Password.ContainsKey($Index)){
                        $Index = Get-Seed
                    }
                    $Password.Add($Index,$Group[((Get-Seed) % $Group.Count)])
                }
            }

            # Fill out with chars from $AllChars
            for($i=$Password.Count;$i -lt $PasswordLength;$i++) {
                $Index = Get-Seed
                While ($Password.ContainsKey($Index)){
                    $Index = Get-Seed
                }
                $Password.Add($Index,$AllChars[((Get-Seed) % $AllChars.Count)])
            }
            Write-Output -InputObject $(-join ($Password.GetEnumerator() | Sort-Object -Property Name | Select-Object -ExpandProperty Value))
        }
    }
}

function Write-Prompt($Message) {
    Write-Host $Message -ForegroundColor Yellow
}
function New-ServicePrincipal() {
    $ErrorActionPreference = "Stop"
    Login-AzAccount
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

    $idUris = "http://" + $Identifier
    $homePage = "http://" + $Identifier

    $tenantId = $subscription.TenantId
    $clientSecret = New-SWRandomPassword -PasswordLength 30
    $securestring = ConvertTo-SecureString $clientSecret -AsPlainText -Force

    Write-Host "Create Active Directory application..."
    $application = New-AzADApplication -DisplayName $identifier -HomePage $homePage -IdentifierUris $idUris -Password $securestring

    $ClientId = $application.ApplicationId

    $ErrorActionPreference = "Continue"

    while ($true) {
        Start-Sleep -Seconds 10
        $appCheck = Get-AzADApplication -ApplicationId $ClientId
        if ($appCheck) {
          break
        }
    }

    $ErrorActionPreference = "Stop"

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
            New-AzRoleAssignment -RoleDefinitionName "Owner" -ApplicationId $ClientId
        }
        else {
            New-AzRoleAssignment -RoleDefinitionName "Contributor" -ApplicationId $ClientId
        }
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
    Write-Host "CLIENT_SECRET:  " $clientSecret
}

New-ServicePrincipal

