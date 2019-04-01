##############################################################################################
# Azure.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
    PS modules for LISAv2 test automation.
    Required for Azure test execution.

.PARAMETER
    <Parameters>

.INPUTS


.NOTES
    Creation Date:
    Purpose/Change:

.EXAMPLE


#>
###############################################################################################

Function Validate-SubscriptionUsage($RGXMLData, $Location, $OverrideVMSize, $StorageAccount) {
    #region VM Cores...
    Try {
        Function Set-Usage($currentStatus, $text, $usage, $AllowedUsagePercentage) {
            $counter = 0
            foreach ($item in $currentStatus) {
                if ($item.Name.Value -eq $text) {
                    $allowedCount = [int](($currentStatus[$counter].Limit) * ($AllowedUsagePercentage / 100))
                    Write-LogInfo "  Current $text usage : $($currentStatus[$counter].CurrentValue) cores. Requested:$usage. Estimated usage=$($($currentStatus[$counter].CurrentValue) + $usage). Max Allowed cores:$allowedCount/$(($currentStatus[$counter].Limit))"
                    $currentStatus[$counter].CurrentValue = $currentStatus[$counter].CurrentValue + $usage
                }
                if ($item.Name.Value -eq "cores") {
                    $allowedCount = [int](($currentStatus[$counter].Limit) * ($AllowedUsagePercentage / 100))
                    Write-LogInfo "  Current Regional Cores usage : $($currentStatus[$counter].CurrentValue) cores. Requested:$usage. Estimated usage=$($($currentStatus[$counter].CurrentValue) + $usage). Max Allowed cores:$allowedCount/$(($currentStatus[$counter].Limit))"
                    $currentStatus[$counter].CurrentValue = $currentStatus[$counter].CurrentValue + $usage
                }
                $counter++
            }

            return $currentStatus
        }

        Function Test-Usage($currentStatus, $text, $AllowedUsagePercentage) {
            $overFlowErrors = 0
            $counter = 0
            foreach ($item in $currentStatus) {
                if ($item.Name.Value -eq $text) {
                    $allowedCount = [int](($currentStatus[$counter].Limit) * ($AllowedUsagePercentage / 100))
                    #Write-LogInfo "Max allowed $($item.Name.LocalizedValue) usage : $allowedCount out of $(($currentStatus[$counter].Limit))."
                    if ($currentStatus[$counter].CurrentValue -gt $allowedCount) {
                        Write-LogErr "  Current $text Estimated use: $($currentStatus[$counter].CurrentValue)"
                        $overFlowErrors += 1
                    }
                }
                if ($item.Name.Value -eq "cores") {
                    $allowedCount = [int](($currentStatus[$counter].Limit) * ($AllowedUsagePercentage / 100))
                    #Write-LogInfo "Max allowed $($item.Name.LocalizedValue) usage : $allowedCount out of $(($currentStatus[$counter].Limit))."
                    if ($currentStatus[$counter].CurrentValue -gt $allowedCount) {
                        Write-LogErr "  Current Regional Cores Estimated use: $($currentStatus[$counter].CurrentValue)"
                        $overFlowErrors += 1
                    }
                }
                $counter++
            }
            return $overFlowErrors
        }

        Function Check-OverflowErrors {
            Param (
                [string] $ResourceType,
                [int] $CurrentValue,
                [int] $RequiredValue,
                [int] $MaximumLimit,
                [int] $AllowedUsagePercentage
            )
            $ActualLimit = [int]($MaximumLimit * ($AllowedUsagePercentage / 100))
            $Message = "Current '$ResourceType' usage:$CurrentValue. "
            $Message += "Requested:$RequiredValue. Estimated usage:$($CurrentValue + $RequiredValue). "
            $Message += "Maximum allowed:$MaximumLimit/$ActualLimit."
            if (($CurrentValue + $RequiredValue) -le $ActualLimit) {
                Write-LogInfo $Message
                return 0
            } else {
                Write-LogErr $Message
                return 1
            }
        }

        #Define LISAv2's subscription usage limit. This is applicable for all the defined resources.
        #  e.g. If your subscription has below maximum limits:
        #    Resource Groups: 200
        #    Storage Accounts: 200
        #    Network Security Groups: 50
        #    Then, Setting $AllowedUsagePercentage = 50 will enforce following limits.
        #    LISAv2 Resource Groups usage limit: 100
        #    LISAv2 Storage Accounts usage limit: 100
        #    LISAv2 Network Security Groups usage limit: 25
        $AllowedUsagePercentage = 100

        #Get the region
        $currentStatus = Get-AzureRmVMUsage -Location $Location
        $overFlowErrors = 0
        $premiumVMs = 0
        $vmCounter = 0
        foreach ($VM in $RGXMLData.VirtualMachine) {
            $vmCounter += 1
            Write-LogInfo "Estimating VM #$vmCounter usage."
            if ($OverrideVMSize) {
                $testVMSize = $OverrideVMSize
            } else {
                $testVMSize = $VM.ARMInstanceSize
            }

            if ($OverrideVMSize -and ($testVMUsage -gt 0)) {
                #Do nothing.
            } else {
                $testVMUsage = (Get-AzureRmVMSize -Location $Location | Where-Object { $_.Name -eq $testVMSize}).NumberOfCores
            }

            $testVMSize = $testVMSize.Replace("Standard_", "")
            $regExpVmSize = @{
                "standardDSv2Family" = @{ "Regexp" = "^DS.*v2$"; "isPremium"= 1};
                "standardDSv3Family" = @{ "Regexp" = "^D.*s_v3$"; "isPremium"= 1};
                "standardDSFamily" = @{ "Regexp" = "^DS((?!v2|s_v3).)*$"; "isPremium"= 1};
                "standardDv2Family" = @{ "Regexp" = "^D[^S].*v2$"; "isPremium"= 0};
                "standardDv3Family" = @{ "Regexp" = "^D[^S]((?!s_v3).)*v3$"; "isPremium"= 0};
                "standardDFamily" = @{ "Regexp" = "^D[^S]((?!v2|v3).)*$"; "isPremium"= 0};
                "standardESv3Family" = @{ "Regexp" = "^E.*s_v3$"; "isPremium"= 1};
                "standardEv3Family" = @{ "Regexp" = "^E.*v3$"; "isPremium"= 0};
                "standardA8_A11Family" = @{ "Regexp" = "A8|A9|A10|A11"; "isPremium"= 0};
                "standardAv2Family"= @{ "Regexp" = "^A.*v2$"; "isPremium"= 0};
                "standardA0_A7Family" = @{ "Regexp" = "A[0-7]$"; "isPremium"= 0};
                "standardFSFamily" = @{ "Regexp" = "^FS"; "isPremium"= 1};
                "standardFFamily" = @{ "Regexp" = '^F[^S]' ; "isPremium"= 0};
                "standardGSFamily" = @{ "Regexp" = "^GS"; "isPremium"= 1};
                "standardGFamily" = @{ "Regexp" = "^G[^S]"; "isPremium"= 0};
                "standardNVFamily"= @{ "Regexp" = "^NV"; "isPremium"= 0};
                "standardNCv2Family" = @{ "Regexp" = "^NC.*v2$"; "isPremium"= 0};
                "standardNCFamily" = @{ "Regexp" = "^NC((?!v2).)*$"; "isPremium"= 0};
                "standardNDFamily" = @{ "Regexp" = "^ND"; "isPremium"= 0};
                "standardHBSFamily"= @{ "Regexp" = "^HB"; "isPremium"= 0};
                "standardHCSFamily" = @{ "Regexp" = "^HC"; "isPremium"= 0};
                "standardHFamily" = @{ "Regexp" = "^H[^BC]"; "isPremium"= 0};
                "basicAFamily" = @{ "Regexp" = "^Basic"; "isPremium"= 0};
                "standardMSFamily" = @{ "Regexp" = "^M"; "isPremium"= 0}
            }
            $identifierTest = ""
            foreach ($vmFamily in $regExpVmSize.Keys) {
                if ($testVMSize -match $regExpVMsize[$vmFamily].RegExp) {
                    $identifierTest = $vmFamily
                    $premiumVMs += $regExpVMsize[$vmFamily].isPremium
                    break
                }
            }
            if ($identifierTest) {
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierTest  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierTest -AllowedUsagePercentage $AllowedUsagePercentage
            } else {
                Write-LogInfo "Requested VM size: $testVMSize is not yet registered to monitor. Usage simulation skipped."
            }
        }
    } catch {
        $line = $_.InvocationInfo.ScriptLineNumber
        $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
        $ErrorMessage = $_.Exception.Message
        Write-LogErr "EXCEPTION : $ErrorMessage"
        Write-LogErr "Source : Line $line in script $script_name."
    }
    #endregion

    #region Resource Groups
    #Source for current limit : https://docs.microsoft.com/en-us/azure/azure-subscription-service-limits#subscription-limits---azure-resource-manager
    $RGLimit = 980
    $currentRGCount = (Get-AzureRmResourceGroup).Count
    $overFlowErrors += Check-OverflowErrors -ResourceType "Resource Group" -CurrentValue $currentRGCount `
        -RequiredValue 1 -MaximumLimit $RGLimit -AllowedUsagePercentage $AllowedUsagePercentage
    #endregion

    #region Storage Accounts
    $currentStorageStatus = Get-AzureRmStorageUsage -Location $Location
    if ( ($premiumVMs -gt 0 ) -and ($StorageAccount -imatch "NewStorage_")) {
        $requiredStorageAccounts = 1
    }
    elseif ( ($premiumVMs -gt 0 ) -and !($StorageAccount -imatch "NewStorage_")) {
        $requiredStorageAccounts = 1
    }
    elseif ( !($premiumVMs -gt 0 ) -and !($StorageAccount -imatch "NewStorage_")) {
        $requiredStorageAccounts = 0
    }
    $overFlowErrors += Check-OverflowErrors -ResourceType "Storage Account" -CurrentValue $currentStorageStatus.CurrentValue `
        -RequiredValue $requiredStorageAccounts -MaximumLimit $currentStorageStatus.Limit -AllowedUsagePercentage $AllowedUsagePercentage
    #endregion

    $GetAzureRmNetworkUsage = Get-AzureRmNetworkUsage -Location $Location

    #region Public IP Addresses
    $PublicIPs = $GetAzureRmNetworkUsage | Where-Object { $_.Name.Value -eq "PublicIPAddresses" }
    $overFlowErrors += Check-OverflowErrors -ResourceType "Public IP" -CurrentValue $PublicIPs.CurrentValue `
        -RequiredValue 1 -MaximumLimit $PublicIPs.Limit -AllowedUsagePercentage $AllowedUsagePercentage
    #endregion

    #region Virtual networks
    $VNETs = $GetAzureRmNetworkUsage | Where-Object { $_.Name.Value -eq "VirtualNetworks" }
    $overFlowErrors += Check-OverflowErrors -ResourceType "Virtual Network" -CurrentValue $VNETs.CurrentValue `
        -RequiredValue 1 -MaximumLimit $VNETs.Limit -AllowedUsagePercentage $AllowedUsagePercentage
    #endregion

    #region Network Security Groups
    $SGs = $GetAzureRmNetworkUsage | Where-Object { $_.Name.Value -eq "NetworkSecurityGroups" }
    $overFlowErrors += Check-OverflowErrors -ResourceType "Network Security Group" -CurrentValue $SGs.CurrentValue `
        -RequiredValue 1 -MaximumLimit $SGs.Limit -AllowedUsagePercentage $AllowedUsagePercentage
    #endregion

    #region Load Balancers
    $LBs = $GetAzureRmNetworkUsage | Where-Object { $_.Name.Value -eq "LoadBalancers" }
    $overFlowErrors += Check-OverflowErrors -ResourceType "Load Balancer" -CurrentValue $LBs.CurrentValue `
        -RequiredValue 1 -MaximumLimit $LBs.Limit -AllowedUsagePercentage $AllowedUsagePercentage
    #endregion

    if ($overFlowErrors -eq 0) {
        Write-LogInfo "Estimated subscription usage is under allowed limits."
        return $true
    } else {
        Write-LogErr "Estimated subscription usage exceeded allowed limits."
        return $false
    }
}

