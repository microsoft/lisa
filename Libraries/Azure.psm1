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

Function ValidateSubscriptionUsage($subscriptionID, $RGXMLData)
{
    #region VM Cores...
    Try
    {
        Function SetUsage($currentStatus, $text, $usage, $AllowedUsagePercentage)
        {
            $counter = 0
            foreach ($item in $currentStatus)
            {
                if ($item.Name.Value -eq $text)
                {
                    $allowedCount = [int](($currentStatus[$counter].Limit)*($AllowedUsagePercentage/100))
                    LogMsg "  Current $text usage : $($currentStatus[$counter].CurrentValue) cores. Requested:$usage. Estimated usage=$($($currentStatus[$counter].CurrentValue) + $usage). Max Allowed cores:$allowedCount/$(($currentStatus[$counter].Limit))"
                    #LogMsg "Current VM Core Estimated use: $($currentStatus[$counter].CurrentValue) + $usage = $($($currentStatus[$counter].CurrentValue) + $usage) VM cores."
                    $currentStatus[$counter].CurrentValue = $currentStatus[$counter].CurrentValue + $usage
                }
                if ($item.Name.Value -eq "cores")
                {
                    $allowedCount = [int](($currentStatus[$counter].Limit)*($AllowedUsagePercentage/100))
                    LogMsg "  Current Regional Cores usage : $($currentStatus[$counter].CurrentValue) cores. Requested:$usage. Estimated usage=$($($currentStatus[$counter].CurrentValue) + $usage). Max Allowed cores:$allowedCount/$(($currentStatus[$counter].Limit))"
                    #LogMsg "Current VM Core Estimated use: $($currentStatus[$counter].CurrentValue) + $usage = $($($currentStatus[$counter].CurrentValue) + $usage) VM cores."
                    $currentStatus[$counter].CurrentValue = $currentStatus[$counter].CurrentValue + $usage
                }
                $counter++
            }

            return $currentStatus
        }

        Function TestUsage($currentStatus, $text, $AllowedUsagePercentage)
        {
            $overFlowErrors = 0
            $counter = 0
            foreach ($item in $currentStatus)
            {
                if ($item.Name.Value -eq $text)
                {
                    $allowedCount = [int](($currentStatus[$counter].Limit)*($AllowedUsagePercentage/100))
                    #LogMsg "Max allowed $($item.Name.LocalizedValue) usage : $allowedCount out of $(($currentStatus[$counter].Limit))."
                    if ($currentStatus[$counter].CurrentValue -le $allowedCount)
                    {
                        
                    }
                    else
                    {
                        LogErr "  Current $text Estimated use: $($currentStatus[$counter].CurrentValue)"
                        $overFlowErrors += 1
                    }
                }
                if ($item.Name.Value -eq "cores")
                {
                    $allowedCount = [int](($currentStatus[$counter].Limit)*($AllowedUsagePercentage/100))
                    #LogMsg "Max allowed $($item.Name.LocalizedValue) usage : $allowedCount out of $(($currentStatus[$counter].Limit))."
                    if ($currentStatus[$counter].CurrentValue -le $allowedCount)
                    {
                        
                    }
                    else
                    {
                        LogErr "  Current Regional Cores Estimated use: $($currentStatus[$counter].CurrentValue)"
                        $overFlowErrors += 1
                    }
                }
                $counter++
            }
            return $overFlowErrors
        }
        #Get the region
        $Location = ($xmlConfig.config.$TestPlatform.General.Location).Replace('"',"").Replace(' ',"").ToLower()
        $AllowedUsagePercentage = 100
        $currentStatus = Get-AzureRmVMUsage -Location $Location
        $overFlowErrors = 0
        $requiredVMCores = 0
        $premiumVMs = 0
        $vmCounter = 0
        foreach ($VM in $RGXMLData.VirtualMachine)
        {
            $vmCounter += 1
            

            LogMsg "Estimating VM #$vmCounter usage."
            if ($OverrideVMSize)
            {
                $testVMSize = $overrideVMSize
            }
            elseif ( $CurrentTestData.OverrideVMSize)
            {
                $testVMSize = $CurrentTestData.OverrideVMSize
            }
            else
            {
                $testVMSize = $VM.ARMInstanceSize
            }

            if (($OverrideVMSize -or $CurrentTestData.OverrideVMSize) -and ($testVMUsage -gt 0))
            {
                #Do nothing.
            }
            else
            {
                $testVMUsage = (Get-AzureRmVMSize -Location $Location | Where { $_.Name -eq $testVMSize}).NumberOfCores
            }


            $testVMSize = $testVMSize.Replace("Standard_","")

            #region D-Series postmartem
            if ( $testVMSize.StartsWith("DS") -and $testVMSize.EndsWith("v2"))
            {
                $identifierText = "standardDSv2Family"
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
                $premiumVMs += 1
            }
            elseif ( $testVMSize.StartsWith("D") -and $testVMSize.EndsWith("s_v3"))
            {
                $identifierText = "standardDSv3Family"
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
                $premiumVMs += 1
            }            
            elseif ( $testVMSize.StartsWith("DS") -and !$testVMSize.EndsWith("v2") -and !$testVMSize.EndsWith("v3"))
            {
                $identifierText = "standardDSFamily" 
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
                $premiumVMs += 1
            }
            elseif ( $testVMSize.StartsWith("D") -and !$testVMSize.StartsWith("DS") -and $testVMSize.EndsWith("v2"))
            {
                $identifierText = "standardDv2Family" 
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }
            elseif ( $testVMSize.StartsWith("D") -and !$testVMSize.EndsWith("s_v3") -and $testVMSize.EndsWith("v3"))
            {
                $identifierText = "standardDv3Family" 
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }            
            elseif ( $testVMSize.StartsWith("D") -and !$testVMSize.StartsWith("DS") -and !$testVMSize.EndsWith("v2") -and !$testVMSize.EndsWith("v3"))
            {
                $identifierText = "standardDFamily" 
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }
            #endregion

            #region E-Series postmartem
            elseif ( $testVMSize.StartsWith("E") -and $testVMSize.EndsWith("s_v3"))
            {
                $identifierText = "standardESv3Family"
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
                $premiumVMs += 1
            }
            elseif ( $testVMSize.StartsWith("E") -and !$testVMSize.EndsWith("s_v3") -and $testVMSize.EndsWith("v3"))
            {
                $identifierText = "standardEv3Family"
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }            
            #endregion            

            #region Standard A series postmartem

            elseif ( ( $testVMSize -eq "A8") -or ( $testVMSize -eq "A9") -or ( $testVMSize -eq "A10") -or ( $testVMSize -eq "A11") )
            {
                $identifierText = "standardA8_A11Family"
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }
            elseif ( $testVMSize.StartsWith("A") -and $testVMSize.EndsWith("v2"))
            {
                $identifierText = "standardAv2Family" 
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }
            elseif ( $testVMSize.StartsWith("A") -and !$testVMSize.EndsWith("v2"))
            {
                $identifierText = "standardA0_A7Family" 
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }
            #endregion

            #region Standard F series postamartem
            elseif ( $testVMSize.StartsWith("FS"))
            {
                $identifierText = "standardFSFamily" 
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
                $premiumVMs += 1
            }
            elseif ( $testVMSize.StartsWith("F"))
            {
                $identifierText = "standardFFamily"
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }
            elseif ( $testVMSize.StartsWith("GS"))
            {
                $identifierText = "standardGSFamily" 
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
                $premiumVMs += 1
            }
            elseif ( $testVMSize.StartsWith("G"))
            {
                $identifierText = "standardGFamily"
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }
            elseif ( $testVMSize.StartsWith("NV"))
            {
                $identifierText = "standardNVFamily"
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }
            elseif (  $testVMSize.StartsWith("NC") -and  $testVMSize.EndsWith("v2") ) 
            {
                $identifierText = "standardNCv2Family"
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }            
            elseif ( $testVMSize.StartsWith("NC"))
            {
                $identifierText = "standardNCFamily"
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }
            elseif ( $testVMSize.StartsWith("ND"))
            {
                $identifierText = "standardNDFamily"
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }
            elseif ( $testVMSize.StartsWith("H"))
            {
                $identifierText = "standardHFamily"
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }
            elseif ( $testVMSize.StartsWith("Basic"))
            {
                $identifierText = "basicAFamily"
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }
            #region M-Series postmartem
            elseif ( $testVMSize.StartsWith("M"))
            {
                $identifierText = "standardMSFamily"
                $currentStatus = SetUsage -currentStatus $currentStatus -text $identifierText  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage 
                $overFlowErrors += TestUsage -currentStatus $currentStatus -text $identifierText -AllowedUsagePercentage $AllowedUsagePercentage 
            }
            #endregion            
        
            else
            {
                LogMsg "Requested VM size: $testVMSize is not yet registered to monitor. Usage simulation skipped."
            }
            #endregion
        }

        #Check the max core quota

        #Get the current usage for current region
        #$currentStorageAccounts = (Get-AzureRmStorageAccount).Count

        #Decide

    }
    catch
    {
        $line = $_.InvocationInfo.ScriptLineNumber
        $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
        $ErrorMessage =  $_.Exception.Message
        LogErr "EXCEPTION : $ErrorMessage"
        LogErr "Source : Line $line in script $script_name."
    }

    #endregion


    #region Storage Accounts
    LogMsg "Estimating storage account usage..."
    $currentStorageStatus = Get-AzureRmStorageUsage
    if ( ($premiumVMs -gt 0 ) -and ($xmlConfig.config.$TestPlatform.General.StorageAccount -imatch "NewStorage_"))
    {
        $requiredStorageAccounts = 1
    }
    elseif( ($premiumVMs -gt 0 ) -and !($xmlConfig.config.$TestPlatform.General.StorageAccount -imatch "NewStorage_"))
    {
        $requiredStorageAccounts = 1
    }
    elseif( !($premiumVMs -gt 0 ) -and !($xmlConfig.config.$TestPlatform.General.StorageAccount -imatch "NewStorage_"))
    {
        $requiredStorageAccounts = 0
    }

    $allowedStorageCount = [int]($currentStorageStatus.Limit*($AllowedUsagePercentage/100))


    if (($currentStorageStatus.CurrentValue + $requiredStorageAccounts) -le $allowedStorageCount)
    {
        LogMsg "Current Storage Accounts usage:$($currentStorageStatus.CurrentValue). Requested:$requiredStorageAccounts. Estimated usage:$($currentStorageStatus.CurrentValue + $requiredStorageAccounts). Maximum allowed:$allowedStorageCount/$(($currentStorageStatus.Limit))."
    }
    else
    {
        LogErr "Current Storage Accounts usage:$($currentStorageStatus.CurrentValue). Requested:$requiredStorageAccounts. Estimated usage:$($currentStorageStatus.CurrentValue + $requiredStorageAccounts). Maximum allowed:$allowedStorageCount/$(($currentStorageStatus.Limit))."
        $overFlowErrors += 1
    }
    #endregion

    $GetAzureRmNetworkUsage  = Get-AzureRmNetworkUsage -Location $Location
    #region Public IP Addresses
    $PublicIPs = $GetAzureRmNetworkUsage | Where-Object { $_.Name.Value -eq "PublicIPAddresses" }
    LogMsg "Current Public IPs usage:$($PublicIPs.CurrentValue). Requested: 1. Estimated usage:$($PublicIPs.CurrentValue + 1). Maximum allowed: $($PublicIPs.Limit)."
    if (($PublicIPs.CurrentValue + 1) -gt $PublicIPs.Limit)
    {
        $overFlowErrors += 1
    }
    #endregion
    #region Virtual networks
    $VNETs = $GetAzureRmNetworkUsage | Where-Object { $_.Name.Value -eq "VirtualNetworks" }
    LogMsg "Current VNET usage:$($VNETs.CurrentValue). Requested: 1. Estimated usage:$($VNETs.CurrentValue + 1). Maximum allowed: $($VNETs.Limit)."
    if (($VNETs.CurrentValue + 1) -gt $VNETs.Limit)
    {
        $overFlowErrors += 1
    }
    #endregion
    #region Network Security Groups
    $SGs = $GetAzureRmNetworkUsage | Where-Object { $_.Name.Value -eq "NetworkSecurityGroups" }
    LogMsg "Current Security Group usage:$($SGs.CurrentValue). Requested: 1. Estimated usage:$($SGs.CurrentValue + 1). Maximum allowed: $($SGs.Limit)."
    if (($SGs.CurrentValue + 1) -gt $SGs.Limit)
    {
        $overFlowErrors += 1
    }
    #endregion
    #region Load Balancers
    $LBs = $GetAzureRmNetworkUsage | Where-Object { $_.Name.Value -eq "LoadBalancers" }
    LogMsg "Current Load Balancer usage:$($LBs.CurrentValue). Requested: 1. Estimated usage:$($LBs.CurrentValue + 1). Maximum allowed: $($LBs.Limit)."
    if (($LBs.CurrentValue + 1) -gt $LBs.Limit)
    {
        $overFlowErrors += 1
    }
    #endregion


    if($overFlowErrors -eq 0)
    {
        LogMsg "Estimated subscription usage is under allowed limits."
        return $true
    }
    else
    {
        LogErr "Estimated subscription usage exceeded allowed limits."
        return $false
    }
}

