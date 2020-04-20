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
        Function Set-Usage($currentStatus, $VMFamily, $usage, $AllowedUsagePercentage) {
            $counter = 0
            foreach ($item in $currentStatus) {
                if ($item.Name.Value -eq $VMFamily) {
                    $allowedCount = [int](($currentStatus[$counter].Limit) * ($AllowedUsagePercentage / 100))
                    Write-LogInfo "  Current $VMFamily usage : $($currentStatus[$counter].CurrentValue) cores. Requested:$usage. Estimated usage=$($($currentStatus[$counter].CurrentValue) + $usage). Max Allowed cores:$allowedCount/$(($currentStatus[$counter].Limit))"
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

        Function Test-Usage($currentStatus, $VMFamily, $AllowedUsagePercentage) {
            $overFlowErrors = 0
            $counter = 0
            foreach ($item in $currentStatus) {
                if ($item.Name.Value -eq $VMFamily) {
                    $allowedCount = [int](($currentStatus[$counter].Limit) * ($AllowedUsagePercentage / 100))
                    #Write-LogInfo "Max allowed $($item.Name.LocalizedValue) usage : $allowedCount out of $(($currentStatus[$counter].Limit))."
                    if ($currentStatus[$counter].CurrentValue -gt $allowedCount) {
                        Write-LogErr "  Current $VMFamily Estimated use: $($currentStatus[$counter].CurrentValue)"
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

        # Get the Azure Compute SKU details
        Write-LogInfo "Getting Azure 'ComputeSKU' details..."
        $ComputeSKU = Get-AzComputeResourceSku

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

        $PremiumStorageVMFamilies = @("standardDSFamily",
        "standardDSv2Family",
        "standardDSv2PromoFamily",
        "standardDSv3Family",
        "standardFSFamily"
        )

        #Get the region
        $currentStatus = Get-AzVMUsage -Location $Location
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
                $testVMUsage = (Get-AzVMSize -Location $Location | Where-Object { $_.Name -eq $testVMSize}).NumberOfCores
            }

            $DetectedVMFamily = ($ComputeSKU | Where-Object { $_.Name -eq $testVMSize }).Family | Get-Unique
            if ($DetectedVMFamily) {
                $currentStatus = Set-Usage -currentStatus $currentStatus -VMFamily $DetectedVMFamily  -usage $testVMUsage -AllowedUsagePercentage $AllowedUsagePercentage
                $overFlowErrors += Test-Usage -currentStatus $currentStatus -VMFamily $DetectedVMFamily -AllowedUsagePercentage $AllowedUsagePercentage
            } else {
                Write-LogInfo "Requested VM size: $testVMSize is not yet registered to monitor. Usage simulation skipped."
            }
            if ($PremiumStorageVMFamilies.Contains($DetectedVMFamily)){
                $premiumVMs += 1
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
    $currentRGCount = (Get-AzResourceGroup).Count
    $overFlowErrors += Check-OverflowErrors -ResourceType "Resource Group" -CurrentValue $currentRGCount `
        -RequiredValue 1 -MaximumLimit $RGLimit -AllowedUsagePercentage $AllowedUsagePercentage
    #endregion

    #region Storage Accounts
    $currentStorageStatus = Get-AzStorageUsage -Location $Location
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

    $GetAzureRmNetworkUsage = Get-AzNetworkUsage -Location $Location

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

Function Change-StorageAccountType($TestCaseData, [string]$Location, $GlobalConfig, $OsVHD) {
    $storageAccount = $GlobalConfig.Global.Azure.Subscription.ARMStorageAccount
    $changedSC = ""
    $copyVHD = $false
    if ($TestCaseData.AdditionalHWConfig.StorageAccountType -and $TestCaseData.AdditionalHWConfig.StorageAccountType.Contains("Premium")) {
        # if SC is ExistingStorage_Standard, switch to ExistingStorage_Premium
        if ($storageAccount -imatch "ExistingStorage_Standard") {
            $changedSC = Get-StorageAccountFromRegion -Region $Location -StorageAccount "ExistingStorage_Premium"
            # if it is OsVHD format, need copy VHD from standard to premium storage account
            if ($OsVHD) {
                $copyVHD = $true
            }
        # if SC is NewStorage_Standard, switch to NewStorage_Premium
        } elseif ($storageAccount -imatch "NewStorage_Standard") {
            $changedSC = "NewStorage_Premium_LRS"
        } elseif (($storageAccount -imatch "NewStorage_Premium") -or ($storageAccount -imatch "ExistingStorage_Premium")) {
            $changedSC = ""
        } else {
            $current_sc = Get-StorageAccountFromRegion -Region $Location -StorageAccount "ExistingStorage_Standard"
            if ($current_sc -eq $storageAccount) {
                $changedSC = Get-StorageAccountFromRegion -Region $Location -StorageAccount "ExistingStorage_Premium"
                if ($OsVHD) {
                    $copyVHD = $true
                }
            } else {
                $storageAccountType = (Get-AzStorageAccount | Where-Object {$_.StorageAccountName -eq $storageAccount}).Sku.Tier.ToString()
                if ($storageAccountType -inotmatch "premium") {
                    Write-LogErr "Provided storage account is not premium type, this case $($TestCaseData.testName) need run under premium type of storage account."
                    Throw "Case $($TestCaseData.testName) need run under premium type of storage account."
                }
            }
        }
    }

    if ($copyVHD) {
        $sourceContainer =  $osVHD.Split("/")[$osVHD.Split("/").Count - 2]
        $vhdName = $osVHD.Split("?")[0].split('/')[-1]
        Write-LogInfo "Copy VHD from $storageAccount to $changedSC."
        if(($OsVHD -imatch 'sp=') -and ($OsVHD -imatch 'sig=')) {
            $copyStatus = Copy-VHDToAnotherStorageAccount -SasUrl $osVHD -destinationStorageAccount $changedSC `
                -destinationStorageContainer "vhds" -vhdName $vhdName
        } else {
            $copyStatus = Copy-VHDToAnotherStorageAccount -sourceStorageAccount $storageAccount -sourceStorageContainer $sourceContainer `
                -destinationStorageAccount $changedSC -destinationStorageContainer "vhds" -vhdName $vhdName
        }
        if (!$copyStatus) {
            Throw "Failed to copy the VHD $storageAccount to $changedSC."
        }
    }

    return $changedSC
}

Function Create-AllResourceGroupDeployments($SetupTypeData, $TestCaseData, $Distro, [string]$TestLocation, $GlobalConfig, $TiPSessionId, $TipCluster, $UseExistingRG, $ResourceCleanup, $PlatformFaultDomainCount, $PlatformUpdateDomainCount) {
	Function Write-AzureDeployJSONFile ($RGName, $ImageName, $osVHD, $RGXMLData, $Location, $azuredeployJSONFilePath, $CurrentTestData, $StorageAccountName) {
		#Random Data
		$RGrandomWord = ([System.IO.Path]::GetRandomFileName() -replace '[^a-z]')
		$RGRandomNumber = Get-Random -Minimum 11111 -Maximum 99999

		$UseManagedDisks = $CurrentTestData.AdditionalHWConfig.DiskType -inotcontains "unmanaged"
		if ($UseManagedDisks) {
			$DiskType = "Managed"
		} else {
			$DiskType = "Unmanaged"
		}

		$UseSpecializedImage = $CurrentTestData.AdditionalHWConfig.ImageType -contains "Specialized"
		$IsWindowsOS = $CurrentTestData.AdditionalHWConfig.OSType -contains "Windows"
		if ($IsWindowsOS) {
			$OSType = "Windows"
		} else {
			$OSType = "Linux"
		}
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
				$GetAzureRMStorageAccount = Get-AzStorageAccount
				if ($null -eq $GetAzureRMStorageAccount) {
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
		if($osVHD) {
			$osVHD = $osVHD.Split("?")[0].split('/')[-1]
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
		$sshKeyData = $global:sshPublicKey
		$createAvailabilitySet = !$UseExistingRG

		if ($UseExistingRG) {
			$existentAvailabilitySet = Get-AzResource | Where-Object { (( $_.ResourceGroupName -eq $RGName ) -and ( $_.ResourceType -imatch "availabilitySets" ))} | `
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
		if ($null -ne $RGXMLData.ARMVnetName) {
			$ExistingVnet = $RGXMLData.ARMVnetName
			Write-LogInfo "Getting $ExistingVnet Virtual Netowrk info ..."
			$ExistingVnetResourceGroupName = ( Get-AzResource | Where-Object {$_.Name -eq $ExistingVnet}).ResourceGroupName
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

			$faultDomainCount = 2
			$updateDomainCount = 5
			if ($PlatformFaultDomainCount) {
				$faultDomainCount = $PlatformFaultDomainCount
			}
			if ($PlatformUpdateDomainCount) {
				$updateDomainCount = $PlatformUpdateDomainCount
			}
			Add-Content -Value "$($indents[3])^properties^:" -Path $jsonFile
			Add-Content -Value "$($indents[3]){" -Path $jsonFile
			Add-Content -Value "$($indents[4])^platformFaultDomainCount^:$faultDomainCount," -Path $jsonFile
			Add-Content -Value "$($indents[4])^platformUpdateDomainCount^:$updateDomainCount" -Path $jsonFile
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
			Add-Content -Value "$($indents[3])^apiVersion^: ^2019-03-01^," -Path $jsonFile
			Add-Content -Value "$($indents[3])^type^: ^Microsoft.Compute/images^," -Path $jsonFile
			Add-Content -Value "$($indents[3])^name^: ^$RGName-Image^," -Path $jsonFile
			Add-Content -Value "$($indents[3])^location^: ^[variables('location')]^," -Path $jsonFile
			Add-Content -Value "$($indents[3])^properties^:" -Path $jsonFile
			Add-Content -Value "$($indents[3]){" -Path $jsonFile
			Add-Content -Value "$($indents[4])^storageProfile^: " -Path $jsonFile
			Add-Content -Value "$($indents[4]){" -Path $jsonFile

			Add-Content -Value "$($indents[5])^osDisk^: " -Path $jsonFile
			Add-Content -Value "$($indents[5]){" -Path $jsonFile
			Add-Content -Value "$($indents[6])^osType^: ^$OSType^," -Path $jsonFile
			Add-Content -Value "$($indents[6])^osState^: ^Generalized^," -Path $jsonFile
			Add-Content -Value "$($indents[6])^blobUri^: ^https://$StorageAccountName.blob.core.windows.net/vhds/$OsVHD^," -Path $jsonFile
			Add-Content -Value "$($indents[6])^storageAccountType^: ^$StorageAccountType^" -Path $jsonFile
			Add-Content -Value "$($indents[5])}" -Path $jsonFile

			Add-Content -Value "$($indents[4])}" -Path $jsonFile
			if ($VMGeneration -eq "2") {
				Add-Content -Value "$($indents[4]),^hyperVGeneration^: ^V2^" -Path $jsonFile
			} else {
				Add-Content -Value "$($indents[4]),^hyperVGeneration^: ^V1^" -Path $jsonFile
			}
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

		#region New ARM Boot Diagnostic Account if Storage Account Type is Premium LRS.
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
		Write-LogInfo "Added Load Balancer."
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
				if (!$sshKeyData) {
					Add-Content -Value "$($indents[5])^adminPassword^: ^[variables('adminPassword')]^" -Path $jsonFile
				} else {
					Add-Content -Value "$($indents[5])^linuxConfiguration^:" -Path $jsonFile
					Add-Content -Value "$($indents[5]){" -Path $jsonFile
						Add-Content -Value "$($indents[6])^disablePasswordAuthentication^:true," -Path $jsonFile
						Add-Content -Value "$($indents[6])^ssh^:" -Path $jsonFile
						Add-Content -Value "$($indents[6]){" -Path $jsonFile
							Add-Content -Value "$($indents[7])^publicKeys^:" -Path $jsonFile
							Add-Content -Value "$($indents[7])[" -Path $jsonFile
								Add-Content -Value "$($indents[8]){" -Path $jsonFile
									Add-Content -Value "$($indents[9])^path^:^$sshPath^," -Path $jsonFile
									Add-Content -Value "$($indents[9])^keyData^:^$sshKeyData^" -Path $jsonFile
								Add-Content -Value "$($indents[8])}" -Path $jsonFile
							Add-Content -Value "$($indents[7])]" -Path $jsonFile
						Add-Content -Value "$($indents[6])}" -Path $jsonFile
					Add-Content -Value "$($indents[5])}" -Path $jsonFile
				}
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
				if ($UseManagedDisks) {
					Write-LogInfo ">>> Using VHD : $osVHD (Converted to Managed Image)"
					Add-Content -Value "$($indents[6])^osType^: ^$OSType^," -Path $jsonFile
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
						Add-Content -Value "$($indents[6])^osType^: ^$OSType^," -Path $jsonFile
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
						Add-Content -Value "$($indents[6])^osType^: ^$OSType^," -Path $jsonFile
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

    $resourceGroupCount = 0
    $outputError = ""
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
    $storageAccount = Change-StorageAccountType -Location $location -TestCaseData $TestCaseData -GlobalConfig $GlobalConfig -OsVHD $OsVHD
    if ($storageAccount) {
        $used_SC = $storageAccount
    } else {
        $used_SC = $GlobalConfig.Global.Azure.Subscription.ARMStorageAccount
    }
    foreach ($RG in $setupTypeData.ResourceGroup ) {
        $validateStartTime = Get-Date
        Write-LogInfo "Checking the subscription usage..."
        $readyToDeploy = $false
        $coreCountExceededTimeout = 3600
        while (!$readyToDeploy) {
            $readyToDeploy = Validate-SubscriptionUsage -RGXMLData $RG -Location $location -OverrideVMSize $TestCaseData.OverrideVMSize `
                                -StorageAccount $used_SC
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
                        $null = Write-AzureDeployJSONFile -RGName $groupName -ImageName $osImage -osVHD $osVHD -RGXMLData $RG -Location $location `
                                -azuredeployJSONFilePath $azureDeployJSONFilePath -CurrentTestData $TestCaseData `
                                -StorageAccountName $used_SC

                        $DeploymentStartTime = (Get-Date)
                        $CreateRGDeployments = Create-ResourceGroupDeployment -RGName $groupName -TemplateFile $azureDeployJSONFilePath `
                                -UseExistingRG $UseExistingRG

                        $DeploymentEndTime = (Get-Date)
                        $DeploymentElapsedTime = $DeploymentEndTime - $DeploymentStartTime
                        if ( $CreateRGDeployments.Status ) {
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
                            $outputError = "Unable to Deploy one or more VM's. " + $CreateRGDeployments.Error
                            Write-LogErr $outputError
                            $retryDeployment = $retryDeployment + 1
                            $retValue = "False"
                            $isServiceDeployed = "False"
                        }
                    }
                    else {
                        $outputError = "Unable to create $groupName"
                        Write-LogErr $outputError
                        $retryDeployment = $retryDeployment + 1
                        $retValue = "False"
                        $isServiceDeployed = "False"
                    }
                } else {
                    $outputError = "Unable to delete existing resource group - $groupName."
                    Write-LogErr $outputError
                    $retryDeployment = 3
                    $retValue = "False"
                    $isServiceDeployed = "False"
                }
            }
        } else {
            $outputError = "Core quota is not sufficient. Stopping VM deployment."
            Write-LogErr $outputError
            $retValue = "False"
            $isServiceDeployed = "False"
        }
    }
    return $retValue, $deployedGroups, $resourceGroupCount, $DeploymentElapsedTime, $outputError
}

Function Start-DeleteResourceGroup ([string]$RGName) {
    $DeleteScriptBlock = {
        $ResourceGroupName = $args[0]
        $WorkingDirectory = $args[1]
        $XMLSecrets = $args[2]

        # This script block runs in background in new Powershell instance.
        # The variables declared here, don't interact with parent powershell instance.
        Set-Location -Path $WorkingDirectory
        Set-Variable -Name LogDir -Value $WorkingDirectory -Scope Global -Force
        Set-Variable -Name LogFileName -Value "Start-DeleteResourceGroup.txt" -Scope Global -Force

        # Authenticate this background powershell session.
        $XmlFilePath = "$WorkingDirectory\AzureSecret-$((Get-Date).Ticks).xml"
        $XMLSecrets.Save($XmlFilePath)
        [void](.\Utilities\AddAzureRmAccountFromSecretsFile.ps1 -customSecretsFilePath $XmlFilePath)
        [void](Remove-Item -Path $XmlFilePath -Force)

        # Get the required resource details.
        $StorageAccounts = Get-AzStorageAccount
        $VMs = Get-AzVm -ResourceGroupName $ResourceGroupName

        # Start the VM Cleanup
        $Jobs = @()
        foreach ($VM in $VMs) {
            Write-LogInfo "[Background Job] : Removing $($VM.Name)"
            $Jobs += $VM | Remove-AzVM -Force -AsJob
        }

        # Wait till all VMs are removed.
        $VMCount = (Get-AzVm -ResourceGroupName $ResourceGroupName).Count
        $MaxAttempts = 1800 # Giving ~30 minutes to delete
        while ($VMCount -gt 0 -and $MaxAttempts -gt 0) {
            $MaxAttempts -= 1
            $VMCount = (Get-AzVm -ResourceGroupName $ResourceGroupName).Count
            Write-LogInfo "[Background Job] : Pending cleanup of $VMCount VMs in $ResourceGroupName"
            Start-Sleep -Seconds 10
        }
        Write-LogInfo "[Background Job] : Cleaned $($VMs.Count) VMs in $ResourceGroupName"
        $Jobs | Remove-Job -Force

        # Start the Disk Cleanup
        foreach ($VM in $VMs) {
            if ($VM.StorageProfile.OSDisk.Vhd) {
                # Remove the unmanaged OS Disks
                $OsDiskURI = $VM.StorageProfile.OSDisk.Vhd.Uri
                $OsDiskName = $OsDiskURI.Split('/')[-1]
                $OsDiskContainerName = $OsDiskURI.Split('/')[-2]
                $OsDiskStorageAccountName = $OsDiskURI.Split('/')[2].Split('.')[0]
                $VHDStorageAccount = $StorageAccounts | Where-Object { $_.StorageAccountName -eq $OsDiskStorageAccountName }
                Write-LogInfo "[Background Job] : DeleteResourceGroup: Removing OS Disk : $OsDiskName"
                $null = $VHDStorageAccount | Remove-AzStorageBlob -Container $OsDiskContainerName -Blob $OsDiskName -Force -Verbose

                # Remove unmanaged data disks
                foreach ($uri in $VM.StorageProfile.DataDisks.Vhd.Uri) {
                    $DataDiskStorageAccountName = $uri.Split('/')[2].Split('.')[0]
                    $DataDiskContainerName = $uri.Split('/')[-2]
                    $DataDiskName = $uri.Split('/')[-1]
                    $DataDiskStorageAccount = $StorageAccounts | Where-Object { $_.StorageAccountName -eq $DataDiskStorageAccountName }
                    Write-LogInfo "[Background Job] : DeleteResourceGroup: Removing Data Disk  : $DataDiskName"
                    $DataDiskStorageAccount | Remove-AzStorageBlob -Container $DataDiskContainerName -Blob $DataDiskName -Verbose -Force
                }
            }
        }

        # Remove the resource group which will remove all the remaining resources.
        $MaxRetryAttemts = 10
        Write-LogInfo "[Background Job] : Removing Resource Group : $ResourceGroupName"
        $RemoveJob = Remove-AzResourceGroup -ResourceGroupName $ResourceGroupName -Force -AsJob
        $isDeleting = (Get-AzResourceGroup -ResourceGroupName $ResourceGroupName).ProvisioningState -eq "Deleting"
        while (!$isDeleting -and $MaxRetryAttemts -gt 0) {
            $RgStatus = (Get-AzResourceGroup -ResourceGroupName $ResourceGroupName).ProvisioningState
            $MaxRetryAttemts -= 1
            $isDeleting = $RgStatus -eq "Deleting"
            Write-LogInfo "[Background Job] : Removing Resource Group : $ResourceGroupName : $RgStatus. Remaining attempts - $MaxRetryAttemts"
            Start-Sleep -Seconds 5
        }
        Write-LogInfo "[Background Job] : Removing Resource Group : $ResourceGroupName : $RgStatus"
        $RemoveJob | Remove-Job -Force
    }

    # Check if VMs have unmanaged disks
    $BackgroundCleanupStarted = $false
    Write-LogInfo "Checking for any unmanaged disks in $RGName ..."
    $VMs = Get-AzVm -ResourceGroupName $RGName
    if ( ($VMs.StorageProfile.OSDisk.Vhd.Uri.Count -gt 0) -or ($VMs.StorageProfile.Datadisks.Vhd.Uri.Count -gt 0) ) {
        $UnManagedOSDisksCount = $VMs.StorageProfile.OSDisk.Vhd.Uri.Count
        $UnManagedDataDisksCount = $VMs.StorageProfile.DataDisks.Vhd.Uri.Count
        $UnmanagedDiskCount = $UnManagedOSDisksCount + $UnManagedDataDisksCount
    } else {
        $UnmanagedDiskCount = 0
    }
    if ($UnmanagedDiskCount -gt 0) {
        if ($Global:XMLSecrets.secrets.SubscriptionServicePrincipalTenantID -and `
            $Global:XMLSecrets.secrets.SubscriptionServicePrincipalClientID -and `
            $Global:XMLSecrets.secrets.SubscriptionServicePrincipalKey) {
            # Unmanaged VHD cleanup is only possible when XML Secrets file (with service principal) is given, since Azure context files authentication doesn't work for background jobs.
            # Azure powershell issue : https://github.com/Azure/azure-powershell/issues/9448
            # Once this issue is resolved, we can use context file authentication for background cleanup.

            Write-LogInfo "Detected unmanaged disks. OS Disks: $UnManagedOSDisksCount, DataDisks: $UnManagedDataDisksCount"
            $null = Start-Job -Name "DeleteResourceGroup-$RGName" `
                -ScriptBlock $DeleteScriptBlock `
                -ArgumentList $RGName,$WorkingDirectory,$Global:XMLSecrets
            $VMStatus = (Get-AzVM -ResourceGroupName $RGName ).ProvisioningState | Get-Unique
            $isDeleting = $VMStatus -eq "Deleting"

            # Give at least 30 seconds to start all the VM cleanup operations.
            # Timeout is adjusted based on number of VMs.
            $MaxAttempts = 10 + ($VMs.Count*2)
            while (!$isDeleting -and $MaxAttempts -gt 0) {
                $MaxAttempts -= 1
                Write-LogInfo "Current VM Status: $VMStatus(Running). Checking again if VM cleanup is started... (Remaining attempts: $MaxAttempts)"
                $VMs = Get-AzVM -ResourceGroupName $RGName
                $VMStatus = $VMs.ProvisioningState | Get-Unique
                $VMStatusCount = $VMStatus.Count
                if ($VMStatusCount -eq 1) {
                     if ( $VMStatus -eq "Deleting" ) {
                         $isDeleting = $true
                         $BackgroundCleanupStarted = $true
                    }
                } else {
                    $isDeleting = $false
                }
                Start-Sleep -Seconds 3
            }
            Write-LogInfo "Current VM Status: $VMStatus."
        } else {
            Write-LogWarn "$UnmanagedDiskCount will be left undeleted due to XML secret file is not available."
            Write-LogInfo "Proceeding resource group cleanup."
            $BackgroundCleanupStarted = $false
        }
    } else {
        Write-LogInfo "No any unmanaged VHDs found. Proceeding resource group cleanup."
        $BackgroundCleanupStarted = $false
    }
    if (-not $BackgroundCleanupStarted) {
        # Give 30 seconds to start all the Resource group cleanup operation.
        $MaxRetryAttemts = 10
        $null = Remove-AzResourceGroup -ResourceGroupName $RGName -AsJob -Force
        $isDeleting = (Get-AzResourceGroup -ResourceGroupName $RGName).ProvisioningState -eq "Deleting"
        while (!$isDeleting -and $MaxRetryAttemts -gt 0) {
            $MaxRetryAttemts -= 1
            Write-LogInfo "Retrying 'Remove-AzResourceGroup -ResourceGroupName $RGName'. Remaining attempts : $MaxRetryAttemts"
            $null = Remove-AzResourceGroup -ResourceGroupName $RGName -AsJob -Force
            $isDeleting = (Get-AzResourceGroup -ResourceGroupName $RGName).ProvisioningState -eq "Deleting"
            Start-Sleep -Seconds 3
        }
    }
    return $isDeleting
}
Function Delete-ResourceGroup([string]$RGName, [switch]$KeepDisks, [bool]$UseExistingRG) {
    Write-LogInfo "Try to delete resource group $RGName..."
    try {
        Write-LogInfo "Checking if $RGName exists..."
        $ResourceGroup = Get-AzResourceGroup -Name $RGName -ErrorAction Ignore
    }
    catch {
        Write-LogInfo "Failed to get resource group: $RGName; maybe this resource group does not exist."
    }
    if ($ResourceGroup) {
        # Get RG lock. If there is any lock in place, don't try to delete the Resource Group
        # "Microsoft.Authorization/locks" is the standard ResourceType for RG locks
        $rgLock = (Get-AzResourceLock -ResourceGroupName $RGName).ResourceType -eq "Microsoft.Authorization/locks"
        if (-not $rgLock) {
            if ($UseExistingRG) {
                $CurrentResources = Get-AzResource -ResourceGroupName $RGName | `
                    Where-Object { (( $_.ResourceGroupName -eq $RGName ) -and ( !($_.ResourceType -imatch "availabilitySets" )))}
                $attempts = 0
                while (($CurrentResources) -and ($attempts -le 10)) {
                    $CurrentResources = Get-AzResource -ResourceGroupName $RGName | `
                        Where-Object { (( $_.ResourceGroupName -eq $RGName ) -and ( !($_.ResourceType -imatch "availabilitySets" )))}
                    $unlockedResources = @()
                    # Get the lock for each resource and compute a list of "unlocked" resources
                    foreach ($resource in $CurrentResources) {
                        $resourceLock = Get-AzResourceLock -ResourceGroupName $RGName `
                            -ResourceType $resource.ResourceType -ResourceName $resource.Name
                        if (-not $resourceLock) {
                            $unlockedResources += $resource
                        }
                    }
                    # Only try to delete the "unlocked" resources
                    foreach ($resource in $unlockedResources) {
                        Write-LogInfo "Removing resource $($resource.Name), type $($resource.ResourceType)"
                        try {
                            $current_resource = Get-AzResource -ResourceId $resource.ResourceId -ErrorAction Ignore
                            if ($current_resource) {
                                $null = Remove-AzResource -ResourceId $resource.ResourceId -Force -Verbose
                            }
                        } catch {
                            Write-LogErr "Failed to delete resource $($resource.Name). We will try to remove it in next attempt."
                        }
                    }
                    $CurrentResources = $unlockedResources
                    $attempts++
                }
                Write-LogInfo "Resources in $RGName are deleted."
                $retValue = $true
            } else {
                Write-LogInfo "Triggering delete operation for Resource Group ${RGName}"
                $isRgDeleting = Start-DeleteResourceGroup -RGName $RGName
                if ($isRgDeleting) {
                    Write-LogInfo "Successfully triggered delete operation for Resource Group ${RGName}"
                } else {
                    Write-LogWarn "Failed to start delete operation for Resource Group ${RGName}"
                }
                $retValue = $isRgDeleting
            }
        } else {
            Write-LogWarn "Lock is in place for $RGName. Skipping RG delete!"
            $retValue = $false
        }
    } else {
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
                $createRG = New-AzResourceGroup -Name $RGName -Location $location.Replace('"', '') -Force -Verbose
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

Function Create-ResourceGroupDeployment([string]$RGName, $TemplateFile, $UseExistingRG, $ResourceCleanup) {
    $retValue = $false
    $errMsg = ""
    $ResourceGroupDeploymentName = "eosg" + (Get-Date).Ticks
    try {
        Write-LogInfo "Testing Deployment using $TemplateFile ..."
        $testRGDeployment = Test-AzResourceGroupDeployment -ResourceGroupName $RGName -TemplateFile $TemplateFile -Verbose
        if (-not $testRGDeployment.Message) {
            Write-LogInfo "Creating Deployment using $TemplateFile ..."
            $createRGDeployment = New-AzResourceGroupDeployment -Name $ResourceGroupDeploymentName `
                                    -ResourceGroupName $RGName -TemplateFile $TemplateFile -Verbose
            $operationStatus = $createRGDeployment.ProvisioningState
            if ($operationStatus -eq "Succeeded") {
                Write-LogInfo "Resource Group Deployment created."
                $retValue = $true
            }
            else {
                # region grab deplyoment operations failures
                $failedDeplyomentOperations = Get-AzResourceGroupDeploymentOperation `
                    -ResourceGroupName $RGName -DeploymentName $createRGDeployment.DeploymentName `
                    | Where-Object { $_.Properties.provisioningState -ne "Succeeded" }
                foreach ($operation in $failedDeplyomentOperations) {
                    $statusObj = $operation.Properties.StatusMessage
                    if ($statusObj.Error) {
                        if ($statusObj.Error.Details) {
                            $errMsg += $statusObj.Error.Details.Message + "`r`n"
                        } else {
                            $errMsg += $statusObj.Error.Message + "`r`n"
                        }
                    } else {
                        $errMsg += $statusObj + "`r`n"
                    }
                }
                Write-LogErr $errMsg
                #endregion

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
                    $VMsCreated = Get-AzVM -ResourceGroupName $RGName
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
        } else {
            $errMsg = $testRGDeployment.Message
            Write-LogErr "Resource group configuration is not valid: $errMsg"
        }
    }
    catch {
        $line = $_.InvocationInfo.ScriptLineNumber
        $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
        $errMsg = "Exception in Create-ResourceGroupDeployment. Source : Line $line in script $script_name."
        Write-LogErr $errMsg
    }
    return @{ "Status" = $retValue ; "Error" = $errMsg }
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
        Add-Member -InputObject $objNode -MemberType NoteProperty -Name VMGeneration -Value $VMGeneration -Force
        return $objNode
    }

    foreach ($ResourceGroup in $ResourceGroups.Split("^"))
    {
        Write-LogInfo "Collecting $ResourceGroup data.."

        Write-LogInfo "	Microsoft.Network/publicIPAddresses data collection in progress.."
        $RGIPsdata = Get-AzResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/publicIPAddresses" -Verbose
        Write-LogInfo "	Microsoft.Compute/virtualMachines data collection in progress.."
        $RGVMs = Get-AzResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Compute/virtualMachines" -Verbose
        Write-LogInfo "	Microsoft.Network/networkInterfaces data collection in progress.."
        $NICdata = Get-AzResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/networkInterfaces" -Verbose
        $currentRGLocation = (Get-AzResourceGroup -ResourceGroupName $ResourceGroup).Location
        Write-LogInfo "	Microsoft.Network/loadBalancers data collection in progress.."
        $LBdata = Get-AzResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/loadBalancers" -Verbose
        foreach($ipData in $RGIPsdata) {
            if ((Get-AzPublicIpAddress -Name $ipData.name -ResourceGroupName $ipData.ResourceGroupName).IpAddress -ne "Not Assigned") {
                $RGIPdata = $ipData
            }
        }

        $AllVMs = Get-AzVM -ResourceGroupName $ResourceGroup
        foreach ($testVM in $RGVMs)
        {
            $testVMDetails = $AllVMs | Where-Object { $_.Name -eq $testVM.Name }
            $QuickVMNode = Create-QuickVMNode
            $lbDetails = Get-AzLoadBalancer -ResourceGroupName $ResourceGroup -Name $LBdata.Name
            $InboundNatRules = $lbDetails.InboundNatRules
            foreach ($endPoint in $InboundNatRules)
            {
                if ( $endPoint.Name -imatch $testVM.ResourceName)
                {
                    $endPointName = "$($endPoint.Name)".Replace("$($testVM.ResourceName)-","")
                    Add-Member -InputObject $QuickVMNode -MemberType NoteProperty -Name "$($endPointName)Port" -Value $endPoint.FrontendPort -Force
                }
            }
            $LoadBalancingRules = $lbDetails.LoadBalancingRules
            foreach ( $LBrule in $LoadBalancingRules )
            {
                if ( $LBrule.Name -imatch "$ResourceGroup-LB-" )
                {
                    $endPointName = "$($LBrule.Name)".Replace("$ResourceGroup-LB-","")
                    Add-Member -InputObject $QuickVMNode -MemberType NoteProperty -Name "$($endPointName)Port" -Value $LBrule.FrontendPort -Force
                }
            }
            $Probes = $lbDetails.Probes
            foreach ( $Probe in $Probes )
            {
                if ( $Probe.Name -imatch "$ResourceGroup-LB-" )
                {
                    $probeName = "$($Probe.Name)".Replace("$ResourceGroup-LB-","").Replace("-probe","")
                    Add-Member -InputObject $QuickVMNode -MemberType NoteProperty -Name "$($probeName)ProbePort" -Value $Probe.Port -Force
                }
            }

            $AllNICs = Get-AzNetworkInterface -ResourceGroupName $ResourceGroup
            foreach ( $nic in $NICdata )
            {
                $nicDetails = $AllNICs | Where-Object { $_.Name -eq $nic.Name }
                if (($nic.Name.Replace("PrimaryNIC-","") -eq $testVM.ResourceName) -and ( $nic.Name -imatch "PrimaryNIC"))
                {
                    $QuickVMNode.InternalIP = "$($nicDetails.IpConfigurations[0].PrivateIPAddress)"
                }
                if (($nic.Name.Replace("ExtraNetworkCard-1-","") -eq $testVM.ResourceName) -and ($nic.Name -imatch "ExtraNetworkCard-1"))
                {
                    $QuickVMNode.SecondInternalIP = "$($nicDetails.IpConfigurations[0].PrivateIPAddress)"
                }
            }
            $QuickVMNode.ResourceGroupName = $ResourceGroup
            $ipDetails = Get-AzPublicIpAddress -Name $RGIPData.Name -ResourceGroupName $ResourceGroup
            $QuickVMNode.PublicIP = ($ipDetails | Where-Object { $_.publicIPAddressVersion -eq "IPv4" }).ipAddress
            $QuickVMNode.PublicIPv6 = ($ipDetails | Where-Object { $_.publicIPAddressVersion -eq "IPv6" }).ipAddress
            $QuickVMNode.URL = ($ipDetails | Where-Object { $_.publicIPAddressVersion -eq "IPv4" }).dnsSettings.fqdn
            $QuickVMNode.URLv6 = ($ipDetails | Where-Object { $_.publicIPAddressVersion -eq "IPv6" }).dnsSettings.fqdn
            $QuickVMNode.RoleName = $testVM.ResourceName
            $QuickVMNode.Status = $testVMDetails.ProvisioningState
            $QuickVMNode.InstanceSize = $testVMDetails.hardwareProfile.vmSize
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

Function Create-RGDeploymentWithTempParameters([string]$RGName, $TemplateFile, $TemplateParameterFile) {
    $FailCounter = 0
    $retValue = "False"
    $ResourceGroupDeploymentName = "eosg" + (Get-Date).Ticks
    While (($retValue -eq $false) -and ($FailCounter -lt 1)) {
        try {
            $FailCounter++
            Write-LogInfo "Creating Deployment using $TemplateFile $TemplateParameterFile..."
            $createRGDeployment = New-AzResourceGroupDeployment -Name $ResourceGroupDeploymentName -ResourceGroupName $RGName -TemplateFile $TemplateFile -TemplateParameterFile $TemplateParameterFile -Verbose
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
            $GetAzureRmStorageAccount = Get-AzStorageAccount
            if ($null -eq $GetAzureRmStorageAccount) {
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
        $SrcStorageAccountKey = (Get-AzStorageAccountKey -ResourceGroupName $(($GetAzureRmStorageAccount  | Where-Object {$_.StorageAccountName -eq "$sourceStorageAccount"}).ResourceGroupName) -Name $sourceStorageAccount)[0].Value
        [string]$SrcStorageAccount = $sourceStorageAccount
        [string]$SrcStorageBlob = $vhdName
        $SrcStorageContainer = $sourceStorageContainer
        $context = New-AzStorageContext -StorageAccountName $srcStorageAccount -StorageAccountKey $srcStorageAccountKey
        $expireTime = Get-Date
        $expireTime = $expireTime.AddYears(1)
        $SasUrl = New-AzStorageBlobSASToken -container $srcStorageContainer -Blob $srcStorageBlob -Permission R -ExpiryTime $expireTime -FullUri -Context $Context
}

    Write-LogInfo "Retrieving $destinationStorageAccount storage account key"
    $DestAccountKey = (Get-AzStorageAccountKey -ResourceGroupName $(($GetAzureRmStorageAccount  | Where-Object {$_.StorageAccountName -eq "$destinationStorageAccount"}).ResourceGroupName) -Name $destinationStorageAccount)[0].Value
    [string]$DestAccountName = $destinationStorageAccount
    [string]$DestBlob = $destVHDName
    $DestContainer = $destinationStorageContainer

    $destContext = New-AzStorageContext -StorageAccountName $destAccountName -StorageAccountKey $destAccountKey
    $testContainer = Get-AzStorageContainer -Name $destContainer -Context $destContext -ErrorAction Ignore
    if ($null -eq $testContainer) {
        $null = New-AzStorageContainer -Name $destContainer -context $destContext
    }
    # Start the Copy
    Write-LogInfo "Copy $vhdName --> $($destContext.StorageAccountName) : Running"
    $null = Start-AzStorageBlobCopy -AbsoluteUri $SasUrl  -DestContainer $destContainer -DestContext $destContext -DestBlob $destBlob -Force
    #
    # Monitor replication status
    #
    $CopyingInProgress = $true
    while ($CopyingInProgress) {
        $CopyingInProgress = $false
        $status = Get-AzStorageBlobCopyState -Container $destContainer -Blob $destBlob -Context $destContext
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
            $AllNics = Get-AzNetworkInterface -ResourceGroupName $ResourceGroup `
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
                    $null = Stop-AzVM -ResourceGroup $ResourceGroup -Name $VMName -Force
                    foreach ($TargetNic in $TargettedNics) {
                        #Enable EnableAccelerated Networking
                        $TargetNic.EnableAcceleratedNetworking = $true
                        $ChangedNic = $TargetNic | Set-AzNetworkInterface
                        $VMPropertiesChanged = $true
                        if ( $ChangedNic.EnableAcceleratedNetworking -eq $true) {
                            Write-LogInfo "$($TargetNic.Name) [EnableAcceleratedNetworking=true]| Set-AzNetworkInterface : SUCCESS"
                        } else {
                            Write-LogInfo "$($TargetNic.Name) [EnableAcceleratedNetworking=true]| Set-AzNetworkInterface : FAIL"
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
                    $null = Stop-AzVM -ResourceGroup $ResourceGroup -Name $VMName -Force
                    foreach ($TargetNic in $TargettedNics) {
                        #Enable EnableAccelerated Networking
                        $TargetNic.EnableAcceleratedNetworking = $false
                        $ChangedNic = $TargetNic | Set-AzNetworkInterface
                        $VMPropertiesChanged = $true
                        if ( $ChangedNic.EnableAcceleratedNetworking -eq $false) {
                            Write-LogInfo "$($TargetNic.Name) [EnableAcceleratedNetworking=false] | Set-AzNetworkInterface : SUCCESS"
                        } else {
                            Write-LogInfo "$($TargetNic.Name) [EnableAcceleratedNetworking=false] | Set-AzNetworkInterface : FAIL"
                        }
                    }
                }
            }

            if ( $VMPropertiesChanged ) {
                # Start the VM..
                Write-LogInfo "Starting VM $($VMName)..."
                $null = Start-AzVM -ResourceGroupName $ResourceGroup -Name $VMName -NoWait
                if ($? -eq "True") {
                    Write-Loginfo "Start-AzVM command executes successfully."
                } else {
                    Write-LogErr "Start-AzVM command executes failed."
                }
                $vm = Get-AzVM -ResourceGroupName $ResourceGroup -Name $VMName -Status
                $MaxAttempts = 30
                while (($vm.Statuses[-1].Code -ne "PowerState/running") -and ($MaxAttempts -gt 0)) {
                    Write-LogInfo "Attempt $(31 - $MaxAttempts) - VM $($VMName) is in $($vm.Statuses[-1].Code) state, still not in running state, wait for 20 seconds..."
                    Start-Sleep -Seconds 20
                    $MaxAttempts -= 1
                    $vm = Get-AzVM -ResourceGroupName $ResourceGroup -Name $VMName -Status
                }
                # Public IP address changes most of the times, when we shutdown the VM.
                # Hence, we need to refresh the data
                $VMData = Get-AllDeploymentData -ResourceGroups $ResourceGroup
                $TestVMData = $VMData | Where-Object {$_.ResourceGroupName -eq $ResourceGroup `
                    -and $_.RoleName -eq $VMName }

                $isVmAlive = Is-VmAlive -AllVMDataObject $TestVMData -MaxRetryCount 70
                if ($isVmAlive -eq "True") {
                    $isRestarted = $true
                } else {
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

                $AllNics = Get-AzNetworkInterface -ResourceGroupName $ResourceGroup `
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
        $ExistingTags = (Get-AzResourceGroup -Name $ResourceGroup).Tags
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
        Set-AzResourceGroup -Name $ResourceGroup -Tag $hash | Out-Null
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
    $vmStatus = Get-AzVM -ResourceGroupName $Vm.ResourceGroupName -VMName $Vm.RoleName -Status
    if ($vmStatus -and $vmStatus.BootDiagnostics) {
        if ($vmStatus.BootDiagnostics.SerialConsoleLogBlobUri) {
            Write-LogInfo "Getting serial boot logs of VM $($Vm.RoleName)"
            try {
                $uri = [System.Uri]$vmStatus.BootDiagnostics.SerialConsoleLogBlobUri
                $storageAccountName = $uri.Host.Split(".")[0]
                $diagnosticRG = ((Get-AzStorageAccount) | Where-Object {$_.StorageAccountName -eq $storageAccountName}).ResourceGroupName.ToString()
                $key = (Get-AzStorageAccountKey -ResourceGroupName $diagnosticRG -Name $storageAccountName)[0].value
                $diagContext = New-AzStorageContext -StorageAccountName $storageAccountName -StorageAccountKey $key
                Get-AzStorageBlobContent -Blob $uri.LocalPath.Split("/")[2] `
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
        if ($diagFileContent -like "*Kernel panic - not syncing:*" -or $diagFileContent -like "*RIP:*" `
              -or $diagFileContent -like '*grub>*') {
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

function Get-CurrentAzurePSAuthStatus() {
    try {
        $UserSubscriptions = Get-AzSubscription
        $SubscriptionUser = $UserSubscriptions.ExtendedProperties.Account | Get-Unique
        if ($UserSubscriptions.Count -gt 0) {
            Write-LogInfo "Current Azure powershell session is authenticated by $SubscriptionUser."
            return $true
        } else {
            Write-LogErr "Current Azure powershell session is authenticated by $SubscriptionUser, but does not contain any Azure subscriptions."
            return $false
        }
    } catch {
        Write-LogErr "Current Azure powershell session is not authenticated."
        return $false
    }
}

Function Import-AzureContextFile ($FilePath) {
    try {
        $ImportedSession = Import-AzContext -Path $FilePath
        if ($ImportedSession.Context.Account.Id) {
            Write-LogInfo "Imported $($ImportedSession.Context.Account.Id) user session."
            return $true
        } else {
            Write-LogErr "$FilePath is not a valid Azure context file."
            return $false
        }
    }
    catch {
        $ErrorMessage = $_.Exception.Message
        $ErrorLine = $_.InvocationInfo.ScriptLineNumber
        Write-LogErr "EXCEPTION in Import-AzureContextFile() : $ErrorMessage at line: $ErrorLine"
        return $false
    }
}
function Add-AzureAccountFromSecretsFile {
    param(
        $CustomSecretsFilePath
    )

    $UserAuthenticated = $false

    if ($env:Azure_Secrets_File) {
        $secretsFile = $env:Azure_Secrets_File
        Write-LogInfo "Using secrets file: $secretsFile, defined in environments."
    } elseif ( $CustomSecretsFilePath ) {
        $secretsFile = $CustomSecretsFilePath
        Write-LogInfo "Using provided secrets file: $secretsFile"
    }

    if ( ($null -eq $secretsFile) -or ($secretsFile -eq [string]::Empty)) {
        Write-LogErr "The Secrets file is not being set."
        Raise-Exception ("XML Secrets file not provided")
    }

    if ( Test-Path $secretsFile ) {
        Write-LogInfo "$secretsFile found."
        $XmlSecrets = [xml](Get-Content $secretsFile)
        $ClientID = $XmlSecrets.secrets.SubscriptionServicePrincipalClientID
        $TenantID = $XmlSecrets.secrets.SubscriptionServicePrincipalTenantID
        $Key = $XmlSecrets.secrets.SubscriptionServicePrincipalKey
        $AzureContextFilePath = $XmlSecrets.secrets.AzureContextFilePath
        $subIDSplitted = ($XmlSecrets.secrets.SubscriptionID).Split("-")
        $subIDMasked = "$($subIDSplitted[0])-xxxx-xxxx-xxxx-$($subIDSplitted[4])"

        # Collect the context files, if any.
        $ContextFiles = (Get-ChildItem -Path $PWD -Recurse | `
            Where-Object { $_.Name.EndsWith(".json") } | Select-String -Pattern "AzureCloud" | Select-Object Path).Path | Get-Unique

        Write-LogInfo "------------------------------------------------------------------"
        if ($ClientID -and $Key) {
            # Scenario 1: Service Principal Credentials are avaialble in Secret File
            Write-LogInfo "Authenticating Azure PS session using Service Principal..."
            $pass = ConvertTo-SecureString $key -AsPlainText -Force
            $mycred = New-Object System.Management.Automation.PSCredential ($ClientID, $pass)
            $null = Add-AzAccount -ServicePrincipal -Tenant $TenantID -Credential $mycred
            $UserAuthenticated = $true
        } elseif ($AzureContextFilePath) {
            # Scenario 2: Azure context file path is avaialble in Secret File
            Write-LogInfo "Authenticating Azure PS session using saved context file $AzureContextFilePath..."
            if ( Import-AzureContextFile -FilePath $AzureContextFilePath ) {
                $UserAuthenticated = $true
            }
        } elseif ($ContextFiles.Count -gt 0)  {
            # Scenario 3: Azure context file is available in current working directory.
            if ($ContextFiles.Count -eq 1) {
                Write-LogInfo "Authenticating Azure PS session using $ContextFiles found in working directory."
                if ( Import-AzureContextFile -FilePath $ContextFiles ) {
                    $UserAuthenticated = $true
                }
            } else {
                Write-LogWarn "$($ContextFiles.Count) Azure context files found in $pwd."
                $Counter = 1
                foreach ( $file in $ContextFiles ) {
                    Write-LogWarn "$Counter. $file"
                }
                Write-LogWarn "Please remove unwanted context files. Expected context files: 1."
            }
        } else {
            # Scenario 4: Current Azure Powershell session check.
            Write-LogWarn "No Azure authentication methods were available in Secret File."
            Write-LogWarn "No Azure authentication context files detected in $PWD."
            Write-LogInfo "Checking if Current Azure powershell session is authenticated..."
            if (Get-CurrentAzurePSAuthStatus) {
                $UserAuthenticated = $true
            }
        }
        #endregion User Authentication.

        if ( $UserAuthenticated ) {
            #Verify if the user is Authorized to use the subscription.
            $selectedSubscription = Select-AzSubscription -SubscriptionId $XmlSecrets.secrets.SubscriptionID  -ErrorAction SilentlyContinue
            if ( $selectedSubscription.Subscription.Id -eq $XmlSecrets.secrets.SubscriptionID ) {
                Write-LogInfo "Current Subscription : $subIDMasked."
            } else {
                Throw "There was an error when selecting $subIDMasked."
            }
        } else {
            Write-LogErr "Unable to proceed with unauthenticated Azure powershell session."
            Write-LogInfo "Please use one of the following method to authenticate this session."
            Write-LogInfo "1. Provide service principal details in XML secrets file."
            Write-LogInfo "    a. SubscriptionServicePrincipalClientID"
            Write-LogInfo "    b. SubscriptionServicePrincipalTenantID"
            Write-LogInfo "    c. SubscriptionServicePrincipalKey"
            Write-LogInfo "2. Provide the path of authenticated context file in XML secrets file."
            Write-LogInfo "    a. AzureContextFilePath"
            Write-LogInfo "3. Copy only 1 authenticated context file in $PWD"
            Write-LogInfo "4. Authenticate this current session by running Connect-AzAccount command, and then run LISAv2 again."
            Throw "User authenticatin failed / not available."
        }
        Write-LogInfo "------------------------------------------------------------------"
    } else {
        Write-LogErr "Secret file $secretsFile does not exist"
        Raise-Exception ("XML Secrets file not provided")
    }
}

Function Upload-AzureBootAndDeploymentDataToDB ($DeploymentTime, $AllVMData, $CurrentTestData) {
    try {
        $TextIdentifiers = [xml](Get-Content -Path ".\XML\Other\text-identifiers.xml")
        $walaStartIdentifier = ""
        $walaEndIdentifier = ""
        $WalaIdentifiersDetected = $false

        Write-LogInfo "Started boot data telemetry collection..."
        $utctime = (Get-Date).ToUniversalTime()
        $DateTimeUTC = "$($utctime.Year)-$($utctime.Month)-$($utctime.Day) $($utctime.Hour):$($utctime.Minute):$($utctime.Second)"

        # Get the subscription data
        $SubscriptionID = $Global:XMLSecrets.secrets.SubscriptionID
        $SubscriptionName = $Global:XMLSecrets.secrets.SubscriptionName

        # Get the Database data
        $dataSource = $Global:XMLSecrets.secrets.DatabaseServer
        $dbuser = $Global:XMLSecrets.secrets.DatabaseUser
        $dbpassword = $Global:XMLSecrets.secrets.DatabasePassword
        $database = $Global:XMLSecrets.secrets.DatabaseName

        # Set the Database table
        $dataTableName = "LinuxDeploymentAndBootData"

        # Set the destination for uploading kernel and wala logs.
        $storageAccountName = $Global:XMLSecrets.secrets.bootPerfLogsStorageAccount
        $storageAccountKey = $Global:XMLSecrets.secrets.bootPerfLogsStorageAccountKey

        # Get the test case data and storage profile
        $TestCaseName = $CurrentTestData.testName
        $StorageProfile = (Get-AzVM -ResourceGroupName $allVMData[0].ResourceGroupName  -Name $allVMData[0].RoleName).StorageProfile
        if ($StorageProfile.OsDisk.ManagedDisk.StorageAccountType) {
            $StorageType = $StorageProfile.OsDisk.ManagedDisk.StorageAccountType
        } else {
            $OsVHdStorageAccountName = $StorageProfile.OsDisk.Vhd.Uri.Split(".").split("/")[2]
            $StorageResourceGroup = (Get-AzResource  | Where-Object {$_.ResourceType -imatch "Microsoft.Storage/storageAccounts" -and $_.Name -eq "$OsVHdStorageAccountName"}).ResourceGroupName
            $StorageType = (Get-AzStorageAccount -ResourceGroupName $StorageResourceGroup -Name $OsVHdStorageAccountName).Sku.Name
        }
        $NumberOfVMsInRG = 0
        foreach ( $vmData in $allVMData ) {
            $NumberOfVMsInRG += 1
        }

        $SQLQuery = "INSERT INTO $dataTableName (DateTimeUTC,TestPlatform,TestLocation,TestCaseName,SubscriptionID,SubscriptionName,ResourceGroupName,NumberOfVMsInRG,RoleName,DeploymentTime,KernelBootTime,WALAProvisionTime,HostVersion,GuestDistro,KernelVersion,LISVersion,WALAVersion,RoleSize,StorageType,CallTraces,kernelLogFile,WALAlogFile) VALUES "

        foreach ( $vmData in $allVMData ) {
            $ResourceGroupName = $vmData.ResourceGroupName
            $RoleName = $vmData.RoleName
            $RoleSize = $vmData.InstanceSize

            #Copy and run test file
            $null = Copy-RemoteFiles -upload -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\Testscripts\Linux\CollectLogFile.sh" -username $user -password $password
            $null = Run-LinuxCmd -username $user -password $password -ip $vmData.PublicIP -port $vmData.SSHPort -command "bash CollectLogFile.sh" -ignoreLinuxExitCode

            #download the log files
            $null = Copy-RemoteFiles -downloadFrom $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -files "$($vmData.RoleName)-*.txt" -downloadTo "$LogDir" -download

            # Upload files in data subfolder to Azure.
            $destfolder = "bootPerf"
            $containerName = "logs"
            $blobContext = New-AzStorageContext -StorageAccountName $storageAccountName -StorageAccountKey $storageAccountKey

            $ticks = (Get-Date).Ticks
            $fileName = "$LogDir\$($vmData.RoleName)-waagent.log.txt"
            $blobName = "$destfolder/$($fileName.Replace("waagent","waagent-$ticks") | Split-Path -Leaf)"
            $null = Set-AzStorageBlobContent -File $filename -Container $containerName -Blob $blobName -Context $blobContext -Force
            $WALAlogFile = "https://$storageAccountName.blob.core.windows.net/$containerName/$destfolder/$($fileName.Replace("waagent","waagent-$ticks") | Split-Path -Leaf)"
            Write-LogInfo "Upload file to Azure: Success: $WALAlogFile"
            $fileName = "$LogDir\$($vmData.RoleName)-dmesg.txt"
            $blobName = "$destfolder/$($fileName.Replace("dmesg","dmesg-$ticks") | Split-Path -Leaf)"
            $null = Set-AzStorageBlobContent -File $filename -Container $containerName -Blob $blobName -Context $blobContext -Force
            $kernelLogFile = "https://$storageAccountName.blob.core.windows.net/$containerName/$destfolder/$($fileName.Replace("dmesg","dmesg-$ticks") | Split-Path -Leaf)"
            Write-LogInfo "Upload file to Azure: Success: $kernelLogFile"


            # Analyse
            $waagentFile = "$LogDir\$($vmData.RoleName)-waagent.log.txt"
            $waagentLogs = Get-Content -Path $waagentFile

            #region Detect the WALA identifiers
            foreach ($line in $waagentLogs.Split("`n")) {
                foreach ( $keyword in $TextIdentifiers.identifiers.waagent.ProvisionStarted.keyword ) {
                    if ($line -imatch $keyword) {
                        $walaStartIdentifier = $keyword
                    }
                }
                foreach ( $keyword in $TextIdentifiers.identifiers.waagent.ProvisionComplete.keyword ) {
                    if ($line -imatch $keyword) {
                        $walaEndIdentifier = $keyword
                    }
                }
                if ($walaStartIdentifier -and $walaEndIdentifier) {
                    $WalaIdentifiersDetected = $true
                }
            }
            Write-Loginfo "WALA Start Identifier = $walaStartIdentifier"
            Write-Loginfo "WALA End Identifier = $walaEndIdentifier"
            if (-not $WalaIdentifiersDetected) {
                Throw "Unable to detect WALA identifiers."
            }
            #endregion

            #region Guest Distro Checking
            $GuestDistro = Get-Content -Path "$LogDir\$($vmData.RoleName)-distroVersion.txt"
            #endregion

            #region Waagent Version Checking.
            $waagentStartLineNumber = (Select-String -Path $waagentFile -Pattern "$walaStartIdentifier")[-1].LineNumber
            $waagentStartLine = (Get-Content -Path $waagentFile)[$waagentStartLineNumber - 1]
            $WALAVersion = ($waagentStartLine.Split(":")[$waagentStartLine.Split(":").Count - 1]).Trim()
            Write-LogInfo "$($vmData.RoleName) - WALA Version = $WALAVersion"
            #endregion

            #region Waagent Provision Time Checking.
            $waagentFile = "$LogDir\$($vmData.RoleName)-waagent.log.txt"
            $waagentStartLineNumber = (Select-String -Path $waagentFile -Pattern "$walaStartIdentifier")[-1].LineNumber
            $waagentStartLine = (Get-Content -Path $waagentFile)[$waagentStartLineNumber - 1]
            try {
                $waagentStartTime = [datetime]($waagentStartLine.Split()[0] + " " + $waagentStartLine.Split()[1])
            } catch {
                if ($_.Exception.Message.Contains("String was not recognized as a valid DateTime")) {
                    $waagentStartTime = [datetime]($waagentStartLine.Split()[0].Split('T')[0] + " " + $waagentStartLine.Split()[0].Split('T')[1].Split('Z')[0])
                }
            }
            $waagentFinishedLineNumber = (Select-String -Path $waagentFile -Pattern "$walaEndIdentifier")[-1].LineNumber
            $waagentFinishedLine = (Get-Content -Path $waagentFile)[$waagentFinishedLineNumber - 1]
            try {
                $waagentFinishedTime = [datetime]($waagentFinishedLine.Split()[0] + " " + $waagentFinishedLine.Split()[1])
            } catch {
                if ($_.Exception.Message.Contains("String was not recognized as a valid DateTime")) {
                    $waagentFinishedTime = [datetime]($waagentFinishedLine.Split()[0].Split('T')[0] + " " + $waagentFinishedLine.Split()[0].Split('T')[1].Split('Z')[0])
                }
            }
            $WALAProvisionTime = [int]($waagentFinishedTime - $waagentStartTime).TotalSeconds
            Write-LogInfo "$($vmData.RoleName) - WALA Provision Time = $WALAProvisionTime seconds"
            #endregion

            #region Boot Time checking.
            $bootStart = [datetime](Get-Content "$LogDir\$($vmData.RoleName)-uptime.txt")

            $kernelBootTime = ($waagentStartTime - $bootStart).TotalSeconds
            if ($kernelBootTime -le 0 -or $kernelBootTime -gt 1800) {
                Write-LogErr "Invalid boot time. Boot time = $kernelBootTime."
                Write-LogErr "Acceptalbe boot time range is 0 - 1800 seconds. Please review the actual logs."
                Throw "Invalid boot time = $kernelBootTime seconds."
            }
            $dmesgFile = "$LogDir\$($vmData.RoleName)-dmesg.txt"
            Write-LogInfo "$($vmData.RoleName) - Kernel Boot Time = $kernelBootTime seconds"
            #endregion

            $KernelLogs = Get-Content $dmesgFile
            $CallTraces = "No"
            if ($KernelLogs) {

                #region Call Trace Checking
                foreach ( $line in $KernelLogs.Split("`n") ) {
                    if ( $line -imatch "Call Trace" ) {
                        $CallTraces = "Yes"
                        break;
                    }
                }
                #endregion

                #region Host Version checking
                $foundLineNumber = (Select-String -Path $dmesgFile -Pattern "Hyper-V Host Build").LineNumber
                $actualLineNumber = $foundLineNumber - 1
                $finalLine = (Get-Content -Path $dmesgFile)[$actualLineNumber]
                $finalLine = $finalLine.Replace('; Vmbus version:4.0', '')
                $finalLine = $finalLine.Replace('; Vmbus version:3.0', '')
                $HostVersion = ($finalLine.Split(":")[$finalLine.Split(":").Count - 1 ]).Trim().TrimEnd(";")
                #endregion
            } else {
                Write-LogWarn "Kernel log file is empty."
                Write-LogWarn "Call trace checking skipped."
                Write-LogWarn "Host Version checking skipped."
                $HostVersion = "Unknown"
            }

            Write-LogInfo "$($vmData.RoleName) - Host Version = $HostVersion"
            #region LIS Version
            $LISVersion = (Select-String -Path "$LogDir\$($vmData.RoleName)-lis.txt" -Pattern "^version:").Line
            if ($LISVersion) {
                $LISVersion = $LISVersion.Split(":").Trim()[1]
            }
            else {
                $LISVersion = "NA"
            }
            #endregion
            #region KernelVersion checking
            $KernelVersion = Get-Content "$LogDir\$($vmData.RoleName)-kernelVersion.txt"
            #endregion
            $SQLQuery += "('$DateTimeUTC','$global:TestPlatform','$global:TestLocation','$TestCaseName','$SubscriptionID','$SubscriptionName','$ResourceGroupName','$NumberOfVMsInRG','$RoleName',$DeploymentTime,$KernelBootTime,$WALAProvisionTime,'$HostVersion','$GuestDistro','$KernelVersion','$LISVersion','$WALAVersion','$RoleSize','$StorageType','$CallTraces','$kernelLogFile','$WALAlogFile'),"
        }
        $SQLQuery = $SQLQuery.TrimEnd(',')

        # Upload the boot time data to DB.
        Run-SQLCmd -DBServer $dataSource `
            -DBName $database `
            -DBUsername $dbuser `
            -DBPassword $dbpassword `
            -SQLQuery $SQLQuery
    }
    catch {
        $line = $_.InvocationInfo.ScriptLineNumber
        $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
        $ErrorMessage = $_.Exception.Message
        Write-LogErr "EXCEPTION : $ErrorMessage"
        Write-LogErr "Source : Line $line in script $script_name."
        Write-LogWarn "Debug: Last boot raw text : $(Get-Content "$LogDir\$($vmData.RoleName)-uptime.txt")"
        Write-LogWarn "Debug: WALA start line raw text : $waagentStartLine"
        Write-LogWarn "Debug: WALA start raw text : $($waagentStartLine.Split()[0] + " " + $waagentStartLine.Split()[1])"
    }
}