Function Create-AllResourceGroupDeployments($SetupTypeData, $TestCaseData, $Distro, [string]$TestLocation, $GlobalConfig, $TiPSessionId, $TipCluster, $UseExistingRG, $ResourceCleanup) {
    $resourceGroupCount = 0

    Write-LogInfo "Current test setup: $($SetupTypeData.Name)"

    $OsVHD = $global:BaseOSVHD
    $osImage = $global:ARMImageName

    $location = $TestLocation
    if ( $location -imatch "-" ) {
        $RGCount = $SetupTypeData.ResourceGroup.Count
        $xRegionTest = $true
        $xRegionLocations = $location.Split("-")
        $locationCounter = 0
        Write-LogInfo "$RGCount Resource groups will be deployed in $($xRegionLocations.Replace('-',' and '))"
    }
    foreach ($RG in $setupTypeData.ResourceGroup ) {
        $validateStartTime = Get-Date
        Write-LogInfo "Checking the subscription usage..."
        $readyToDeploy = $false
        $coreCountExceededTimeout = 3600
        while (!$readyToDeploy) {
            $readyToDeploy = Validate-SubscriptionUsage -RGXMLData $RG -Location $location -OverrideVMSize $TestCaseData.OverrideVMSize `
                                -StorageAccount $GlobalConfig.Global.Azure.Subscription.ARMStorageAccount
            $validateCurrentTime = Get-Date
            $elapsedWaitTime = ($validateCurrentTime - $validateStartTime).TotalSeconds
            if ( (!$readyToDeploy) -and ($elapsedWaitTime -lt $coreCountExceededTimeout)) {
                $waitPeriod = Get-Random -Minimum 1 -Maximum 10 -SetSeed (Get-Random)
                Write-LogInfo "Timeout in approx. $($coreCountExceededTimeout - $elapsedWaitTime) seconds..."
                Write-LogInfo "Waiting $waitPeriod minutes..."
                Start-Sleep -Seconds ($waitPeriod * 60)
            }
            if ( $elapsedWaitTime -gt $coreCountExceededTimeout ) {
                break
            }
        }
        if ($readyToDeploy) {
            $uniqueId = New-TimeBasedUniqueId
            $isServiceDeployed = "False"
            $retryDeployment = 0
            if ( $null -ne $RG.Tag ) {
                $groupName = "LISAv2-" + $RG.Tag + "-" + $Distro + "-" + "$TestID-" + "$uniqueId"
            } else {
                $groupName = "LISAv2-" + $SetupTypeData.Name + "-" + $Distro + "-" + "$TestID-" + "$uniqueId"
            }
            if ($SetupTypeData.ResourceGroup.Count -gt 1) {
                $groupName = $groupName + "-" + $resourceGroupCount
            }
            while (($isServiceDeployed -eq "False") -and ($retryDeployment -lt 1)) {
                if ($UseExistingRG) {
                    $isServiceCreated = "True"
                    $isRGDeleted = $true
                    $groupName = $Distro
                } else {
                    Write-LogInfo "Creating Resource Group : $groupName."
                    Write-LogInfo "Verifying that Resource group name is not in use."
                    $isRGDeleted = Delete-ResourceGroup -RGName $groupName
                }
                if ($isRGDeleted) {
                    if ( $xRegionTest ) {
                        $location = $xRegionLocations[$locationCounter]
                        $locationCounter += 1
                    }
                    elseif (!$UseExistingRG) {
                        $isServiceCreated = Create-ResourceGroup -RGName $groupName -location $location -CurrentTestData $TestCaseData
                    }
                    Write-LogInfo "test platform is : $testPlatform"
                    if ($isServiceCreated -eq "True") {
                        $azureDeployJSONFilePath = Join-Path $env:TEMP "$groupName.json"
                        $null = Generate-AzureDeployJSONFile -RGName $groupName -ImageName $osImage -osVHD $osVHD -RGXMLData $RG -Location $location `
                                -azuredeployJSONFilePath $azureDeployJSONFilePath -CurrentTestData $TestCaseData -TiPSessionId $TiPSessionId -TipCluster $TipCluster `
                                -StorageAccountName $GlobalConfig.Global.Azure.Subscription.ARMStorageAccount

                        $DeploymentStartTime = (Get-Date)
                        $CreateRGDeployments = Create-ResourceGroupDeployment -RGName $groupName -location $location -TemplateFile $azureDeployJSONFilePath `
                                -UseExistingRG $UseExistingRG

                        $DeploymentEndTime = (Get-Date)
                        $DeploymentElapsedTime = $DeploymentEndTime - $DeploymentStartTime
                        if ( $CreateRGDeployments ) {
                            $retValue = "True"
                            $isServiceDeployed = "True"
                            $resourceGroupCount = $resourceGroupCount + 1
                            if ($resourceGroupCount -eq 1) {
                                $deployedGroups = $groupName
                            }
                            else {
                                $deployedGroups = $deployedGroups + "^" + $groupName
                            }
                        }
                        else {
                            Write-LogErr "Unable to Deploy one or more VM's"
                            $retryDeployment = $retryDeployment + 1
                            $retValue = "False"
                            $isServiceDeployed = "False"
                        }
                    }
                    else {
                        Write-LogErr "Unable to create $groupName"
                        $retryDeployment = $retryDeployment + 1
                        $retValue = "False"
                        $isServiceDeployed = "False"
                    }
                } else {
                    Write-LogErr "Unable to delete existing resource group - $groupName"
                    $retryDeployment = 3
                    $retValue = "False"
                    $isServiceDeployed = "False"
                }
            }
        } else {
            Write-LogErr "Core quota is not sufficient. Stopping VM deployment."
            $retValue = "False"
            $isServiceDeployed = "False"
        }
    }
    return $retValue, $deployedGroups, $resourceGroupCount, $DeploymentElapsedTime
}
Function Delete-ResourceGroup([string]$RGName, [switch]$KeepDisks, [bool]$UseExistingRG) {
    Write-LogInfo "Try to delete resource group $RGName..."
    try {
        Write-LogInfo "Checking if $RGName exists..."
        $ResourceGroup = Get-AzureRmResourceGroup -Name $RGName -ErrorAction Ignore
    }
    catch {
        Write-LogInfo "Failed to get resource group: $RGName; maybe this resource group does not exist."
    }
    if ($ResourceGroup) {
        if ($UseExistingRG) {
            # Get RG lock. If there is any lock in place, don't try to delete the Resource Group
            # "Microsoft.Authorization/locks" is the standard ResourceType for RG locks
            $rgLock = (Get-AzureRmResourceLock -ResourceGroupName $RGName).ResourceType -eq "Microsoft.Authorization/locks"
            if (-not $rgLock) {
                $CurrentResources = Get-AzureRmResource -ResourceGroupName $RGName | `
                    Where-Object { (( $_.ResourceGroupName -eq $RGName ) -and ( !($_.ResourceType -imatch "availabilitySets" )))}
                $attempts = 0
                while (($CurrentResources) -and ($attempts -le 10)) {
                    $CurrentResources = Get-AzureRmResource -ResourceGroupName $RGName | `
                        Where-Object { (( $_.ResourceGroupName -eq $RGName ) -and ( !($_.ResourceType -imatch "availabilitySets" )))}
                    $unlockedResources = @()
                    # Get the lock for each resource and compute a list of "unlocked" resources
                    foreach ($resource in $CurrentResources) {
                        $resourceLock = Get-AzureRmResourceLock -ResourceGroupName $RGName `
                            -ResourceType $resource.ResourceType -ResourceName $resource.Name
                        if (-not $resourceLock) {
                            $unlockedResources += $resource
                        }
                    }
                    # Only try to delete the "unlocked" resources
                    foreach ($resource in $unlockedResources) {
                        Write-LogInfo "Removing resource $($resource.Name), type $($resource.ResourceType)"
                        try {
                            $current_resource = Get-AzureRmResource -ResourceId $resource.ResourceId -ErrorAction Ignore
                            if ($current_resource) {
                                $null = Remove-AzureRmResource -ResourceId $resource.ResourceId -Force -Verbose
                            }
                        }
                        catch {
                            Write-LogErr "Failed to delete resource $($resource.Name). We will try to remove it in next attempt."
                        }
                    }
                    $CurrentResources = $unlockedResources
                    $attempts++
                }
                Write-LogInfo "Resources in $RGName are deleted."
                $retValue = $true
            } else {
                Write-LogWarn "Lock is in place for $RGName. Skipping RG delete!"
            }
        }
        else {
            if ( $XmlSecrets.secrets.AutomationRunbooks.CleanupResourceGroupRunBook ) {
                $parameters = $parameters = @{"NAMEFILTER" = "$RGName"; "PREVIEWMODE" = $false};
                $CleanupRG = Get-AzureRmResourceGroup  -Name $XmlSecrets.secrets.AutomationRunbooks.ResourceGroupName -ErrorAction SilentlyContinue
            }
            if ($CleanupRG) {
                $rubookJob = Start-AzureRmAutomationRunbook -Name $XmlSecrets.secrets.AutomationRunbooks.CleanupResourceGroupRunBook `
                                -Parameters $parameters -AutomationAccountName $XmlSecrets.secrets.AutomationRunbooks.AutomationAccountName `
                                -ResourceGroupName $XmlSecrets.secrets.AutomationRunbooks.ResourceGroupName
                Write-LogInfo "Cleanup job ID: '$($rubookJob.JobId)' for '$RGName' started using runbooks."
                $retValue = $true
            }
            else {
                $cleanupRGScriptBlock = {
                    $RGName = $args[0]
                    Remove-AzureRmResourceGroup -Name $RGName -Verbose -Force
                }
                Write-LogInfo "Triggering : Delete-ResourceGroup-$RGName..."
                $null = Start-Job -ScriptBlock $cleanupRGScriptBlock -ArgumentList @($RGName) -Name "Delete-ResourceGroup-$RGName"
                $retValue = $true
            }
        }
    }
    else {
        Write-LogInfo "$RGName does not exists."
        $retValue = $true
    }
    return $retValue
}

Function Create-ResourceGroup([string]$RGName, $location, $CurrentTestData) {
    $FailCounter = 0
    $retValue = "False"

    While (($retValue -eq $false) -and ($FailCounter -lt 5)) {
        try {
            $FailCounter++
            if ($location) {
                Write-LogInfo "Using location : $location"
                $createRG = New-AzureRmResourceGroup -Name $RGName -Location $location.Replace('"', '') -Force -Verbose
            }
            $operationStatus = $createRG.ProvisioningState
            if ($operationStatus -eq "Succeeded") {
                Write-LogInfo "Resource Group $RGName created."
                Add-DefaultTagsToResourceGroup -ResourceGroup $RGName -CurrentTestData $CurrentTestData
                $retValue = $true
            }
            else {
                Write-LogErr "Failed to create Resource Group: $RGName."
                Write-LogInfo "[$FailCounter / 5] Retrying after 10 seconds..."
                Start-Sleep -Seconds 10
                $retValue = $false
            }
        }
        catch {
            $retValue = $false

            $line = $_.InvocationInfo.ScriptLineNumber
            $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
            Write-LogErr "Exception in Create-ResourceGroup"
            Write-LogErr "Source : Line $line in script $script_name."
        }
    }
    return $retValue
}

Function Create-ResourceGroupDeployment([string]$RGName, $location, $TemplateFile, $UseExistingRG, $ResourceCleanup) {
    $FailCounter = 0
    $retValue = "False"
    $ResourceGroupDeploymentName = "eosg" + (Get-Date).Ticks
    While (($retValue -eq $false) -and ($FailCounter -lt 1)) {
        try {
            $FailCounter++
            if ($location) {
                Write-LogInfo "Creating Deployment using $TemplateFile ..."
                $createRGDeployment = New-AzureRmResourceGroupDeployment -Name $ResourceGroupDeploymentName `
                                        -ResourceGroupName $RGName -TemplateFile $TemplateFile -Verbose
            }
            $operationStatus = $createRGDeployment.ProvisioningState
            if ($operationStatus -eq "Succeeded") {
                Write-LogInfo "Resource Group Deployment created."
                $retValue = $true
            }
            else {
                $retValue = $false
                Write-LogErr "Failed to create Resource Group Deployment - $RGName."
                if ($ResourceCleanup -imatch "Delete") {
                    Write-LogInfo "-ResourceCleanup = Delete is Set. Deleting $RGName."
                    $isCleaned = Delete-ResourceGroup -RGName $RGName -UseExistingRG $UseExistingRG
                    if (!$isCleaned) {
                        Write-LogInfo "Cleanup unsuccessful for $RGName.. Please delete the services manually."
                    }
                    else {
                        Write-LogInfo "Cleanup successful for $RGName."
                    }
                }
                else {
                    $VMsCreated = Get-AzureRmVM -ResourceGroupName $RGName
                    if ( $VMsCreated ) {
                        Write-LogInfo "Keeping Failed resource group, as we found $($VMsCreated.Count) VM(s) deployed."
                    }
                    else {
                        Write-LogInfo "Removing Failed resource group, as we found 0 VM(s) deployed."
                        $isCleaned = Delete-ResourceGroup -RGName $RGName -UseExistingRG $UseExistingRG
                        if (!$isCleaned) {
                            Write-LogInfo "Cleanup unsuccessful for $RGName.. Please delete the services manually."
                        }
                        else {
                            Write-LogInfo "Cleanup successful for $RGName."
                        }
                    }
                }
            }
        }
        catch {
            $retValue = $false

            $line = $_.InvocationInfo.ScriptLineNumber
            $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
            Write-LogErr "Exception in Create-ResourceGroupDeployment"
            Write-LogErr "Source : Line $line in script $script_name."
        }
    }
    return $retValue
}

Function Get-AllDeploymentData($ResourceGroups)
{
    $allDeployedVMs = @()
    function Create-QuickVMNode()
    {
        $objNode = New-Object -TypeName PSObject
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name ServiceName -Value $ServiceName -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name ResourceGroupName -Value $ResourceGroupName -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name Location -Value $ResourceGroupName -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name RoleName -Value $RoleName -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name PublicIP -Value $PublicIP -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name PublicIPv6 -Value $PublicIP -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name InternalIP -Value $InternalIP -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name SecondInternalIP -Value $SecondInternalIP -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name URL -Value $URL -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name URLv6 -Value $URL -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name Status -Value $Status -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name InstanceSize -Value $InstanceSize -Force
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name VMGeneration -Value 1 -Force
        return $objNode
    }

    foreach ($ResourceGroup in $ResourceGroups.Split("^"))
    {
        Write-LogInfo "Collecting $ResourceGroup data.."

        Write-LogInfo "	Microsoft.Network/publicIPAddresses data collection in progress.."
        $RGIPsdata = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/publicIPAddresses" -Verbose -ExpandProperties
        Write-LogInfo "	Microsoft.Compute/virtualMachines data collection in progress.."
        $RGVMs = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Compute/virtualMachines" -Verbose -ExpandProperties
        Write-LogInfo "	Microsoft.Network/networkInterfaces data collection in progress.."
        $NICdata = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/networkInterfaces" -Verbose -ExpandProperties
        $currentRGLocation = (Get-AzureRmResourceGroup -ResourceGroupName $ResourceGroup).Location
        Write-LogInfo "	Microsoft.Network/loadBalancers data collection in progress.."
        $LBdata = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/loadBalancers" -ExpandProperties -Verbose
        foreach($ipData in $RGIPsdata) {
            if ((Get-AzureRmPublicIpAddress -Name $ipData.name -ResourceGroupName $ipData.ResourceGroupName).IpAddress -ne "Not Assigned") {
                $RGIPdata = $ipData
            }
        }

        foreach ($testVM in $RGVMs)
        {
            $QuickVMNode = Create-QuickVMNode
            $InboundNatRules = $LBdata.Properties.InboundNatRules
            foreach ($endPoint in $InboundNatRules)
            {
                if ( $endPoint.Name -imatch $testVM.ResourceName)
                {
                    $endPointName = "$($endPoint.Name)".Replace("$($testVM.ResourceName)-","")
                    Add-Member -InputObject $QuickVMNode -MemberType NoteProperty -Name "$($endPointName)Port" -Value $endPoint.Properties.FrontendPort -Force
                }
            }
            $LoadBalancingRules = $LBdata.Properties.LoadBalancingRules
            foreach ( $LBrule in $LoadBalancingRules )
            {
                if ( $LBrule.Name -imatch "$ResourceGroup-LB-" )
                {
                    $endPointName = "$($LBrule.Name)".Replace("$ResourceGroup-LB-","")
                    Add-Member -InputObject $QuickVMNode -MemberType NoteProperty -Name "$($endPointName)Port" -Value $LBrule.Properties.FrontendPort -Force
                }
            }
            $Probes = $LBdata.Properties.Probes
            foreach ( $Probe in $Probes )
            {
                if ( $Probe.Name -imatch "$ResourceGroup-LB-" )
                {
                    $probeName = "$($Probe.Name)".Replace("$ResourceGroup-LB-","").Replace("-probe","")
                    Add-Member -InputObject $QuickVMNode -MemberType NoteProperty -Name "$($probeName)ProbePort" -Value $Probe.Properties.Port -Force
                }
            }

            foreach ( $nic in $NICdata )
            {
                if (($nic.Name.Replace("PrimaryNIC-","") -eq $testVM.ResourceName) -and ( $nic.Name -imatch "PrimaryNIC"))
                {
                    $QuickVMNode.InternalIP = "$($nic.Properties.IpConfigurations[0].Properties.PrivateIPAddress)"
                }
                if (($nic.Name.Replace("ExtraNetworkCard-1-","") -eq $testVM.ResourceName) -and ($nic.Name -imatch "ExtraNetworkCard-1"))
                {
                    $QuickVMNode.SecondInternalIP = "$($nic.Properties.IpConfigurations[0].Properties.PrivateIPAddress)"
                }
            }
            $QuickVMNode.ResourceGroupName = $ResourceGroup

            $QuickVMNode.PublicIP = ($RGIPData | Where-Object { $_.Properties.publicIPAddressVersion -eq "IPv4" }).Properties.ipAddress
            $QuickVMNode.PublicIPv6 = ($RGIPData | Where-Object { $_.Properties.publicIPAddressVersion -eq "IPv6" }).Properties.ipAddress
            $QuickVMNode.URL = ($RGIPData | Where-Object { $_.Properties.publicIPAddressVersion -eq "IPv4" }).Properties.dnsSettings.fqdn
            $QuickVMNode.URLv6 = ($RGIPData | Where-Object { $_.Properties.publicIPAddressVersion -eq "IPv6" }).Properties.dnsSettings.fqdn
            $QuickVMNode.RoleName = $testVM.ResourceName
            $QuickVMNode.Status = $testVM.Properties.ProvisioningState
            $QuickVMNode.InstanceSize = $testVM.Properties.hardwareProfile.vmSize
            $QuickVMNode.Location = $currentRGLocation
            $allDeployedVMs += $QuickVMNode
        }
        Write-LogInfo "Collected $ResourceGroup data!"
    }
    return $allDeployedVMs
}

Function Get-NewVMName ($namePrefix, $numberOfVMs) {
    if ($global:IsWindowsImage) {
        # Windows computer name cannot be more than 15 characters long on Azure
        $suffix = "-$numberOfVMs"
        $len = 15 - $suffix.Length
        $VMName = $namePrefix.Substring(0, $len) + $suffix
    }
    else {
        $VMName = "$namePrefix-role-$numberOfVMs"
    }
    return $VMName
}

Function Generate-AzureDeployJSONFile ($RGName, $ImageName, $osVHD, $RGXMLData, $Location, $azuredeployJSONFilePath,
    $CurrentTestData, $StorageAccountName, $TiPSessionId, $TipCluster) {

    #Random Data
    $RGrandomWord = ([System.IO.Path]::GetRandomFileName() -replace '[^a-z]')
    $RGRandomNumber = Get-Random -Minimum 11111 -Maximum 99999

    $UseManagedDisks = $CurrentTestData.AdditionalHWConfig.DiskType -contains "managed"
    if ($UseManagedDisks) {
        $DiskType = "Managed"
    } else {
        $DiskType = "Unmanaged"
    }

    $UseSpecializedImage = $CurrentTestData.AdditionalHWConfig.ImageType -contains "Specialized"

    if ( $CurrentTestData.AdditionalHWConfig.OSDiskType -eq "Ephemeral" ) {
        if ( $UseManagedDisks ) {
            $UseEphemeralOSDisk = $true
            $DiskType += "-Ephemeral"
        }
        else {
            Throw "Invalid VM configuration. Ephemeral disks can only be created using Managed disk option."
        }
    }
    else {
        $DiskType += "-Persistent"
        $UseEphemeralOSDisk = $false
    }
    #Generate the initial data
    $numberOfVMs = 0
    $VMNames = @()
    $EnableIPv6 = $false
    $totalSubnetsRequired = 0
    foreach ( $newVM in $RGXMLData.VirtualMachine) {
        if ( !$EnableIPv6 ) {
            foreach ( $endpoint in $newVM.EndPoints ) {
                if ( $endpoint.EnableIPv6 -eq "True" ) {
                    $EnableIPv6 = $true
                }
                #Check total subnets required
                if ( $newVM.ExtraNICs -ne 0) {
                    $totalSubnetsRequired = $newVM.ExtraNICs
                }
            }
        }
        if ($newVM.RoleName) {
            $VMNames += $newVM.RoleName
        }
        else {
            $VMNames += Get-NewVMName -namePrefix $RGName -numberOfVMs $numberOfVMs
        }
        $numberOfVMs += 1
    }


    $saInfoCollected = $false
    $retryCount = 0
    $maxRetryCount = 999
    while (!$saInfoCollected -and ($retryCount -lt $maxRetryCount)) {
        try {
            $retryCount += 1
            Write-LogInfo "[Attempt $retryCount/$maxRetryCount] : Getting Existing Storage account information..."
            $GetAzureRMStorageAccount = $null
            $GetAzureRMStorageAccount = Get-AzureRmStorageAccount
            if ($GetAzureRMStorageAccount -eq $null) {
                $saInfoCollected = $false
            }
            else {
                $saInfoCollected = $true
            }

        }
        catch {
            Write-LogErr "Error in fetching Storage Account info. Retrying in 10 seconds."
            Start-Sleep -Seconds 10
            $saInfoCollected = $false
        }
    }

    #Condition Existing Storage - NonManaged disks
    if ( $StorageAccountName -inotmatch "NewStorage" -and !$UseManagedDisks ) {
        $StorageAccountType = ($GetAzureRMStorageAccount | Where-Object {$_.StorageAccountName -eq $StorageAccountName}).Sku.Tier.ToString()
        if ($StorageAccountType -match 'Premium') {
            $StorageAccountType = "Premium_LRS"
        }
        else {
            $StorageAccountType = "Standard_LRS"
        }
        Write-LogInfo "Storage Account Type : $StorageAccountType"
    }

    #Condition Existing Storage - Managed Disks
    if ( $StorageAccountName -inotmatch "NewStorage" -and $UseManagedDisks ) {
        $StorageAccountType = ($GetAzureRMStorageAccount | Where-Object {$_.StorageAccountName -eq $StorageAccountName}).Sku.Tier.ToString()
        if ($StorageAccountType -match 'Premium') {
            $StorageAccountType = "Premium_LRS"
        }
        else {
            $StorageAccountType = "Standard_LRS"
        }
    }

    #Condition New Storage - NonManaged disk
    if ( $StorageAccountName -imatch "NewStorage" -and !$UseManagedDisks) {
        $NewARMStorageAccountType = ($StorageAccountName).Replace("NewStorage_", "")
        $StorageAccountName = $($NewARMStorageAccountType.ToLower().Replace("_", "")) + "$RGRandomNumber"
        $NewStorageAccountName = $StorageAccountName
        Write-LogInfo "Using New ARM Storage Account : $StorageAccountName"
        $StorageAccountType = $NewARMStorageAccountType
    }

    #Condition New Storage - Managed disk
    if ( $StorageAccountName -imatch "NewStorage" -and $UseManagedDisks) {
        Write-LogInfo "Conflicting parameters - NewStorage and UseManagedDisks. Storage account will not be created."
    }
    #Region Define all Variables.

    Write-LogInfo "Generating Template : $azuredeployJSONFilePath"
    $jsonFile = $azuredeployJSONFilePath

    if ($ImageName -and !$osVHD) {
        $imageInfo = $ImageName.Split(' ')
        $publisher = $imageInfo[0]
        $offer = $imageInfo[1]
        $sku = $imageInfo[2]
        $version = $imageInfo[3]
    }

    $vmCount = 0
    $indents = @()
    $indent = ""
    $singleIndent = ""
    $indents += $indent
    $dnsNameForPublicIP = "ica$RGRandomNumber" + "v4"
    $dnsNameForPublicIPv6 = "ica$RGRandomNumber" + "v6"
    #$virtualNetworkName = $($RGName.ToUpper() -replace '[^a-z]') + "VNET"
    $virtualNetworkName = "VirtualNetwork"
    $defaultSubnetName = "SubnetForPrimaryNIC"
    $availabilitySetName = "AvailabilitySet"
    #$LoadBalancerName =  $($RGName.ToUpper() -replace '[^a-z]') + "LoadBalancer"
    $LoadBalancerName = "LoadBalancer"
    $apiVersion = "2018-04-01"
    #$PublicIPName = $($RGName.ToUpper() -replace '[^a-z]') + "PublicIPv4"
    $PublicIPName = "PublicIPv4-$RGRandomNumber"
    #$PublicIPv6Name = $($RGName.ToUpper() -replace '[^a-z]') + "PublicIPv6"
    $PublicIPv6Name = "PublicIPv6"
    $sshPath = '/home/' + $user + '/.ssh/authorized_keys'
    $sshKeyData = ""
    $createAvailabilitySet = !$UseExistingRG

    if ($UseExistingRG) {
        $existentAvailabilitySet = Get-AzureRmResource | Where-Object { (( $_.ResourceGroupName -eq $RGName ) -and ( $_.ResourceType -imatch "availabilitySets" ))} | `
            Select-Object -First 1
        if ($existentAvailabilitySet) {
            $availabilitySetName = $existentAvailabilitySet.Name
        } else {
            $createAvailabilitySet = $true
        }
    }

    if ( $CurrentTestData.ProvisionTimeExtensions ) {
        $extensionString = (Get-Content .\XML\Extensions.xml)
        foreach ($line in $extensionString.Split("`n")) {
            if ($line -imatch ">$($CurrentTestData.ProvisionTimeExtensions)<") {
                $ExecutePS = $true
            }
            if ($line -imatch '</Extension>') {
                $ExecutePS = $false
            }
            if ( ($line -imatch "EXECUTE-PS-" ) -and $ExecutePS) {
                $PSoutout = ""
                $line = $line.Trim()
                $line = $line.Replace("EXECUTE-PS-", "")
                $line = $line.Split(">")
                $line = $line.Split("<")
                Write-LogInfo "Executing Powershell command from Extensions.XML file : $($line[2])..."
                $PSoutout = Invoke-Expression -Command $line[2]
                $extensionString = $extensionString.Replace("EXECUTE-PS-$($line[2])", $PSoutout)
                Start-Sleep -Milliseconds 1
            }
        }
    }

    Write-LogInfo "Using API VERSION : $apiVersion"
    $ExistingVnet = $null
    if ($RGXMLData.ARMVnetName -ne $null) {
        $ExistingVnet = $RGXMLData.ARMVnetName
        Write-LogInfo "Getting $ExistingVnet Virtual Netowrk info ..."
        $ExistingVnetResourceGroupName = ( Get-AzureRmResource | Where-Object {$_.Name -eq $ExistingVnet}).ResourceGroupName
        Write-LogInfo "ARM VNET : $ExistingVnet (ResourceGroup : $ExistingVnetResourceGroupName)"
        $virtualNetworkName = $ExistingVnet
    }

    #Generate Single Indent
    for ($i = 0; $i -lt 4; $i++) {
        $singleIndent += " "
    }

    #Generate Indent Levels
    for ($i = 0; $i -lt 30; $i++) {
        $indent += $singleIndent
        $indents += $indent
    }


    #region Generate JSON file
    Set-Content -Value "$($indents[0]){" -Path $jsonFile -Force
    Add-Content -Value "$($indents[1])^`$schema^: ^https://schema.management.azure.com/schemas/2015-01-01/deploymentTemplate.json#^," -Path $jsonFile
    Add-Content -Value "$($indents[1])^contentVersion^: ^1.0.0.0^," -Path $jsonFile
    Add-Content -Value "$($indents[1])^parameters^: {}," -Path $jsonFile
    Add-Content -Value "$($indents[1])^variables^:" -Path $jsonFile
    Add-Content -Value "$($indents[1]){" -Path $jsonFile

    #region Variables
    Add-Content -Value "$($indents[2])^StorageAccountName^: ^$StorageAccountName^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^dnsNameForPublicIP^: ^$dnsNameForPublicIP^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^dnsNameForPublicIPv6^: ^$dnsNameForPublicIPv6^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^adminUserName^: ^$user^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^adminPassword^: ^$($password.Replace('"',''))^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^sshKeyPublicThumbPrint^: ^$sshPublicKeyThumbprint^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^sshKeyPath^: ^$sshPath^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^sshKeyData^: ^$sshKeyData^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^location^: ^$($Location.Replace('"',''))^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^publicIPv4AddressName^: ^$PublicIPName^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^publicIPv6AddressName^: ^$PublicIPv6Name^," -Path $jsonFile

    Add-Content -Value "$($indents[2])^virtualNetworkName^: ^$virtualNetworkName^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^nicName^: ^$nicName^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^addressPrefix^: ^10.0.0.0/16^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^vmSourceImageName^ : ^^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^CompliedSourceImageName^ : ^[concat('/',subscription().subscriptionId,'/services/images/',variables('vmSourceImageName'))]^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^defaultSubnetPrefix^: ^10.0.0.0/24^," -Path $jsonFile
    #Add-Content -Value "$($indents[2])^subnet2Prefix^: ^10.0.1.0/24^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^vmStorageAccountContainerName^: ^vhds^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^publicIPAddressType^: ^Dynamic^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^storageAccountType^: ^$storageAccountType^," -Path $jsonFile
    if ($ExistingVnet) {
        Add-Content -Value "$($indents[2])^virtualNetworkResourceGroup^: ^$ExistingVnetResourceGroupName^," -Path $jsonFile
        Add-Content -Value "$($indents[2])^vnetID^: ^[resourceId(variables('virtualNetworkResourceGroup'), 'Microsoft.Network/virtualNetworks', '$virtualNetworkName')]^," -Path $jsonFile
    }
    else {
        Add-Content -Value "$($indents[2])^defaultSubnet^: ^$defaultSubnetName^," -Path $jsonFile
        Add-Content -Value "$($indents[2])^defaultSubnetID^: ^[concat(variables('vnetID'),'/subnets/', variables('defaultSubnet'))]^," -Path $jsonFile
        Add-Content -Value "$($indents[2])^vnetID^: ^[resourceId('Microsoft.Network/virtualNetworks',variables('virtualNetworkName'))]^," -Path $jsonFile
    }
    Add-Content -Value "$($indents[2])^availabilitySetName^: ^$availabilitySetName^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^lbName^: ^$LoadBalancerName^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^lbID^: ^[resourceId('Microsoft.Network/loadBalancers',variables('lbName'))]^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^frontEndIPv4ConfigID^: ^[concat(variables('lbID'),'/frontendIPConfigurations/LoadBalancerFrontEndIPv4')]^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^frontEndIPv6ConfigID^: ^[concat(variables('lbID'),'/frontendIPConfigurations/LoadBalancerFrontEndIPv6')]^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^lbIPv4PoolID^: ^[concat(variables('lbID'),'/backendAddressPools/BackendPoolIPv4')]^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^lbIPv6PoolID^: ^[concat(variables('lbID'),'/backendAddressPools/BackendPoolIPv6')]^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^lbProbeID^: ^[concat(variables('lbID'),'/probes/tcpProbe')]^" -Path $jsonFile
    #Add more variables here, if required..
    Add-Content -Value "$($indents[1])}," -Path $jsonFile
    Write-LogInfo "Added Variables.."

    #endregion

    #region Define Resources
    Add-Content -Value "$($indents[1])^resources^:" -Path $jsonFile
    Add-Content -Value "$($indents[1])[" -Path $jsonFile

    #region Common Resources for all deployments..

    #region availabilitySets
    if (!$createAvailabilitySet) {
        Write-LogInfo "Using existing Availability Set: $availabilitySetName"
    }
    else {
        Add-Content -Value "$($indents[2]){" -Path $jsonFile
        Add-Content -Value "$($indents[3])^apiVersion^: ^$apiVersion^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^type^: ^Microsoft.Compute/availabilitySets^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^name^: ^[variables('availabilitySetName')]^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
        if ($UseManagedDisks) {
            Add-Content -Value "$($indents[3])^sku^:" -Path $jsonFile
            Add-Content -Value "$($indents[3]){" -Path $jsonFile
            Add-Content -Value "$($indents[4])^name^: ^Aligned^" -Path $jsonFile
            Add-Content -Value "$($indents[3])}," -Path $jsonFile
        }
        if ( $TiPSessionId -and $TiPCluster) {
            Add-Content -Value "$($indents[3])^tags^:" -Path $jsonFile
            Add-Content -Value "$($indents[3]){" -Path $jsonFile
            Add-Content -Value "$($indents[4])^TipNode.SessionId^: ^$TiPSessionId^" -Path $jsonFile
            Add-Content -Value "$($indents[3])}," -Path $jsonFile
        }
        Add-Content -Value "$($indents[3])^properties^:" -Path $jsonFile
        Add-Content -Value "$($indents[3]){" -Path $jsonFile
        Add-Content -Value "$($indents[4])^platformFaultDomainCount^:2," -Path $jsonFile
        Add-Content -Value "$($indents[4])^platformUpdateDomainCount^:5" -Path $jsonFile
        if ( $TiPSessionId -and $TiPCluster) {
            Add-Content -Value "$($indents[4])," -Path $jsonFile
            Add-Content -Value "$($indents[4])^internalData^:" -Path $jsonFile
            Add-Content -Value "$($indents[4]){" -Path $jsonFile
            Add-Content -Value "$($indents[5])^pinnedFabricCluster^ : ^$TiPCluster^" -Path $jsonFile
            Add-Content -Value "$($indents[4])}" -Path $jsonFile
        }
        Add-Content -Value "$($indents[3])}" -Path $jsonFile
        Add-Content -Value "$($indents[2])}," -Path $jsonFile
        Write-LogInfo "Added availabilitySet $availabilitySetName.."
    }
    #endregion

    #region publicIPAddresses
    Add-Content -Value "$($indents[2]){" -Path $jsonFile
    Add-Content -Value "$($indents[3])^apiVersion^: ^$apiVersion^," -Path $jsonFile
    Add-Content -Value "$($indents[3])^type^: ^Microsoft.Network/publicIPAddresses^," -Path $jsonFile
    Add-Content -Value "$($indents[3])^name^: ^[variables('publicIPv4AddressName')]^," -Path $jsonFile
    Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
    Add-Content -Value "$($indents[3])^properties^:" -Path $jsonFile
    Add-Content -Value "$($indents[3]){" -Path $jsonFile
    Add-Content -Value "$($indents[4])^publicIPAllocationMethod^: ^[variables('publicIPAddressType')]^," -Path $jsonFile
    Add-Content -Value "$($indents[4])^dnsSettings^: " -Path $jsonFile
    Add-Content -Value "$($indents[4]){" -Path $jsonFile
    Add-Content -Value "$($indents[5])^domainNameLabel^: ^[variables('dnsNameForPublicIP')]^" -Path $jsonFile
    Add-Content -Value "$($indents[4])}" -Path $jsonFile
    Add-Content -Value "$($indents[3])}" -Path $jsonFile
    Add-Content -Value "$($indents[2])}," -Path $jsonFile
    Write-LogInfo "Added Public IP Address $PublicIPName.."
    #endregion

    #region CustomImages
    if ($OsVHD -and $UseManagedDisks) {
        Add-Content -Value "$($indents[2]){" -Path $jsonFile
        Add-Content -Value "$($indents[3])^apiVersion^: ^2017-12-01^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^type^: ^Microsoft.Compute/images^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^name^: ^$RGName-Image^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^properties^:" -Path $jsonFile
        Add-Content -Value "$($indents[3]){" -Path $jsonFile
        Add-Content -Value "$($indents[4])^storageProfile^: " -Path $jsonFile
        Add-Content -Value "$($indents[4]){" -Path $jsonFile

        Add-Content -Value "$($indents[5])^osDisk^: " -Path $jsonFile
        Add-Content -Value "$($indents[5]){" -Path $jsonFile
        Add-Content -Value "$($indents[6])^osType^: ^Linux^," -Path $jsonFile
        Add-Content -Value "$($indents[6])^osState^: ^Generalized^," -Path $jsonFile
        Add-Content -Value "$($indents[6])^blobUri^: ^https://$StorageAccountName.blob.core.windows.net/vhds/$OsVHD^," -Path $jsonFile
        Add-Content -Value "$($indents[6])^storageAccountType^: ^$StorageAccountType^," -Path $jsonFile
        Add-Content -Value "$($indents[5])}" -Path $jsonFile

        Add-Content -Value "$($indents[4])}" -Path $jsonFile
        Add-Content -Value "$($indents[3])}" -Path $jsonFile
        Add-Content -Value "$($indents[2])}," -Path $jsonFile
        Write-LogInfo "Added Custom image '$RGName-Image' from '$OsVHD'.."

    }
    #endregion


    #region New ARM Storage Account, if necessary!
    if ( $NewStorageAccountName) {
        Add-Content -Value "$($indents[2]){" -Path $jsonFile
        Add-Content -Value "$($indents[3])^apiVersion^: ^2015-06-15^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^type^: ^Microsoft.Storage/storageAccounts^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^name^: ^$NewStorageAccountName^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^properties^:" -Path $jsonFile
        Add-Content -Value "$($indents[3]){" -Path $jsonFile
        Add-Content -Value "$($indents[4])^accountType^: ^$($NewARMStorageAccountType.Trim())^" -Path $jsonFile
        Add-Content -Value "$($indents[3])}" -Path $jsonFile
        Add-Content -Value "$($indents[2])}," -Path $jsonFile
        Write-LogInfo "Added New Storage Account $NewStorageAccountName.."
    }
    #endregion

    #region New ARM Bood Diagnostic Account if Storage Account Type is Premium LRS.
    $bootDiagnosticsSA = ([xml](Get-Content .\XML\RegionAndStorageAccounts.xml)).AllRegions.$Location.StandardStorage
    $diagnosticRG = ($GetAzureRMStorageAccount | Where-Object {$_.StorageAccountName -eq $bootDiagnosticsSA}).ResourceGroupName.ToString()
    #endregion

    #region virtualNetworks
    if (!$ExistingVnet) {
        Add-Content -Value "$($indents[2]){" -Path $jsonFile
        Add-Content -Value "$($indents[3])^apiVersion^: ^$apiVersion^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^type^: ^Microsoft.Network/virtualNetworks^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^name^: ^[variables('virtualNetworkName')]^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^properties^:" -Path $jsonFile
        Add-Content -Value "$($indents[3]){" -Path $jsonFile
        #AddressSpace
        Add-Content -Value "$($indents[4])^addressSpace^: " -Path $jsonFile
        Add-Content -Value "$($indents[4]){" -Path $jsonFile
        Add-Content -Value "$($indents[5])^addressPrefixes^: " -Path $jsonFile
        Add-Content -Value "$($indents[5])[" -Path $jsonFile
        Add-Content -Value "$($indents[6])^[variables('addressPrefix')]^" -Path $jsonFile
        Add-Content -Value "$($indents[5])]" -Path $jsonFile
        Add-Content -Value "$($indents[4])}," -Path $jsonFile
        #Subnets
        Add-Content -Value "$($indents[4])^subnets^: " -Path $jsonFile
        Add-Content -Value "$($indents[4])[" -Path $jsonFile
        Add-Content -Value "$($indents[5]){" -Path $jsonFile
        Add-Content -Value "$($indents[6])^name^: ^[variables('defaultSubnet')]^," -Path $jsonFile
        Add-Content -Value "$($indents[6])^properties^: " -Path $jsonFile
        Add-Content -Value "$($indents[6]){" -Path $jsonFile
        Add-Content -Value "$($indents[7])^addressPrefix^: ^[variables('defaultSubnetPrefix')]^" -Path $jsonFile
        Add-Content -Value "$($indents[6])}" -Path $jsonFile
        Add-Content -Value "$($indents[5])}" -Path $jsonFile
        Write-LogInfo "Added Default Subnet to $virtualNetworkName.."

        if ($totalSubnetsRequired -ne 0) {
            $subnetCounter = 1
            While ($subnetCounter -le $totalSubnetsRequired) {
                Add-Content -Value "$($indents[5])," -Path $jsonFile
                Add-Content -Value "$($indents[5]){" -Path $jsonFile
                Add-Content -Value "$($indents[6])^name^: ^ExtraSubnet-$subnetCounter^," -Path $jsonFile
                Add-Content -Value "$($indents[6])^properties^: " -Path $jsonFile
                Add-Content -Value "$($indents[6]){" -Path $jsonFile
                Add-Content -Value "$($indents[7])^addressPrefix^: ^10.0.$subnetCounter.0/24^" -Path $jsonFile
                Add-Content -Value "$($indents[6])}" -Path $jsonFile
                Add-Content -Value "$($indents[5])}" -Path $jsonFile
                Write-LogInfo "  Added ExtraSubnet-$subnetCounter to $virtualNetworkName.."
                $subnetCounter += 1
            }
        }
        Add-Content -Value "$($indents[4])]" -Path $jsonFile
        Add-Content -Value "$($indents[3])}" -Path $jsonFile
        Add-Content -Value "$($indents[2])}," -Path $jsonFile
        Write-LogInfo "Added Virtual Network $virtualNetworkName.."
    }
    #endregion

    #endregion

    #region publicIPAddresses
    if ( $EnableIPv6 ) {
        Add-Content -Value "$($indents[2]){" -Path $jsonFile
        Add-Content -Value "$($indents[3])^apiVersion^: ^$apiVersion^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^type^: ^Microsoft.Network/publicIPAddresses^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^name^: ^[variables('publicIPv6AddressName')]^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^properties^:" -Path $jsonFile
        Add-Content -Value "$($indents[3]){" -Path $jsonFile
        Add-Content -Value "$($indents[4])^publicIPAllocationMethod^: ^[variables('publicIPAddressType')]^," -Path $jsonFile
        Add-Content -Value "$($indents[4])^publicIPAddressVersion^: ^IPv6^," -Path $jsonFile
        Add-Content -Value "$($indents[4])^dnsSettings^: " -Path $jsonFile
        Add-Content -Value "$($indents[4]){" -Path $jsonFile
        Add-Content -Value "$($indents[5])^domainNameLabel^: ^[variables('dnsNameForPublicIPv6')]^" -Path $jsonFile
        Add-Content -Value "$($indents[4])}" -Path $jsonFile
        Add-Content -Value "$($indents[3])}" -Path $jsonFile
        Add-Content -Value "$($indents[2])}," -Path $jsonFile
        Write-LogInfo "Added Public IPv6 Address $PublicIPv6Name.."
    }
    #endregion

    #region Multiple VM Deployment

    #region LoadBalancer
    Write-LogInfo "Adding Load Balancer ..."
    Add-Content -Value "$($indents[2]){" -Path $jsonFile
    Add-Content -Value "$($indents[3])^apiVersion^: ^$apiVersion^," -Path $jsonFile
    Add-Content -Value "$($indents[3])^type^: ^Microsoft.Network/loadBalancers^," -Path $jsonFile
    Add-Content -Value "$($indents[3])^name^: ^[variables('lbName')]^," -Path $jsonFile
    Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
    Add-Content -Value "$($indents[3])^dependsOn^: " -Path $jsonFile
    Add-Content -Value "$($indents[3])[" -Path $jsonFile
    if ( $EnableIPv6 ) {
        Add-Content -Value "$($indents[4])^[concat('Microsoft.Network/publicIPAddresses/', variables('publicIPv6AddressName'))]^," -Path $jsonFile
    }
    Add-Content -Value "$($indents[4])^[concat('Microsoft.Network/publicIPAddresses/', variables('publicIPv4AddressName'))]^" -Path $jsonFile
    Add-Content -Value "$($indents[3])]," -Path $jsonFile
    Add-Content -Value "$($indents[3])^properties^:" -Path $jsonFile
    Add-Content -Value "$($indents[3]){" -Path $jsonFile
    Add-Content -Value "$($indents[4])^frontendIPConfigurations^: " -Path $jsonFile
    Add-Content -Value "$($indents[4])[" -Path $jsonFile
    Add-Content -Value "$($indents[5]){" -Path $jsonFile
    Add-Content -Value "$($indents[6])^name^: ^LoadBalancerFrontEndIPv4^," -Path $jsonFile
    Add-Content -Value "$($indents[6])^properties^:" -Path $jsonFile
    Add-Content -Value "$($indents[6]){" -Path $jsonFile
    Add-Content -Value "$($indents[7])^publicIPAddress^:" -Path $jsonFile
    Add-Content -Value "$($indents[7]){" -Path $jsonFile
    Add-Content -Value "$($indents[8])^id^: ^[resourceId('Microsoft.Network/publicIPAddresses',variables('publicIPv4AddressName'))]^" -Path $jsonFile
    Add-Content -Value "$($indents[7])}" -Path $jsonFile
    Add-Content -Value "$($indents[6])}" -Path $jsonFile
    Add-Content -Value "$($indents[5])}" -Path $jsonFile

    #region IPV6 frondend loadbalancer config
    if ( $EnableIPv6 ) {
        Add-Content -Value "$($indents[5])," -Path $jsonFile
        Add-Content -Value "$($indents[5]){" -Path $jsonFile
        Add-Content -Value "$($indents[6])^name^: ^LoadBalancerFrontEndIPv6^," -Path $jsonFile
        Add-Content -Value "$($indents[6])^properties^:" -Path $jsonFile
        Add-Content -Value "$($indents[6]){" -Path $jsonFile
        Add-Content -Value "$($indents[7])^publicIPAddress^:" -Path $jsonFile
        Add-Content -Value "$($indents[7]){" -Path $jsonFile
        Add-Content -Value "$($indents[8])^id^: ^[resourceId('Microsoft.Network/publicIPAddresses',variables('publicIPv6AddressName'))]^" -Path $jsonFile
        Add-Content -Value "$($indents[7])}" -Path $jsonFile
        Add-Content -Value "$($indents[6])}" -Path $jsonFile
        Add-Content -Value "$($indents[5])}" -Path $jsonFile
    }
    #endregion

    Add-Content -Value "$($indents[4])]," -Path $jsonFile
    Add-Content -Value "$($indents[4])^backendAddressPools^:" -Path $jsonFile
    Add-Content -Value "$($indents[4])[" -Path $jsonFile
    Add-Content -Value "$($indents[5]){" -Path $jsonFile
    Add-Content -Value "$($indents[6])^name^:^BackendPoolIPv4^" -Path $jsonFile
    Add-Content -Value "$($indents[5])}" -Path $jsonFile
    if ( $EnableIPv6 ) {
        Add-Content -Value "$($indents[5])," -Path $jsonFile
        Add-Content -Value "$($indents[5]){" -Path $jsonFile
        Add-Content -Value "$($indents[6])^name^:^BackendPoolIPv6^" -Path $jsonFile
        Add-Content -Value "$($indents[5])}" -Path $jsonFile
    }
    Add-Content -Value "$($indents[4])]," -Path $jsonFile
    #region Normal Endpoints

    Add-Content -Value "$($indents[4])^inboundNatRules^:" -Path $jsonFile
    Add-Content -Value "$($indents[4])[" -Path $jsonFile
    $LBPorts = 0
    $EndPointAdded = $false
    $role = 0
    foreach ( $newVM in $RGXMLData.VirtualMachine) {
        if ($newVM.RoleName) {
            $vmName = $newVM.RoleName
        }
        else {
            $vmName = Get-NewVMName -namePrefix $RGName -numberOfVMs $role
        }
        foreach ( $endpoint in $newVM.EndPoints) {
            if ( !($endpoint.LoadBalanced) -or ($endpoint.LoadBalanced -eq "False") ) {
                if ( $EndPointAdded ) {
                    Add-Content -Value "$($indents[5])," -Path $jsonFile
                }
                Add-Content -Value "$($indents[5]){" -Path $jsonFile
                Add-Content -Value "$($indents[6])^name^: ^$vmName-$($endpoint.Name)^," -Path $jsonFile
                Add-Content -Value "$($indents[6])^properties^:" -Path $jsonFile
                Add-Content -Value "$($indents[6]){" -Path $jsonFile
                Add-Content -Value "$($indents[7])^frontendIPConfiguration^:" -Path $jsonFile
                Add-Content -Value "$($indents[7]){" -Path $jsonFile
                Add-Content -Value "$($indents[8])^id^: ^[variables('frontEndIPv4ConfigID')]^" -Path $jsonFile
                Add-Content -Value "$($indents[7])}," -Path $jsonFile
                Add-Content -Value "$($indents[7])^protocol^: ^$($endpoint.Protocol)^," -Path $jsonFile
                Add-Content -Value "$($indents[7])^frontendPort^: ^$($endpoint.PublicPort)^," -Path $jsonFile
                Add-Content -Value "$($indents[7])^backendPort^: ^$($endpoint.LocalPort)^," -Path $jsonFile
                Add-Content -Value "$($indents[7])^enableFloatingIP^: false" -Path $jsonFile
                Add-Content -Value "$($indents[6])}" -Path $jsonFile
                Add-Content -Value "$($indents[5])}" -Path $jsonFile
                Write-LogInfo "Added inboundNatRule Name:$vmName-$($endpoint.Name) frontendPort:$($endpoint.PublicPort) backendPort:$($endpoint.LocalPort) Protocol:$($endpoint.Protocol)."
                $EndPointAdded = $true
            }
            else {
                $LBPorts += 1
            }
        }
        $role += 1
    }
    Add-Content -Value "$($indents[4])]" -Path $jsonFile
    #endregion

    #region LoadBalanced Endpoints
    if ( $LBPorts -gt 0 ) {
        Add-Content -Value "$($indents[4])," -Path $jsonFile
        Add-Content -Value "$($indents[4])^loadBalancingRules^:" -Path $jsonFile
        Add-Content -Value "$($indents[4])[" -Path $jsonFile
        $probePorts = 0
        $EndPointAdded = $false
        $addedLBPort = $null
        $role = 0
        foreach ( $newVM in $RGXMLData.VirtualMachine) {
            if ($newVM.RoleName) {
                $vmName = $newVM.RoleName
            }
            else {
                $vmName = Get-NewVMName -namePrefix $RGName -numberOfVMs $role
            }

            foreach ( $endpoint in $newVM.EndPoints) {
                if ( ($endpoint.LoadBalanced -eq "True") -and !($addedLBPort -imatch "$($endpoint.Name)-$($endpoint.PublicPort)" ) ) {
                    if ( $EndPointAdded ) {
                        Add-Content -Value "$($indents[5])," -Path $jsonFile
                    }
                    Add-Content -Value "$($indents[5]){" -Path $jsonFile
                    Add-Content -Value "$($indents[6])^name^: ^$RGName-LB-$($endpoint.Name)^," -Path $jsonFile
                    Add-Content -Value "$($indents[6])^properties^:" -Path $jsonFile
                    Add-Content -Value "$($indents[6]){" -Path $jsonFile

                    Add-Content -Value "$($indents[7])^frontendIPConfiguration^:" -Path $jsonFile
                    Add-Content -Value "$($indents[7]){" -Path $jsonFile
                    if ($endpoint.EnableIPv6 -eq "True") {
                        Add-Content -Value "$($indents[8])^id^: ^[variables('frontEndIPv6ConfigID')]^" -Path $jsonFile
                    }
                    else {
                        Add-Content -Value "$($indents[8])^id^: ^[variables('frontEndIPv4ConfigID')]^" -Path $jsonFile
                    }
                    Add-Content -Value "$($indents[7])}," -Path $jsonFile
                    Add-Content -Value "$($indents[7])^backendAddressPool^:" -Path $jsonFile
                    Add-Content -Value "$($indents[7]){" -Path $jsonFile
                    if ($endpoint.EnableIPv6 -eq "True") {
                        Add-Content -Value "$($indents[8])^id^: ^[variables('lbIPv6PoolID')]^" -Path $jsonFile
                    }
                    else {
                        Add-Content -Value "$($indents[8])^id^: ^[variables('lbIPv4PoolID')]^" -Path $jsonFile
                    }
                    Add-Content -Value "$($indents[7])}," -Path $jsonFile
                    Add-Content -Value "$($indents[7])^protocol^: ^$($endpoint.Protocol)^," -Path $jsonFile
                    Add-Content -Value "$($indents[7])^frontendPort^: ^$($endpoint.PublicPort)^," -Path $jsonFile
                    Add-Content -Value "$($indents[7])^backendPort^: ^$($endpoint.LocalPort)^" -Path $jsonFile


                    if ( $endpoint.ProbePort ) {
                        $probePorts += 1
                        Add-Content -Value "$($indents[7])," -Path $jsonFile
                        Add-Content -Value "$($indents[7])^probe^:" -Path $jsonFile
                        Add-Content -Value "$($indents[7]){" -Path $jsonFile
                        Add-Content -Value "$($indents[8])^id^: ^[concat(variables('lbID'),'/probes/$RGName-LB-$($endpoint.Name)-probe')]^" -Path $jsonFile
                        Add-Content -Value "$($indents[7])}," -Path $jsonFile
                        Write-LogInfo "Enabled Probe for loadBalancingRule Name:$RGName-LB-$($endpoint.Name) : $RGName-LB-$($endpoint.Name)-probe."
                    }
                    else {
                        if ( $endpoint.EnableIPv6 -ne "True" ) {
                            Add-Content -Value "$($indents[7])," -Path $jsonFile
                            Add-Content -Value "$($indents[7])^enableFloatingIP^: false," -Path $jsonFile
                            Add-Content -Value "$($indents[7])^idleTimeoutInMinutes^: 5" -Path $jsonFile
                        }
                    }
                    Add-Content -Value "$($indents[6])}" -Path $jsonFile
                    Add-Content -Value "$($indents[5])}" -Path $jsonFile
                    Write-LogInfo "Added loadBalancingRule Name:$RGName-LB-$($endpoint.Name) frontendPort:$($endpoint.PublicPort) backendPort:$($endpoint.LocalPort) Protocol:$($endpoint.Protocol)."
                    if ( $addedLBPort ) {
                        $addedLBPort += "-$($endpoint.Name)-$($endpoint.PublicPort)"
                    }
                    else {
                        $addedLBPort = "$($endpoint.Name)-$($endpoint.PublicPort)"
                    }
                    $EndPointAdded = $true
                }
            }
            $role += 1
        }
        Add-Content -Value "$($indents[4])]" -Path $jsonFile
    }
    #endregion

    #region Probe Ports
    if ( $probePorts -gt 0 ) {
        Add-Content -Value "$($indents[4])," -Path $jsonFile
        Add-Content -Value "$($indents[4])^probes^:" -Path $jsonFile
        Add-Content -Value "$($indents[4])[" -Path $jsonFile

        $EndPointAdded = $false
        $addedProbes = $null
        $role = 0
        foreach ( $newVM in $RGXMLData.VirtualMachine) {

            if ($newVM.RoleName) {
                $vmName = $newVM.RoleName
            }
            else {
                $vmName = Get-NewVMName -namePrefix $RGName -numberOfVMs $role
            }

            foreach ( $endpoint in $newVM.EndPoints) {
                if ( ($endpoint.LoadBalanced -eq "True") ) {
                    if ( $endpoint.ProbePort -and !($addedProbes -imatch "$($endpoint.Name)-probe-$($endpoint.ProbePort)")) {
                        if ( $EndPointAdded ) {
                            Add-Content -Value "$($indents[5])," -Path $jsonFile
                        }
                        Add-Content -Value "$($indents[5]){" -Path $jsonFile
                        Add-Content -Value "$($indents[6])^name^: ^$RGName-LB-$($endpoint.Name)-probe^," -Path $jsonFile
                        Add-Content -Value "$($indents[6])^properties^:" -Path $jsonFile
                        Add-Content -Value "$($indents[6]){" -Path $jsonFile
                        Add-Content -Value "$($indents[7])^protocol^ : ^$($endpoint.Protocol)^," -Path $jsonFile
                        Add-Content -Value "$($indents[7])^port^ : ^$($endpoint.ProbePort)^," -Path $jsonFile
                        Add-Content -Value "$($indents[7])^intervalInSeconds^ : ^15^," -Path $jsonFile
                        Add-Content -Value "$($indents[7])^numberOfProbes^ : ^$probePorts^" -Path $jsonFile
                        Add-Content -Value "$($indents[6])}" -Path $jsonFile
                        Add-Content -Value "$($indents[5])}" -Path $jsonFile
                        Write-LogInfo "Added probe :$RGName-LB-$($endpoint.Name)-probe Probe Port:$($endpoint.ProbePort) Protocol:$($endpoint.Protocol)."
                        if ( $addedProbes ) {
                            $addedProbes += "-$($endpoint.Name)-probe-$($endpoint.ProbePort)"
                        }
                        else {
                            $addedProbes = "$($endpoint.Name)-probe-$($endpoint.ProbePort)"
                        }
                        $EndPointAdded = $true
                    }
                }
            }

            $role += 1
        }
        Add-Content -Value "$($indents[4])]" -Path $jsonFile
    }
    #endregion

    Add-Content -Value "$($indents[3])}" -Path $jsonFile
    Add-Content -Value "$($indents[2])}," -Path $jsonFile
    Write-LogInfo "Addded Load Balancer."
    #endregion

    $vmAdded = $false
    $role = 0
    foreach ( $newVM in $RGXMLData.VirtualMachine) {
        if ( $CurrentTestData.OverrideVMSize) {
            $instanceSize = $CurrentTestData.OverrideVMSize
        }
        else {
            $instanceSize = $newVM.ARMInstanceSize
        }

        $ExistingSubnet = $newVM.ARMSubnetName
        if ($newVM.RoleName) {
            $vmName = $newVM.RoleName
        }
        else {
            $vmName = Get-NewVMName -namePrefix $RGName -numberOfVMs $role
        }
        $NIC = "PrimaryNIC" + "-$vmName"

        if ( $vmAdded ) {
            Add-Content -Value "$($indents[2])," -Path $jsonFile
        }

        #region networkInterfaces
        Write-LogInfo "Adding Network Interface Card $NIC"
        Add-Content -Value "$($indents[2]){" -Path $jsonFile
        Add-Content -Value "$($indents[3])^apiVersion^: ^2016-09-01^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^type^: ^Microsoft.Network/networkInterfaces^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^name^: ^$NIC^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^dependsOn^: " -Path $jsonFile
        Add-Content -Value "$($indents[3])[" -Path $jsonFile
        if ( $EnableIPv6 ) {
            Add-Content -Value "$($indents[4])^[concat('Microsoft.Network/publicIPAddresses/', variables('publicIPv6AddressName'))]^," -Path $jsonFile
        }
        Add-Content -Value "$($indents[4])^[concat('Microsoft.Network/publicIPAddresses/', variables('publicIPv4AddressName'))]^," -Path $jsonFile
        if (!$ExistingVnet) {
            Add-Content -Value "$($indents[4])^[concat('Microsoft.Network/virtualNetworks/', variables('virtualNetworkName'))]^," -Path $jsonFile
        }
        Add-Content -Value "$($indents[4])^[variables('lbID')]^" -Path $jsonFile
        Add-Content -Value "$($indents[3])]," -Path $jsonFile

        Add-Content -Value "$($indents[3])^properties^:" -Path $jsonFile
        Add-Content -Value "$($indents[3]){" -Path $jsonFile
        Add-Content -Value "$($indents[4])^ipConfigurations^: " -Path $jsonFile
        Add-Content -Value "$($indents[4])[" -Path $jsonFile

        #region IPv4 Config
        Add-Content -Value "$($indents[5]){" -Path $jsonFile
        Add-Content -Value "$($indents[6])^name^: ^IPv4Config1^," -Path $jsonFile
        Add-Content -Value "$($indents[6])^properties^: " -Path $jsonFile
        Add-Content -Value "$($indents[6]){" -Path $jsonFile
        Add-Content -Value "$($indents[7])^privateIPAddressVersion^:^IPv4^," -Path $jsonFile
        Add-Content -Value "$($indents[7])^loadBalancerBackendAddressPools^:" -Path $jsonFile
        Add-Content -Value "$($indents[7])[" -Path $jsonFile
        Add-Content -Value "$($indents[8]){" -Path $jsonFile
        Add-Content -Value "$($indents[9])^id^: ^[concat(variables('lbID'), '/backendAddressPools/BackendPoolIPv4')]^" -Path $jsonFile
        Add-Content -Value "$($indents[8])}" -Path $jsonFile
        Add-Content -Value "$($indents[7])]," -Path $jsonFile

        #region Enable InboundRules in NIC
        Add-Content -Value "$($indents[7])^loadBalancerInboundNatRules^:" -Path $jsonFile
        Add-Content -Value "$($indents[7])[" -Path $jsonFile
        $EndPointAdded = $false
        foreach ( $endpoint in $newVM.EndPoints) {
            if ( !($endpoint.LoadBalanced) -or ($endpoint.LoadBalanced -eq "False") ) {
                if ( $EndPointAdded ) {
                    Add-Content -Value "$($indents[8])," -Path $jsonFile
                }
                Add-Content -Value "$($indents[8]){" -Path $jsonFile
                Add-Content -Value "$($indents[9])^id^:^[concat(variables('lbID'),'/inboundNatRules/$vmName-$($endpoint.Name)')]^" -Path $jsonFile
                Add-Content -Value "$($indents[8])}" -Path $jsonFile
                Write-LogInfo "Enabled inboundNatRule Name:$vmName-$($endpoint.Name) frontendPort:$($endpoint.PublicPort) backendPort:$($endpoint.LocalPort) Protocol:$($endpoint.Protocol) to $NIC."
                $EndPointAdded = $true
            }
        }

        Add-Content -Value "$($indents[7])]," -Path $jsonFile
        #endregion

        Add-Content -Value "$($indents[7])^subnet^:" -Path $jsonFile
        Add-Content -Value "$($indents[7]){" -Path $jsonFile
        if ( $existingSubnet ) {
            Add-Content -Value "$($indents[8])^id^: ^[concat(variables('vnetID'),'/subnets/', '$existingSubnet')]^" -Path $jsonFile
        }
        else {
            Add-Content -Value "$($indents[8])^id^: ^[variables('defaultSubnetID')]^" -Path $jsonFile
        }
        Add-Content -Value "$($indents[7])}," -Path $jsonFile
        Add-Content -Value "$($indents[7])^privateIPAllocationMethod^: ^Dynamic^" -Path $jsonFile
        Add-Content -Value "$($indents[6])}" -Path $jsonFile
        Add-Content -Value "$($indents[5])}" -Path $jsonFile
        #endregion

        #region IPv6 Config...
        if ( $EnableIPv6 ) {
            Add-Content -Value "$($indents[5])," -Path $jsonFile
            Add-Content -Value "$($indents[5]){" -Path $jsonFile
            Add-Content -Value "$($indents[6])^name^: ^IPv6Config1^," -Path $jsonFile
            Add-Content -Value "$($indents[6])^properties^: " -Path $jsonFile
            Add-Content -Value "$($indents[6]){" -Path $jsonFile
            Add-Content -Value "$($indents[7])^privateIPAddressVersion^:^IPv6^," -Path $jsonFile
            Add-Content -Value "$($indents[7])^loadBalancerBackendAddressPools^:" -Path $jsonFile
            Add-Content -Value "$($indents[7])[" -Path $jsonFile
            Add-Content -Value "$($indents[8]){" -Path $jsonFile
            Add-Content -Value "$($indents[9])^id^: ^[concat(variables('lbID'), '/backendAddressPools/BackendPoolIPv6')]^" -Path $jsonFile
            Add-Content -Value "$($indents[8])}" -Path $jsonFile
            Add-Content -Value "$($indents[7])]," -Path $jsonFile
            Add-Content -Value "$($indents[7])^privateIPAllocationMethod^: ^Dynamic^" -Path $jsonFile
            Add-Content -Value "$($indents[6])}" -Path $jsonFile
            Add-Content -Value "$($indents[5])}" -Path $jsonFile
        }
        #endregion
        Add-Content -Value "$($indents[4])]" -Path $jsonFile
        if ($CurrentTestData.AdditionalHWConfig.Networking -imatch "SRIOV") {
            Add-Content -Value "$($indents[4])," -Path $jsonFile
            Add-Content -Value "$($indents[4])^enableAcceleratedNetworking^: true" -Path $jsonFile
            Write-LogInfo "Enabled Accelerated Networking."
        }
        Add-Content -Value "$($indents[3])}" -Path $jsonFile


        Add-Content -Value "$($indents[2])}," -Path $jsonFile
        Write-LogInfo "Added NIC $NIC.."
        #endregion

        #region multiple Nics
        [System.Collections.ArrayList]$NicNameList = @()
        foreach ($NetworkInterface in $newVM.NetworkInterfaces) {
            $NicName = $NetworkInterface.Name
            $NicNameList.add($NicName)
            Add-Content -Value "$($indents[2]){" -Path $jsonFile
            Add-Content -Value "$($indents[3])^apiVersion^: ^2016-09-01^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^type^: ^Microsoft.Network/networkInterfaces^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^name^: ^$NicName^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^dependsOn^: " -Path $jsonFile
            Add-Content -Value "$($indents[3])[" -Path $jsonFile
            Add-Content -Value "$($indents[4])^[concat('Microsoft.Network/virtualNetworks/', variables('virtualNetworkName'))]^," -Path $jsonFile
            Add-Content -Value "$($indents[4])^[variables('lbID')]^" -Path $jsonFile
            Add-Content -Value "$($indents[3])]," -Path $jsonFile

            Add-Content -Value "$($indents[3])^properties^:" -Path $jsonFile
            Add-Content -Value "$($indents[3]){" -Path $jsonFile
            Add-Content -Value "$($indents[4])^ipConfigurations^: " -Path $jsonFile
            Add-Content -Value "$($indents[4])[" -Path $jsonFile
            Add-Content -Value "$($indents[5]){" -Path $jsonFile
            Add-Content -Value "$($indents[6])^name^: ^IPv4Config1^," -Path $jsonFile
            Add-Content -Value "$($indents[6])^properties^: " -Path $jsonFile
            Add-Content -Value "$($indents[6]){" -Path $jsonFile
            Add-Content -Value "$($indents[7])^subnet^:" -Path $jsonFile
            Add-Content -Value "$($indents[7]){" -Path $jsonFile
            Add-Content -Value "$($indents[8])^id^: ^[variables('defaultSubnetID')]^" -Path $jsonFile
            Add-Content -Value "$($indents[7])}" -Path $jsonFile
            Add-Content -Value "$($indents[6])}" -Path $jsonFile
            Add-Content -Value "$($indents[5])}" -Path $jsonFile
            Add-Content -Value "$($indents[4])]" -Path $jsonFile
            if ($CurrentTestData.AdditionalHWConfig.Networking -imatch "SRIOV") {
                Add-Content -Value "$($indents[4])," -Path $jsonFile
                Add-Content -Value "$($indents[4])^enableAcceleratedNetworking^: true" -Path $jsonFile
                Write-LogInfo "Enabled Accelerated Networking for $NicName."
            }
            Add-Content -Value "$($indents[3])}" -Path $jsonFile
            Add-Content -Value "$($indents[2])}," -Path $jsonFile
        }

        #Add Bulk NICs
        $currentVMNics = 0
        while ($currentVMNics -lt $newVM.ExtraNICs) {
            $totalRGNics += 1
            $currentVMNics += 1
            $NicName = "ExtraNetworkCard-$currentVMNics-$($vmName)"
            $NicNameList.add($NicName)
            Add-Content -Value "$($indents[2]){" -Path $jsonFile
            Add-Content -Value "$($indents[3])^apiVersion^: ^2016-09-01^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^type^: ^Microsoft.Network/networkInterfaces^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^name^: ^$NicName^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^,"   -Path $jsonFile
            Add-Content -Value "$($indents[3])^dependsOn^: " -Path $jsonFile
            Add-Content -Value "$($indents[3])[" -Path $jsonFile
            Add-Content -Value "$($indents[4])^[concat('Microsoft.Network/virtualNetworks/', variables('virtualNetworkName'))]^," -Path $jsonFile
            Add-Content -Value "$($indents[4])^[variables('lbID')]^" -Path $jsonFile
            Add-Content -Value "$($indents[3])]," -Path $jsonFile

            Add-Content -Value "$($indents[3])^properties^:" -Path $jsonFile
            Add-Content -Value "$($indents[3]){" -Path $jsonFile
            Add-Content -Value "$($indents[4])^ipConfigurations^: " -Path $jsonFile
            Add-Content -Value "$($indents[4])[" -Path $jsonFile
            Add-Content -Value "$($indents[5]){" -Path $jsonFile
            Add-Content -Value "$($indents[6])^name^: ^IPv4Config1^," -Path $jsonFile
            Add-Content -Value "$($indents[6])^properties^: " -Path $jsonFile
            Add-Content -Value "$($indents[6]){" -Path $jsonFile
            Add-Content -Value "$($indents[7])^subnet^:" -Path $jsonFile
            Add-Content -Value "$($indents[7]){" -Path $jsonFile
            Add-Content -Value "$($indents[8])^id^: ^[concat(variables('vnetID'),'/subnets/', 'ExtraSubnet-$currentVMNics')]^" -Path $jsonFile
            Write-LogInfo "  $NicName is part of subnet - ExtraSubnet-$currentVMNics"
            Add-Content -Value "$($indents[7])}" -Path $jsonFile
            Add-Content -Value "$($indents[6])}" -Path $jsonFile
            Add-Content -Value "$($indents[5])}" -Path $jsonFile
            Add-Content -Value "$($indents[4])]" -Path $jsonFile
            if ($CurrentTestData.AdditionalHWConfig.Networking -imatch "SRIOV") {
                Add-Content -Value "$($indents[4])," -Path $jsonFile
                Add-Content -Value "$($indents[4])^enableAcceleratedNetworking^: true" -Path $jsonFile
                Write-LogInfo "  Enabled Accelerated Networking for $NicName."
            }
            Add-Content -Value "$($indents[3])}" -Path $jsonFile
            Add-Content -Value "$($indents[2])}," -Path $jsonFile
        }

        #endregion
        #region virtualMachines
        Write-LogInfo "Adding Virtual Machine $vmName"
        Add-Content -Value "$($indents[2]){" -Path $jsonFile
        Add-Content -Value "$($indents[3])^apiVersion^: ^2018-06-01^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^type^: ^Microsoft.Compute/virtualMachines^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^name^: ^$vmName^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
        if ($publisher -imatch "clear-linux-project") {
            Write-LogInfo "  Adding plan information for clear-linux.."
            Add-Content -Value "$($indents[3])^plan^:" -Path $jsonFile
            Add-Content -Value "$($indents[3]){" -Path $jsonFile
            Add-Content -Value "$($indents[4])^name^: ^$sku^," -Path $jsonFile
            Add-Content -Value "$($indents[4])^product^: ^clear-linux-os^," -Path $jsonFile
            Add-Content -Value "$($indents[4])^publisher^: ^clear-linux-project^" -Path $jsonFile
            Add-Content -Value "$($indents[3])}," -Path $jsonFile
        }
        Add-Content -Value "$($indents[3])^tags^: {^TestID^: ^$TestID^}," -Path $jsonFile
        Add-Content -Value "$($indents[3])^dependsOn^: " -Path $jsonFile
        Add-Content -Value "$($indents[3])[" -Path $jsonFile
        if (!$createAvailabilitySet) {
            #Add-Content -Value "$($indents[4])^[concat('Microsoft.Compute/availabilitySets/', variables('availabilitySetName'))]^," -Path $jsonFile
        }
        else {
            Add-Content -Value "$($indents[4])^[concat('Microsoft.Compute/availabilitySets/', variables('availabilitySetName'))]^," -Path $jsonFile
        }
        if ( $NewARMStorageAccountType) {
            Add-Content -Value "$($indents[4])^[concat('Microsoft.Storage/storageAccounts/', variables('StorageAccountName'))]^," -Path $jsonFile
        }
        if ( $OsVHD -and $UseManagedDisks ) {
            Add-Content -Value "$($indents[4])^[resourceId('Microsoft.Compute/images', '$RGName-Image')]^," -Path $jsonFile
        }

        if ($NicNameList) {
            foreach ($NicName in $NicNameList) {
                Add-Content -Value "$($indents[4])^[concat('Microsoft.Network/networkInterfaces/', '$NicName')]^," -Path $jsonFile
            }
        }
        Add-Content -Value "$($indents[4])^[concat('Microsoft.Network/networkInterfaces/', '$NIC')]^" -Path $jsonFile
        Add-Content -Value "$($indents[3])]," -Path $jsonFile

        #region VM Properties
        Add-Content -Value "$($indents[3])^properties^:" -Path $jsonFile
        Add-Content -Value "$($indents[3]){" -Path $jsonFile
        #region availabilitySet
        Add-Content -Value "$($indents[4])^availabilitySet^: " -Path $jsonFile
        Add-Content -Value "$($indents[4]){" -Path $jsonFile
        Add-Content -Value "$($indents[5])^id^: ^[resourceId('Microsoft.Compute/availabilitySets','$availabilitySetName')]^" -Path $jsonFile
        Add-Content -Value "$($indents[4])}," -Path $jsonFile
        #endregion

        #region Hardware Profile
        Add-Content -Value "$($indents[4])^hardwareProfile^: " -Path $jsonFile
        Add-Content -Value "$($indents[4]){" -Path $jsonFile
        Add-Content -Value "$($indents[5])^vmSize^: ^$instanceSize^" -Path $jsonFile
        Add-Content -Value "$($indents[4])}," -Path $jsonFile
        #endregion

        if ( !($UseSpecializedImage) ) {
            #region OSProfile
            Add-Content -Value "$($indents[4])^osProfile^: " -Path $jsonFile
            Add-Content -Value "$($indents[4]){" -Path $jsonFile
            Add-Content -Value "$($indents[5])^computername^: ^$vmName^," -Path $jsonFile
            Add-Content -Value "$($indents[5])^adminUsername^: ^[variables('adminUserName')]^," -Path $jsonFile
            Add-Content -Value "$($indents[5])^adminPassword^: ^[variables('adminPassword')]^" -Path $jsonFile
            #Add-Content -Value "$($indents[5])^linuxConfiguration^:" -Path $jsonFile
            #Add-Content -Value "$($indents[5]){" -Path $jsonFile
            #    Add-Content -Value "$($indents[6])^ssh^:" -Path $jsonFile
            #    Add-Content -Value "$($indents[6]){" -Path $jsonFile
            #        Add-Content -Value "$($indents[7])^publicKeys^:" -Path $jsonFile
            #        Add-Content -Value "$($indents[7])[" -Path $jsonFile
            #            Add-Content -Value "$($indents[8])[" -Path $jsonFile
            #                Add-Content -Value "$($indents[9]){" -Path $jsonFile
            #                    Add-Content -Value "$($indents[10])^path^:^$sshPath^," -Path $jsonFile
            #                    Add-Content -Value "$($indents[10])^keyData^:^$sshKeyData^" -Path $jsonFile
            #                Add-Content -Value "$($indents[9])}" -Path $jsonFile
            #            Add-Content -Value "$($indents[8])]" -Path $jsonFile
            #        Add-Content -Value "$($indents[7])]" -Path $jsonFile
            #    Add-Content -Value "$($indents[6])}" -Path $jsonFile
            #Add-Content -Value "$($indents[5])}" -Path $jsonFile
            Add-Content -Value "$($indents[4])}," -Path $jsonFile
            #endregion
        }
        #region Storage Profile
        Add-Content -Value "$($indents[4])^storageProfile^: " -Path $jsonFile
        Add-Content -Value "$($indents[4]){" -Path $jsonFile
        if ($ImageName -and !$osVHD) {
            Write-LogInfo ">>> Using ARMImage : $publisher : $offer : $sku : $version"
            Add-Content -Value "$($indents[5])^imageReference^ : " -Path $jsonFile
            Add-Content -Value "$($indents[5]){" -Path $jsonFile
            Add-Content -Value "$($indents[6])^publisher^: ^$publisher^," -Path $jsonFile
            Add-Content -Value "$($indents[6])^offer^: ^$offer^," -Path $jsonFile
            Add-Content -Value "$($indents[6])^sku^: ^$sku^," -Path $jsonFile
            Add-Content -Value "$($indents[6])^version^: ^$version^" -Path $jsonFile
            Add-Content -Value "$($indents[5])}," -Path $jsonFile
        }
        elseif ( $OsVHD -and $UseManagedDisks ) {
            Add-Content -Value "$($indents[5])^imageReference^ : " -Path $jsonFile
            Add-Content -Value "$($indents[5]){" -Path $jsonFile
            Add-Content -Value "$($indents[6])^id^: ^[resourceId('Microsoft.Compute/images', '$RGName-Image')]^," -Path $jsonFile
            Add-Content -Value "$($indents[5])}," -Path $jsonFile
        }
        Add-Content -Value "$($indents[5])^osDisk^ : " -Path $jsonFile
        Add-Content -Value "$($indents[5]){" -Path $jsonFile
        if ($osVHD) {
            $osVHD = $osVHD.Split('/')[-1]
            if ($UseManagedDisks) {
                Write-LogInfo ">>> Using VHD : $osVHD (Converted to Managed Image)"
                Add-Content -Value "$($indents[6])^osType^: ^Linux^," -Path $jsonFile
                Add-Content -Value "$($indents[6])^name^: ^$vmName-OSDisk^," -Path $jsonFile
                Add-Content -Value "$($indents[6])^managedDisk^: " -Path $jsonFile
                Add-Content -Value "$($indents[6]){" -Path $jsonFile
                Add-Content -Value "$($indents[7])^storageAccountType^: ^$StorageAccountType^" -Path $jsonFile

                Add-Content -Value "$($indents[6])}," -Path $jsonFile
                if ($UseEphemeralOSDisk) {
                    Add-Content -Value "$($indents[6])^caching^: ^ReadOnly^," -Path $jsonFile
                    Add-Content -Value "$($indents[6])^diffDiskSettings^: " -Path $jsonFile
                    Add-Content -Value "$($indents[6]){" -Path $jsonFile
                    Add-Content -Value "$($indents[7])^option^: ^local^" -Path $jsonFile
                    Add-Content -Value "$($indents[6])}," -Path $jsonFile
                }
                else {
                    Add-Content -Value "$($indents[6])^caching^: ^ReadWrite^," -Path $jsonFile
                }
                Add-Content -Value "$($indents[6])^createOption^: ^FromImage^" -Path $jsonFile
            }
            else {
                Write-LogInfo ">>> Using VHD : $osVHD"
                if ($UseSpecializedImage) {
                    $vhduri = "https://$StorageAccountName.blob.core.windows.net/vhds/$OsVHD"
                    $sourceContainer = $vhduri.Split("/")[$vhduri.Split("/").Count - 2]
                    $destVHDName = "$vmName-$RGrandomWord-osdisk.vhd"

                    $copyStatus = Copy-VHDToAnotherStorageAccount -sourceStorageAccount $StorageAccountName -sourceStorageContainer $sourceContainer -destinationStorageAccount $StorageAccountName -destinationStorageContainer "vhds" -vhdName $OsVHD -destVHDName $destVHDName
                    if (!$copyStatus) {
                        Throw "Failed to copy the VHD to $ARMStorageAccount"
                    } else {
                        Write-LogInfo "New Base VHD name - $destVHDName"
                    }
                    Add-Content -Value "$($indents[6])^osType^: ^Linux^," -Path $jsonFile
                    Add-Content -Value "$($indents[6])^name^: ^$vmName-OSDisk^," -Path $jsonFile
                    #Add-Content -Value "$($indents[6])^osType^: ^Linux^," -Path $jsonFile
                    Add-Content -Value "$($indents[6])^vhd^: " -Path $jsonFile
                    Add-Content -Value "$($indents[6]){" -Path $jsonFile
                    Add-Content -Value "$($indents[7])^uri^: ^[concat('http://',variables('StorageAccountName'),'.blob.core.windows.net/vhds/','$vmName-$RGrandomWord-osdisk.vhd')]^" -Path $jsonFile
                    Add-Content -Value "$($indents[6])}," -Path $jsonFile
                    Add-Content -Value "$($indents[6])^caching^: ^ReadWrite^," -Path $jsonFile
                    Add-Content -Value "$($indents[6])^createOption^: ^Attach^" -Path $jsonFile
                }
                else {
                    Add-Content -Value "$($indents[6])^image^: " -Path $jsonFile
                    Add-Content -Value "$($indents[6]){" -Path $jsonFile
                    Add-Content -Value "$($indents[7])^uri^: ^[concat('http://',variables('StorageAccountName'),'.blob.core.windows.net/vhds/','$osVHD')]^" -Path $jsonFile
                    Add-Content -Value "$($indents[6])}," -Path $jsonFile
                    Add-Content -Value "$($indents[6])^osType^: ^Linux^," -Path $jsonFile
                    Add-Content -Value "$($indents[6])^name^: ^$vmName-OSDisk^," -Path $jsonFile
                    #Add-Content -Value "$($indents[6])^osType^: ^Linux^," -Path $jsonFile
                    Add-Content -Value "$($indents[6])^vhd^: " -Path $jsonFile
                    Add-Content -Value "$($indents[6]){" -Path $jsonFile
                    Add-Content -Value "$($indents[7])^uri^: ^[concat('http://',variables('StorageAccountName'),'.blob.core.windows.net/vhds/','$vmName-$RGrandomWord-osdisk.vhd')]^" -Path $jsonFile
                    Add-Content -Value "$($indents[6])}," -Path $jsonFile
                    Add-Content -Value "$($indents[6])^caching^: ^ReadWrite^," -Path $jsonFile
                    Add-Content -Value "$($indents[6])^createOption^: ^FromImage^" -Path $jsonFile
                }
            }
        }
        else {
            if ($UseManagedDisks) {
                Add-Content -Value "$($indents[6])^name^: ^$vmName-OSDisk^," -Path $jsonFile
                Add-Content -Value "$($indents[6])^managedDisk^: " -Path $jsonFile
                Add-Content -Value "$($indents[6]){" -Path $jsonFile
                Add-Content -Value "$($indents[7])^storageAccountType^: ^$StorageAccountType^" -Path $jsonFile
                Add-Content -Value "$($indents[6])}," -Path $jsonFile
                if ($UseEphemeralOSDisk) {
                    Add-Content -Value "$($indents[6])^caching^: ^ReadOnly^," -Path $jsonFile
                    Add-Content -Value "$($indents[6])^diffDiskSettings^: " -Path $jsonFile
                    Add-Content -Value "$($indents[6]){" -Path $jsonFile
                    Add-Content -Value "$($indents[7])^option^: ^local^" -Path $jsonFile
                    Add-Content -Value "$($indents[6])}," -Path $jsonFile
                } else {
                    Add-Content -Value "$($indents[6])^caching^: ^ReadWrite^," -Path $jsonFile
                }
                Add-Content -Value "$($indents[6])^createOption^: ^FromImage^" -Path $jsonFile
            } else {
                Add-Content -Value "$($indents[6])^name^: ^$vmName-OSDisk^," -Path $jsonFile
                Add-Content -Value "$($indents[6])^createOption^: ^FromImage^," -Path $jsonFile
                Add-Content -Value "$($indents[6])^vhd^: " -Path $jsonFile
                Add-Content -Value "$($indents[6]){" -Path $jsonFile
                Add-Content -Value "$($indents[7])^uri^: ^[concat('http://',variables('StorageAccountName'),'.blob.core.windows.net/vhds/','$vmName-$RGrandomWord-osdisk.vhd')]^" -Path $jsonFile
                Add-Content -Value "$($indents[6])}," -Path $jsonFile
                Add-Content -Value "$($indents[6])^caching^: ^ReadWrite^" -Path $jsonFile
            }
        }
        Add-Content -Value "$($indents[5])}," -Path $jsonFile
        Write-LogInfo "Added $DiskType OS disk : $vmName-OSDisk"
        $dataDiskAdded = $false
        Add-Content -Value "$($indents[5])^dataDisks^ : " -Path $jsonFile
        Add-Content -Value "$($indents[5])[" -Path $jsonFile
        foreach ( $dataDisk in $newVM.DataDisk ) {
            if ( $dataDisk.LUN -ge 0 ) {
                if ( $dataDiskAdded ) {
                    Add-Content -Value "$($indents[6])," -Path $jsonFile
                }

                if ($UseManagedDisks) {
                    Add-Content -Value "$($indents[6]){" -Path $jsonFile
                    Add-Content -Value "$($indents[7])^name^: ^$vmName-disk-lun-$($dataDisk.LUN)^," -Path $jsonFile
                    Add-Content -Value "$($indents[7])^diskSizeGB^: ^$($dataDisk.DiskSizeInGB)^," -Path $jsonFile
                    Add-Content -Value "$($indents[7])^lun^: ^$($dataDisk.LUN)^," -Path $jsonFile
                    Add-Content -Value "$($indents[7])^createOption^: ^Empty^," -Path $jsonFile
                    Add-Content -Value "$($indents[7])^caching^: ^$($dataDisk.HostCaching)^," -Path $jsonFile
                    Add-Content -Value "$($indents[7])^managedDisk^:" -Path $jsonFile
                    Add-Content -Value "$($indents[7]){" -Path $jsonFile
                    Add-Content -Value "$($indents[8])^storageAccountType^: ^$StorageAccountType^" -Path $jsonFile
                    Add-Content -Value "$($indents[7])}" -Path $jsonFile
                    Add-Content -Value "$($indents[6])}" -Path $jsonFile
                    Write-LogInfo "Added managed $($dataDisk.DiskSizeInGB)GB Datadisk to $($dataDisk.LUN)."
                } else {
                    Add-Content -Value "$($indents[6]){" -Path $jsonFile
                    Add-Content -Value "$($indents[7])^name^: ^$vmName-disk-lun-$($dataDisk.LUN)^," -Path $jsonFile
                    Add-Content -Value "$($indents[7])^diskSizeGB^: ^$($dataDisk.DiskSizeInGB)^," -Path $jsonFile
                    Add-Content -Value "$($indents[7])^lun^: ^$($dataDisk.LUN)^," -Path $jsonFile
                    Add-Content -Value "$($indents[7])^createOption^: ^Empty^," -Path $jsonFile
                    Add-Content -Value "$($indents[7])^caching^: ^$($dataDisk.HostCaching)^," -Path $jsonFile
                    Add-Content -Value "$($indents[7])^vhd^:" -Path $jsonFile
                    Add-Content -Value "$($indents[7]){" -Path $jsonFile
                    Add-Content -Value "$($indents[8])^uri^: ^[concat('http://',variables('StorageAccountName'),'.blob.core.windows.net/vhds/','$vmName-$RGrandomWord-disk-lun-$($dataDisk.LUN).vhd')]^" -Path $jsonFile
                    Add-Content -Value "$($indents[7])}" -Path $jsonFile
                    Add-Content -Value "$($indents[6])}" -Path $jsonFile
                    Write-LogInfo "Added unmanaged $($dataDisk.DiskSizeInGB)GB Datadisk to $($dataDisk.LUN)."
                }

                $dataDiskAdded = $true
            }
        }
        Add-Content -Value "$($indents[5])]" -Path $jsonFile
        Add-Content -Value "$($indents[4])}" -Path $jsonFile

        Add-Content -Value "$($indents[4])," -Path $jsonFile
        #endregion

        Write-LogInfo "Added Virtual Machine $vmName"

        #region Network Profile
        Add-Content -Value "$($indents[4])^networkProfile^: " -Path $jsonFile
        Add-Content -Value "$($indents[4]){" -Path $jsonFile
        Add-Content -Value "$($indents[5])^networkInterfaces^: " -Path $jsonFile
        Add-Content -Value "$($indents[5])[" -Path $jsonFile
        #region configure multiple NICs to networkProfile
        if ($NicNameList) {
            foreach ($NicName in $NicNameList) {
                Add-Content -Value "$($indents[6]){" -Path $jsonFile
                Add-Content -Value "$($indents[7])^id^: ^[resourceId('Microsoft.Network/networkInterfaces','$NicName')]^," -Path $jsonFile
                Add-Content -Value "$($indents[7])^properties^: { ^primary^: false }" -Path $jsonFile
                Add-Content -Value "$($indents[6])}," -Path $jsonFile
                Write-LogInfo "Attached Network Interface Card `"$NicName`" to Virtual Machine `"$vmName`"."
            }
            Add-Content -Value "$($indents[6]){" -Path $jsonFile
            Add-Content -Value "$($indents[7])^id^: ^[resourceId('Microsoft.Network/networkInterfaces','$NIC')]^," -Path $jsonFile
            Add-Content -Value "$($indents[7])^properties^: { ^primary^: true }" -Path $jsonFile
            Add-Content -Value "$($indents[6])}" -Path $jsonFile
            Write-LogInfo "Attached Network Interface Card `"$NIC`" to Virtual Machine `"$vmName`"."
        } else {
            Add-Content -Value "$($indents[6]){" -Path $jsonFile
            Add-Content -Value "$($indents[7])^id^: ^[resourceId('Microsoft.Network/networkInterfaces','$NIC')]^" -Path $jsonFile
            Add-Content -Value "$($indents[6])}" -Path $jsonFile
        }
        #endregion
        Add-Content -Value "$($indents[5])]" -Path $jsonFile
        Add-Content -Value "$($indents[4])}" -Path $jsonFile


        #region Enable boot dignostics.
        Add-Content -Value "$($indents[4])," -Path $jsonFile
        Add-Content -Value "$($indents[4])^diagnosticsProfile^: " -Path $jsonFile
        Add-Content -Value "$($indents[4]){" -Path $jsonFile
        Add-Content -Value "$($indents[5])^bootDiagnostics^: " -Path $jsonFile
        Add-Content -Value "$($indents[5]){" -Path $jsonFile
        Add-Content -Value "$($indents[6])^enabled^: true," -Path $jsonFile
        Add-Content -Value "$($indents[6])^storageUri^: ^[reference(resourceId('$diagnosticRG', 'Microsoft.Storage/storageAccounts', '$bootDiagnosticsSA'), '2015-06-15').primaryEndpoints['blob']]^" -Path $jsonFile
        Add-Content -Value "$($indents[5])}" -Path $jsonFile
        Add-Content -Value "$($indents[4])}" -Path $jsonFile
        #endregion

        Add-Content -Value "$($indents[3])}" -Path $jsonFile
        #endregion

        Add-Content -Value "$($indents[2])}" -Path $jsonFile
        #endregion

        $vmAdded = $true
        $role = $role + 1
        $vmCount = $role
    }
    Add-Content -Value "$($indents[1])]" -Path $jsonFile

    #endregion

    Add-Content -Value "$($indents[0])}" -Path $jsonFile
    Set-Content -Path $jsonFile -Value (Get-Content $jsonFile).Replace("^", '"') -Force
    #endregion

    Write-LogInfo "Template generated successfully."
    return $createSetupCommand, $RGName, $vmCount
}