Function CreateAllResourceGroupDeployments($setupType, $xmlConfig, $Distro, [string]$region = "", $DebugRG = "")
{
    if ($DebugRG)
    {
        return "True", $DebugRG, 1, 180
    }
    else
    {
        $resourceGroupCount = 0
        LogMsg $setupType
        $setupTypeData = $xmlConfig.config.$TestPlatform.Deployment.$setupType
        $allsetupGroups = $setupTypeData
        if ($allsetupGroups.ResourceGroup[0].Location -or $allsetupGroups.ResourceGroup[0].AffinityGroup)
        {
            $isMultiple = 'True'
            $resourceGroupCount = 0
        }
        else
        {
            $isMultiple = 'False'
        }
        $OsVHD = $BaseOsVHD
        $location = $xmlConfig.config.$TestPlatform.General.Location
        if($region)
        {
          $location = $region;
        }
    
        if ( $location -imatch "-" )
        {
            $RGCount = $setupTypeData.ResourceGroup.Count
            $xRegionTest = $true
            $xRegionTotalLocations = $location.Split("-").Count
            $xRegionLocations = $location.Split("-")
            $locationCounter = 0
            LogMsg "$RGCount Resource groups will be deployed in $($xRegionLocations.Replace('-',' and '))"
        }
        foreach ($RG in $setupTypeData.ResourceGroup )
        {
            $validateStartTime = Get-Date
            LogMsg "Checking the subscription usage..."
            $readyToDeploy = $false
            while (!$readyToDeploy)
            {
                $readyToDeploy = ValidateSubscriptionUsage -subscriptionID $xmlConfig.config.$TestPlatform.General.SubscriptionID -RGXMLData $RG
                $validateCurrentTime = Get-Date
                $elapsedWaitTime = ($validateCurrentTime - $validateStartTime).TotalSeconds
                if ( (!$readyToDeploy) -and ($elapsedWaitTime -lt $CoreCountExceededTimeout))
                {
                    $waitPeriod = Get-Random -Minimum 1 -Maximum 10 -SetSeed (Get-Random)
                    LogMsg "Timeout in approx. $($CoreCountExceededTimeout - $elapsedWaitTime) seconds..."
                    LogMsg "Waiting $waitPeriod minutes..."
                    sleep -Seconds ($waitPeriod*60)
                }
                if ( $elapsedWaitTime -gt $CoreCountExceededTimeout )
                {
                    break
                }
            }
            if ($readyToDeploy)
            {
                $curtime = ([string]((Get-Date).Ticks / 1000000)).Split(".")[0]
                $randomNumber = $global4digitRandom
                $isServiceDeployed = "False"
                $retryDeployment = 0
                if ( $RG.Tag -ne $null )
                {
                    $groupName = "ICA-RG-" + $RG.Tag + "-" + $Distro + "-" + "$shortRandomWord-" + "$curtime"
                }
                else
                {
                    $groupName = "ICA-RG-" + $setupType + "-" + $Distro + "-" + "$shortRandomWord-" + "$curtime"
                }
                if($isMultiple -eq "True")
                {
                    $groupName = $groupName + "-" + $resourceGroupCount
                }
                while (($isServiceDeployed -eq "False") -and ($retryDeployment -lt 1))
                {
                    if ($ExistingRG)
                    {
        
                        $isServiceCreated = "True"
                        LogMsg "Detecting $ExistingRG region..."
                        $location=(Get-AzureRmResourceGroup -Name $ExistingRG).Location
                        LogMsg "Region: $location..."
                        $groupName = $ExistingRG
                        LogMsg "Using existing Resource Group : $ExistingRG"
                        if ($CleanupExistingRG)
                        {
                            LogMsg "CleanupExistingRG flag is Set. All resources except availibility set will be cleaned."
                            LogMsg "If you do not wish to cleanup $ExistingRG, abort NOW. Sleeping 10 Seconds."
                            Sleep 10
                            $isRGDeleted = DeleteResourceGroup -RGName $groupName
                        }
                        else
                        {
                            $isRGDeleted  = $true
                        }
                    }
                    else
                    {
                        LogMsg "Creating Resource Group : $groupName."
                        LogMsg "Verifying that Resource group name is not in use."
                        $isRGDeleted = DeleteResourceGroup -RGName $groupName
                    }
                    if ($isRGDeleted)
                    {    
                        if ( $xRegionTest )
                        {
                            $location = $xRegionLocations[$locationCounter]
                            $locationCounter += 1
                        }
                        else
                        {				
                            $isServiceCreated = CreateResourceGroup -RGName $groupName -location $location
                        }
                        if ($isServiceCreated -eq "True")
                        {
                            $azureDeployJSONFilePath = ".\Temp\$groupName.json"
                            $DeploymentCommand = GenerateAzureDeployJSONFile -RGName $groupName -osImage $osImage -osVHD $osVHD -RGXMLData $RG -Location $location -azuredeployJSONFilePath $azureDeployJSONFilePath
                            $DeploymentStartTime = (Get-Date)
                            $CreateRGDeployments = CreateResourceGroupDeployment -RGName $groupName -location $location -setupType $setupType -TemplateFile $azureDeployJSONFilePath
                            $DeploymentEndTime = (Get-Date)
                            $DeploymentElapsedTime = $DeploymentEndTime - $DeploymentStartTime
                            if ( $CreateRGDeployments )
                            {
                                $retValue = "True"
                                $isServiceDeployed = "True"
                                $resourceGroupCount = $resourceGroupCount + 1
                                if ($resourceGroupCount -eq 1)
                                {
                                    $deployedGroups = $groupName
                                }
                                else
                                {
                                    $deployedGroups = $deployedGroups + "^" + $groupName
                                }
        
                            }
                            else
                            {
                                LogErr "Unable to Deploy one or more VM's"
                                $retryDeployment = $retryDeployment + 1
                                $retValue = "False"
                                $isServiceDeployed = "False"
                            }
                        }
                        else
                        {
                            LogErr "Unable to create $groupName"
                            $retryDeployment = $retryDeployment + 1
                            $retValue = "False"
                            $isServiceDeployed = "False"
                        }
                    }    
                    else
                    {
                        LogErr "Unable to delete existing resource group - $groupName"
                        $retryDeployment = 3
                        $retValue = "False"
                        $isServiceDeployed = "False"
                    }
                }
            }
            else
            {
                LogErr "Core quota is not sufficient. Stopping VM deployment."
                $retValue = "False"
                $isServiceDeployed = "False"
            }
        }
        return $retValue, $deployedGroups, $resourceGroupCount, $DeploymentElapsedTime
    }
    
}

