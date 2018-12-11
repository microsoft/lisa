##############################################################################################
# Azure.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for Azure test automation

.PARAMETER
	<Parameters>

.INPUTS


.NOTES
    Creation Date:
    Purpose/Change:

.EXAMPLE


#>
###############################################################################################

Function Validate-SubscriptionUsage($subscriptionID, $RGXMLData) {
    #region VM Cores...
    Try {
        Function Set-Usage($currentStatus, $text, $usage, $AllowedUsagePercentage) {
            $counter = 0
            foreach ($item in $currentStatus) {
                if ($item.Name.Value -eq $text) {
                    $allowedCount = [int](($currentStatus[$counter].Limit) * ($AllowedUsagePercentage / 100))
                    Write-LogInfo "  Current $text usage : $($currentStatus[$counter].CurrentValue) cores. Requested:$usage. Estimated usage=$($($currentStatus[$counter].CurrentValue) + $usage). Max Allowed cores:$allowedCount/$(($currentStatus[$counter].Limit))"
                    #Write-LogInfo "Current VM Core Estimated use: $($currentStatus[$counter].CurrentValue) + $usage = $($($currentStatus[$counter].CurrentValue) + $usage) VM cores."
                    $currentStatus[$counter].CurrentValue = $currentStatus[$counter].CurrentValue + $usage
                }
                if ($item.Name.Value -eq "cores") {
                    $allowedCount = [int](($currentStatus[$counter].Limit) * ($AllowedUsagePercentage / 100))
                    Write-LogInfo "  Current Regional Cores usage : $($currentStatus[$counter].CurrentValue) cores. Requested:$usage. Estimated usage=$($($currentStatus[$counter].CurrentValue) + $usage). Max Allowed cores:$allowedCount/$(($currentStatus[$counter].Limit))"
                    #Write-LogInfo "Current VM Core Estimated use: $($currentStatus[$counter].CurrentValue) + $usage = $($($currentStatus[$counter].CurrentValue) + $usage) VM cores."
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
                    if ($currentStatus[$counter].CurrentValue -le $allowedCount) {

                    }
                    else {
                        Write-LogErr "  Current $text Estimated use: $($currentStatus[$counter].CurrentValue)"
                        $overFlowErrors += 1
                    }
                }
                if ($item.Name.Value -eq "cores") {
                    $allowedCount = [int](($currentStatus[$counter].Limit) * ($AllowedUsagePercentage / 100))
                    #Write-LogInfo "Max allowed $($item.Name.LocalizedValue) usage : $allowedCount out of $(($currentStatus[$counter].Limit))."
                    if ($currentStatus[$counter].CurrentValue -le $allowedCount) {

                    }
                    else {
                        Write-LogErr "  Current Regional Cores Estimated use: $($currentStatus[$counter].CurrentValue)"
                        $overFlowErrors += 1
                    }
                }
                $counter++
            }
            return $overFlowErrors
        }
        #Get the region
        $Location = ($xmlConfig.config.$TestPlatform.General.Location).Replace('"', "").Replace(' ', "").ToLower()
        $AllowedUsagePercentage = 100
        $currentStatus = Get-AzureRmVMUsage -Location $Location
        $overFlowErrors = 0
        $premiumVMs = 0
        $vmCounter = 0
        foreach ($VM in $RGXMLData.VirtualMachine) {
            $vmCounter += 1


            Write-LogInfo "Estimating VM #$vmCounter usage."
            if ($OverrideVMSize) {
                $testVMSize = $overrideVMSize
            }
            elseif ( $CurrentTestData.OverrideVMSize) {
                $testVMSize = $CurrentTestData.OverrideVMSize
            }
            else {
                $testVMSize = $VM.ARMInstanceSize
            }

            if (($OverrideVMSize -or $CurrentTestData.OverrideVMSize) -and ($testVMUsage -gt 0)) {
                #Do nothing.
            }
            else {
                $testVMUsage = (Get-AzureRmVMSize -Location $Location | Where { $_.Name -eq $testVMSize}).NumberOfCores
            }


            $testVMSize = $testVMSize.Replace("Standard_", "")

            #region D-Series
            if ( $testVMSize.StartsWith("DS") -and $testVMSize.EndsWith("v2")) {
                $identifierText = "standardDSv2Family"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
                $premiumVMs += 1
            }
            elseif ( $testVMSize.StartsWith("D") -and $testVMSize.EndsWith("s_v3")) {
                $identifierText = "standardDSv3Family"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
                $premiumVMs += 1
            }
            elseif ( $testVMSize.StartsWith("DS") -and !$testVMSize.EndsWith("v2") -and !$testVMSize.EndsWith("v3")) {
                $identifierText = "standardDSFamily"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
                $premiumVMs += 1
            }
            elseif ( $testVMSize.StartsWith("D") -and !$testVMSize.StartsWith("DS") -and $testVMSize.EndsWith("v2")) {
                $identifierText = "standardDv2Family"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            elseif ( $testVMSize.StartsWith("D") -and !$testVMSize.EndsWith("s_v3") -and $testVMSize.EndsWith("v3")) {
                $identifierText = "standardDv3Family"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            elseif ( $testVMSize.StartsWith("D") -and !$testVMSize.StartsWith("DS") -and !$testVMSize.EndsWith("v2") -and !$testVMSize.EndsWith("v3")) {
                $identifierText = "standardDFamily"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            #endregion

            #region E-Series
            elseif ( $testVMSize.StartsWith("E") -and $testVMSize.EndsWith("s_v3")) {
                $identifierText = "standardESv3Family"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
                $premiumVMs += 1
            }
            elseif ( $testVMSize.StartsWith("E") -and !$testVMSize.EndsWith("s_v3") -and $testVMSize.EndsWith("v3")) {
                $identifierText = "standardEv3Family"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            #endregion

            #region Standard A series

            elseif ( ( $testVMSize -eq "A8") -or ( $testVMSize -eq "A9") -or ( $testVMSize -eq "A10") -or ( $testVMSize -eq "A11") ) {
                $identifierText = "standardA8_A11Family"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            elseif ( $testVMSize.StartsWith("A") -and $testVMSize.EndsWith("v2")) {
                $identifierText = "standardAv2Family"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            elseif ( $testVMSize.StartsWith("A") -and !$testVMSize.EndsWith("v2")) {
                $identifierText = "standardA0_A7Family"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            #endregion

            #region Standard F series
            elseif ( $testVMSize.StartsWith("FS")) {
                $identifierText = "standardFSFamily"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
                $premiumVMs += 1
            }
            elseif ( $testVMSize.StartsWith("F")) {
                $identifierText = "standardFFamily"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            elseif ( $testVMSize.StartsWith("GS")) {
                $identifierText = "standardGSFamily"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
                $premiumVMs += 1
            }
            elseif ( $testVMSize.StartsWith("G")) {
                $identifierText = "standardGFamily"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            elseif ( $testVMSize.StartsWith("NV")) {
                $identifierText = "standardNVFamily"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            elseif (  $testVMSize.StartsWith("NC") -and $testVMSize.EndsWith("v2") ) {
                $identifierText = "standardNCv2Family"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            elseif ( $testVMSize.StartsWith("NC")) {
                $identifierText = "standardNCFamily"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            elseif ( $testVMSize.StartsWith("ND")) {
                $identifierText = "standardNDFamily"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            elseif ( $testVMSize.StartsWith("H")) {
                $identifierText = "standardHFamily"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            elseif ( $testVMSize.StartsWith("Basic")) {
                $identifierText = "basicAFamily"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            #region M-Series
            elseif ( $testVMSize.StartsWith("M")) {
                $identifierText = "standardMSFamily"
                $currentStatus = Set-Usage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage
            }
            #endregion

            else {
                Write-LogInfo "Requested VM size: $testVMSize is not yet registered to monitor. Usage simulation skipped."
            }
            #endregion
        }

        #Check the max core quota

        #Get the current usage for current region
        #$currentStorageAccounts = (Get-AzureRmStorageAccount).Count

        #Decide

    }
    catch {
        $line = $_.InvocationInfo.ScriptLineNumber
        $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
        $ErrorMessage = $_.Exception.Message
        Write-LogErr "EXCEPTION : $ErrorMessage"
        Write-LogErr "Source : Line $line in script $script_name."
    }

    #endregion


    #region Storage Accounts
    Write-LogInfo "Estimating storage account usage..."
    $currentStorageStatus = Get-AzureRmStorageUsage
    if ( ($premiumVMs -gt 0 ) -and ($xmlConfig.config.$TestPlatform.General.StorageAccount -imatch "NewStorage_")) {
        $requiredStorageAccounts = 1
    }
    elseif ( ($premiumVMs -gt 0 ) -and !($xmlConfig.config.$TestPlatform.General.StorageAccount -imatch "NewStorage_")) {
        $requiredStorageAccounts = 1
    }
    elseif ( !($premiumVMs -gt 0 ) -and !($xmlConfig.config.$TestPlatform.General.StorageAccount -imatch "NewStorage_")) {
        $requiredStorageAccounts = 0
    }

    $allowedStorageCount = [int]($currentStorageStatus.Limit * ($AllowedUsagePercentage / 100))


    if (($currentStorageStatus.CurrentValue + $requiredStorageAccounts) -le $allowedStorageCount) {
        Write-LogInfo "Current Storage Accounts usage:$($currentStorageStatus.CurrentValue). Requested:$requiredStorageAccounts. Estimated usage:$($currentStorageStatus.CurrentValue + $requiredStorageAccounts). Maximum allowed:$allowedStorageCount/$(($currentStorageStatus.Limit))."
    }
    else {
        Write-LogErr "Current Storage Accounts usage:$($currentStorageStatus.CurrentValue). Requested:$requiredStorageAccounts. Estimated usage:$($currentStorageStatus.CurrentValue + $requiredStorageAccounts). Maximum allowed:$allowedStorageCount/$(($currentStorageStatus.Limit))."
        $overFlowErrors += 1
    }
    #endregion

    $GetAzureRmNetworkUsage = Get-AzureRmNetworkUsage -Location $Location
    #region Public IP Addresses
    $PublicIPs = $GetAzureRmNetworkUsage | Where-Object { $_.Name.Value -eq "PublicIPAddresses" }
    Write-LogInfo "Current Public IPs usage:$($PublicIPs.CurrentValue). Requested: 1. Estimated usage:$($PublicIPs.CurrentValue + 1). Maximum allowed: $($PublicIPs.Limit)."
    if (($PublicIPs.CurrentValue + 1) -gt $PublicIPs.Limit) {
        $overFlowErrors += 1
    }
    #endregion
    #region Virtual networks
    $VNETs = $GetAzureRmNetworkUsage | Where-Object { $_.Name.Value -eq "VirtualNetworks" }
    Write-LogInfo "Current VNET usage:$($VNETs.CurrentValue). Requested: 1. Estimated usage:$($VNETs.CurrentValue + 1). Maximum allowed: $($VNETs.Limit)."
    if (($VNETs.CurrentValue + 1) -gt $VNETs.Limit) {
        $overFlowErrors += 1
    }
    #endregion
    #region Network Security Groups
    $SGs = $GetAzureRmNetworkUsage | Where-Object { $_.Name.Value -eq "NetworkSecurityGroups" }
    Write-LogInfo "Current Security Group usage:$($SGs.CurrentValue). Requested: 1. Estimated usage:$($SGs.CurrentValue + 1). Maximum allowed: $($SGs.Limit)."
    if (($SGs.CurrentValue + 1) -gt $SGs.Limit) {
        $overFlowErrors += 1
    }
    #endregion
    #region Load Balancers
    $LBs = $GetAzureRmNetworkUsage | Where-Object { $_.Name.Value -eq "LoadBalancers" }
    Write-LogInfo "Current Load Balancer usage:$($LBs.CurrentValue). Requested: 1. Estimated usage:$($LBs.CurrentValue + 1). Maximum allowed: $($LBs.Limit)."
    if (($LBs.CurrentValue + 1) -gt $LBs.Limit) {
        $overFlowErrors += 1
    }
    #endregion


    if ($overFlowErrors -eq 0) {
        Write-LogInfo "Estimated subscription usage is under allowed limits."
        return $true
    }
    else {
        Write-LogErr "Estimated subscription usage exceeded allowed limits."
        return $false
    }
}

Function Create-AllResourceGroupDeployments($setupType, $xmlConfig, $Distro, [string]$region = "", $DebugRG = "") {
    if ($DebugRG) {
        return "True", $DebugRG, 1, 180
    }
    else {
        $resourceGroupCount = 0
        Write-LogInfo "Current test setup: $setupType"
        $setupTypeData = $xmlConfig.config.$TestPlatform.Deployment.$setupType
        $allsetupGroups = $setupTypeData
        if ($allsetupGroups.ResourceGroup[0].Location -or $allsetupGroups.ResourceGroup[0].AffinityGroup) {
            $isMultiple = 'True'
            $resourceGroupCount = 0
        }
        else {
            $isMultiple = 'False'
        }
        $OsVHD = $BaseOsVHD
        $location = $xmlConfig.config.$TestPlatform.General.Location
        if ($region) {
            $location = $region;
        }

        if ( $location -imatch "-" ) {
            $RGCount = $setupTypeData.ResourceGroup.Count
            $xRegionTest = $true
            $xRegionLocations = $location.Split("-")
            $locationCounter = 0
            Write-LogInfo "$RGCount Resource groups will be deployed in $($xRegionLocations.Replace('-',' and '))"
        }
        foreach ($RG in $setupTypeData.ResourceGroup ) {
            $validateStartTime = Get-Date
            Write-LogInfo "Checking the subscription usage..."
            $readyToDeploy = $false
            while (!$readyToDeploy) {
                $readyToDeploy = Validate-SubscriptionUsage -subscriptionID $xmlConfig.config.$TestPlatform.General.SubscriptionID -RGXMLData $RG
                $validateCurrentTime = Get-Date
                $elapsedWaitTime = ($validateCurrentTime - $validateStartTime).TotalSeconds
                if ( (!$readyToDeploy) -and ($elapsedWaitTime -lt $CoreCountExceededTimeout)) {
                    $waitPeriod = Get-Random -Minimum 1 -Maximum 10 -SetSeed (Get-Random)
                    Write-LogInfo "Timeout in approx. $($CoreCountExceededTimeout - $elapsedWaitTime) seconds..."
                    Write-LogInfo "Waiting $waitPeriod minutes..."
                    sleep -Seconds ($waitPeriod * 60)
                }
                if ( $elapsedWaitTime -gt $CoreCountExceededTimeout ) {
                    break
                }
            }
            if ($readyToDeploy) {
                $curtime = ([string]((Get-Date).Ticks / 1000000)).Split(".")[0]
                $isServiceDeployed = "False"
                $retryDeployment = 0
                if ( $null -ne $RG.Tag ) {
                    $groupName = "ICA-RG-" + $RG.Tag + "-" + $Distro + "-" + "$TestID-" + "$curtime"
                }
                else {
                    $groupName = "ICA-RG-" + $setupType + "-" + $Distro + "-" + "$TestID-" + "$curtime"
                }
                if ($isMultiple -eq "True") {
                    $groupName = $groupName + "-" + $resourceGroupCount
                }
                while (($isServiceDeployed -eq "False") -and ($retryDeployment -lt 1)) {
                    if ($ExistingRG) {

                        $isServiceCreated = "True"
                        Write-LogInfo "Detecting $ExistingRG region..."
                        $location = (Get-AzureRmResourceGroup -Name $ExistingRG).Location
                        Write-LogInfo "Region: $location..."
                        $groupName = $ExistingRG
                        Write-LogInfo "Using existing Resource Group : $ExistingRG"
                        if ($CleanupExistingRG) {
                            Write-LogInfo "CleanupExistingRG flag is Set. All resources except availibility set will be cleaned."
                            Write-LogInfo "If you do not wish to cleanup $ExistingRG, abort NOW. Sleeping 10 Seconds."
                            Sleep 10
                            $isRGDeleted = Delete-ResourceGroup -RGName $groupName
                        }
                        else {
                            $isRGDeleted = $true
                        }
                    }
                    else {
                        Write-LogInfo "Creating Resource Group : $groupName."
                        Write-LogInfo "Verifying that Resource group name is not in use."
                        $isRGDeleted = Delete-ResourceGroup -RGName $groupName
                    }
                    if ($isRGDeleted) {
                        if ( $xRegionTest ) {
                            $location = $xRegionLocations[$locationCounter]
                            $locationCounter += 1
                        }
                        else {
                            $isServiceCreated = Create-ResourceGroup -RGName $groupName -location $location
                        }
                        if ($isServiceCreated -eq "True") {
                            $azureDeployJSONFilePath = Join-Path $env:TEMP "$groupName.json"
                            $null = Generate-AzureDeployJSONFile -RGName $groupName -osImage $osImage -osVHD $osVHD -RGXMLData $RG -Location $location -azuredeployJSONFilePath $azureDeployJSONFilePath
                            $DeploymentStartTime = (Get-Date)
                            $CreateRGDeployments = Create-ResourceGroupDeployment -RGName $groupName -location $location -setupType $setupType -TemplateFile $azureDeployJSONFilePath
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
                    }
                    else {
                        Write-LogErr "Unable to delete existing resource group - $groupName"
                        $retryDeployment = 3
                        $retValue = "False"
                        $isServiceDeployed = "False"
                    }
                }
            }
            else {
                Write-LogErr "Core quota is not sufficient. Stopping VM deployment."
                $retValue = "False"
                $isServiceDeployed = "False"
            }
        }
        return $retValue, $deployedGroups, $resourceGroupCount, $DeploymentElapsedTime
    }

}

Function Delete-ResourceGroup([string]$RGName, [switch]$KeepDisks) {
    Write-LogInfo "Try to delete resource group $RGName ..."
    try {
        Write-LogInfo "Checking if $RGName exists ..."
        $ResourceGroup = Get-AzureRmResourceGroup -Name $RGName -ErrorAction Ignore
    }
    catch {
        Write-LogInfo "Failed to get resource group: $RGName; maybe this resource group does not exist."
    }
    if ($ResourceGroup) {
        if ($ExistingRG) {
            $CurrentResources = @()
            $CurrentResources += Get-AzureRmResource | Where-Object {$_.ResourceGroupName -eq $ResourceGroup.ResourceGroupName}
            while ( $CurrentResources.Count -ne 1 ) {
                foreach ($resource in $CurrentResources) {
                    Write-Host $resource.ResourceType
                    if ( $resource.ResourceType -imatch "availabilitySets" ) {
                        Write-LogInfo "Skipping $($resource.ResourceName)"
                    }
                    else {
                        Write-LogInfo "Removing $($resource.ResourceName)"
                        try {
                            $null = Remove-AzureRmResource -ResourceId $resource.ResourceId -Force -Verbose
                        }
                        catch {
                            Write-LogErr "Error. We will try to remove this in next attempt."
                        }

                    }
                }
                $CurrentResources = @()
                $CurrentResources += Get-AzureRmResource | Where {$_.ResourceGroupName -eq $ResourceGroup.ResourceGroupName}
            }
            Write-LogInfo "$($ResourceGroup.ResourceGroupName) is cleaned."
            $retValue = $?
        }
        else {
            if ( $XmlSecrets.secrets.AutomationRunbooks.CleanupResourceGroupRunBook ) {
                $parameters = $parameters = @{"NAMEFILTER" = "$RGName"; "PREVIEWMODE" = $false};
                $CleanupRG = Get-AzureRmResourceGroup  -Name $XmlSecrets.secrets.AutomationRunbooks.ResourceGroupName -ErrorAction SilentlyContinue
            }
            if ($CleanupRG) {
                $rubookJob = Start-AzureRmAutomationRunbook -Name $XmlSecrets.secrets.AutomationRunbooks.CleanupResourceGroupRunBook -Parameters $parameters -AutomationAccountName $XmlSecrets.secrets.AutomationRunbooks.AutomationAccountName -ResourceGroupName $XmlSecrets.secrets.AutomationRunbooks.ResourceGroupName
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

Function Remove-ResidualResourceGroupVHDs($ResourceGroup, $storageAccount) {
    # Verify that the OS VHD does not already exist

    $azureStorage = $storageAccount
    Write-LogInfo "Removing residual VHDs of $ResourceGroup from $azureStorage..."
    $storageContext = (Get-AzureRmStorageAccount | Where-Object {$_.StorageAccountName -match $azureStorage}).Context
    $storageBlob = Get-AzureStorageBlob -Context $storageContext -Container "vhds"
    $vhdList = $storageBlob | Where-Object {$_.Name -match "$ResourceGroup"}
    if ($vhdList) {
        # Remove VHD files
        foreach ($diskName in $vhdList.Name) {
            Write-LogInfo "Removing VHD $diskName"
            Remove-AzureStorageBlob -Blob $diskname -Container vhds -Context $storageContext -Verbose -ErrorAction SilentlyContinue
        }
    }
}
Function Create-ResourceGroup([string]$RGName, $location) {
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
                Write-LogInfo "Resource Group $RGName Created."
                Add-DefaultTagsToResourceGroup -ResourceGroup $RGName
                $retValue = $true
            }
            else {
                Write-LogErr "Failed to create Resource Group: $RGName."
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

Function Create-ResourceGroupDeployment([string]$RGName, $location, $setupType, $TemplateFile) {
    $FailCounter = 0
    $retValue = "False"
    $ResourceGroupDeploymentName = "eosg" + (Get-Date).Ticks
    While (($retValue -eq $false) -and ($FailCounter -lt 1)) {
        try {
            $FailCounter++
            if ($location) {
                Write-LogInfo "Creating Deployment using $TemplateFile ..."
                $createRGDeployment = New-AzureRmResourceGroupDeployment -Name $ResourceGroupDeploymentName -ResourceGroupName $RGName -TemplateFile $TemplateFile -Verbose
            }
            $operationStatus = $createRGDeployment.ProvisioningState
            if ($operationStatus -eq "Succeeded") {
                Write-LogInfo "Resource Group Deployment Created."
                $retValue = $true
            }
            else {
                $retValue = $false
                Write-LogErr "Failed to create Resource Group - $RGName."
                if ($ForceDeleteResources) {
                    Write-LogInfo "-ForceDeleteResources is Set. Deleting $RGName."
                    $isCleaned = Delete-ResourceGroup -RGName $RGName
                    if (!$isCleaned) {
                        Write-LogInfo "Cleanup unsuccessful for $RGName.. Please delete the services manually."
                    }
                    else {
                        Write-LogInfo "Cleanup Successful for $RGName.."
                    }
                }
                else {
                    $VMsCreated = Get-AzureRmVM -ResourceGroupName $RGName
                    if ( $VMsCreated ) {
                        Write-LogInfo "Keeping Failed resource group, as we found $($VMsCreated.Count) VM(s) deployed."
                    }
                    else {
                        Write-LogInfo "Removing Failed resource group, as we found 0 VM(s) deployed."
                        $isCleaned = Delete-ResourceGroup -RGName $RGName
                        if (!$isCleaned) {
                            Write-LogInfo "Cleanup unsuccessful for $RGName.. Please delete the services manually."
                        }
                        else {
                            Write-LogInfo "Cleanup Successful for $RGName.."
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

Function Get-NewVMName ($namePrefix, $numberOfVMs) {
    if ($IsWindows) {
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

Function Generate-AzureDeployJSONFile ($RGName, $osImage, $osVHD, $RGXMLData, $Location, $azuredeployJSONFilePath) {

    #Random Data
    $RGrandomWord = ([System.IO.Path]::GetRandomFileName() -replace '[^a-z]')
    $RGRandomNumber = Get-Random -Minimum 11111 -Maximum 99999
    if ( $CurrentTestData.AdditionalHWConfig.DiskType -eq "Managed" -or $UseManagedDisks ) {
        if ( $CurrentTestData.AdditionalHWConfig.DiskType -eq "Managed" ) {
            $UseManageDiskForCurrentTest = $true
        }
        $DiskType = "Managed"
    }
    else {
        $UseManageDiskForCurrentTest = $false
        $DiskType = "Unmanaged"
    }
    if ( $CurrentTestData.AdditionalHWConfig.OSDiskType -eq "Ephemeral" ) {
        if ( $UseManageDiskForCurrentTest ) {
            $UseEphemeralOSDisk = $true
            $DiskType += "-Ephemeral"
        }
        else {
            Throw "Invalid VM configuration. Ephemeral disks can only be created using Managed disk option."
        }
    }
    else {
        $DiskType += "-Persistant"
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
            sleep -Seconds 10
            $saInfoCollected = $false
        }
    }

    $StorageAccountName = $xmlConfig.config.$TestPlatform.General.ARMStorageAccount
    #Condition Existing Storage - NonManaged disks
    if ( $StorageAccountName -inotmatch "NewStorage" -and !$UseManagedDisks -and !$UseManageDiskForCurrentTest) {
        $StorageAccountType = ($GetAzureRMStorageAccount | where {$_.StorageAccountName -eq $StorageAccountName}).Sku.Tier.ToString()
        if ($StorageAccountType -match 'Premium') {
            $StorageAccountType = "Premium_LRS"
        }
        else {
            $StorageAccountType = "Standard_LRS"
        }
        Write-LogInfo "Storage Account Type : $StorageAccountType"
        Set-Variable -Name StorageAccountTypeGlobal -Value $StorageAccountType -Scope Global
    }

    #Condition Existing Storage - Managed Disks
    if ( $StorageAccountName -inotmatch "NewStorage" -and ($UseManagedDisks -or $UseManageDiskForCurrentTest)) {
        $StorageAccountType = ($GetAzureRMStorageAccount | where {$_.StorageAccountName -eq $StorageAccountName}).Sku.Tier.ToString()
        if ($StorageAccountType -match 'Premium') {
            $StorageAccountType = "Premium_LRS"
        }
        else {
            $StorageAccountType = "Standard_LRS"
        }
        Set-Variable -Name StorageAccountTypeGlobal -Value $StorageAccountType -Scope Global
    }


    #Condition New Storage - NonManaged disk
    if ( $StorageAccountName -imatch "NewStorage" -and !$UseManagedDisks -and !$UseManageDiskForCurrentTest) {
        $NewARMStorageAccountType = ($StorageAccountName).Replace("NewStorage_", "")
        Set-Variable -Name StorageAccountTypeGlobal -Value $NewARMStorageAccountType  -Scope Global
        $StorageAccountName = $($NewARMStorageAccountType.ToLower().Replace("_", "")) + "$RGRandomNumber"
        $NewStorageAccountName = $StorageAccountName
        Write-LogInfo "Using New ARM Storage Account : $StorageAccountName"
        $StorageAccountType = $NewARMStorageAccountType
    }

    #Condition New Storage - Managed disk
    if ( $StorageAccountName -imatch "NewStorage" -and ($UseManagedDisks -or $UseManageDiskForCurrentTest)) {
        Set-Variable -Name StorageAccountTypeGlobal -Value ($StorageAccountName).Replace("NewStorage_", "")  -Scope Global
        Write-LogInfo "Conflicting parameters - NewStorage and UseManagedDisks. Storage account will not be created."
    }
    #Region Define all Variables.


    Write-LogInfo "Generating Template : $azuredeployJSONFilePath"
    $jsonFile = $azuredeployJSONFilePath


    if ($ARMImage -and !$osVHD) {
        $publisher = $ARMImage.Publisher
        $offer = $ARMImage.Offer
        $sku = $ARMImage.Sku
        $version = $ARMImage.Version
    }
    elseif ($CurrentTestData.Publisher -and $CurrentTestData.Offer) {
        $publisher = $CurrentTestData.Publisher
        $offer = $CurrentTestData.Offer
        $sku = $CurrentTestData.Sku
        $version = $CurrentTestData.Version
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
    #$availabilitySetName = $($RGName.ToUpper() -replace '[^a-z]') + "AvSet"
    $availibilitySetName = "AvailibilitySet"
    #$LoadBalancerName =  $($RGName.ToUpper() -replace '[^a-z]') + "LoadBalancer"
    $LoadBalancerName = "LoadBalancer"
    $apiVersion = "2018-04-01"
    #$PublicIPName = $($RGName.ToUpper() -replace '[^a-z]') + "PublicIPv4"
    $PublicIPName = "PublicIPv4-$RGRandomNumber"
    #$PublicIPv6Name = $($RGName.ToUpper() -replace '[^a-z]') + "PublicIPv6"
    $PublicIPv6Name = "PublicIPv6"
    $sshPath = '/home/' + $user + '/.ssh/authorized_keys'
    $sshKeyData = ""
    if ($ExistingRG) {
        $customAVSetName = (Get-AzureRmResource | Where { (( $_.ResourceGroupName -eq $RGName ) -and ( $_.ResourceType -imatch "availabilitySets" ))}).ResourceName
    }
    else {
        $availibilitySetName = "AvailibilitySet"
        $customAVSetName = $availibilitySetName
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
                sleep -Milliseconds 1
            }
        }
    }



    #Create Managed OS Disks for all VMs using OSVHD.



    Write-LogInfo "Using API VERSION : $apiVersion"
    $ExistingVnet = $null
    if ($RGXMLData.ARMVnetName -ne $null) {
        $ExistingVnet = $RGXMLData.ARMVnetName
        Write-LogInfo "Getting $ExistingVnet Virtual Netowrk info ..."
        $ExistingVnetResourceGroupName = ( Get-AzureRmResource | Where {$_.Name -eq $ExistingVnet}).ResourceGroupName
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
    Add-Content -Value "$($indents[2])^vmSourceImageName^ : ^$osImage^," -Path $jsonFile
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
    if ($ExistingRG) {
        Add-Content -Value "$($indents[2])^availabilitySetName^: ^$customAVSetName^," -Path $jsonFile
    }
    else {
        Add-Content -Value "$($indents[2])^availabilitySetName^: ^$availibilitySetName^," -Path $jsonFile
    }
    Add-Content -Value "$($indents[2])^lbName^: ^$LoadBalancerName^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^lbID^: ^[resourceId('Microsoft.Network/loadBalancers',variables('lbName'))]^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^frontEndIPv4ConfigID^: ^[concat(variables('lbID'),'/frontendIPConfigurations/LoadBalancerFrontEndIPv4')]^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^frontEndIPv6ConfigID^: ^[concat(variables('lbID'),'/frontendIPConfigurations/LoadBalancerFrontEndIPv6')]^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^lbIPv4PoolID^: ^[concat(variables('lbID'),'/backendAddressPools/BackendPoolIPv4')]^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^lbIPv6PoolID^: ^[concat(variables('lbID'),'/backendAddressPools/BackendPoolIPv6')]^," -Path $jsonFile
    Add-Content -Value "$($indents[2])^lbProbeID^: ^[concat(variables('lbID'),'/probes/tcpProbe')]^" -Path $jsonFile
    #Add more variables here, if required..
    #Add more variables here, if required..
    #Add more variables here, if required..
    #Add more variables here, if required..
    Add-Content -Value "$($indents[1])}," -Path $jsonFile
    Write-LogInfo "Added Variables.."

    #endregion

    #region Define Resources
    Add-Content -Value "$($indents[1])^resources^:" -Path $jsonFile
    Add-Content -Value "$($indents[1])[" -Path $jsonFile

    #region Common Resources for all deployments..

    #region availabilitySets
    if ($ExistingRG) {
        Write-LogInfo "Using existing Availibility Set: $customAVSetName"
    }
    else {
        Add-Content -Value "$($indents[2]){" -Path $jsonFile
        Add-Content -Value "$($indents[3])^apiVersion^: ^$apiVersion^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^type^: ^Microsoft.Compute/availabilitySets^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^name^: ^[variables('availabilitySetName')]^," -Path $jsonFile
        Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
        if ($UseManagedDisks -or ($UseManageDiskForCurrentTest)) {
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
        Write-LogInfo "Added availabilitySet $availibilitySetName.."
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
    if ($OsVHD -and ($UseManagedDisks -or $UseManageDiskForCurrentTest)) {
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
    $diagnosticRG = ($GetAzureRMStorageAccount | where {$_.StorageAccountName -eq $bootDiagnosticsSA}).ResourceGroupName.ToString()
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
        if ( $OverrideVMSize ) {
            $instanceSize = $OverrideVMSize
        }
        elseif ( $CurrentTestData.OverrideVMSize) {
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
        if ($EnableAcceleratedNetworking -or $CurrentTestData.AdditionalHWConfig.Networking -imatch "SRIOV") {
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
            if ($EnableAcceleratedNetworking -or $CurrentTestData.AdditionalHWConfig.Networking -imatch "SRIOV") {
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
            if ($EnableAcceleratedNetworking -or $CurrentTestData.AdditionalHWConfig.Networking -imatch "SRIOV") {
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
        if ($ExistingRG) {
            #Add-Content -Value "$($indents[4])^[concat('Microsoft.Compute/availabilitySets/', variables('availabilitySetName'))]^," -Path $jsonFile
        }
        else {
            Add-Content -Value "$($indents[4])^[concat('Microsoft.Compute/availabilitySets/', variables('availabilitySetName'))]^," -Path $jsonFile
        }
        if ( $NewARMStorageAccountType) {
            Add-Content -Value "$($indents[4])^[concat('Microsoft.Storage/storageAccounts/', variables('StorageAccountName'))]^," -Path $jsonFile
        }
        if ( $OsVHD -and ($UseManagedDisks -or $UseManageDiskForCurrentTest) ) {
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
        Add-Content -Value "$($indents[5])^id^: ^[resourceId('Microsoft.Compute/availabilitySets','$customAVSetName')]^" -Path $jsonFile
        Add-Content -Value "$($indents[4])}," -Path $jsonFile
        #endregion

        #region Hardware Profile
        Add-Content -Value "$($indents[4])^hardwareProfile^: " -Path $jsonFile
        Add-Content -Value "$($indents[4]){" -Path $jsonFile
        Add-Content -Value "$($indents[5])^vmSize^: ^$instanceSize^" -Path $jsonFile
        Add-Content -Value "$($indents[4])}," -Path $jsonFile
        #endregion

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

        #region Storage Profile
        Add-Content -Value "$($indents[4])^storageProfile^: " -Path $jsonFile
        Add-Content -Value "$($indents[4]){" -Path $jsonFile
        if ($ARMImage -and !$osVHD) {
            Write-LogInfo ">>> Using ARMImage : $($ARMImage.Publisher):$($ARMImage.Offer):$($ARMImage.Sku):$($ARMImage.Version)"
            Add-Content -Value "$($indents[5])^imageReference^ : " -Path $jsonFile
            Add-Content -Value "$($indents[5]){" -Path $jsonFile
            Add-Content -Value "$($indents[6])^publisher^: ^$publisher^," -Path $jsonFile
            Add-Content -Value "$($indents[6])^offer^: ^$offer^," -Path $jsonFile
            Add-Content -Value "$($indents[6])^sku^: ^$sku^," -Path $jsonFile
            Add-Content -Value "$($indents[6])^version^: ^$version^" -Path $jsonFile
            Add-Content -Value "$($indents[5])}," -Path $jsonFile
        }
        elseif ($CurrentTestData.Publisher -and $CurrentTestData.Offer) {
            Add-Content -Value "$($indents[5])^imageReference^ : " -Path $jsonFile
            Add-Content -Value "$($indents[5]){" -Path $jsonFile
            Add-Content -Value "$($indents[6])^publisher^: ^$publisher^," -Path $jsonFile
            Add-Content -Value "$($indents[6])^offer^: ^$offer^," -Path $jsonFile
            Add-Content -Value "$($indents[6])^sku^: ^$sku^," -Path $jsonFile
            Add-Content -Value "$($indents[6])^version^: ^$version^" -Path $jsonFile
            Add-Content -Value "$($indents[5])}," -Path $jsonFile
        }
        elseif ( $OsVHD -and ($UseManagedDisks -or $UseManageDiskForCurrentTest) ) {
            Add-Content -Value "$($indents[5])^imageReference^ : " -Path $jsonFile
            Add-Content -Value "$($indents[5]){" -Path $jsonFile
            Add-Content -Value "$($indents[6])^id^: ^[resourceId('Microsoft.Compute/images', '$RGName-Image')]^," -Path $jsonFile
            Add-Content -Value "$($indents[5])}," -Path $jsonFile
        }
        Add-Content -Value "$($indents[5])^osDisk^ : " -Path $jsonFile
        Add-Content -Value "$($indents[5]){" -Path $jsonFile
        if ($osVHD) {
            if ($UseManagedDisks -or $UseManageDiskForCurrentTest) {
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
        else {
            if ($UseManagedDisks -or $UseManageDiskForCurrentTest) {
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

                if ($UseManagedDisks -or $UseManageDiskForCurrentTest) {
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
                }
                else {
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
        }
        else {
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

Function Deploy-ResourceGroups ($xmlConfig, $setupType, $Distro, $getLogsIfFailed = $false, $GetDeploymentStatistics = $false, [string]$region = "") {
    try {
        $VerifiedGroups = $NULL
        $retValue = $NULL
        $isAllDeployed = Create-AllResourceGroupDeployments -setupType $setupType -xmlConfig $xmlConfig -Distro $Distro -region $region
        $isAllConnected = "False"
        if ($isAllDeployed[0] -eq "True") {
            $deployedGroups = $isAllDeployed[1]
            $DeploymentElapsedTime = $isAllDeployed[3]
            $global:allVMData = Get-AllDeploymentData -ResourceGroups $deployedGroups
            $isAllConnected = Check-SSHPortsEnabled -AllVMDataObject $allVMData
            if ($isAllConnected -eq "True") {
                $VerifiedGroups = $deployedGroups
                $retValue = $VerifiedGroups
                if ( Test-Path -Path  .\Extras\UploadDeploymentDataToDB.ps1 ) {
                    $null = .\Extras\UploadDeploymentDataToDB.ps1 -allVMData $allVMData -DeploymentTime $DeploymentElapsedTime.TotalSeconds
                }
            }
            else {
                Write-LogErr "Unable to connect SSH ports.."
                $retValue = $NULL
            }
        }
        else {
            Write-LogErr "One or More Deployments are Failed..!"
            $retValue = $NULL
        }
    }
    catch {
        Write-LogInfo "Exception detected. Source : Deploy-ResourceGroups()"
        $line = $_.InvocationInfo.ScriptLineNumber
        $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
        $ErrorMessage = $_.Exception.Message
        Write-LogErr "EXCEPTION : $ErrorMessage"
        Write-LogErr "Source : Line $line in script $script_name."
        $retValue = $NULL
    }
    if ( $GetDeploymentStatistics ) {
        return $retValue, $DeploymentElapsedTime
    }
    else {
        return $retValue
    }
}

Function Check-SSHPortsEnabled($AllVMDataObject) {
    Write-LogInfo "Trying to Connect to deployed VM(s)"
    $timeout = 0
    do {
        $WaitingForConnect = 0
        foreach ( $vm in $AllVMDataObject) {
            if ($IsWindows) {
                $port = $($vm.RDPPort)
            }
            else {
                $port = $($vm.SSHPort)
            }

            $out = Test-TCP  -testIP $($vm.PublicIP) -testport $port
            if ($out -ne "True") {
                Write-LogInfo "Connecting to  $($vm.PublicIP) : $port : Failed"
                $WaitingForConnect = $WaitingForConnect + 1
            }
            else {
                Write-LogInfo "Connecting to  $($vm.PublicIP) : $port : Connected"
            }
        }

        if ($WaitingForConnect -gt 0) {
            $timeout = $timeout + 1
            Write-LogInfo "$WaitingForConnect VM(s) still awaiting to open port $port .."
            Write-LogInfo "Retry $timeout/20"
            sleep 3
            $retValue = "False"
        } else {
            Write-LogInfo "ALL VM's port $port is/are open now.."
            $retValue = "True"
        }

    } While (($timeout -lt 20) -and ($WaitingForConnect -gt 0))

	if ($retValue -eq "False") {
		foreach ($vm in $AllVMDataObject) {
			$out = Test-TCP -testIP $($vm.PublicIP) -testport $port
			if ($out -ne "True") {
				Write-LogInfo "Getting boot diagnostic data of VM $($vm.RoleName)"
				$vmStatus = Get-AzureRmVm -ResourceGroupName $vm.ResourceGroupName -VMName $vm.RoleName -Status
				if ($vmStatus -and $vmStatus.BootDiagnostics) {
					if ($vmStatus.BootDiagnostics.SerialConsoleLogBlobUri) {
						Write-LogInfo "Getting serial boot logs of VM $($vm.RoleName)"
						$uri = [System.Uri]$vmStatus.BootDiagnostics.SerialConsoleLogBlobUri
						$storageAccountName = $uri.Host.Split(".")[0]
						$diagnosticRG = ((Get-AzureRmStorageAccount) | where {$_.StorageAccountName -eq $storageAccountName}).ResourceGroupName.ToString()
						$key = (Get-AzureRmStorageAccountKey -ResourceGroupName $diagnosticRG -Name $storageAccountName)[0].value
						$diagContext = New-AzureStorageContext -StorageAccountName $storageAccountName -StorageAccountKey $key
						Get-AzureStorageBlobContent -Blob $uri.LocalPath.Split("/")[2] `
							-Context $diagContext -Container $uri.LocalPath.Split("/")[1] `
							-Destination "$LogDir\$($vm.RoleName)-SSH-Fail-Boot-Logs.txt"
					}
				}
			}
		}
    }

    return $retValue
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
            }
            else {
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
    $curtime = Get-Date
    $isServiceDeployed = "False"
    $retryDeployment = 0
    $groupName = "ICA-RG-" + $templateName + "-" + $curtime.Month + "-" + $curtime.Day + "-" + $curtime.Hour + "-" + $curtime.Minute + "-" + $curtime.Second

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
        }
        else {
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
            sleep -Seconds 10
        }
    }

    if ( !$SasUrl ) {
        Write-LogInfo "Retrieving $sourceStorageAccount storage account key"
        $SrcStorageAccountKey = (Get-AzureRmStorageAccountKey -ResourceGroupName $(($GetAzureRmStorageAccount  | Where {$_.StorageAccountName -eq "$sourceStorageAccount"}).ResourceGroupName) -Name $sourceStorageAccount)[0].Value
        [string]$SrcStorageAccount = $sourceStorageAccount
        [string]$SrcStorageBlob = $vhdName
        $SrcStorageContainer = $sourceStorageContainer
        $context = New-AzureStorageContext -StorageAccountName $srcStorageAccount -StorageAccountKey $srcStorageAccountKey
        $expireTime = Get-Date
        $expireTime = $expireTime.AddYears(1)
        $SasUrl = New-AzureStorageBlobSASToken -container $srcStorageContainer -Blob $srcStorageBlob -Permission R -ExpiryTime $expireTime -FullUri -Context $Context
}

    Write-LogInfo "Retrieving $destinationStorageAccount storage account key"
    $DestAccountKey = (Get-AzureRmStorageAccountKey -ResourceGroupName $(($GetAzureRmStorageAccount  | Where {$_.StorageAccountName -eq "$destinationStorageAccount"}).ResourceGroupName) -Name $destinationStorageAccount)[0].Value
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
        }
        else {
            Write-LogInfo "Copy $DestBlob --> $($destContext.StorageAccountName) : Done"
            $retValue = $true

        }
        if ($CopyingInProgress) {
            $copyPercentage = [math]::Round( $(($status.BytesCopied * 100 / $status.TotalBytes)) , 2 )
            Write-LogInfo "Bytes Copied:$($status.BytesCopied), Total Bytes:$($status.TotalBytes) [ $copyPercentage % ]"
            Sleep -Seconds 10
        }
    }
    return $retValue
}

Function Set-ResourceGroupLock ([string]$ResourceGroup, [string]$LockNote, [string]$LockName = "ReproVM", $LockType = "CanNotDelete") {
    $parameterErrors = 0
    if ($LockNote -eq $null) {
        Write-LogErr "You did not provide -LockNote <string>. Please give a valid note."
        $parameterErrors += 1
    }
    if ($ResourceGroup -eq $null) {
        Write-LogErr "You did not provide -ResourceGroup <string>.."
        $parameterErrors += 1
    }
    if ($parameterErrors -eq 0) {
        Write-LogInfo "Adding '$LockName' lock to '$ResourceGroup'"
        $lock = Set-AzureRmResourceLock -LockName $LockName -LockLevel $LockType -LockNotes $LockNote -Force -ResourceGroupName $ResourceGroup
        if ( $lock.Properties.level -eq $LockType) {
            Write-LogInfo ">>>$ResourceGroup LOCKED<<<."
        }
        else {
            Write-LogErr "Something went wrong. Please try again."
        }
    }
    else {
        Write-LogInfo "Fix the paremeters and try again."
    }
}

Function Restart-AllAzureDeployments($allVMData) {
    $restartJobs = @()
    foreach ( $vmData in $AllVMData ) {
        Write-LogInfo "Triggering Restart-$($vmData.RoleName)..."
        $restartJobs += Start-Job -ScriptBlock {
            $vmData = $args[0]
            $retries = 0
            $maxRetryCount = 3
            $vmRestarted = $false

            # Note(v-advlad): Azure API can sometimes fail on burst requests, we have to retry
            while (!$vmRestarted -and $retries -lt $maxRetryCount) {
                $null = Restart-AzureRmVM -ResourceGroupName $vmData.ResourceGroupName -Name $vmData.RoleName -Verbose
                if (!$?) {
                    Start-Sleep -Seconds 0.5
                    $retries++
                } else {
                    $vmRestarted = $true
                }
            }
            if (!$vmRestarted) {
                throw "Failed to restart Azure VM $($vmData.RoleName)"
            }
        } -ArgumentList @($vmData) -Name "Restart-$($vmData.RoleName)"
    }
    $recheckAgain = $true
    Write-LogInfo "Waiting until VMs restart..."
    $jobCount = $restartJobs.Count
    $completedJobsCount = 0
    while ($recheckAgain) {
        $recheckAgain = $false
        $tempJobs = @()
        foreach ($restartJob in $restartJobs) {
            if ($restartJob.State -eq "Completed") {
                $completedJobsCount += 1
                Write-LogInfo "[$completedJobsCount/$jobCount] $($restartJob.Name) is done."
                $null = Remove-Job -Id $restartJob.ID -Force -ErrorAction SilentlyContinue
            } elseif ($restartJob.State -eq "Failed") {
                $jobError = Get-Job -Name $restartJob.Name | Receive-Job 2>&1
                Write-LogErr "$($restartJob.Name) failed with error: ${jobError}"
                return $false
            } else {
                $tempJobs += $restartJob
                $recheckAgain = $true
            }
        }
        $restartJobs = $tempJobs
        Start-Sleep -Seconds 1
    }

    $isSSHOpened = Check-SSHPortsEnabled -AllVMDataObject $AllVMData
    return $isSSHOpened
}

Function Set-SRIOVinAzureVMs {
    param (
        $ResourceGroup,
        $VMNames, #... Optional
        [switch]$Enable,
        [switch]$Disable)
    try {
        Function Check-CurrentNICStatus () {
            if ($Enable) {
                if ($AllNics.Count -eq 1) {
                    if ($AllNics.EnableAcceleratedNetworking -eq $true) {
                        $StatusChangeNotRequired = $true
                    }
                }
                else {
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
                }
                else {
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
        #"SS-R75SRIOV-Deploy2VM-ECMI-636723398793"
        $AllVMs = Get-AzureRmVM -ResourceGroupName $ResourceGroup
        if ($VMNames) {
            $VMNames = $VMNames.Trim()
            foreach ( $VMName in $VMNames.Split(",")) {
                if ( -not $VMNames.Contains("$VMName")) {
                    Throw "$VMName does not exist in $ResourceGroup."
                }
                else {
                    $TargettedVMs += $ALLVMs | Where-Object { $_.Name -eq "$VMName" }
                }
            }
        }
        else {
            $TargettedVMs = $AllVMs
        }

        foreach ( $TargetVM in $TargettedVMs) {
            $VMName = $TargetVM.Name
            $AllNics = Get-AzureRmNetworkInterface -ResourceGroupName $ResourceGroup `
                | Where-Object { $($_.VirtualMachine.Id | Split-Path -leaf) -eq $VMName }

            if ($Enable) {
                $DesiredState = "Enabled"
                if (Check-CurrentNICStatus) {
                    Write-LogInfo "Accelerated networking is already enabled for all nics in $VMName."
                    $retValue = $true
                    $VMPropertiesChanged = $false
                }
                else {
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
                        }
                        else {
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
                }
                else {
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
                        }
                        else {
                            Write-LogInfo "$($TargetNic.Name) [EnableAcceleratedNetworking=false] | Set-AzureRmNetworkInterface : FAIL"
                        }
                    }
                }
            }
        }
        if ( $VMPropertiesChanged ) {
            foreach ( $TargetVM in $TargettedVMs) {
                #Start the VM..
                Write-LogInfo "Starting VM $($TargetVM.Name)..."
                $null = Start-AzureRmVM -ResourceGroup $ResourceGroup -Name $TargetVM.Name
            }
            #Public IP address changes most of the times, when we shutdown the VM.
            #Hence, we need to refresh the data
            $global:AllVMData = Get-AllDeploymentData -ResourceGroups $ResourceGroup
            $TestVMData = @()
            foreach ( $TargetVM in $TargettedVMs) {
                $TestVMData += $AllVMData | Where-Object {$_.ResourceGroupName -eq $ResourceGroup `
                        -and $_.RoleName -eq $TargetVM.Name }
                #Start the VM..
            }
            $isSSHOpened = Check-SSHPortsEnabled -AllVMDataObject $TestVMData
            if ($isSSHOpened -eq "True") {
                $isRestarted = $true
            }
            else {
                Write-LogErr "VM is not available after restart"
                $isRestarted = $false
            }
            foreach ( $TargetVM in $TargettedVMs) {
                $VMName = $TargetVM.Name
                $AllNics = Get-AzureRmNetworkInterface -ResourceGroupName $ResourceGroup `
                    | Where-Object { $($_.VirtualMachine.Id | Split-Path -leaf) -eq $VMName }
                if ($Enable) {
                    if (Check-CurrentNICStatus) {
                        Write-LogInfo "Accelerated networking is successfully enabled for all nics in $VMName."
                        $NicVerified = $true
                    }
                    else {
                        Write-LogInfo "Accelerated networking is failed to enable for all/some nics in $VMName."
                        $NicVerified = $false
                    }
                }
                if ($Disable) {
                    if (Check-CurrentNICStatus) {
                        Write-LogInfo "Accelerated networking is successfully disabled for all nics in $VMName."
                        $NicVerified = $true
                    }
                    else {
                        Write-LogInfo "Accelerated networking is failed to disable for all/some nics in $VMName."
                        $NicVerified = $false
                    }
                }
                if ($isRestarted -and $NicVerified) {
                    $SuccessCount += 1
                    Write-LogInfo "Accelarated networking '$DesiredState' successfully for $VMName"
                }
                else {
                    Write-LogErr "Accelarated networking '$DesiredState' failed for $VMName"
                }
            }
            if ( $TargettedVMs.Count -eq $SuccessCount ) {
                $retValue = $true
            }
            else {
                $retValue = $false
            }
        }
        else {
            Write-LogInfo "Accelarated networking is already '$DesiredState'."
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
        }
        else {
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
        [string] $ResourceGroup
    )
    try {
        # Add jenkins username if available or add username of current windows account.
        if ($env:BUILD_USER) {
            $UserTag = $env:BUILD_USER
        }
        else {
            $UserTag = $env:UserName
        }
        Add-ResourceGroupTag -ResourceGroup $ResourceGroup -TagName BuildUser -TagValue $UserTag
        # Add jenkins build url if available.
        if ($env:BUILD_URL) {
            $BuildURLTag = $env:BUILD_URL
        }
        else {
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