Function Create-RGDeploymentWithTempParameters([string]$RGName, $TemplateFile, $TemplateParameterFile) {
    $FailCounter = 0
    $retValue = "False"
    $ResourceGroupDeploymentName = "eosg" + (Get-Date).Ticks
    While (($retValue -eq $false) -and ($FailCounter -lt 1)) {
        try {
            $FailCounter++
            Write-LogInfo "Creating Deployment using $TemplateFile $TemplateParameterFile..."
            $createRGDeployment = New-AzureRmResourceGroupDeployment -Name $ResourceGroupDeploymentName -ResourceGroupName $RGName -TemplateFile $TemplateFile -TemplateParameterFile $TemplateParameterFile -Verbose
            $operationStatus = $createRGDeployment.ProvisioningState
            if ($operationStatus -eq "Succeeded") {
                Write-LogInfo "Resource Group Deployment Created."
                $retValue = $true
            } else {
                Write-LogErr "Failed to create Resource Group Deployment."
                $retValue = $false
            }
        }
        catch {
            $retValue = $false
        }
    }
    return $retValue
}

Function Create-AllRGDeploymentsWithTempParameters($templateName, $location, $TemplateFile, $TemplateParameterFile) {
    $resourceGroupCount = 0
    $isServiceDeployed = "False"
    $retryDeployment = 0
    $uniqueId = New-TimeBasedUniqueId
    $groupName = "LISAv2-" + $templateName + "-" + $uniqueId

    while (($isServiceDeployed -eq "False") -and ($retryDeployment -lt 3)) {
        Write-LogInfo "Creating Resource Group : $groupName."
        Write-LogInfo "Verifying that Resource group name is not in use."
        $isRGDeleted = Delete-ResourceGroup -RGName $groupName
        if ($isRGDeleted) {
            $isServiceCreated = Create-ResourceGroup -RGName $groupName -location $location
            if ($isServiceCreated -eq "True") {
                $DeploymentStartTime = (Get-Date)
                $CreateRGDeployments = Create-RGDeploymentWithTempParameters -RGName $groupName -location $location -TemplateFile $TemplateFile -TemplateParameterFile $TemplateParameterFile
                $DeploymentEndTime = (Get-Date)
                $DeploymentElapsedTime = $DeploymentEndTime - $DeploymentStartTime
                if ( $CreateRGDeployments ) {
                    $retValue = "True"
                    $isServiceDeployed = "True"
                    $resourceGroupCount = $resourceGroupCount + 1
                    $deployedGroups = $groupName
                } else {
                    Write-LogErr "Unable to Deploy one or more VM's"
                    $retryDeployment = $retryDeployment + 1
                    $retValue = "False"
                    $isServiceDeployed = "False"
                }
            } else {
                Write-LogErr "Unable to create $groupName"
                $retryDeployment = $retryDeployment + 1
                $retValue = "False"
                $isServiceDeployed = "False"
            }
        } else {
            Write-LogErr "Unable to delete existing resource group - $groupName"
            $retryDeployment = $retryDeployment + 1
            $retValue = "False"
            $isServiceDeployed = "False"
        }
    }
    return $retValue, $deployedGroups, $resourceGroupCount, $DeploymentElapsedTime
}