Function DeleteResourceGroup([string]$RGName, [switch]$KeepDisks)
{
    try
    {
        LogMsg "Checking if $RGName exists..."
        $ResourceGroup = Get-AzureRmResourceGroup -Name $RGName -ErrorAction Ignore
    }
    catch
    {
    }
    if ($ResourceGroup)
    {
		if ($ExistingRG)
		{
			$CurrentResources = @()
	        $CurrentResources += Get-AzureRmResource | Where {$_.ResourceGroupName -eq  $ResourceGroup.ResourceGroupName}
	        while ( $CurrentResources.Count -ne 1 )
	        {
	            foreach ($resource in $CurrentResources) 
	            {
	                Write-Host $resource.ResourceType
	                if ( $resource.ResourceType -imatch "availabilitySets" )
	                {
	                    LogMsg "Skipping $($resource.ResourceName)"
	                }
	                else
	                {
                        LogMsg "Removing $($resource.ResourceName)"
                        try 
                        {
                            $out = Remove-AzureRmResource -ResourceId $resource.ResourceId -Force -Verbose    
                        }
                        catch 
                        {
                            LogErr "Error. We will try to remove this in next attempt."
                        }
	                    
	                }
	            }
	            $CurrentResources = @()
	            $CurrentResources += Get-AzureRmResource | Where {$_.ResourceGroupName -eq  $ResourceGroup.ResourceGroupName}
	        }
	        LogMsg "$($ResourceGroup.ResourceGroupName) is cleaned."
			$retValue = $?
		}
		else
		{
            if ( $XmlSecrets.secrets.AutomationRunbooks.CleanupResourceGroupRunBook )
            {
                $parameters = $parameters = @{"NAMEFILTER"="$RGName"; "PREVIEWMODE"=$false};
                $CleanupRG = Get-AzureRmResourceGroup  -Name $XmlSecrets.secrets.AutomationRunbooks.ResourceGroupName -ErrorAction SilentlyContinue
            }
            if ($CleanupRG)
            {
                $rubookJob = Start-AzureRmAutomationRunbook -Name $XmlSecrets.secrets.AutomationRunbooks.CleanupResourceGroupRunBook -Parameters $parameters -AutomationAccountName $XmlSecrets.secrets.AutomationRunbooks.AutomationAccountName -ResourceGroupName $XmlSecrets.secrets.AutomationRunbooks.ResourceGroupName
                LogMsg "Cleanup job ID: '$($rubookJob.JobId)' for '$RGName' started using runbooks."
                $retValue = $true
            }            
            else
            {
                $currentGUID = ([guid]::newguid()).Guid
                $out = Save-AzureRmContext -Path "$env:TEMP\$($currentGUID).azurecontext" -Force
                $cleanupRGScriptBlock = {
                    $RGName = $args[0]
                    $currentGUID = $args[1]
                    Import-AzureRmContext -AzureContext "$env:TEMP\$($currentGUID).azurecontext"
                    Remove-AzureRmResourceGroup -Name $RGName -Verbose -Force
                }
                $currentGUID = ([guid]::newguid()).Guid
                $out = Save-AzureRmContext -Path "$env:TEMP\$($currentGUID).azurecontext" -Force
                LogMsg "Triggering : DeleteResourceGroup-$RGName..."
                $deleteJob = Start-Job -ScriptBlock $cleanupRGScriptBlock -ArgumentList $RGName,$currentGUID -Name "DeleteResourceGroup-$RGName"
                $retValue = $true
            }
        }
    }
    else
    {
        LogMsg "$RGName does not exists."
        $retValue = $true
    }
    return $retValue
}

Function RemoveResidualResourceGroupVHDs($ResourceGroup,$storageAccount)
{
    # Verify that the OS VHD does not already exist
    
    $azureStorage = $storageAccount
    LogMsg "Removing residual VHDs of $ResourceGroup from $azureStorage..."
    $storageContext = (Get-AzureRmStorageAccount | Where-Object{$_.StorageAccountName -match $azureStorage}).Context
    $storageBlob = Get-AzureStorageBlob -Context $storageContext -Container "vhds"
    $vhdList = $storageBlob | Where-Object{$_.Name -match "$ResourceGroup"}
    if ($vhdList) 
    {
        # Remove VHD files
        foreach($diskName in $vhdList.Name) 
        {
            LogMsg "Removing VHD $diskName"
            Remove-AzureStorageBlob -Blob $diskname -Container vhds -Context $storageContext -Verbose -ErrorAction SilentlyContinue
        }
    }
}
Function CreateResourceGroup([string]$RGName, $location)
{
    $FailCounter = 0
    $retValue = "False"
    $ResourceGroupDeploymentName = $RGName + "-arm"

    While(($retValue -eq $false) -and ($FailCounter -lt 5))
    {
        try
        {
            $FailCounter++
            if($location)
            {
                LogMsg "Using location : $location"
                $createRG = New-AzureRmResourceGroup -Name $RGName -Location $location.Replace('"','') -Force -Verbose
            }
            $operationStatus = $createRG.ProvisioningState
            if ($operationStatus  -eq "Succeeded")
            {
                LogMsg "Resource Group $RGName Created."
                $retValue = $true
            }
            else 
            {
                LogErr "Failed to Resource Group $RGName."
                $retValue = $false
            }
        }
        catch
        {
            $retValue = $false
        }
    }
    return $retValue
}

Function CreateResourceGroupDeployment([string]$RGName, $location, $setupType, $TemplateFile)
{
    $FailCounter = 0
    $retValue = "False"
    $ResourceGroupDeploymentName = "eosg" + (Get-Date).Ticks
    While(($retValue -eq $false) -and ($FailCounter -lt 1))
    {
        try
        {
            $FailCounter++
            if($location)
            {
                LogMsg "Creating Deployment using $TemplateFile ..."
                $createRGDeployment = New-AzureRmResourceGroupDeployment -Name $ResourceGroupDeploymentName -ResourceGroupName $RGName -TemplateFile $TemplateFile -Verbose
            }
            $operationStatus = $createRGDeployment.ProvisioningState
            if ($operationStatus  -eq "Succeeded")
            {
                LogMsg "Resource Group Deployment Created."
                $retValue = $true
            }
            else 
            {
                $retValue = $false
                LogErr "Failed to create Resource Group - $RGName."
                if ($ForceDeleteResources)
                {
                    LogMsg "-ForceDeleteResources is Set. Deleting $RGName."
                    $isClened = DeleteResourceGroup -RGName $RGName
                
                }
                else 
                {
                    $VMsCreated = Get-AzureRmVM -ResourceGroupName $RGName
                    if ( $VMsCreated )
                    {
                        LogMsg "Keeping Failed resource group, as we found $($VMsCreated.Count) VM(s) deployed."
                    }
                    else
                    {
                        LogMsg "Removing Failed resource group, as we found 0 VM(s) deployed."
                        $isClened = DeleteResourceGroup -RGName $RGName
                    }                        
                }                
            }
        }
        catch
        {
            $retValue = $false
        }
    }
    return $retValue
}

Function GenerateAzureDeployJSONFile ($RGName, $osImage, $osVHD, $RGXMLData, $Location, $azuredeployJSONFilePath)
{

#Random Data
$RGrandomWord = ([System.IO.Path]::GetRandomFileName() -replace '[^a-z]')
$RGRandomNumber = Get-Random -Minimum 11111 -Maximum 99999
if ( $CurrentTestData.AdditionalHWConfig.DiskType -eq "Managed" )
{
    $UseManageDiskForCurrentTest = $true
}
else
{
    $UseManageDiskForCurrentTest = $false
}
#Generate the initial data
$numberOfVMs = 0
$VMNames = @()
$EnableIPv6 = $false
$ForceLoadBalancerForSingleVM = $false
$totalSubnetsRequired = 0
foreach ( $newVM in $RGXMLData.VirtualMachine)
{
    if ( !$EnableIPv6 )
    {
        foreach ( $endpoint in $newVM.EndPoints )
        {
            if ( $endpoint.EnableIPv6 -eq "True" )
            {
                $EnableIPv6 = $true
            }
            if ( $endpoint.LoadBalanced -eq "True" )
            {
                $ForceLoadBalancerForSingleVM = $true
            }
            #Check total subnets required
            if ( $newVM.ExtraNICs -ne 0)
            {
                $totalSubnetsRequired = $newVM.ExtraNICs
            }            
        }
    }
    if($newVM.RoleName)
    {
        $VMNames += $newVM.RoleName
    }
    else
    {
        $VMNames += "$RGName-role-$numberOfVMs"
    }
    $numberOfVMs += 1
}


$saInfoCollected = $false
$retryCount = 0
$maxRetryCount = 999
while(!$saInfoCollected -and ($retryCount -lt $maxRetryCount))
{
    try
    {
        $retryCount += 1
        LogMsg "[Attempt $retryCount/$maxRetryCount] : Getting Existing Storage account information..."
        $GetAzureRMStorageAccount = $null
        $GetAzureRMStorageAccount = Get-AzureRmStorageAccount
        if ($GetAzureRMStorageAccount -eq $null)
        {
            $saInfoCollected = $false
        }
        else
        {
            $saInfoCollected = $true
        }
        
    }
    catch
    {
        LogErr "Error in fetching Storage Account info. Retrying in 10 seconds."
        sleep -Seconds 10
        $saInfoCollected = $false
    }
}

$StorageAccountName = $xmlConfig.config.$TestPlatform.General.ARMStorageAccount
#Condition Existing Storage - NonManaged disks
if ( $StorageAccountName -inotmatch "NewStorage" -and !$UseManagedDisks -and !$UseManageDiskForCurrentTest)
{
    $StorageAccountType = ($GetAzureRMStorageAccount | where {$_.StorageAccountName -eq $StorageAccountName}).Sku.Tier.ToString()
    $StorageAccountRG = ($GetAzureRMStorageAccount | where {$_.StorageAccountName -eq $StorageAccountName}).ResourceGroupName.ToString()
    if($StorageAccountType -match 'Premium')
    {
        $StorageAccountType = "Premium_LRS"
    }
    else
    {
	    $StorageAccountType = "Standard_LRS"
    }
    LogMsg "Storage Account Type : $StorageAccountType"  
    Set-Variable -Name StorageAccountTypeGlobal -Value $StorageAccountType -Scope Global  
}

#Condition Existing Storage - Managed Disks
if ( $StorageAccountName -inotmatch "NewStorage" -and ($UseManagedDisks -or $UseManageDiskForCurrentTest))
{
    $StorageAccountType = ($GetAzureRMStorageAccount | where {$_.StorageAccountName -eq $StorageAccountName}).Sku.Tier.ToString()
    if($StorageAccountType -match 'Premium')
    {
        $StorageAccountType = "Premium_LRS"
    }
    else
    {
	    $StorageAccountType = "Standard_LRS"
    }
    Set-Variable -Name StorageAccountTypeGlobal -Value $StorageAccountType -Scope Global      
}


#Condition New Storage - NonManaged disk
if ( $StorageAccountName -imatch "NewStorage" -and !$UseManagedDisks -and !$UseManageDiskForCurrentTest)
{
    $NewARMStorageAccountType = ($StorageAccountName).Replace("NewStorage_","")
    Set-Variable -Name StorageAccountTypeGlobal -Value $NewARMStorageAccountType  -Scope Global
    $StorageAccountName = $($NewARMStorageAccountType.ToLower().Replace("_","")) + "$RGRandomNumber"
    $NewStorageAccountName = $StorageAccountName
    LogMsg "Using New ARM Storage Account : $StorageAccountName"
    $StorageAccountType= $NewARMStorageAccountType
    $StorageAccountRG = $RGName
}

#Condition New Storage - Managed disk
if ( $StorageAccountName -imatch "NewStorage" -and ($UseManagedDisks -or $UseManageDiskForCurrentTest))
{
    Set-Variable -Name StorageAccountTypeGlobal -Value ($StorageAccountName).Replace("NewStorage_","")  -Scope Global
    LogMsg "Conflicting parameters - NewStorage and UseManagedDisks. Storage account will not be created."
}
#Region Define all Variables.


LogMsg "Generating Template : $azuredeployJSONFilePath"
$jsonFile = $azuredeployJSONFilePath


if ($ARMImage -and !$osVHD)
{
    $publisher = $ARMImage.Publisher
    $offer = $ARMImage.Offer
    $sku = $ARMImage.Sku
    $version = $ARMImage.Version
}
elseif ($CurrentTestData.Publisher -and $CurrentTestData.Offer)
{
    $publisher = $CurrentTestData.Publisher
    $offer = $CurrentTestData.Offer
    $sku = $CurrentTestData.Sku
    $version = $CurrentTestData.Version
}


$HS = $RGXMLData
$setupType = $Setup
$totalVMs = 0
$totalHS = 0
$extensionCounter = 0
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
#$availibilitySetName = $($RGName.ToUpper() -replace '[^a-z]') + "AvSet"
$availibilitySetName = "AvailibilitySet"
#$LoadBalancerName =  $($RGName.ToUpper() -replace '[^a-z]') + "LoadBalancer"
$LoadBalancerName =  "LoadBalancer"
$apiVersion = "2018-04-01"
#$PublicIPName = $($RGName.ToUpper() -replace '[^a-z]') + "PublicIPv4"
$PublicIPName = "PublicIPv4-$RGRandomNumber"
#$PublicIPv6Name = $($RGName.ToUpper() -replace '[^a-z]') + "PublicIPv6"
$PublicIPv6Name = "PublicIPv6"
$sshPath = '/home/' + $user + '/.ssh/authorized_keys'
$sshKeyData = ""
if($ExistingRG)
{
	$customAVSetName = (Get-AzureRmResource | Where { (( $_.ResourceGroupName -eq  $RGName ) -and  ( $_.ResourceType -imatch  "availabilitySets" ))}).ResourceName
}
else
{
	$availibilitySetName = "AvailibilitySet"
	$customAVSetName = $availibilitySetName
}
if ( $CurrentTestData.ProvisionTimeExtensions )
{
	$extensionString = (Get-Content .\XML\Extensions.xml)
	foreach ($line in $extensionString.Split("`n"))
	{
		if ($line -imatch ">$($CurrentTestData.ProvisionTimeExtensions)<")
		{
			$ExecutePS = $true
		}
		if ($line -imatch '</Extension>')
		{
			$ExecutePS = $false
		}
		if ( ($line -imatch "EXECUTE-PS-" ) -and $ExecutePS)
		{
			$PSoutout = ""
			$line = $line.Trim()
			$line = $line.Replace("EXECUTE-PS-","")
			$line = $line.Split(">")
			$line = $line.Split("<")
			LogMsg "Executing Powershell command from Extensions.XML file : $($line[2])..."
			$PSoutout = Invoke-Expression -Command $line[2]
			$extensionString = $extensionString.Replace("EXECUTE-PS-$($line[2])",$PSoutout)
			sleep -Milliseconds 1
		}
	}
	$extensionXML = [xml]$extensionString
}



#Create Managed OS Disks for all VMs using OSVHD.



LogMsg "Using API VERSION : $apiVersion"
$ExistingVnet = $null
if ($RGXMLData.ARMVnetName -ne $null)
{
    $ExistingVnet = $RGXMLData.ARMVnetName
    LogMsg "Getting $ExistingVnet Virtual Netowrk info ..."
    $ExistingVnetResourceGroupName = ( Get-AzureRmResource | Where {$_.Name -eq $ExistingVnet}).ResourceGroupName
    LogMsg "ARM VNET : $ExistingVnet (ResourceGroup : $ExistingVnetResourceGroupName)"
    $virtualNetworkName = $ExistingVnet
}

#Generate Single Indent
for($i =0; $i -lt 4; $i++)
{
    $singleIndent += " "
}

#Generate Indent Levels
for ($i =0; $i -lt 30; $i++)
{
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
    if ($ExistingVnet)
    {
        Add-Content -Value "$($indents[2])^virtualNetworkResourceGroup^: ^$ExistingVnetResourceGroupName^," -Path $jsonFile
        Add-Content -Value "$($indents[2])^vnetID^: ^[resourceId(variables('virtualNetworkResourceGroup'), 'Microsoft.Network/virtualNetworks', '$virtualNetworkName')]^," -Path $jsonFile
    }
    else
    {
        Add-Content -Value "$($indents[2])^defaultSubnet^: ^$defaultSubnetName^," -Path $jsonFile
        Add-Content -Value "$($indents[2])^defaultSubnetID^: ^[concat(variables('vnetID'),'/subnets/', variables('defaultSubnet'))]^," -Path $jsonFile
        Add-Content -Value "$($indents[2])^vnetID^: ^[resourceId('Microsoft.Network/virtualNetworks',variables('virtualNetworkName'))]^," -Path $jsonFile
    }
    if ($ExistingRG)
    {
        Add-Content -Value "$($indents[2])^availabilitySetName^: ^$customAVSetName^," -Path $jsonFile
    }
    else
    {
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
    LogMsg "Added Variables.."

    #endregion

    #region Define Resources
    Add-Content -Value "$($indents[1])^resources^:" -Path $jsonFile
    Add-Content -Value "$($indents[1])[" -Path $jsonFile

    #region Common Resources for all deployments..

        #region availabilitySets
        if ($ExistingRG)
        {
            LogMsg "Using existing Availibility Set: $customAVSetName"
        }
        else
        {        
            Add-Content -Value "$($indents[2]){" -Path $jsonFile
                Add-Content -Value "$($indents[3])^apiVersion^: ^$apiVersion^," -Path $jsonFile
                Add-Content -Value "$($indents[3])^type^: ^Microsoft.Compute/availabilitySets^," -Path $jsonFile
                Add-Content -Value "$($indents[3])^name^: ^[variables('availabilitySetName')]^," -Path $jsonFile
                Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
                if ($UseManagedDisks -or ($UseManageDiskForCurrentTest))
                {
                    Add-Content -Value "$($indents[3])^sku^:" -Path $jsonFile
                    Add-Content -Value "$($indents[3]){" -Path $jsonFile
                        Add-Content -Value "$($indents[4])^name^: ^Aligned^" -Path $jsonFile
                    Add-Content -Value "$($indents[3])}," -Path $jsonFile                    
                }
                if ( $TiPSessionId -and $TiPCluster)
                {
                    Add-Content -Value "$($indents[3])^tags^:" -Path $jsonFile
                    Add-Content -Value "$($indents[3]){" -Path $jsonFile
                        Add-Content -Value "$($indents[4])^TipNode.SessionId^: ^$TiPSessionId^" -Path $jsonFile
                    Add-Content -Value "$($indents[3])}," -Path $jsonFile
                }
                Add-Content -Value "$($indents[3])^properties^:" -Path $jsonFile
                Add-Content -Value "$($indents[3]){" -Path $jsonFile
                    Add-Content -Value "$($indents[4])^platformFaultDomainCount^:2," -Path $jsonFile
                    Add-Content -Value "$($indents[4])^platformUpdateDomainCount^:5" -Path $jsonFile              
                if ( $TiPSessionId -and $TiPCluster)
                {
                    Add-Content -Value "$($indents[4])^," -Path $jsonFile
                    Add-Content -Value "$($indents[4])^internalData^:" -Path $jsonFile
                    Add-Content -Value "$($indents[4]){" -Path $jsonFile
                        Add-Content -Value "$($indents[5])^pinnedFabricCluster^ : ^$TiPCluster^" -Path $jsonFile  
                    Add-Content -Value "$($indents[4])}" -Path $jsonFile
                }
                Add-Content -Value "$($indents[3])}" -Path $jsonFile
            Add-Content -Value "$($indents[2])}," -Path $jsonFile
            LogMsg "Added availabilitySet $availibilitySetName.."
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
        LogMsg "Added Public IP Address $PublicIPName.."
        #endregion

        #region CustomImages
        if ($OsVHD -and ($UseManagedDisks -or $UseManageDiskForCurrentTest))
        {
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
        LogMsg "Added Custom image '$RGName-Image' from '$OsVHD'.."

        }
        #endregion
        

    #region New ARM Storage Account, if necessary!
    if ( $NewStorageAccountName)
    {
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
        LogMsg "Added New Storage Account $NewStorageAccountName.."
    }
    #endregion

    #region New ARM Bood Diagnostic Account if Storage Account Type is Premium LRS.
 
    $bootDiagnosticsSA = ([xml](Get-Content .\XML\RegionAndStorageAccounts.xml)).AllRegions.$Location.StandardStorage
    $diagnosticRG = ($GetAzureRMStorageAccount | where {$_.StorageAccountName -eq $bootDiagnosticsSA}).ResourceGroupName.ToString()
    #endregion

        #region virtualNetworks
    if (!$ExistingVnet)
    {
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
                    LogMsg "  Added Default Subnet to $virtualNetworkName.."

                    if ($totalSubnetsRequired -ne 0)
                    {
                        $subnetCounter = 1
                        While($subnetCounter -le $totalSubnetsRequired)
                        {
                    Add-Content -Value "$($indents[5])," -Path $jsonFile
                    Add-Content -Value "$($indents[5]){" -Path $jsonFile
                        Add-Content -Value "$($indents[6])^name^: ^ExtraSubnet-$subnetCounter^," -Path $jsonFile
                        Add-Content -Value "$($indents[6])^properties^: " -Path $jsonFile
                        Add-Content -Value "$($indents[6]){" -Path $jsonFile
                            Add-Content -Value "$($indents[7])^addressPrefix^: ^10.0.$subnetCounter.0/24^" -Path $jsonFile
                        Add-Content -Value "$($indents[6])}" -Path $jsonFile
                    Add-Content -Value "$($indents[5])}" -Path $jsonFile
                    LogMsg "  Added ExtraSubnet-$subnetCounter to $virtualNetworkName.."
                    $subnetCounter += 1
                        }
                    }
                Add-Content -Value "$($indents[4])]" -Path $jsonFile
            Add-Content -Value "$($indents[3])}" -Path $jsonFile
        Add-Content -Value "$($indents[2])}," -Path $jsonFile
        LogMsg "Added Virtual Network $virtualNetworkName.."
    }
        #endregion

    #endregion

        #region publicIPAddresses
    if ( $EnableIPv6 )
    {
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
        LogMsg "Added Public IPv6 Address $PublicIPv6Name.."
    }
        #endregion

    #region Multiple VM Deployment

        #region LoadBalancer
        LogMsg "Adding Load Balancer ..."
        Add-Content -Value "$($indents[2]){" -Path $jsonFile
            Add-Content -Value "$($indents[3])^apiVersion^: ^$apiVersion^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^type^: ^Microsoft.Network/loadBalancers^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^name^: ^[variables('lbName')]^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^dependsOn^: " -Path $jsonFile
            Add-Content -Value "$($indents[3])[" -Path $jsonFile
            if ( $EnableIPv6 )
            {
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
                    if ( $EnableIPv6 )
                    {
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
                if ( $EnableIPv6 )
                {
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
foreach ( $newVM in $RGXMLData.VirtualMachine)
{
    if($newVM.RoleName)
    {
        $vmName = $newVM.RoleName
    }
    else
    {
        $vmName = "$RGName-role-$role"
    }
    foreach ( $endpoint in $newVM.EndPoints)
    {
        if ( !($endpoint.LoadBalanced) -or ($endpoint.LoadBalanced -eq "False") )
        { 
            if ( $EndPointAdded )
            {
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
                    LogMsg "Added inboundNatRule Name:$vmName-$($endpoint.Name) frontendPort:$($endpoint.PublicPort) backendPort:$($endpoint.LocalPort) Protocol:$($endpoint.Protocol)."
                    $EndPointAdded = $true
        }
        else
        {
                $LBPorts += 1
        }
    }
                $role += 1
}
                Add-Content -Value "$($indents[4])]" -Path $jsonFile
                #endregion
                
                #region LoadBalanced Endpoints
if ( $LBPorts -gt 0 )
{
                Add-Content -Value "$($indents[4])," -Path $jsonFile
                Add-Content -Value "$($indents[4])^loadBalancingRules^:" -Path $jsonFile
                Add-Content -Value "$($indents[4])[" -Path $jsonFile
$probePorts = 0
$EndPointAdded = $false
$addedLBPort = $null
$role = 0
foreach ( $newVM in $RGXMLData.VirtualMachine)
{
    if($newVM.RoleName)
    {
        $vmName = $newVM.RoleName
    }
    else
    {
        $vmName = "$RGName-role-$role"
    }
    
    foreach ( $endpoint in $newVM.EndPoints)
    {
        if ( ($endpoint.LoadBalanced -eq "True") -and !($addedLBPort -imatch "$($endpoint.Name)-$($endpoint.PublicPort)" ) )
        { 
            if ( $EndPointAdded )
            {
                    Add-Content -Value "$($indents[5])," -Path $jsonFile            
            }
                    Add-Content -Value "$($indents[5]){" -Path $jsonFile
                        Add-Content -Value "$($indents[6])^name^: ^$RGName-LB-$($endpoint.Name)^," -Path $jsonFile
                        Add-Content -Value "$($indents[6])^properties^:" -Path $jsonFile
                        Add-Content -Value "$($indents[6]){" -Path $jsonFile
                       
                            Add-Content -Value "$($indents[7])^frontendIPConfiguration^:" -Path $jsonFile
                            Add-Content -Value "$($indents[7]){" -Path $jsonFile
                            if ($endpoint.EnableIPv6 -eq "True")
                            {
                                Add-Content -Value "$($indents[8])^id^: ^[variables('frontEndIPv6ConfigID')]^" -Path $jsonFile
                            }
                            else
                            {
                                Add-Content -Value "$($indents[8])^id^: ^[variables('frontEndIPv4ConfigID')]^" -Path $jsonFile
                            }
                            Add-Content -Value "$($indents[7])}," -Path $jsonFile
                            Add-Content -Value "$($indents[7])^backendAddressPool^:" -Path $jsonFile
                            Add-Content -Value "$($indents[7]){" -Path $jsonFile
                            if ($endpoint.EnableIPv6 -eq "True")
                            {
                                Add-Content -Value "$($indents[8])^id^: ^[variables('lbIPv6PoolID')]^" -Path $jsonFile
                            }
                            else
                            {
                                Add-Content -Value "$($indents[8])^id^: ^[variables('lbIPv4PoolID')]^" -Path $jsonFile
                            }
                            Add-Content -Value "$($indents[7])}," -Path $jsonFile
                            Add-Content -Value "$($indents[7])^protocol^: ^$($endpoint.Protocol)^," -Path $jsonFile
                            Add-Content -Value "$($indents[7])^frontendPort^: ^$($endpoint.PublicPort)^," -Path $jsonFile
                            Add-Content -Value "$($indents[7])^backendPort^: ^$($endpoint.LocalPort)^" -Path $jsonFile
                            

            if ( $endpoint.ProbePort )
            {
                            $probePorts += 1
                            Add-Content -Value "$($indents[7])," -Path $jsonFile
                            Add-Content -Value "$($indents[7])^probe^:" -Path $jsonFile
                            Add-Content -Value "$($indents[7]){" -Path $jsonFile
                                Add-Content -Value "$($indents[8])^id^: ^[concat(variables('lbID'),'/probes/$RGName-LB-$($endpoint.Name)-probe')]^" -Path $jsonFile
                            Add-Content -Value "$($indents[7])}," -Path $jsonFile
                            LogMsg "Enabled Probe for loadBalancingRule Name:$RGName-LB-$($endpoint.Name) : $RGName-LB-$($endpoint.Name)-probe."
            }
            else
            {
                            if ( $endpoint.EnableIPv6 -ne "True" )
                            {
                            Add-Content -Value "$($indents[7])," -Path $jsonFile
                            Add-Content -Value "$($indents[7])^enableFloatingIP^: false," -Path $jsonFile
                            Add-Content -Value "$($indents[7])^idleTimeoutInMinutes^: 5" -Path $jsonFile
                            }
            }
                        Add-Content -Value "$($indents[6])}" -Path $jsonFile
                    Add-Content -Value "$($indents[5])}" -Path $jsonFile
                    LogMsg "Added loadBalancingRule Name:$RGName-LB-$($endpoint.Name) frontendPort:$($endpoint.PublicPort) backendPort:$($endpoint.LocalPort) Protocol:$($endpoint.Protocol)."
                    if ( $addedLBPort )
                    {
                        $addedLBPort += "-$($endpoint.Name)-$($endpoint.PublicPort)"
                    }
                    else
                    {
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
if ( $probePorts -gt 0 )
{
                Add-Content -Value "$($indents[4])," -Path $jsonFile
                Add-Content -Value "$($indents[4])^probes^:" -Path $jsonFile
                Add-Content -Value "$($indents[4])[" -Path $jsonFile

$EndPointAdded = $false
$addedProbes = $null
$role = 0
foreach ( $newVM in $RGXMLData.VirtualMachine)
{
    
    if($newVM.RoleName)
    {
        $vmName = $newVM.RoleName
    }
    else
    {
        $vmName = "$RGName-role-$role"
    }

    foreach ( $endpoint in $newVM.EndPoints)
    {
        if ( ($endpoint.LoadBalanced -eq "True") )
        { 
            if ( $endpoint.ProbePort -and !($addedProbes -imatch "$($endpoint.Name)-probe-$($endpoint.ProbePort)"))
            {
                if ( $EndPointAdded )
                {
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
                    LogMsg "Added probe :$RGName-LB-$($endpoint.Name)-probe Probe Port:$($endpoint.ProbePort) Protocol:$($endpoint.Protocol)."
                    if ( $addedProbes )
                    {
                        $addedProbes += "-$($endpoint.Name)-probe-$($endpoint.ProbePort)"
                    }
                    else
                    {
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
        LogMsg "Addded Load Balancer."
    #endregion

    $vmAdded = $false
    $role = 0
foreach ( $newVM in $RGXMLData.VirtualMachine)
{
    $VnetName = $RGXMLData.VnetName
    if ( $OverrideVMSize )
    {
        $instanceSize = $OverrideVMSize
    }
    elseif ( $CurrentTestData.OverrideVMSize)
    {
        $instanceSize = $CurrentTestData.OverrideVMSize
    }    
    else
    {
		$instanceSize = $newVM.ARMInstanceSize
    }
    
    $ExistingSubnet = $newVM.ARMSubnetName
    $DnsServerIP = $RGXMLData.DnsServerIP
    if($newVM.RoleName)
    {
        $vmName = $newVM.RoleName
    }
    else
    {
        $vmName = "$RGName-role-$role"
    }
    $NIC = "PrimaryNIC" + "-$vmName"

        if ( $vmAdded )
        {
            Add-Content -Value "$($indents[2])," -Path $jsonFile
        }

        #region networkInterfaces
        LogMsg "Adding Network Interface Card $NIC"
        Add-Content -Value "$($indents[2]){" -Path $jsonFile
            Add-Content -Value "$($indents[3])^apiVersion^: ^2016-09-01^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^type^: ^Microsoft.Network/networkInterfaces^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^name^: ^$NIC^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^dependsOn^: " -Path $jsonFile
            Add-Content -Value "$($indents[3])[" -Path $jsonFile
                if ( $EnableIPv6 )
                {
                Add-Content -Value "$($indents[4])^[concat('Microsoft.Network/publicIPAddresses/', variables('publicIPv6AddressName'))]^," -Path $jsonFile
                }
                Add-Content -Value "$($indents[4])^[concat('Microsoft.Network/publicIPAddresses/', variables('publicIPv4AddressName'))]^," -Path $jsonFile
            if(!$ExistingVnet)
            {
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
    foreach ( $endpoint in $newVM.EndPoints)
    {
        if ( !($endpoint.LoadBalanced) -or ($endpoint.LoadBalanced -eq "False") )
        {
            if ( $EndPointAdded )
            {
                                Add-Content -Value "$($indents[8])," -Path $jsonFile            
            }
                                Add-Content -Value "$($indents[8]){" -Path $jsonFile
                                    Add-Content -Value "$($indents[9])^id^:^[concat(variables('lbID'),'/inboundNatRules/$vmName-$($endpoint.Name)')]^" -Path $jsonFile
                                Add-Content -Value "$($indents[8])}" -Path $jsonFile
                                LogMsg "Enabled inboundNatRule Name:$vmName-$($endpoint.Name) frontendPort:$($endpoint.PublicPort) backendPort:$($endpoint.LocalPort) Protocol:$($endpoint.Protocol) to $NIC."
                                $EndPointAdded = $true
        }
    }

                            Add-Content -Value "$($indents[7])]," -Path $jsonFile
                                #endregion
                            
                            Add-Content -Value "$($indents[7])^subnet^:" -Path $jsonFile
                            Add-Content -Value "$($indents[7]){" -Path $jsonFile
                            if ( $existingSubnet )
                            {
                                Add-Content -Value "$($indents[8])^id^: ^[concat(variables('vnetID'),'/subnets/', '$existingSubnet')]^" -Path $jsonFile
                            }
                            else
                            {
                                Add-Content -Value "$($indents[8])^id^: ^[variables('defaultSubnetID')]^" -Path $jsonFile
                            }
                            Add-Content -Value "$($indents[7])}," -Path $jsonFile
                            Add-Content -Value "$($indents[7])^privateIPAllocationMethod^: ^Dynamic^" -Path $jsonFile
                        Add-Content -Value "$($indents[6])}" -Path $jsonFile
                    Add-Content -Value "$($indents[5])}" -Path $jsonFile
                #endregion



                #region IPv6 Config...
                if ( $EnableIPv6 )
                {
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
            if ($EnableAcceleratedNetworking -or $CurrentTestData.AdditionalHWConfig.Networking -imatch "SRIOV")
            {
                Add-Content -Value "$($indents[4])," -Path $jsonFile
                Add-Content -Value "$($indents[4])^enableAcceleratedNetworking^: true" -Path $jsonFile
                LogMsg "Enabled Accelerated Networking."
            }
            Add-Content -Value "$($indents[3])}" -Path $jsonFile


        Add-Content -Value "$($indents[2])}," -Path $jsonFile
        LogMsg "Added NIC $NIC.."
        #endregion

		#region multiple Nics
		[System.Collections.ArrayList]$NicNameList= @()
		foreach ($NetworkInterface in $newVM.NetworkInterfaces)
		{
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
            if ($EnableAcceleratedNetworking -or $CurrentTestData.AdditionalHWConfig.Networking -imatch "SRIOV")
            {
                Add-Content -Value "$($indents[4])," -Path $jsonFile
                Add-Content -Value "$($indents[4])^enableAcceleratedNetworking^: true" -Path $jsonFile
                LogMsg "Enabled Accelerated Networking for $NicName."
            }
				Add-Content -Value "$($indents[3])}" -Path $jsonFile
			Add-Content -Value "$($indents[2])}," -Path $jsonFile
        }
        
        #Add Bulk NICs
        $currentVMNics = 0
		while ($currentVMNics -lt $newVM.ExtraNICs)
		{
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
                                    LogMsg "  $NicName is part of subnet - ExtraSubnet-$currentVMNics"
								Add-Content -Value "$($indents[7])}" -Path $jsonFile
							Add-Content -Value "$($indents[6])}" -Path $jsonFile
						Add-Content -Value "$($indents[5])}" -Path $jsonFile
					Add-Content -Value "$($indents[4])]" -Path $jsonFile
            if ($EnableAcceleratedNetworking -or $CurrentTestData.AdditionalHWConfig.Networking -imatch "SRIOV")
            {
                Add-Content -Value "$($indents[4])," -Path $jsonFile
                Add-Content -Value "$($indents[4])^enableAcceleratedNetworking^: true" -Path $jsonFile
                LogMsg "  Enabled Accelerated Networking for $NicName."
            }
				Add-Content -Value "$($indents[3])}" -Path $jsonFile
			Add-Content -Value "$($indents[2])}," -Path $jsonFile
        }
                
		#endregion
        #region virtualMachines
        LogMsg "Adding Virtual Machine $vmName"
        Add-Content -Value "$($indents[2]){" -Path $jsonFile
            Add-Content -Value "$($indents[3])^apiVersion^: ^2017-03-30^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^type^: ^Microsoft.Compute/virtualMachines^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^name^: ^$vmName^," -Path $jsonFile
            Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
            if ($publisher -imatch "clear-linux-project")
            {
                LogMsg "  Adding plan information for clear-linux.."
                Add-Content -Value "$($indents[3])^plan^:" -Path $jsonFile
                Add-Content -Value "$($indents[3]){" -Path $jsonFile
                    Add-Content -Value "$($indents[4])^name^: ^$sku^," -Path $jsonFile
                    Add-Content -Value "$($indents[4])^product^: ^clear-linux-os^," -Path $jsonFile
                    Add-Content -Value "$($indents[4])^publisher^: ^clear-linux-project^" -Path $jsonFile
                Add-Content -Value "$($indents[3])}," -Path $jsonFile              
            }	    
            Add-Content -Value "$($indents[3])^tags^: {^GlobalRandom^: ^$GlobalRandom^}," -Path $jsonFile
            Add-Content -Value "$($indents[3])^dependsOn^: " -Path $jsonFile
            Add-Content -Value "$($indents[3])[" -Path $jsonFile
			if ($ExistingRG)
			{
				#Add-Content -Value "$($indents[4])^[concat('Microsoft.Compute/availabilitySets/', variables('availabilitySetName'))]^," -Path $jsonFile
			}
			else
			{
                Add-Content -Value "$($indents[4])^[concat('Microsoft.Compute/availabilitySets/', variables('availabilitySetName'))]^," -Path $jsonFile
			}
            if ( $NewARMStorageAccountType) 
            {
                Add-Content -Value "$($indents[4])^[concat('Microsoft.Storage/storageAccounts/', variables('StorageAccountName'))]^," -Path $jsonFile
            }
            if ( $OsVHD -and ($UseManagedDisks -or $UseManageDiskForCurrentTest) )
            {
                Add-Content -Value "$($indents[4])^[resourceId('Microsoft.Compute/images', '$RGName-Image')]^," -Path $jsonFile
            }
            
            if($NicNameList)
            {
                foreach($NicName in $NicNameList)
                {
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
                if ($ARMImage -and !$osVHD)
                {
                    LogMsg ">>Using ARMImage : $($ARMImage.Publisher):$($ARMImage.Offer):$($ARMImage.Sku):$($ARMImage.Version)"
                    Add-Content -Value "$($indents[5])^imageReference^ : " -Path $jsonFile
                    Add-Content -Value "$($indents[5]){" -Path $jsonFile
                        Add-Content -Value "$($indents[6])^publisher^: ^$publisher^," -Path $jsonFile
                        Add-Content -Value "$($indents[6])^offer^: ^$offer^," -Path $jsonFile
                        Add-Content -Value "$($indents[6])^sku^: ^$sku^," -Path $jsonFile
                        Add-Content -Value "$($indents[6])^version^: ^$version^" -Path $jsonFile
                    Add-Content -Value "$($indents[5])}," -Path $jsonFile
                }
                elseif ($CurrentTestData.Publisher -and $CurrentTestData.Offer)
                {
                    Add-Content -Value "$($indents[5])^imageReference^ : " -Path $jsonFile
                    Add-Content -Value "$($indents[5]){" -Path $jsonFile
                        Add-Content -Value "$($indents[6])^publisher^: ^$publisher^," -Path $jsonFile
                        Add-Content -Value "$($indents[6])^offer^: ^$offer^," -Path $jsonFile
                        Add-Content -Value "$($indents[6])^sku^: ^$sku^," -Path $jsonFile
                        Add-Content -Value "$($indents[6])^version^: ^$version^" -Path $jsonFile
                    Add-Content -Value "$($indents[5])}," -Path $jsonFile
                }
                elseif ( $OsVHD -and ($UseManagedDisks -or $UseManageDiskForCurrentTest) )
                {
                    Add-Content -Value "$($indents[5])^imageReference^ : " -Path $jsonFile
                    Add-Content -Value "$($indents[5]){" -Path $jsonFile
                        Add-Content -Value "$($indents[6])^id^: ^[resourceId('Microsoft.Compute/images', '$RGName-Image')]^," -Path $jsonFile
                    Add-Content -Value "$($indents[5])}," -Path $jsonFile                    
                }
                    Add-Content -Value "$($indents[5])^osDisk^ : " -Path $jsonFile
                    Add-Content -Value "$($indents[5]){" -Path $jsonFile
                    if($osVHD)
                    {
                        if ($UseManagedDisks -or $UseManageDiskForCurrentTest)
                        {
                            LogMsg ">>Using VHD : $osVHD (Converted to Managed Image)"
                            Add-Content -Value "$($indents[6])^osType^: ^Linux^," -Path $jsonFile
                            Add-Content -Value "$($indents[6])^name^: ^$vmName-OSDisk^," -Path $jsonFile
                            Add-Content -Value "$($indents[6])^managedDisk^: " -Path $jsonFile
                            Add-Content -Value "$($indents[6]){" -Path $jsonFile
                                Add-Content -Value "$($indents[7])^storageAccountType^: ^$StorageAccountType^" -Path $jsonFile
                    
                            Add-Content -Value "$($indents[6])}," -Path $jsonFile
                            Add-Content -Value "$($indents[6])^caching^: ^ReadWrite^," -Path $jsonFile
                            Add-Content -Value "$($indents[6])^createOption^: ^FromImage^" -Path $jsonFile
                        }
                        else 
                        {
                            LogMsg ">>Using VHD : $osVHD"
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
                    else
                    {
                        if ($UseManagedDisks -or $UseManageDiskForCurrentTest)
                        {
                            Add-Content -Value "$($indents[6])^name^: ^$vmName-OSDisk^," -Path $jsonFile
                            Add-Content -Value "$($indents[6])^createOption^: ^FromImage^," -Path $jsonFile
                            Add-Content -Value "$($indents[6])^managedDisk^: " -Path $jsonFile
                            Add-Content -Value "$($indents[6]){" -Path $jsonFile
                                Add-Content -Value "$($indents[7])^storageAccountType^: ^$StorageAccountType^" -Path $jsonFile
                            Add-Content -Value "$($indents[6])}" -Path $jsonFile
                            LogMsg "Added managed OS disk : $vmName-OSDisk"

                        }
                        else 
                        {
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
                    $dataDiskAdded = $false
                    Add-Content -Value "$($indents[5])^dataDisks^ : " -Path $jsonFile
                    Add-Content -Value "$($indents[5])[" -Path $jsonFile
                foreach ( $dataDisk in $newVM.DataDisk )
                {
                    if ( $dataDisk.LUN -ge 0 )
                    {
                        if( $dataDiskAdded )
                        {
                        Add-Content -Value "$($indents[6])," -Path $jsonFile
                        }

                        if ($UseManagedDisks -or $UseManageDiskForCurrentTest)
                        {
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
                        LogMsg "Added managed $($dataDisk.DiskSizeInGB)GB Datadisk to $($dataDisk.LUN)."
                        }
                        else 
                        {
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
                        LogMsg "Added unmanaged $($dataDisk.DiskSizeInGB)GB Datadisk to $($dataDisk.LUN)."
                        }
                        
                        $dataDiskAdded = $true
                    }
                }
                    Add-Content -Value "$($indents[5])]" -Path $jsonFile
                Add-Content -Value "$($indents[4])}" -Path $jsonFile

                Add-Content -Value "$($indents[4])," -Path $jsonFile
                #endregion
                
                LogMsg "Added Virtual Machine $vmName"

                #region Network Profile
                Add-Content -Value "$($indents[4])^networkProfile^: " -Path $jsonFile
                Add-Content -Value "$($indents[4]){" -Path $jsonFile
                    Add-Content -Value "$($indents[5])^networkInterfaces^: " -Path $jsonFile
                    Add-Content -Value "$($indents[5])[" -Path $jsonFile
					#region configure multiple Nics to networkProfile
					if($NicNameList)
					{
						foreach($NicName in $NicNameList)
						{
							Add-Content -Value "$($indents[6]){" -Path $jsonFile
								Add-Content -Value "$($indents[7])^id^: ^[resourceId('Microsoft.Network/networkInterfaces','$NicName')]^," -Path $jsonFile
								Add-Content -Value "$($indents[7])^properties^: { ^primary^: false }" -Path $jsonFile
							Add-Content -Value "$($indents[6])}," -Path $jsonFile
                            LogMsg "Attached Network Interface Card `"$NicName`" to Virtual Machine `"$vmName`"."
						}							
						Add-Content -Value "$($indents[6]){" -Path $jsonFile
							Add-Content -Value "$($indents[7])^id^: ^[resourceId('Microsoft.Network/networkInterfaces','$NIC')]^," -Path $jsonFile
							Add-Content -Value "$($indents[7])^properties^: { ^primary^: true }" -Path $jsonFile
						Add-Content -Value "$($indents[6])}" -Path $jsonFile
                        LogMsg "Attached Network Interface Card `"$NIC`" to Virtual Machine `"$vmName`"."
					}
					else
					{
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
        $role  = $role + 1
        $vmCount = $role
}
    Add-Content -Value "$($indents[1])]" -Path $jsonFile
    
    #endregion

Add-Content -Value "$($indents[0])}" -Path $jsonFile
Set-Content -Path $jsonFile -Value (Get-Content $jsonFile).Replace("^",'"') -Force
#endregion

    LogMsg "Template generated successfully."
    return $createSetupCommand,  $RGName, $vmCount
} 

Function DeployResourceGroups ($xmlConfig, $setupType, $Distro, $getLogsIfFailed = $false, $GetDeploymentStatistics = $false, [string]$region = "")
{
    if( (!$EconomyMode) -or ( $EconomyMode -and ($xmlConfig.config.$TestPlatform.Deployment.$setupType.isDeployed -eq "NO")))
    {
        try
        {

            $VerifiedGroups =  $NULL
            $retValue = $NULL
            #$ExistingGroups = RetryOperation -operation { Get-AzureRmResourceGroup } -description "Getting information of existing resource groups.." -retryInterval 5 -maxRetryCount 5
            $i = 0
            $role = 1
            $setupTypeData = $xmlConfig.config.$TestPlatform.Deployment.$setupType
            #DEBUGRG
            #$isAllDeployed = CreateAllResourceGroupDeployments -setupType $setupType -xmlConfig $xmlConfig -Distro $Distro -region $region -storageAccount $storageAccount -DebugRG "ICA-RG-M1S1-SSTEST-GZBX-636621761998"
            $isAllDeployed = CreateAllResourceGroupDeployments -setupType $setupType -xmlConfig $xmlConfig -Distro $Distro -region $region
            $isAllVerified = "False"
            $isAllConnected = "False"
            #$isAllDeployed = @("True","ICA-RG-IEndpointSingleHS-U1510-8-10-12-34-9","30")
            if($isAllDeployed[0] -eq "True")
            {
                $deployedGroups = $isAllDeployed[1]
                $resourceGroupCount = $isAllDeployed[2]
                $DeploymentElapsedTime = $isAllDeployed[3]
                $GroupsToVerify = $deployedGroups.Split('^')
                #if ( $GetDeploymentStatistics )
                #{
                #    $VMBooTime = GetVMBootTime -DeployedGroups $deployedGroups -TimeoutInSeconds 1800
                #    $verifyAll = VerifyAllDeployments -GroupsToVerify $GroupsToVerify -GetVMProvisionTime $GetDeploymentStatistics
                #    $isAllVerified = $verifyAll[0]
                #    $VMProvisionTime = $verifyAll[1]
                #}
                #else
                #{
                #    $isAllVerified = VerifyAllDeployments -GroupsToVerify $GroupsToVerify
                #}
                #if ($isAllVerified -eq "True")
                #{
                    $allVMData = GetAllDeployementData -ResourceGroups $deployedGroups
                    Set-Variable -Name allVMData -Value $allVMData -Force -Scope Global
                    $isAllConnected = isAllSSHPortsEnabledRG -AllVMDataObject $allVMData
                    if ($isAllConnected -eq "True")
                    {
                        $VerifiedGroups = $deployedGroups
                        $retValue = $VerifiedGroups
                        #$vnetIsAllConfigured = $false
                        $xmlConfig.config.$TestPlatform.Deployment.$setupType.isDeployed = $retValue
                        #Collecting Initial Kernel
                        if ( Test-Path -Path  .\Extras\UploadDeploymentDataToDB.ps1 )
                        {
                            $out = .\Extras\UploadDeploymentDataToDB.ps1 -allVMData $allVMData -DeploymentTime $DeploymentElapsedTime.TotalSeconds
                        }
                        $KernelLogOutput= GetAndCheckKernelLogs -allDeployedVMs $allVMData -status "Initial"
                    }
                    else
                    {
                        LogErr "Unable to connect Some/All SSH ports.."
                        $retValue = $NULL  
                    }
                #}
                #else
                #{
                #    Write-Host "Provision Failed for one or more VMs"
                #    $retValue = $NULL
                #}
                
            }
            else
            {
                LogErr "One or More Deployments are Failed..!"
                $retValue = $NULL
            }
            # get the logs of the first provision-failed VM
            #if ($retValue -eq $NULL -and $getLogsIfFailed -and $DebugOsImage)
            #{
            #    foreach ($service in $GroupsToVerify)
            #    {
            #        $VMs = Get-AzureVM -ServiceName $service
            #        foreach ($vm in $VMs)
            #        {
            #            if ($vm.InstanceStatus -ne "ReadyRole" )
            #            {
            #                $out = GetLogsFromProvisionFailedVM -vmName $vm.Name -serviceName $service -xmlConfig $xmlConfig
            #                return $NULL
            #            }
            #        }
            #    }
            #}
        }
        catch
        {
            LogMsg "Exception detected. Source : DeployVMs()"
            $line = $_.InvocationInfo.ScriptLineNumber
            $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
            $ErrorMessage =  $_.Exception.Message
            LogErr "EXCEPTION : $ErrorMessage"
            LogErr "Source : Line $line in script $script_name."              
            $retValue = $NULL
        }
    }
    else
    {
        $retValue = $xmlConfig.config.$TestPlatform.Deployment.$setupType.isDeployed
        $KernelLogOutput= GetAndCheckKernelLogs -allDeployedVMs $allVMData -status "Initial"
    }
    if ( $GetDeploymentStatistics )
    {
        return $retValue, $DeploymentElapsedTime
    }
    else
    {
        return $retValue
    }
}

Function isAllSSHPortsEnabledRG($AllVMDataObject)
{
    LogMsg "Trying to Connect to deployed VM(s)"
    $timeout = 0
    do
    {
        $WaitingForConnect = 0
        foreach ( $vm in $AllVMDataObject)
        {
            $out = Test-TCP  -testIP $($vm.PublicIP) -testport $($vm.SSHPort)
            if ($out -ne "True")
            {
                LogMsg "Connecting to  $($vm.PublicIP) : $($vm.SSHPort) : Failed"
                $WaitingForConnect = $WaitingForConnect + 1
            }
            else
            {
                LogMsg "Connecting to  $($vm.PublicIP) : $($vm.SSHPort) : Connected"
            }
        }
        if($WaitingForConnect -gt 0)
        {
            $timeout = $timeout + 1
            LogMsg "$WaitingForConnect VM(s) still awaiting to open SSH port.."
            LogMsg "Retry $timeout/100"
            sleep 3
            $retValue = "False"
        }
        else
        {
            LogMsg "ALL VM's SSH port is/are open now.."
            $retValue = "True"
        }

    }
    While (($timeout -lt 100) -and ($WaitingForConnect -gt 0))

    #Following Code will be enabled once https://github.com/Azure/azure-powershell/issues/4168 issue resolves.

    #if ($retValue -eq "False")
    #{
    #    foreach ( $vm in $AllVMDataObject)
    #    {
    #        $out = Test-TCP  -testIP $($vm.PublicIP) -testport $($vm.SSHPort)
    #        if ($out -ne "True")
    #        {
    #            LogMsg "Getting boot diagnostic data from $($vm.RoleName)"
    #            $bootData = Get-AzureRmVMBootDiagnosticsData -ResourceGroupName $vm.ResourceGroupName -Name $vm.RoleName -Linux
    #            Set-Content -Value $bootData -Path "$LogDir\$($vm.RoleName)-SSH-Fail-Boot-Logs.txt"
    #        }
    #    }
    #}

    return $retValue
}

Function CreateRGDeploymentWithTempParameters([string]$RGName, $TemplateFile, $TemplateParameterFile)
{
    $FailCounter = 0
    $retValue = "False"
    $ResourceGroupDeploymentName = "eosg" + (Get-Date).Ticks
    While(($retValue -eq $false) -and ($FailCounter -lt 1))
    {
        try
        {
            $FailCounter++
            LogMsg "Creating Deployment using $TemplateFile $TemplateParameterFile..."
            $createRGDeployment = New-AzureRmResourceGroupDeployment -Name $ResourceGroupDeploymentName -ResourceGroupName $RGName -TemplateFile $TemplateFile -TemplateParameterFile $TemplateParameterFile -Verbose
            $operationStatus = $createRGDeployment.ProvisioningState
            if ($operationStatus  -eq "Succeeded")
            {
                LogMsg "Resource Group Deployment Created."
                $retValue = $true
            }
            else 
            {
                LogErr "Failed to create Resource Group Deployment."
                $retValue = $false
            }
        }
        catch
        {
            $retValue = $false
        }
    }
    return $retValue
}

Function CreateAllRGDeploymentsWithTempParameters($templateName, $location, $TemplateFile, $TemplateParameterFile)
{
    $resourceGroupCount = 0
    $curtime = Get-Date
    $isServiceDeployed = "False"
    $retryDeployment = 0
    $groupName = "ICA-RG-" + $templateName + "-" + $curtime.Month + "-" +  $curtime.Day  + "-" + $curtime.Hour + "-" + $curtime.Minute + "-" + $curtime.Second

    while (($isServiceDeployed -eq "False") -and ($retryDeployment -lt 3))
    {
        LogMsg "Creating Resource Group : $groupName."
        LogMsg "Verifying that Resource group name is not in use."
        $isRGDeleted = DeleteResourceGroup -RGName $groupName
        if ($isRGDeleted)
        {    
            $isServiceCreated = CreateResourceGroup -RGName $groupName -location $location
            if ($isServiceCreated -eq "True")
            {
                $DeploymentStartTime = (Get-Date)
				$CreateRGDeployments = CreateRGDeploymentWithTempParameters -RGName $groupName -location $location -TemplateFile $TemplateFile -TemplateParameterFile $TemplateParameterFile
                $DeploymentEndTime = (Get-Date)
                $DeploymentElapsedTime = $DeploymentEndTime - $DeploymentStartTime
                if ( $CreateRGDeployments )
                {
                        $retValue = "True"
                        $isServiceDeployed = "True"
                        $resourceGroupCount = $resourceGroupCount + 1
                        $deployedGroups = $groupName

                }
                else
                {
                    LogErr "Unable to Deploy one or more VM's"
                    $retryDeployment = $retryDeployment + 1
                    $retValue = "False"
                    $isServiceDeployed = "False"
                }
            }
            else
            {
                LogErr "Unable to create $groupName"
                $retryDeployment = $retryDeployment + 1
                $retValue = "False"
                $isServiceDeployed = "False"
            }
        }    
        else
        {
            LogErr "Unable to delete existing resource group - $groupName"
            $retryDeployment = $retryDeployment + 1
            $retValue = "False"
            $isServiceDeployed = "False"
        }
    }
    return $retValue, $deployedGroups, $resourceGroupCount, $DeploymentElapsedTime
}

Function CopyVHDToAnotherStorageAccount ($sourceStorageAccount,$sourceStorageContainer,$destinationStorageAccount,$destinationStorageContainer,$vhdName,$destVHDName)
{
    $retValue = $false
    if (!$destVHDName)
    {
        $destVHDName = $vhdName
    }
    $saInfoCollected = $false
    $retryCount = 0
    $maxRetryCount = 999
    while(!$saInfoCollected -and ($retryCount -lt $maxRetryCount))
    {
        try
        {
            $retryCount += 1
            LogMsg "[Attempt $retryCount/$maxRetryCount] : Getting Existing Storage Account details ..."
            $GetAzureRmStorageAccount = $null
            $GetAzureRmStorageAccount = Get-AzureRmStorageAccount
            if ($GetAzureRmStorageAccount -eq $null)
            {
                throw
            }
            $saInfoCollected = $true
        }
        catch
        {
            $saInfoCollected = $false
            LogErr "Error in fetching Storage Account info. Retrying in 10 seconds."
            sleep -Seconds 10
        }
    }

    LogMsg "Retrieving $sourceStorageAccount storage account key"
    $SrcStorageAccountKey = (Get-AzureRmStorageAccountKey -ResourceGroupName $(($GetAzureRmStorageAccount  | Where {$_.StorageAccountName -eq "$sourceStorageAccount"}).ResourceGroupName) -Name $sourceStorageAccount)[0].Value
    [string]$SrcStorageAccount = $sourceStorageAccount
    [string]$SrcStorageBlob = $vhdName
    $SrcStorageContainer = $sourceStorageContainer


    LogMsg "Retrieving $destinationStorageAccount storage account key"
    $DestAccountKey= (Get-AzureRmStorageAccountKey -ResourceGroupName $(($GetAzureRmStorageAccount  | Where {$_.StorageAccountName -eq "$destinationStorageAccount"}).ResourceGroupName) -Name $destinationStorageAccount)[0].Value
    [string]$DestAccountName =  $destinationStorageAccount
    [string]$DestBlob = $destVHDName
    $DestContainer = $destinationStorageContainer

    $context = New-AzureStorageContext -StorageAccountName $srcStorageAccount -StorageAccountKey $srcStorageAccountKey 
    $expireTime = Get-Date
    $expireTime = $expireTime.AddYears(1)
    $SasUrl = New-AzureStorageBlobSASToken -container $srcStorageContainer -Blob $srcStorageBlob -Permission R -ExpiryTime $expireTime -FullUri -Context $Context 

    $destContext = New-AzureStorageContext -StorageAccountName $destAccountName -StorageAccountKey $destAccountKey
    $testContainer = Get-AzureStorageContainer -Name $destContainer -Context $destContext -ErrorAction Ignore
    if ($testContainer -eq $null) 
    {
        $out = New-AzureStorageContainer -Name $destContainer -context $destContext
    }
    # Start the Copy
    LogMsg "Copy $vhdName --> $($destContext.StorageAccountName) : Running"
    $out = Start-AzureStorageBlobCopy -AbsoluteUri $SasUrl  -DestContainer $destContainer -DestContext $destContext -DestBlob $destBlob -Force
    #
    # Monitor replication status
    #
    $CopyingInProgress = $true
    while($CopyingInProgress)
    {
        $CopyingInProgress = $false
        $status = Get-AzureStorageBlobCopyState -Container $destContainer -Blob $destBlob -Context $destContext   
        if ($status.Status -ne "Success") 
        {
            $CopyingInProgress = $true
        }
        else
        {
            LogMsg "Copy $DestBlob --> $($destContext.StorageAccountName) : Done"
            $retValue = $true

        }
        if ($CopyingInProgress)
        {
            $copyPercentage = [math]::Round( $(($status.BytesCopied * 100 / $status.TotalBytes)) , 2 )
            LogMsg "Bytes Copied:$($status.BytesCopied), Total Bytes:$($status.TotalBytes) [ $copyPercentage % ]"            
            Sleep -Seconds 10
        }
    }
    return $retValue
}

Function SetResourceGroupLock ([string]$ResourceGroup,  [string]$LockNote, [string]$LockName="ReproVM",  $LockType = "CanNotDelete")
{
    $parameterErrors = 0
    if ($LockNote -eq $null)
    {
        LogErr "You did not provide -LockNote <string>. Please give a valid note."
        $parameterErrors += 1
    }
    if ($ResourceGroup -eq $null)
    {
        LogErr "You did not provide -ResourceGroup <string>.."
        $parameterErrors += 1
    }
    if ($parameterErrors -eq 0)
    {
        LogMsg "Adding '$LockName' lock to '$ResourceGroup'"
        $lock = Set-AzureRmResourceLock -LockName $LockName -LockLevel $LockType -LockNotes $LockNote -Force -ResourceGroupName $ResourceGroup
        if ( $lock.Properties.level -eq $LockType)
        {
            LogMsg ">>>$ResourceGroup LOCKED<<<."
        }
        else 
        {
            LogErr "Something went wrong. Please try again."    
        }
    }
    else
    {
        LogMsg "Fix the paremeters and try again."    
    }
}

Function RestartAllAzureDeployments($allVMData)
{
	$currentGUID = ([guid]::newguid()).Guid
	$out = Save-AzureRmContext -Path "$env:TEMP\$($currentGUID).azurecontext" -Force
	$restartJobs = @()	
	foreach ( $vmData in $AllVMData )
	{
		if ( $UseAzureResourceManager)
		{
			LogMsg "Triggering Restart-$($vmData.RoleName)..."
			$restartJobs += Start-Job -ScriptBlock { $vmData = $args[0]
				$currentGUID = $args[1]
				Import-AzureRmContext -AzureContext "$env:TEMP\$($currentGUID).azurecontext"
				$restartVM = Restart-AzureRmVM -ResourceGroupName $vmData.ResourceGroupName -Name $vmData.RoleName -Verbose
			} -ArgumentList $vmData,$currentGUID -Name "Restart-$($vmData.RoleName)"
		}
		else
		{
			$restartVM = Restart-AzureVM -ServiceName $vmData.ServiceName -Name $vmData.RoleName -Verbose
			$isRestarted = $?
			if ($isRestarted)
			{
				LogMsg "Restarted : $($vmData.RoleName)"
			}
			else
			{
				LogError "FAILED TO RESTART : $($vmData.RoleName)"
				$retryCount = $retryCount + 1
				if ($retryCount -gt 0)
				{
					LogMsg "Retrying..."
				}
				if ($retryCount -eq 0)
				{
					Throw "Calling function - $($MyInvocation.MyCommand). Unable to Restart : $($vmData.RoleName)"
				}
			}
		}
	}
	$recheckAgain = $true
	LogMsg "Waiting until VMs restart..."
	$jobCount = $restartJobs.Count
	$completedJobsCount = 0
	While ($recheckAgain)
	{
		$recheckAgain = $false
		$tempJobs = @()
		foreach ($restartJob in $restartJobs)
		{
			if ($restartJob.State -eq "Completed")
			{
				$completedJobsCount += 1
				LogMsg "[$completedJobsCount/$jobCount] $($restartJob.Name) is done."
				$out = Remove-Job -Id $restartJob.ID -Force -ErrorAction SilentlyContinue
			}
			else
			{
				$tempJobs += $restartJob
				$recheckAgain = $true
			}
		}
		$restartJobs = $tempJobs
		Start-Sleep -Seconds 1
	}
	
	Remove-Item -Path "$env:TEMP\$($currentGUID).azurecontext" -Force -ErrorAction SilentlyContinue | Out-Null
	$isSSHOpened = isAllSSHPortsEnabledRG -AllVMDataObject $AllVMData
	return $isSSHOpened
}