Function Copy-VHDToAnotherStorageAccount ($sourceStorageAccount, $sourceStorageContainer, $destinationStorageAccount, $destinationStorageContainer, $vhdName, $destVHDName, $SasUrl) {
    $retValue = $false
    if (!$destVHDName) {
        $destVHDName = $vhdName
    }
    $saInfoCollected = $false
    $retryCount = 0
    $maxRetryCount = 999
    while (!$saInfoCollected -and ($retryCount -lt $maxRetryCount)) {
        try {
            $retryCount += 1
            Write-LogInfo "[Attempt $retryCount/$maxRetryCount] : Getting Existing Storage Account details ..."
            $GetAzureRmStorageAccount = $null
            $GetAzureRmStorageAccount = Get-AzureRmStorageAccount
            if ($GetAzureRmStorageAccount -eq $null) {
                throw
            }
            $saInfoCollected = $true
        }
        catch {
            $saInfoCollected = $false
            Write-LogErr "Error in fetching Storage Account info. Retrying in 10 seconds."
            Start-Sleep -Seconds 10
        }
    }

    if ( !$SasUrl ) {
        Write-LogInfo "Retrieving $sourceStorageAccount storage account key"
        $SrcStorageAccountKey = (Get-AzureRmStorageAccountKey -ResourceGroupName $(($GetAzureRmStorageAccount  | Where-Object {$_.StorageAccountName -eq "$sourceStorageAccount"}).ResourceGroupName) -Name $sourceStorageAccount)[0].Value
        [string]$SrcStorageAccount = $sourceStorageAccount
        [string]$SrcStorageBlob = $vhdName
        $SrcStorageContainer = $sourceStorageContainer
        $context = New-AzureStorageContext -StorageAccountName $srcStorageAccount -StorageAccountKey $srcStorageAccountKey
        $expireTime = Get-Date
        $expireTime = $expireTime.AddYears(1)
        $SasUrl = New-AzureStorageBlobSASToken -container $srcStorageContainer -Blob $srcStorageBlob -Permission R -ExpiryTime $expireTime -FullUri -Context $Context
}

    Write-LogInfo "Retrieving $destinationStorageAccount storage account key"
    $DestAccountKey = (Get-AzureRmStorageAccountKey -ResourceGroupName $(($GetAzureRmStorageAccount  | Where-Object {$_.StorageAccountName -eq "$destinationStorageAccount"}).ResourceGroupName) -Name $destinationStorageAccount)[0].Value
    [string]$DestAccountName = $destinationStorageAccount
    [string]$DestBlob = $destVHDName
    $DestContainer = $destinationStorageContainer

    $destContext = New-AzureStorageContext -StorageAccountName $destAccountName -StorageAccountKey $destAccountKey
    $testContainer = Get-AzureStorageContainer -Name $destContainer -Context $destContext -ErrorAction Ignore
    if ($testContainer -eq $null) {
        $null = New-AzureStorageContainer -Name $destContainer -context $destContext
    }
    # Start the Copy
    Write-LogInfo "Copy $vhdName --> $($destContext.StorageAccountName) : Running"
    $null = Start-AzureStorageBlobCopy -AbsoluteUri $SasUrl  -DestContainer $destContainer -DestContext $destContext -DestBlob $destBlob -Force
    #
    # Monitor replication status
    #
    $CopyingInProgress = $true
    while ($CopyingInProgress) {
        $CopyingInProgress = $false
        $status = Get-AzureStorageBlobCopyState -Container $destContainer -Blob $destBlob -Context $destContext
        if ($status.Status -ne "Success") {
            $CopyingInProgress = $true
        } else {
            Write-LogInfo "Copy $DestBlob --> $($destContext.StorageAccountName) : Done"
            $retValue = $true

        }
        if ($CopyingInProgress) {
            $copyPercentage = [math]::Round( $(($status.BytesCopied * 100 / $status.TotalBytes)) , 2 )
            Write-LogInfo "Bytes Copied:$($status.BytesCopied), Total Bytes:$($status.TotalBytes) [ $copyPercentage % ]"
            Start-Sleep -Seconds 10
        }
    }
    return $retValue
}

Function Set-SRIOVinAzureVMs {
    param (
        [object]$AllVMData,
        [string]$VMNames, #... Optional
        [switch]$Enable,
        [switch]$Disable)
    try {
        Function Check-CurrentNICStatus () {
            if ($Enable) {
                if ($AllNics.Count -eq 1) {
                    if ($AllNics.EnableAcceleratedNetworking -eq $true) {
                        $StatusChangeNotRequired = $true
                    }
                } else {
                    if (-not $AllNics.EnableAcceleratedNetworking.Contains($false)) {
                        $StatusChangeNotRequired = $true
                    }
                }
            }
            if ($Disable) {
                if ($AllNics.Count -eq 1) {
                    if ($AllNics.EnableAcceleratedNetworking -eq $false) {
                        $StatusChangeNotRequired = $true
                    }
                } else {
                    if (-not $AllNics.EnableAcceleratedNetworking.Contains($true)) {
                        $StatusChangeNotRequired = $true
                    }
                }
            }
            return $StatusChangeNotRequired
        }

        if ( $Enable -and $Disable ) {
            Throw "Please mention either -Enable or -Disable. Don't use both switches."
        }

        $TargettedVMs = @()
        $SuccessCount = 0
        if ($VMNames) {
            $VMNames = $VMNames.Trim()
            foreach ($vmData in $AllVMData) {
                if ($VMNames.Contains($vmData.RoleName)) {
                    $TargettedVMs += $vmData
                }
            }
        } else {
            $TargettedVMs += $AllVMData
        }

        foreach ( $TargetVM in $TargettedVMs) {
            $VMName = $TargetVM.RoleName
            $ResourceGroup = $TargetVM.ResourceGroupName
            $AllNics = Get-AzureRmNetworkInterface -ResourceGroupName $ResourceGroup `
                | Where-Object { $($_.VirtualMachine.Id | Split-Path -leaf) -eq $VMName }

            if ($Enable) {
                $DesiredState = "Enabled"
                if (Check-CurrentNICStatus) {
                    Write-LogInfo "Accelerated networking is already enabled for all nics in $VMName."
                    $retValue = $true
                    $VMPropertiesChanged = $false
                } else {
                    $TargettedNics = $AllNics | Where-Object { $_.EnableAcceleratedNetworking -eq $false}
                    Write-LogInfo "Current Accelerated networking disabled NICs : $($TargettedNics.Name)"
                    Write-LogInfo "Shutting down $VMName..."
                    $null = Stop-AzureRmVM -ResourceGroup $ResourceGroup -Name $VMName -Force
                    foreach ($TargetNic in $TargettedNics) {
                        #Enable EnableAccelerated Networking
                        $TargetNic.EnableAcceleratedNetworking = $true
                        $ChangedNic = $TargetNic | Set-AzureRmNetworkInterface
                        $VMPropertiesChanged = $true
                        if ( $ChangedNic.EnableAcceleratedNetworking -eq $true) {
                            Write-LogInfo "$($TargetNic.Name) [EnableAcceleratedNetworking=true]| Set-AzureRmNetworkInterface : SUCCESS"
                        } else {
                            Write-LogInfo "$($TargetNic.Name) [EnableAcceleratedNetworking=true]| Set-AzureRmNetworkInterface : FAIL"
                        }
                    }
                }
            }
            if ($Disable) {
                $DesiredState = "Disabled"
                if (Check-CurrentNICStatus) {
                    Write-LogInfo "Accelerated networking is already disabled for all nics in $VMName."
                    $retValue = $true
                    $VMPropertiesChanged = $false
                } else {
                    $TargettedNics = $AllNics | Where-Object { $_.EnableAcceleratedNetworking -eq $true}
                    Write-LogInfo "Current Accelerated networking enabled NICs : $($TargettedNics.Name)"
                    Write-LogInfo "Shutting down $VMName..."
                    $null = Stop-AzureRmVM -ResourceGroup $ResourceGroup -Name $VMName -Force
                    foreach ($TargetNic in $TargettedNics) {
                        #Enable EnableAccelerated Networking
                        $TargetNic.EnableAcceleratedNetworking = $false
                        $ChangedNic = $TargetNic | Set-AzureRmNetworkInterface
                        $VMPropertiesChanged = $true
                        if ( $ChangedNic.EnableAcceleratedNetworking -eq $false) {
                            Write-LogInfo "$($TargetNic.Name) [EnableAcceleratedNetworking=false] | Set-AzureRmNetworkInterface : SUCCESS"
                        } else {
                            Write-LogInfo "$($TargetNic.Name) [EnableAcceleratedNetworking=false] | Set-AzureRmNetworkInterface : FAIL"
                        }
                    }
                }
            }

            if ( $VMPropertiesChanged ) {
                # Start the VM..
                Write-LogInfo "Starting VM $($VMName)..."
                $null = Start-AzureRmVM -ResourceGroup $ResourceGroup -Name $VMName

                # Public IP address changes most of the times, when we shutdown the VM.
                # Hence, we need to refresh the data
                $VMData = Get-AllDeploymentData -ResourceGroups $ResourceGroup
                $TestVMData = $VMData | Where-Object {$_.ResourceGroupName -eq $ResourceGroup `
                    -and $_.RoleName -eq $VMName }

                $isVmAlive = Is-VmAlive -AllVMDataObject $TestVMData
                if ($isVmAlive -eq "True") {
                    $isRestarted = $true
                }
                else {
                    Write-LogErr "VM $VMName is not available after restart"
                    $isRestarted = $false
                }
                # refresh $AllVMData
                $VMCount = 1
                if ($AllVMData.Count) {
                    $VMCount = $AllVMData.Count
                }
                for ($i = 0; $i -lt $VMCount; $i++) {
                    if ($AllVMData[$i].RoleName -eq $TestVMData.RoleName -and $AllVMData[$i].ResourceGroupName -eq $TestVMData.ResourceGroupName) {
                        $AllVMData[$i].PublicIP = $TestVMData.PublicIP
                    }
                }

                $AllNics = Get-AzureRmNetworkInterface -ResourceGroupName $ResourceGroup `
                    | Where-Object { $($_.VirtualMachine.Id | Split-Path -leaf) -eq $VMName }
                if ($Enable) {
                    if (Check-CurrentNICStatus) {
                        Write-LogInfo "Accelerated Networking successfully enabled for all NICs in $VMName."
                        $NicVerified = $true
                    } else {
                        Write-LogInfo "Accelerated Networking failed to enable for all/some NICs in $VMName."
                        $NicVerified = $false
                    }
                }
                if ($Disable) {
                    if (Check-CurrentNICStatus) {
                        Write-LogInfo "Accelerated Networking successfully disabled for all NICs in $VMName."
                        $NicVerified = $true
                    } else {
                        Write-LogInfo "Accelerated Networking failed to disable for all/some NICs in $VMName."
                        $NicVerified = $false
                    }
                }
                if ($isRestarted -and $NicVerified) {
                    $SuccessCount += 1
                    Write-LogInfo "Accelerated Networking '$DesiredState' successfully for $VMName"
                } else {
                    Write-LogErr "Accelerated Networking '$DesiredState' failed for $VMName"
                }
            } else {
                Write-LogInfo "Accelerated Networking is already '$DesiredState' for $VMName."
                $SuccessCount += 1
            }
        }
        if ( $TargettedVMs.Count -eq $SuccessCount ) {
            $retValue = $true
        } else {
            $retValue = $false
        }
    }
    catch {
        $retValue = $false
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION : $ErrorMessage at line: $ErrorLine"
    }
    return $retValue
}

Function Add-ResourceGroupTag {
    param (
        [Parameter(Mandatory = $true)]
        [string] $ResourceGroup,
        [Parameter(Mandatory = $true)]
        [string] $TagName,
        [Parameter(Mandatory = $true)]
        [string] $TagValue
    )
    try {
        Write-LogInfo "Setting $ResourceGroup tag : $TagName = $TagValue"
        $ExistingTags = (Get-AzureRmResourceGroup -Name $ResourceGroup).Tags
        if ( $ExistingTags.Keys.Count -gt 0 ) {
            $ExistingKeyUpdated = $false
            foreach ($Key in $ExistingTags.Keys) {
                if ($Key -eq $TagName) {
                    $ExistingTags.$Key = $TagValue
                    $ExistingKeyUpdated = $true
                    break;
                }
            }
            $hash = $ExistingTags
            if ( -not $ExistingKeyUpdated) {
                $hash.Add($TagName, $TagValue)
            }
        } else {
            $hash = @{}
            $hash.Add($TagName, $TagValue)
        }
        Set-AzureRmResourceGroup -Name $ResourceGroup -Tag $hash | Out-Null
    }
    catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION in Add-ResourceGroupTag() : $ErrorMessage at line: $ErrorLine"
    }
}

Function Add-DefaultTagsToResourceGroup {
    param (
        [Parameter(Mandatory = $true)]
        [string] $ResourceGroup,
        [object] $CurrentTestData
    )
    try {
        # Add jenkins username if available or add username of current windows account.
        if ($env:BUILD_USER) {
            $UserTag = $env:BUILD_USER
        } else {
            $UserTag = $env:UserName
        }
        Add-ResourceGroupTag -ResourceGroup $ResourceGroup -TagName BuildUser -TagValue $UserTag
        # Add jenkins build url if available.
        if ($env:BUILD_URL) {
            $BuildURLTag = $env:BUILD_URL
        } else {
            $BuildURLTag = "NA"
        }
        Add-ResourceGroupTag -ResourceGroup $ResourceGroup -TagName BuildURL -TagValue $BuildURLTag
        # Add test name.
        Add-ResourceGroupTag -ResourceGroup $ResourceGroup -TagName TestName -TagValue $currentTestData.testName
        # Add LISAv2 launch machine name.
        Add-ResourceGroupTag -ResourceGroup $ResourceGroup -TagName BuildMachine -TagValue "$env:UserDomain\$env:ComputerName"
        # Add date-time.
        $Time = $(((Get-Date).ToUniversalTime()).ToString("yyyy/MM/dd HH:mm:ss"))
        Add-ResourceGroupTag -ResourceGroup $ResourceGroup -TagName CreationTime -TagValue "$Time"
    }
    catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION in Add-DefaultTagsToResourceGroup() : $ErrorMessage at line: $ErrorLine"
    }
}

function Get-AzureBootDiagnostics {
    <#
    .SYNOPSIS
        Downloads the associated serial console boot logs for an Azure VM (if any).
    #>
    param(
        $Vm,
        $BootDiagnosticFile
    )

    Write-LogInfo "Getting Azure boot diagnostic data of VM $($Vm.RoleName)"
    $vmStatus = Get-AzureRmVm -ResourceGroupName $Vm.ResourceGroupName -VMName $Vm.RoleName -Status
    if ($vmStatus -and $vmStatus.BootDiagnostics) {
        if ($vmStatus.BootDiagnostics.SerialConsoleLogBlobUri) {
            Write-LogInfo "Getting serial boot logs of VM $($Vm.RoleName)"
            try {
                $uri = [System.Uri]$vmStatus.BootDiagnostics.SerialConsoleLogBlobUri
                $storageAccountName = $uri.Host.Split(".")[0]
                $diagnosticRG = ((Get-AzureRmStorageAccount) | Where-Object {$_.StorageAccountName -eq $storageAccountName}).ResourceGroupName.ToString()
                $key = (Get-AzureRmStorageAccountKey -ResourceGroupName $diagnosticRG -Name $storageAccountName)[0].value
                $diagContext = New-AzureStorageContext -StorageAccountName $storageAccountName -StorageAccountKey $key
                Get-AzureStorageBlobContent -Blob $uri.LocalPath.Split("/")[2] `
                    -Context $diagContext -Container $uri.LocalPath.Split("/")[1] `
                    -Destination $BootDiagnosticFile -Force | Out-Null
            } catch {
                Write-LogInfo $_
                return $false
            }
            return $true
        }
    }
    return $false
}

function Check-AzureVmKernelPanic {
    <#
    .SYNOPSIS
        Downloads the Azure Boot diagnostics and checks if they contain kernel panic or RIPs.
    #>
    param(
        $Vm
    )

    $bootDiagnosticFile = "$LogDir\$($vm.RoleName)-SSH-Fail-Boot-Logs.txt"
    $diagStatus = Get-AzureBootDiagnostics -Vm $vm -BootDiagnosticFile $bootDiagnosticFile
    if ($diagStatus -and (Test-Path $bootDiagnosticFile)) {
        $diagFileContent = Get-Content $bootDiagnosticFile
        if ($diagFileContent -like "*Kernel panic - not syncing:*" -or $diagFileContent -like "*RIP:*") {
            return $true
        }
    }
    return $false
}

Function Get-StorageAccountFromRegion($Region,$StorageAccount)
{
#region Select Storage Account Type
    $RegionName = $Region.Replace(" ","").Replace('"',"").ToLower()
    $regionStorageMapping = [xml](Get-Content .\XML\RegionAndStorageAccounts.xml)
    if ($StorageAccount) {
        if ( $StorageAccount -imatch "ExistingStorage_Standard" ) {
            $StorageAccountName = $regionStorageMapping.AllRegions.$RegionName.StandardStorage
        }
        elseif ( $StorageAccount -imatch "ExistingStorage_Premium" )
        {
            $StorageAccountName = $regionStorageMapping.AllRegions.$RegionName.PremiumStorage
        }
        elseif ( $StorageAccount -imatch "NewStorage_Standard" )
        {
            $StorageAccountName = "NewStorage_Standard_LRS"
        }
        elseif ( $StorageAccount -imatch "NewStorage_Premium" )
        {
            $StorageAccountName = "NewStorage_Premium_LRS"
        }
        elseif ($StorageAccount -eq "")
        {
            $StorageAccountName = $regionStorageMapping.AllRegions.$RegionName.StandardStorage
        }
    } else {
        $StorageAccountName = $regionStorageMapping.AllRegions.$RegionName.StandardStorage
    }
    Write-LogInfo "Selected : $StorageAccountName"
    return $StorageAccountName
}

function Add-AzureAccountFromSecretsFile {
    param(
        $CustomSecretsFilePath
    )

    if ($env:Azure_Secrets_File) {
        $secretsFile = $env:Azure_Secrets_File
        Write-LogInfo "Using secrets file: $secretsFile, defined in environments."
    } elseif ( $CustomSecretsFilePath ) {
        $secretsFile = $CustomSecretsFilePath
        Write-LogInfo "Using provided secrets file: $secretsFile"
    }

    if ( ($null -eq $secretsFile) -or ($secretsFile -eq [string]::Empty)) {
        Write-LogErr "ERROR: The Secrets file is not being set."
        Raise-Exception ("XML Secrets file not provided")
    }

    if ( Test-Path $secretsFile ) {
        Write-LogInfo "$secretsFile found."
        Write-LogInfo "------------------------------------------------------------------"
        Write-LogInfo "Authenticating Azure PS session.."
        $XmlSecrets = [xml](Get-Content $secretsFile)
        $ClientID = $XmlSecrets.secrets.SubscriptionServicePrincipalClientID
        $TenantID = $XmlSecrets.secrets.SubscriptionServicePrincipalTenantID
        $Key = $XmlSecrets.secrets.SubscriptionServicePrincipalKey
        $pass = ConvertTo-SecureString $key -AsPlainText -Force
        $mycred = New-Object System.Management.Automation.PSCredential ($ClientID, $pass)
        $subIDSplitted = ($XmlSecrets.secrets.SubscriptionID).Split("-")
        $subIDMasked = "$($subIDSplitted[0])-xxxx-xxxx-xxxx-$($subIDSplitted[4])"

        $null = Add-AzureRmAccount -ServicePrincipal -Tenant $TenantID -Credential $mycred
        $selectedSubscription = Select-AzureRmSubscription -SubscriptionId $XmlSecrets.secrets.SubscriptionID
        if ( $selectedSubscription.Subscription.Id -eq $XmlSecrets.secrets.SubscriptionID ) {
            Write-LogInfo "Current Subscription : $subIDMasked."
        } else {
            Write-LogInfo "There was an error when selecting $subIDMasked."
        }
        Write-LogInfo "------------------------------------------------------------------"
    } else {
        Write-LogErr "Secret file $secretsFile does not exist"
        Raise-Exception ("XML Secrets file not provided")
    }
}
