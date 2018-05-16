Function ListOSImages()
{
	$images = Get-AzureVMImage
	$i=0
	foreach ( $t in $images )
	{
		if (!$t.MediaLink)
		{
			LogMsg $t.Label
			LogMsg $t.ImageName
		}
	}
}

Function DeleteUnwantedVMImages([switch]$preserveVHDs)
{
	$images = Get-AzureVMImage
	$imageCount = 0
	foreach ($image in $images)
	{
		if ($image.ImageName -imatch "CentOS-6-20-2013")
		{
			$imageCount = $imageCount + 1
			$retryCount =  3
			$isDeleted = $false
			$stillNotDeleted=$true
			While (($retryCount -gt 0) -and ($stillNotDeleted))
			{
				$stillNotDeleted=$true
				$retryCount = $retryCount - 1
				if ($preserveVHDs)
				{
					LogMsg "Deleting image $($image.ImageName), keeping its VHD file inact in storage account.."
					Remove-AzureVMImage -ImageName $image.ImageName -Verbose
					$stillNotDeleted = !$?
				}
				else
				{
					LogMsg "Deleting image $($image.ImageName) & deleting its VHD file from storage account.."
					Remove-AzureVMImage -ImageName $image.ImageName -Verbose -DeleteVHD
					$stillNotDeleted = !$?
				}
			}
			if ($stillNotDeleted)
			{
				Write-Host "Failed.. :-("
			}
			else
			{
				Write-Host "Deleted successfully :-)"
			}
		}
	}
}
<#
.SYNOPSIS 
Set the Azure Subscription based subcription id on Host machine 
.PARAMETER subscription
Specifies the subsciption id
#>

Function DetectLinuxDistro($VIP, $SSHport, $testVMUser, $testVMPassword)
{
	if ( !$detectedDistro )
	{
		$tempout = RemoteCopy  -upload -uploadTo $VIP -port $SSHport -files ".\SetupScripts\DetectLinuxDistro.sh" -username $testVMUser -password $testVMPassword 2>&1 | Out-Null
		$tempout = RunLinuxCmd -username $testVMUser -password $testVMPassword -ip $VIP -port $SSHport -command "chmod +x *.sh" -runAsSudo 2>&1 | Out-Null
		$DistroName = RunLinuxCmd -username $testVMUser -password $testVMPassword -ip $VIP -port $SSHport -command "/home/$user/DetectLinuxDistro.sh" -runAsSudo
		if(($DistroName -imatch "Unknown") -or (!$DistroName))
		{
			LogError "Linux distro detected : $DistroName"
			Throw "Calling function - $($MyInvocation.MyCommand). Unable to detect distro."
		}
		else
		{
			if ($DistroName -imatch "UBUNTU")
			{
				$CleanedDistroName = "UBUNTU" 
			}
			elseif ($DistroName -imatch "DEBIAN")
			{
				$CleanedDistroName = "DEBIAN"
			}
			elseif ($DistroName -imatch "CENTOS")
			{
				$CleanedDistroName = "CENTOS"
			}
			elseif ($DistroName -imatch "SLES")
			{
				$CleanedDistroName = "SLES"
			}
			elseif ($DistroName -imatch "SUSE")
			{
				$CleanedDistroName = "SUSE"
			}
			elseif ($DistroName -imatch "ORACLELINUX")
			{
				$CleanedDistroName = "ORACLELINUX"
			}
			elseif ($DistroName -imatch "REDHAT")
			{
				$CleanedDistroName = "REDHAT"
			}
			elseif ($DistroName -imatch "FEDORA")
			{
				$CleanedDistroName = "FEDORA"
			}
			elseif ($DistroName -imatch "COREOS")
			{
				$CleanedDistroName = "COREOS"
			}
			elseif ($DistroName -imatch "CLEARLINUX")
			{
				$CleanedDistroName = "CLEARLINUX"
			}
			else
			{
				$CleanedDistroName = "UNKNOWN"
			}
			Set-Variable -Name detectedDistro -Value $CleanedDistroName -Scope Global
			SetDistroSpecificVariables -detectedDistro $detectedDistro
			LogMsg "Linux distro detected : $CleanedDistroName"	
		}
	}
	else
	{
		LogMsg "Distro Already Detected as : $detectedDistro"
		$CleanedDistroName = $detectedDistro 
	}
	return $CleanedDistroName
}

Function GetCurrentPackageData ($packageXml, $packageName)
{
	$failed = $true
	foreach ($packageDefinition in $packageXml.data.packageDefinition.package)
	{
		if ($packageDefinition.name -eq $packageName)
		{
			$expectedDefinition = $packageDefinition
			$failed = $false
			break
		}
	}
	if ($failed)
	{
		Throw "Calling function - $($MyInvocation.MyCommand). Unable to find $packageName in package definitions.."
	}
	return $expectedDefinition
}



Function InstallPackages ($VMIpAddress, $VMSshPort, $VMUserName, $VMPassword)
{
	$installError=0
	$installCount=0
	$installSuccess=0
	Set-Content -Value "" -Path .\VHD_Provision.log
	$password = "redhat"
	$packageXml = [xml](Get-Content .\XML\packageInstall.xml)
	$detectedDistro = DetectLinuxDistro -VIP $VMIpAddress -SSHport $VMSshPort -testVMUser $VMUserName -testVMPassword $VMPassword
	
	Write-Host "Detected Distro : $detectedDistro.."
	foreach ($package in $packageXml.data.installPackages.$detectedDistro.package)
	{
		#Write-Host "In the loop now.."
		#Write-Host "$($package.name)"
		$installCount=$installCount+1
		$currentPackageName =  $package.name

		$currentPackageData = GetCurrentPackageData -packageXml $packageXml -packageName $currentPackageName
		$currentDistroPackageData = $currentPackageData.$detectedDistro
		$currentPackageFile = $currentDistroPackageData.file
		LogMsg "Now installing .. $currentPackageName"
		Add-Content -Value "START--------------- INSTALL : $currentPackageName --------------------" -Path .\VHD_Provision.log
		if ($currentDistroPackageData.Location -eq "Remote")
		{

#LogMsg "Invoking command : /root/packageInstall.sh -install $currentPackageName -isLocal no"
			try
			{
				$out = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $VMIpAddress -port $VMSshPort -command "./packageInstall.sh -install $currentPackageName -isLocal no" -runAsSudo
			}
			catch
			{

			}
			if ($out -imatch "InstallSuccess")
			{
				LogMsg "Package : $currentPackageName : Installed successfully."
				$installSuccess=$installSuccess+1
			}
			else
			{
				LogError "Package : $currentPackageName : Installation failed."
				$installError=$installError+1
			}


		}
		elseif ($currentDistroPackageData.Location -eq "local")
		{
			LogMsg "Uploading install file : $currentPackageFile..."

			RemoteCopy -upload -uploadTo $VMIpAddress -port $VMSshPort -username $VMUserName -password $VMPassword -files ".\tools\Packages\$currentPackageFile"

#LogMsg "Invoking command : /root/packageInstall.sh -install $currentPackageName -isLocal yes -file $currentPackageFile"
			if ($currentDistroPackageData.supportingFiles)
			{
				foreach ($supprotFile in ($currentDistroPackageData.supportingFiles).Split(",") )
				{
					LogMsg "Uploading support file - $supprotFile .. "
					RemoteCopy -upload -uploadTo $VMIpAddress -port $VMSshPort -username $VMUserName -password $VMPassword -files ".\tools\Packages\$supprotFile"
				}
			}
			$out = RunLinuxCmd -username $VMUserName -password $VMPassword -ip $VMIpAddress -port $VMSshPort -command "./packageInstall.sh -install $currentPackageName -isLocal yes -file $currentPackageFile" -runAsSudo
			if ($out -imatch "InstallSuccess")
			{
				LogMsg "Package : $currentPackageName : Installed successfully."
				$installSuccess=$installSuccess+1
			}
			else
			{
				LogError "Package : $currentPackageName : Installation failed."
				$installError=$installError+1
			}

		}
		Add-Content -Value $out -Path .\VHD_Provision.log
		Add-Content -Value "END----------------- INSTALL : $currentPackageName --------------------" -Path .\VHD_Provision.log
	}

	LogMsg "Total packages  : $installCount."
	LogMsg "Total installed : $installSuccess"
	LogMsg "Total failed	: $installError"

	if ($installError -gt 0)
	{
		LogError "$installError out of $installCount packages failed to install"
		$retValue=$false
	}
	else
	{
		LogMsg "All packages installed successfully."
		$retValue=$true
	}
	return $retValue
}

Function IsEnvironmentSupported()
{
	$version = (Get-Module -ListAvailable Azure).Version
	If ($version.Major -GT 0 -OR
		$version.Minor -GT 8 -OR
		(($version.Minor -EQ 8) -And ($version.Build -GE 8)))
	{
		return $true
	}
	Else
	{
		return $false
	}
}

Function SetSubscription ($subscriptionID, $subscriptionName, $certificateThumbprint, $managementEndpoint, $storageAccount, $environment = "AzureCloud")
{
	if ( $UseAzureResourceManager )
	{
		#Add-AzureAccount
	}
	else
	{
		$myCert = $null
		$myCert = Get-Item Cert:\CurrentUser\My\$certificateThumbprint -ErrorAction SilentlyContinue
		if ( $myCert.Thumbprint -ne $certificateThumbprint )
		{
			$myCert = Get-Item Cert:\LocalMachine\My\$certificateThumbprint -ErrorAction SilentlyContinue
		}
		if ( $myCert.Thumbprint -ne $certificateThumbprint )
		{
			Throw "Calling function - $($MyInvocation.MyCommand). Unable to load certificate from `"Cert:\LocalMachine\`" and `"Cert:\CurrentUser\`""
		}
		# For Azure Powershell Version >= 0.8.8, Environment is used in Set-AzureSubscription for replacing ManagementEndpoint
		if (IsEnvironmentSupported)
		{
			Set-AzureSubscription -SubscriptionName $subscriptionName -Certificate $myCert -SubscriptionID $subscriptionID `
								  -CurrentStorageAccountName $storageAccount -Environment $environment
		}
		Else
		{
			Set-AzureSubscription -SubscriptionName $subscriptionName -Certificate $myCert -SubscriptionID $subscriptionID `
								  -CurrentStorageAccountName $storageAccount -ServiceEndpoint $managementEndpoint
		}
		Select-AzureSubscription -Current $subscriptionName
	}
}

<#
.SYNOPSIS 
Gets the Azure Hosted Service VIP 
.PARAMETER servicename
Specifies the servicename
#>
Function GetHsVmVip([string]$servicename)
{
	$endpoints = Get-AzureService $serviceName |  Get-AzureVM | Get-AzureEndpoint
	$vip = $endpoints[0].Vip
	return $VIP
}

<#
.SYNOPSIS 
Deletes Azure Service 
.PARAMETER servicename
Specifies the servicename
#>
Function DeleteService ($serviceName, [switch]$KeepDisks)
{
	$j= 0 
	$ExistingServices = Get-AzureService

	foreach ( $eachService in $ExistingServices )
	{
		if( $eachService.ServiceName -eq $serviceName )
		{
			$j = $j + 1

			LogMsg "$serviceName ..service exists!"
			if ($eachService.Description -imatch "DONOTDISTURB")
			{
				Write-Host "Not Removing $($eachService.ServiceName). As it is labelled as DO NOT DISTURB. Please try Not to remove it..." -ForegroundColor Red
				$retValue = "True"
				break
			}
			LogWarn "Warning : Deleting All Virtual Machines in $serviceName in 5 seconds. Interrupt to break.."
			WaitFor -seconds 5
			LogMsg "Deleting $serviceName..."
			$retValue = "False"
			$retryCount = 1
			while (($retValue -eq "False") -and ($retryCount -lt 10))
			{
				if ( $KeepDisks )
				{
					$out = Remove-AzureService -ServiceName $serviceName -Force  -Verbose
				}
				else
				{
					$out = Remove-AzureService -ServiceName $serviceName -DeleteAll -Force  -Verbose
				}
				$RemoveServiceExitCode =  $?
				if(($out -imatch "Complete") -or $RemoveServiceExitCode)
				{
					if($retryCount -lt 1)
					{
						LogMsg "Deleted $serviceName"
					}
					else
					{
						LogMsg "Deleted $serviceName after $retryCount Attempt"
					}
					$retValue = "True"
				}
				else
				{
					$retryCount = $retryCount + 1
					LogWarn "Error in deletion. Retry Attempt $retryCount "
				}
			}
		}
	}

	if ($j -eq 0 )
	{
		LogMsg "$serviceName not found!"
		$retValue = "True"
	}

	return $retValue
}

<#
.SYNOPSIS 
Creates Azure Service 
.PARAMETER servicename
Specifies the servicename
#>
Function CreateService($serviceName, $location, $AffinityGroup)
{
	$FailCounter = 0
	$retValue = "False"
	While(($retValue -eq "False") -and ($FailCounter -lt 5))
	{
	try{
		$FailCounter++

		if($location) {
			LogMsg "Using location : $location"
			$out = RunAzureCmd -AzureCmdlet "New-AzureService -ServiceName $serviceName -Location $location"
		}
		else {
			if($AffinityGroup) {
			LogMsg "Using Affinity Group : $AffinityGroup" 
			$out = RunAzureCmd -AzureCmdlet "New-AzureService -ServiceName $serviceName -AffinityGroup $AffinityGroup"
			}
		}

		$operationID = $out.OperationID
		$operationStatus = $out.OperationStatus
		LogMsg "New-AzureService`t" -NoNewline 
		if ($operationStatus  -eq "Succeeded"){
			LogMsg "Hosted Service Created."
			$retValue = "True"
		}
		else {
			LogError "Failed"
			$retValue = "False"
		  
		}
		}
		catch
		{
		$retValue = "False"
		}
	}
	return $retValue
}

Function AddCertificate($serviceName)
{
	$FailCounter = 0
	$retValue = $false

	#Added try catch to handle "Unable to Send Request error"
	While(($retValue -eq $false) -and ($FailCounter -lt 5))
	{
		try
		{
		$FailCounter++
		$currentDirectory = (pwd).Path
		LogMsg "Adding Certificate to hosted service.."
		$out = RunAzureCmd -AzureCmdlet "Add-AzureCertificate -CertToDeploy `"$currentDirectory\ssh\myCert.cer`" -ServiceName $serviceName"
		$retValue = $?
		}
		catch
		{
			$retValue = $false	  
		}
	}
	return $retValue
}

Function GenerateCommand ($Setup, $serviceName, $osImage, $HSData)
{
	$role = 0
	$HS = $HSData
	$setupType = $Setup
	$defaultuser = $xml.config.Azure.Deployment.Data.UserName
	$defaultPassword = $xml.config.Azure.Deployment.Data.Password
	$totalVMs = 0
	$totalHS = 0
	$extensionCounter = 0
	$vmCommands = @()
	$vmCount = 0
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
	foreach ( $newVM in $HS.VirtualMachine)
	{
		$vmCount = $vmCount + 1
		$VnetName = $HS.VnetName
        if ( $OverrideVMSize )
        {
            $instanceSize = $OverrideVMSize
        }
        else
        {
		    $instanceSize = $newVM.InstanceSize
        }
		$SubnetName = $newVM.SubnetName
		$DnsServerIP = $HS.DnsServerIP
#...............................................
# LIST OUT THE TOTAL PORTS TO BE OPENED AND ADD THEM ACCORDINGLY...
#'''''''''''''''''''''''''''''''''''''''''''''''
		$portCommand = ""   
		$portNo = 0
		$Endpoints = $newVM.Endpoints
		foreach ( $openedPort in $newVM.EndPoints)
		{
			if($openedPort.Name -eq "SSH")
			{
				$portCommand =  $portCommand + " Set-AzureEndpoint -Name `"" + $openedPort.Name + "`" -LocalPort `"" + $openedPort.LocalPort + "`" -PublicPort `"" +  $openedPort.PublicPort + "`" -Protocol `"" + $openedPort.Protocol + "`""
			}
			else
			{
				$portCommand =  $portCommand + " Add-AzureEndpoint" + " -Name `"" + $openedPort.Name  + "`"" + " -LocalPort `"" + $openedPort.LocalPort + "`" -PublicPort `"" +  $openedPort.PublicPort + "`" -Protocol `"" + $openedPort.Protocol + "`""
				if ($openedPort.LoadBalanced -eq "True")
				{
					if ($openedPort.ProbePort)
					{
						$portCommand = $portCommand + " -LBSetName `"" + $openedPort.Name + "`"" + "-ProbePort " +  $openedPort.ProbePort + " -ProbeProtocol tcp"
					}
					else
					{
						$portCommand = $portCommand + " -LBSetName `"" + $openedPort.Name + "`"" + " -NoProbe"
					}
				}
			}
			$portCommand = $portCommand + " |"
			$portNo = $portNo + 1
		}
		if($newVM.RoleName)
		{
			$vmName = $newVM.RoleName
		}
		else
		{
			$vmName = $serviceName +"-role-"+$role
		}
		$diskCommand = ""
		foreach ( $dataDisk in $newVM.DataDisk)
		{
			if ( $dataDisk.LUN -and $dataDisk.DiskSizeInGB -and $dataDisk.HostCaching )
			{
				if ($diskCommand)
				{
					$diskCommand = $diskCommand + " | " + "Add-AzureDataDisk -CreateNew -DiskSizeInGB $($dataDisk.DiskSizeInGB) -LUN $($dataDisk.LUN) -HostCaching $($dataDisk.HostCaching) -DiskLabel `"$vmName-Disk-$($dataDisk.LUN)`"" 
				}
				else
				{
					$diskCommand = "Add-AzureDataDisk -CreateNew -DiskSizeInGB $($dataDisk.DiskSizeInGB) -LUN $($dataDisk.LUN) -HostCaching $($dataDisk.HostCaching) -DiskLabel `"$vmName-Disk-$($dataDisk.LUN)`""
				}
			}
		}
		if ( $CurrentTestData.ProvisionTimeExtensions )
		{
			$ExtensionCommand = ""
			foreach ( $extn in $CurrentTestData.ProvisionTimeExtensions.Split(","))
			{
				$extn = $extn.Trim()
				foreach ( $newExtn in $extensionXML.Extensions.Extension )
				{
					if ($newExtn.Name -eq $extn)
					{
						if ($newExtn.PublicConfiguration)
						{
							[hashtable]$extensionHashTable = @{};
							$newExtn.PublicConfiguration.ChildNodes | foreach {$extensionHashTable[$_.Name] = $_.'#text'};
							$PublicConfiguration += $extensionHashTable | ConvertTo-Json
						}
						if ($newExtn.PrivateConfiguration)
						{
							[hashtable]$extensionHashTable = @{};
							$newExtn.PrivateConfiguration.ChildNodes | foreach {$extensionHashTable[$_.Name] = $_.'#text'};
							$PrivateConfiguration += $extensionHashTable | ConvertTo-Json
						}
						if ( $ExtensionCommand )
						{
							if ($PublicConfiguration -and $PrivateConfiguration)
							{
								$ExtensionCommand = $ExtensionCommand + " | Set-AzureVMExtension -ExtensionName $($newExtn.OfficialName) -ReferenceName $extn -Publisher $($newExtn.Publisher) -Version $($newExtn.Version) -PublicConfiguration `$PublicConfiguration[$extensionCounter] -PrivateConfiguration `$PrivateConfiguration[$extensionCounter]"
							}
							elseif($PublicConfiguration)
							{
								$ExtensionCommand = $ExtensionCommand + " | Set-AzureVMExtension -ExtensionName $($newExtn.OfficialName) -ReferenceName $extn -Publisher $($newExtn.Publisher) -Version $($newExtn.Version) -PublicConfiguration `$PublicConfiguration[$extensionCounter]"
							}
							elseif($PrivateConfiguration)
							{
								$ExtensionCommand = $ExtensionCommand + " | Set-AzureVMExtension -ExtensionName $($newExtn.OfficialName) -ReferenceName $extn -Publisher $($newExtn.Publisher) -Version $($newExtn.Version) -PrivateConfiguration `$PrivateConfiguration[$extensionCounter]"
							}
						}
						else
						{
							if ( $PublicConfiguration -and $PrivateConfiguration )
							{
								$ExtensionCommand = "Set-AzureVMExtension -ExtensionName $($newExtn.OfficialName) -ReferenceName $extn -Publisher $($newExtn.Publisher) -Version $($newExtn.Version) -PublicConfiguration `$PublicConfiguration[$extensionCounter] -PrivateConfiguration `$PrivateConfiguration[$extensionCounter]"
							}
							elseif($PublicConfiguration)
							{
								$ExtensionCommand = "Set-AzureVMExtension -ExtensionName $($newExtn.OfficialName) -ReferenceName $extn -Publisher $($newExtn.Publisher) -Version $($newExtn.Version) -PublicConfiguration `$PublicConfiguration[$extensionCounter]"
							}
							elseif($PrivateConfiguration)
							{
								$ExtensionCommand = "Set-AzureVMExtension -ExtensionName $($newExtn.OfficialName) -ReferenceName $extn -Publisher $($newExtn.Publisher) -Version $($newExtn.Version) -PrivateConfiguration `$PrivateConfiguration[$extensionCounter]"
							}
							else
							{
								$ExtensionCommand = "Set-AzureVMExtension -ExtensionName $($newExtn.OfficialName) -ReferenceName $extn -Publisher $($newExtn.Publisher) -Version $($newExtn.Version)"
							}								
						}
						LogMsg "Extension $extn (OfficialName : $($newExtn.OfficialName)) added to deployment command."
						$extensionCounter += 1
					}
				}
			}
			if ( $PublicConfiguration )
			{
				Set-Variable -Name PublicConfiguration -Value $PublicConfiguration -Scope Global
			}
			if ( $PrivateConfiguration )
			{
				Set-Variable -Name PrivateConfiguration -Value $PrivateConfiguration -Scope Global
			}
		}
		$sshPath = '/home/' + $defaultuser + '/.ssh/authorized_keys'		 	
		$vmRoleConfig = "New-AzureVMConfig -Name $vmName -InstanceSize $instanceSize -ImageName $osImage"
		$vmProvConfig = "Add-AzureProvisioningConfig -Linux -LinuxUser $defaultuser -Password $defaultPassword -SSHPublicKeys (New-AzureSSHKey -PublicKey -Fingerprint $sshPublicKeyThumbprint -Path $sshPath)"
		if($SubnetName)
		{
			$vmProvConfig = $vmProvConfig + "| Set-AzureSubnet -SubnetNames $SubnetName"
		}
		$vmPortConfig =  $portCommand.Substring(0,$portCommand.Length-1)
		#Add multiply NICs configuration
		$vmNetworkInterfaceConfig = ""
		foreach ( $NetworkInterface in $newVM.NetworkInterfaces)
		{
			if($vmNetworkInterfaceConfig)
			{
				$vmNetworkInterfaceConfig = $vmNetworkInterfaceConfig + " | " + "Add-AzureNetworkInterfaceConfig -Name $($NetworkInterface.Name) -SubnetName $SubnetName"			
			}
			else
			{
				$vmNetworkInterfaceConfig = "Add-AzureNetworkInterfaceConfig -Name $($NetworkInterface.Name) -SubnetName $SubnetName"
			}
		}
		
		#Start building SingleVM Config command..

		$singleVMCommand = "( " + $vmRoleConfig + " | " + $vmProvConfig + " | " + $vmPortConfig

		if ( $vmNetworkInterfaceConfig )
		{
			$singleVMCommand = $singleVMCommand + " | " + $vmNetworkInterfaceConfig
		}		
		if ( $diskCommand )
		{
			$singleVMCommand = $singleVMCommand + " | " + $diskCommand
		}
		if ( $ExtensionCommand )
		{
			$singleVMCommand = $singleVMCommand + " | " + $ExtensionCommand
		}

		$singleVMCommand = $singleVMCommand + " )"
		
		#Finished building SingleVM Config command..

		$totalVMs = $totalVMs + 1
		$role = $role + 1

		if ($totalVMs -gt 1)
		{
			$finalVMcommand = $finalVMcommand + ', ' + $singleVMCommand
		}
		else
		{
			$finalVMcommand = $singleVMCommand
		}
	}			

	if ($VnetName)
	{
		$newDNS  = "(New-AzureDns -Name `"DNSsettings`" -IPAddress $DnsServerIP)"
		$createSetupCommand = "New-AzureVM -ServiceName $serviceName -VMs ($finalVMcommand)  -VNetName $VnetName -DnsSettings $newDNS"
	}
	else
	{
		$createSetupCommand = "New-AzureVM -ServiceName $serviceName -VMs ($finalVMcommand)"
	}   

	return $createSetupCommand,  $serviceName, $vmCount
} 

Function CreateDeployment ($DeploymentCommand, $NewServiceName , $vmCount, [string]$storageaccount="", $timeOutSeconds)
{
	
	$FailCounter = 0
	$retValue = "False"
	#While(($retValue -eq "False") -and ($FailCounter -lt 5))
	#{
		try
		{
			$FailCounter++
			$out = RunAzureCmd -AzureCmdlet "$DeploymentCommand" -storageaccount $storageaccount -maxWaitTimeSeconds $timeOutSeconds
			#LogMsg $DeploymentCommand
			$retValue = $?
			LogMsg "VM's deployed. Verifying.."
			$VMDetails = Get-AzureVM -ServiceName $NewServiceName
			$tempcounter = 0
			foreach ($vm in $VMDetails)
			{
				$VMcounter = $VMcounter + 1
			}
			if ($VMcounter -eq $vmCount)
			{
				LogMsg "Expected VMs : $vmCount. Deployed VMs : $vmCounter"
				$retValue = "True"
			}
			else
			{
				$retValue = "False"
				LogError "Expected VMs : $vmCount. Deployed VMs : $vmCounter"
			}
		 }
		 catch
		 {
		   $retValue = "False"
		 }   
	#}
	return $retValue 
}

Function CheckVMsInService($serviceName)
{
	try
	{
		$allVMsReady = "False"
		$isTimedOut = "False"
		$VMCheckStarted = Get-Date
		While (($allVMsReady -eq "False") -and ($isTimedOut -eq "False"))
		{
			$i = 0
			$VMStatus = @()
	#$DeployedVMs = Get-AzureService -ServiceName $serviceName  | Get-AzureVM 
			$DeployedVMs = RetryOperation -operation { Get-AzureVM -ServiceName $serviceName } -retryInterval 1 -maxRetryCount 10 -NoLogsPlease
            if($DeployedVMs -eq $null)
            {
                Write-Host "No Deployment found in service."
                $remainigSeconds = 1800
                $VMStatuString = "service: $serviceName, vm provision-failed"
                break
            }
			$Recheck = 0
			$VMStatuString = ""
			foreach ( $VM in $DeployedVMs )
			{
				$VMStatuString += "$($VM.InstanceName) : $($VM.InstanceStatus) "
				if ( $VM.InstanceStatus -ne "ReadyRole" )
				{
					$VMStatus = $VM.InstanceStatus
	#Write-Host $VMStatus
					$Recheck = $Recheck + 1
				}
				else
				{
	#Write-Host $VMStatus
				}
			}

			$VMcheckTimeNow = Get-Date
			$VMtime= $VMcheckTimeNow - $VMCheckStarted
			if ($VMtime.TotalSeconds -gt 1800 )
			{
				$isTimedOut = "True"
			}   
			if ($Recheck -eq 0 )
			{
				$allVMsReady = "True"
			}
			$remainigSeconds = 1800 - $VMtime.TotalSeconds
			Write-Progress -Id 500 -Activity "Checking Deployed VM in Service : $serviceName. Seconds Remaining : $remainigSeconds" -Status "$VMStatuString"
			Write-Host "." -NoNewline
			#Write-Host $VMStatus -NoNewline
			sleep 1
		}
		Write-Progress -Id 500 -Activity "Checking Deployed VM in Service : $serviceName. Seconds Remaining : $remainigSeconds" -Status "$VMStatuString" -Completed   
	}
	catch
	{
		$ErrorMessage =  $_.Exception.Message
		LogMsg "EXCEPTION in CheckVMsInService() : $ErrorMessage"
		$allVMsReady = "False"
	}
	return $allVMsReady
}

Function CreateAllDeployments($setupType, $xmlConfig, $Distro, [string]$region ="", [string]$storageAccount="", $timeOutSeconds)
{

	$hostedServiceCount = 0
	$osImage = @()
	$xml = $xmlConfig
	LogMsg $setupType
	$setupTypeData = $xml.config.Azure.Deployment.$setupType
	$allsetupServices = $setupTypeData
	if ($allsetupServices.HostedService[0].Location -or $allsetupServices.HostedService[0].AffinityGroup)
	{
		$isMultiple = 'True'
		$hostedServiceCount = 0
	}
	else
	{
		$isMultiple = 'False'
	}

	foreach ($newDistro in $xml.config.Azure.Deployment.Data.Distro)
	{

		if ($newDistro.Name -eq $Distro)
		{
			$osImage += $newDistro.OsImage
		}
	}

	$location = $xml.config.Azure.General.Location
	$AffinityGroup = $xml.config.Azure.General.AffinityGroup
	$currentStorageAccount = $xmlConfig.config.Azure.General.StorageAccount

    if($region)
    {
      $location = $region
      $AffinityGroup = ""
      $currentStorageAccount = $storageAccount
    }
	foreach ($HS in $setupTypeData.HostedService )
	{
        foreach ($img in $osImage)
        {
        	$curtime = Get-Date
        	$randomNumber = Get-Random -Maximum 999 -Minimum 111 -SetSeed (Get-Random -Maximum 999 -Minimum 111 )
		    $isServiceDeployed = "False"
		    $retryDeployment = 0
		    if ( $HS.Tag -ne $null )
		    {
			    $serviceName = "ICA-HS-" + $HS.Tag + "-" + $Distro + "-" + $curtime.Month + "-" +  $curtime.Day  + "-" + $curtime.Hour + "-" + $curtime.Minute + "-" + $randomNumber
		    }
		    else
		    {
			    $serviceName = "ICA-HS-" + $setupType + "-" + $Distro + "-" + $curtime.Month + "-" +  $curtime.Day  + "-" + $curtime.Hour + "-" + $curtime.Minute + "-" + $randomNumber
		    }
		    if($isMultiple -eq "True")
		    {
			    $serviceName = $serviceName + "-" + $hostedServiceCount
		    }

		    while (($isServiceDeployed -eq "False") -and ($retryDeployment -lt 5))
		    {
			    LogMsg "Creating Hosted Service : $serviceName."
			    LogMsg "Verifying that service name is not in use."
			    $isServiceDeleted = DeleteService -serviceName $serviceName
    #$isServiceDeleted = "True"
			    if ($isServiceDeleted -eq "True")
			    {	 
				    $isServiceCreated = CreateService -serviceName $serviceName -location $location -AffinityGroup $AffinityGroup
    #$isServiceCreated = "True"
				    if ($isServiceCreated -eq "True")
				    {
					    $isCertAdded = AddCertificate -serviceName $serviceName
    #$isCertAdded = "True"
					    if ($isCertAdded -eq "True")
					    {
						    LogMsg "Certificate added successfully."
						    $DeploymentCommand = GenerateCommand -Setup $Setup -serviceName $serviceName -osImage $img -HSData $HS
						    Set-AzureSubscription -SubscriptionName $xmlConfig.config.Azure.General.SubscriptionName  -CurrentStorageAccountName $currentStorageAccount
						    $DeploymentStartTime = (Get-Date)
						    $isDeployed = CreateDeployment -DeploymentCommand $DeploymentCommand[0] -NewServiceName $DeploymentCommand[1] -vmCount $DeploymentCommand[2] -storageaccount $currentStorageAccount -timeOutSeconds $timeOutSeconds
						    $DeploymentEndTime = (Get-Date)
						    $DeploymentElapsedTime = $DeploymentEndTime - $DeploymentStartTime
						    if ( $isDeployed -eq "True" )
						    {
							    LogMsg "Deployment Created!"
							    $retValue = "True"
							    $isServiceDeployed = "True"
							    $hostedServiceCount = $hostedServiceCount + 1
							    if ($hostedServiceCount -eq 1)
							    {
								    $deployedServices = $serviceName
							    }
							    else
							    {
								    $deployedServices = $deployedServices + "^" + $serviceName
							    }

						    }
						    else
						    {
							    LogError "Unable to Deploy one or more VM's"
							    $retryDeployment = $retryDeployment + 1
							    $retValue = "False"
							    $isServiceDeployed = "False"
						    }
					    }
					    else
					    {
						    LogError "Unable to Add certificate to $serviceName"
						    $retryDeployment = $retryDeployment + 1
						    $retValue = "False"
						    $isServiceDeployed = "False"
					    }

				    }
				    else
				    {
					    LogError "Unable to create $serviceName"
					    $retryDeployment = $retryDeployment + 1
					    $retValue = "False"
					    $isServiceDeployed = "False"
				    }
			    }	
			    else
			    {
				    LogError "Unable to delete existing service - $serviceName"
				    $retryDeployment = 3
				    $retValue = "False"
				    $isServiceDeployed = "False"
			    }

		    }
        }
	}
	return $retValue, $deployedServices, $DeploymentElapsedTime
}

Function VerifyAllDeployments($servicesToVerify, [Switch]$GetVMProvisionTime)
{
	$VMProvisionElapsedTime = $null
	$VMProvisionStarted = Get-Date
	LogMsg "Waiting for VM(s) to become Ready."
	foreach ($service in  $servicesToVerify)
	{
		$serviceName = $service
		LogMsg "checking $serviceName.. "
		$isDeploymentReady = CheckVMsInService ($serviceName)
		$VMProvisionFinished = Get-Date
		$VMProvisionElapsedTime = $VMProvisionFinished - $VMProvisionStarted
		if ($isDeploymentReady -eq "True")
		{
			LogMsg ""
			LogMsg "$serviceName is Ready.."
            if ( $currentTestData.InitialWaitSeconds )
            {
                LogMsg "Waiting for initial wait time. $($currentTestData.InitialWaitSeconds) seconds."
                WaitFor -seconds $currentTestData.InitialWaitSeconds
            }
			Write-Host ""
			$retValue = "True"
		}
		else
		{
			LogError "$serviceName provision Failed.."
			$retValue = "False"
			break
		}
	}
	if($GetVMProvisionTime)
	{
		return $retValue, $VMProvisionElapsedTime
	}
	else
	{
		return $retValue
	}
}

Function WaitFor($seconds,$minutes,$hours)
{
	if(!$hours -and !$minutes -and !$seconds)
	{
		Write-Host "Come on.. Mention at least one second bro ;-)"
	}
	else
	{
		if(!$hours)
		{
			$hours = 0
		}
		if(!$minutes)
		{
			$minutes = 0
		}
		if(!$seconds)
		{
			$seconds = 0
		}

		$timeToSleepInSeconds = ($hours*60*60) + ($minutes*60) + $seconds
		$secondsRemaining = $timeToSleepInSeconds 
		$secondsRemainingPercentage = (100 - (($secondsRemaining/$timeToSleepInSeconds)*100))
		for ($i = 1; $i -le $timeToSleepInSeconds; $i++)
		{
			write-progress -Id 27 -activity SLEEPING -Status "$($secondsRemaining) seconds remaining..." -percentcomplete $secondsRemainingPercentage
			$secondsRemaining = $timeToSleepInSeconds - $i
			$secondsRemainingPercentage = (100 - (($secondsRemaining/$timeToSleepInSeconds)*100))
			sleep -Seconds 1
		}
		write-progress -Id 27 -activity SLEEPING -Status "Wait Completed..!" -Completed
	}

}

Function RemoveICAUnusedServices([switch]$removePreservedServices, $pattern="ICA-", [switch]$onlyPreservedServices)
{
	$ExistingServices = Get-AzureService
	foreach ($service in $ExistingServices)
	{
		if ($service.ServiceName -imatch $pattern) 
		{
			if (!($service.Description -imatch "DONOTDISTURB"))
			{
				if(($service.Description -imatch "Preserving"))
				{
					if($removePreservedServices -or $onlyPreservedServices)
					{
						Write-Host "ATTENTION : Removing preserved service : $($service.ServiceName).." -ForegroundColor Red
						DeleteService -ServiceName $service.ServiceName 
					}
					else
					{
						Write-Host "Skipping preserved hosted service : $($service.ServiceName).." -ForegroundColor Green
					}
				}
				else
				{
					if(!$onlyPreservedServices)
					{
						Write-Host "Removing $($service.ServiceName).." -ForegroundColor Red
						DeleteService -ServiceName $service.ServiceName 
					}
				}
			}
			else
			{
				Write-Host "Not Removing $($service.ServiceName). As it is labelled as DO NOT DISTURB. Please try Not to remove it..." -ForegroundColor Red
			}
		}		
	}
}
Function RemoveICAUnusedDataDisks()
{
	$dataDisks = Get-AzureDisk
	$removeDiskId = 55
	$totalIcaDisks = 0
	$dataDiskToRemove = @()
	foreach ($disk in $dataDisks)
	{
		if (($disk.DiskName -imatch "ICA-") -and (!$disk.AttachedTo))
		{
			$totalIcaDisks +=  1
			$dataDiskToRemove += $disk.DiskName
		}
	}

	if ($totalIcaDisks -ge 1)
	{
		Write-Progress -Id $removeDiskId -Activity "Removing unused ICA data disks.." -PercentComplete 0
		$totalRemaining = $totalIcaDisks
		$index = 1
		foreach ($disk in $dataDiskToRemove)
		{
			Write-Progress -Id $removeDiskId -Activity "Removing unused ICA data disks.." -PercentComplete (100 - ($totalRemaining*100/$totalIcaDisks)) -Status "[$index/$totalIcaDisks] $disk"
			try
			{
				Write-Host "Removing - $disk.." -NoNewline
				sleep 3
				$out = Remove-AzureDisk -DiskName $disk -DeleteVHD
				Write-Host ".Ok!" -ForegroundColor Green
				$totalRemaining -= 1
				$index += 1
			}
			catch
			{
				Write-Host ".Failed" -ForegroundColor Red
			}

		}
		Write-Progress -Id $removeDiskId -Activity "Removed!" -Completed
	}
	else
	{
		Write-Host "No unused ICA disks found." -ForegroundColor Green
	}
}

#function to collect and compare kernel logs
Function GetAndCheckKernelLogs($allDeployedVMs, $status, $vmUser, $vmPassword)
{
	try
	{
		if ( !$vmUser )
		{
			$vmUser = $user
		}
		if ( !$vmPassword )
		{
			$vmPassword = $password
		}
		$retValue = $false
		foreach ($VM in $allDeployedVMs)
		{
			$BootLogDir="$Logdir\$($VM.RoleName)"
			mkdir $BootLogDir -Force | Out-Null
			LogMsg "Collecting $($VM.RoleName) VM Kernel $status Logs.."
			$InitailBootLog="$BootLogDir\InitialBootLogs.txt"
			$FinalBootLog="$BootLogDir\FinalBootLogs.txt"
			$KernelLogStatus="$BootLogDir\KernelLogStatus.txt"
			if($status -imatch "Initial")
			{
				$randomFileName = [System.IO.Path]::GetRandomFileName()
				Set-Content -Value "A Random file." -Path "$Logdir\$randomFileName"
				$out = RemoteCopy -uploadTo $VM.PublicIP -port $VM.SSHPort  -files "$Logdir\$randomFileName" -username $vmUser -password $vmPassword -upload
				Remove-Item -Path "$Logdir\$randomFileName" -Force
				$out = RunLinuxCmd -ip $VM.PublicIP -port $VM.SSHPort -username $vmUser -password $vmPassword -command "dmesg > /home/$vmUser/InitialBootLogs.txt" -runAsSudo
				$out = RemoteCopy -download -downloadFrom $VM.PublicIP -port $VM.SSHPort -files "/home/$vmUser/InitialBootLogs.txt" -downloadTo $BootLogDir -username $vmUser -password $vmPassword
				LogMsg "$($VM.RoleName): $status Kernel logs collected ..SUCCESSFULLY"
				LogMsg "Checking for call traces in kernel logs.."
				$KernelLogs = Get-Content $InitailBootLog 
				$callTraceFound  = $false
				foreach ( $line in $KernelLogs )
				{
					if (( $line -imatch "Call Trace" ) -and  ($line -inotmatch "initcall "))
					{
						LogError $line
						$callTraceFound = $true
					}
					if ( $callTraceFound )
					{
						if ( $line -imatch "\[<")
						{
							LogError $line
						}
					}
				}
				if ( !$callTraceFound )
				{
					LogMsg "No any call traces found."
				}
				$detectedDistro = DetectLinuxDistro -VIP $VM.PublicIP -SSHport $VM.SSHPort -testVMUser $vmUser -testVMPassword $vmPassword
				SetDistroSpecificVariables -detectedDistro $detectedDistro
				$retValue = $true
			}
			elseif($status -imatch "Final")
			{
				$out = RunLinuxCmd -ip $VM.PublicIP -port $VM.SSHPort -username $vmUser -password $vmPassword -command "dmesg > /home/$vmUser/FinalBootLogs.txt" -runAsSudo
				$out = RemoteCopy -download -downloadFrom $VM.PublicIP -port $VM.SSHPort -files "/home/$vmUser/FinalBootLogs.txt" -downloadTo $BootLogDir -username $vmUser -password $vmPassword
				LogMsg "Checking for call traces in kernel logs.."
				$KernelLogs = Get-Content $FinalBootLog
				$callTraceFound  = $false
				foreach ( $line in $KernelLogs )
				{
					if (( $line -imatch "Call Trace" ) -and ($line -inotmatch "initcall "))
					{
						LogError $line
						$callTraceFound = $true
					}
					if ( $callTraceFound )
					{
						if ( $line -imatch "\[<")
						{
							LogError $line
						}
					}
				}
				if ( !$callTraceFound )
				{
					LogMsg "No any call traces found."
				}
				$KernelDiff = Compare-Object -ReferenceObject (Get-Content $FinalBootLog) -DifferenceObject (Get-Content $InitailBootLog)
				#Removing final dmesg file from logs to reduce the size of logs. We can alwayas see complete Final Logs as : Initial Kernel Logs + Difference in Kernel Logs
				Remove-Item -Path $FinalBootLog -Force | Out-Null
				if($KernelDiff -eq $null)
				{
					LogMsg "** Initial and Final Kernel Logs has same content **"  
					Set-Content -Value "*** Initial and Final Kernel Logs has same content ***" -Path $KernelLogStatus
					$retValue = $true
				}
				else
				{
					$errorCount = 0
					Set-Content -Value "Following lines were added in the kernel log during execution of test." -Path $KernelLogStatus
					LogMsg "Following lines were added in the kernel log during execution of test." 
					Add-Content -Value "-------------------------------START----------------------------------" -Path $KernelLogStatus
					foreach ($line in $KernelDiff)
					{
						Add-Content -Value $line.InputObject -Path $KernelLogStatus
						if ( ($line.InputObject -imatch "fail") -or ($line.InputObject -imatch "error") -or ($line.InputObject -imatch "warning"))
						{
							$errorCount += 1
							LogError $line.InputObject
						}
						else
						{
							LogMsg $line.InputObject
						}
					}
					Add-Content -Value "--------------------------------EOF-----------------------------------" -Path $KernelLogStatus
				}
				LogMsg "$($VM.RoleName): $status Kernel logs collected and Compared ..SUCCESSFULLY"
				if ($errorCount -gt 0)
				{
					LogError "Found $errorCount fail/error/warning messages in kernel logs during execution."
					$retValue = $false
				}
				if ( $callTraceFound )
				{
					if ( $UseAzureResourceManager )
					{
						LogMsg "Preserving the Resource Group(s) $($VM.ResourceGroupName)"
						LogMsg "Setting tags : $preserveKeyword = yes; testName = $testName"
						$hash = @{}
						$hash.Add($preserveKeyword,"yes")
						$hash.Add("testName","$testName")
						$out = Set-AzureRmResourceGroup -Name $($VM.ResourceGroupName) -Tag $hash
						LogMsg "Setting tags : calltrace = yes; testName = $testName"
						$hash = @{}
						$hash.Add("calltrace","yes")
						$hash.Add("testName","$testName")
						$out = Set-AzureRmResourceGroup -Name $($VM.ResourceGroupName) -Tag $hash
					}
					else
					{
						LogMsg "Adding preserve tag to $($VM.ServiceName) .."
						$out = Set-AzureService -ServiceName $($VM.ServiceName) -Description $preserveKeyword
					}
				}
			}
			else
			{
				LogMsg "pass value for status variable either final or initial"
				$retValue = $false
			}
		}
	}
	catch
	{
		$retValue = $false
	}
	return $retValue
}

Function CheckKernelLogs($allVMData, $vmUser, $vmPassword)
{
	try
	{
		$errorLines = @()
		$errorLines += "Call Trace"
		$errorLines += "rcu_sched self-detected stall on CPU"
		$errorLines += "rcu_sched detected stalls on"
		$errorLines += "BUG: soft lockup"
		$totalErrors = 0
		if ( !$vmUser )
		{
			$vmUser = $user
		}
		if ( !$vmPassword )
		{
			$vmPassword = $password
		}
		$retValue = $false
		foreach ($VM in $allVMData)
		{
			$vmErrors = 0
			$BootLogDir="$Logdir\$($VM.RoleName)"
			mkdir $BootLogDir -Force | Out-Null
			LogMsg "Collecting $($VM.RoleName) VM Kernel $status Logs.."
			$currentKernelLogFile="$BootLogDir\CurrentKernelLogs.txt"
			$out = RunLinuxCmd -ip $VM.PublicIP -port $VM.SSHPort -username $vmUser -password $vmPassword -command "dmesg > /home/$vmUser/CurrentKernelLogs.txt" -runAsSudo
			$out = RemoteCopy -download -downloadFrom $VM.PublicIP -port $VM.SSHPort -files "/home/$vmUser/CurrentKernelLogs.txt" -downloadTo $BootLogDir -username $vmUser -password $vmPassword
			LogMsg "$($VM.RoleName): $status Kernel logs collected ..SUCCESSFULLY"
			foreach ($errorLine in $errorLines)
			{
				LogMsg "Checking for $errorLine in kernel logs.."
				$KernelLogs = Get-Content $currentKernelLogFile 
				$callTraceFound  = $false
				foreach ( $line in $KernelLogs )
				{
					if ( ($line -imatch "$errorLine") -and ($line -inotmatch "initcall "))
					{
						LogError $line
						$totalErrors += 1
						$vmErrors += 1
					}
					if ( $line -imatch "\[<")
					{
						LogError $line
					}
				}
			}
			if ( $vmErrors -eq 0 )
			{
				LogMsg "$($VM.RoleName) : No issues in kernel logs."
				$retValue = $true
			}
			else
			{
				LogError "$($VM.RoleName) : $vmErrors errors found."
				$retValue = $false
			}
		}
		if ( $totalErrors -eq 0 )
		{
			$retValue = $true
		}
		else
		{
			$retValue = $false
		}
	}
	catch
	{
		$retValue = $false
	}
	return $retValue
}
Function SetDistroSpecificVariables($detectedDistro)
{
	$python_cmd = "python"	
	LogMsg "Set `$python_cmd > $python_cmd"
	Set-Variable -Name python_cmd -Value $python_cmd -Scope Global
	Set-Variable -Name ifconfig_cmd -Value "ifconfig" -Scope Global
	if(($detectedDistro -eq "SLES") -or ($detectedDistro -eq "SUSE"))
	{
		Set-Variable -Name ifconfig_cmd -Value "/sbin/ifconfig" -Scope Global
		Set-Variable -Name fdisk -Value "/sbin/fdisk" -Scope Global
		LogMsg "Set `$ifconfig_cmd > $ifconfig_cmd for $detectedDistro"
		LogMsg "Set `$fdisk > /sbin/fdisk for $detectedDistro"
	}
	else
	{
		Set-Variable -Name fdisk -Value "fdisk" -Scope Global
		LogMsg "Set `$fdisk > fdisk for $detectedDistro"
	}
}

Function DeployManagementServices ($xmlConfig, $setupType, $Distro, $getLogsIfFailed = $false, $GetDeploymentStatistics = $false, [string]$region ="", [string]$storageAccount="",[int]$timeOutSeconds)
{
	if( (!$EconomyMode) -or ( $EconomyMode -and ($xmlConfig.config.Azure.Deployment.$setupType.isDeployed -eq "NO")))
	{
		try
		{
			$position = 0
			$VerifiedServices =  $NULL
			$retValue = $NULL
			$position = 1
			$i = 0
			$role = 1
			$setupTypeData = $xmlConfig.config.Azure.Deployment.$setupType
			$isAllDeployed = CreateAllDeployments -xmlConfig $xmlConfig -setupType $setupType -Distro $Distro -region $region -storageAccount $storageAccount -timeOutSeconds $timeOutSeconds
			$isAllVerified = "False"
			$isAllConnected = "False"
			if($isAllDeployed[0] -eq "True")
			{
				$deployedServices = $isAllDeployed[1]
				$DeploymentElapsedTime = $isAllDeployed[2]
				$servicesToVerify = $deployedServices.Split('^')
				if ( $GetDeploymentStatistics )
				{
					$VMBooTime = GetVMBootTime -DeployedServices $deployedServices -TimeoutInSeconds 200
					$verifyAll = VerifyAllDeployments -servicesToVerify $servicesToVerify -GetVMProvisionTime $GetDeploymentStatistics
					$isAllVerified = $verifyAll[0]
					$VMProvisionTime = $verifyAll[1]
				}
				else
				{
					$isAllVerified = VerifyAllDeployments -servicesToVerify $servicesToVerify
				}
				if ($isAllVerified -eq "True")
				{
					$allVMData = GetAllDeployementData -DeployedServices $deployedServices
					Set-Variable -Name allVMData -Value $allVMData -Force -Scope Global
					$isAllConnected = isAllSSHPortsEnabledRG -AllVMDataObject $allVMData
					if ($isAllConnected -eq "True")
					{
			#Set-Content .\temp\DeployedServicesFile.txt "$deployedServices"
						$VerifiedServices = $deployedServices
						$retValue = $VerifiedServices
						$vnetIsAllConfigured = $false
						$xmlConfig.config.Azure.Deployment.$setupType.isDeployed = $retValue
					#Collecting Initial Kernel
						$user=$xmlConfig.config.Azure.Deployment.Data.UserName
						$KernelLogOutput= GetAndCheckKernelLogs -allDeployedVMs $allVMData -status "Initial"
					}
					else
					{
						Write-Host "Unable to connect Some/All SSH ports.."
						$retValue = $NULL  
					}
				}
				else
				{
					Write-Host "Provision Failed for one or more VMs"
					$retValue = $NULL
				}

			}
			else
			{
				Write-Host "One or More Deployments are Failed..!"
				$retValue = $NULL
			}
			# get the logs of the first provision-failed VM
			if ($retValue -eq $NULL -and $getLogsIfFailed -and $DebugOsImage)
			{
				foreach ($service in $servicesToVerify)
				{
					$VMs = Get-AzureVM -ServiceName $service
					foreach ($vm in $VMs)
					{
						if ($vm.InstanceStatus -ne "ReadyRole" )
						{
							$out = GetLogsFromProvisionFailedVM -vmName $vm.Name -serviceName $service -xmlConfig $xmlConfig
							return $NULL
						}
					}
				}
			}
		}
		catch
		{
			if ($position -eq 0)
			{
				Write-Host "Failed to execute Get-AzureService. Source : DeployVMs()"
			}
			else
			{
				Write-Host "Exception detected. Source : DeployVMs()"
				Write-Host "$($_.Exception.GetType().FullName, " : ",$_.Exception.Message)"
			}
			$retValue = $NULL
		}
	}
	else
	{
		$retValue = $xmlConfig.config.Azure.Deployment.$setupType.isDeployed
		$KernelLogOutput= GetAndCheckKernelLogs -allDeployedVMs $allVMData -status "Initial"
	}
	Set-Variable -Name setupType -Value $setupType -Scope Global
	if ( $GetDeploymentStatistics )
	{
		return $retValue, $DeploymentElapsedTime, $VMBooTime, $VMProvisionTime
	}
	else
	{
		return $retValue
	}
}

Function DeployVMs ($xmlConfig, $setupType, $Distro, $getLogsIfFailed = $false, $GetDeploymentStatistics = $false, [string]$region = "", [string]$storageAccount = "", [int]$timeOutSeconds = 600)
{
    $AzureSetup = $xmlConfig.config.Azure.General

	if ($UseAzureResourceManager)
	{
        if($storageAccount)
        {
		 LogMsg "CurrentStorageAccount  : $($storageAccount)"
        }
       $retValue = DeployResourceGroups  -xmlConfig $xmlConfig -setupType $setupType -Distro $Distro -getLogsIfFailed $getLogsIfFailed -GetDeploymentStatistics $GetDeploymentStatistics -region $region -storageAccount $storageAccount 
	}
	else
	{
        if($storageAccount)
        {
         LogMsg "CurrentStorageAccount  : $($storageAccount)"
       }
		$retValue = DeployManagementServices -xmlConfig $xmlConfig -setupType $setupType -Distro $Distro -getLogsIfFailed $getLogsIfFailed -GetDeploymentStatistics $GetDeploymentStatistics -region $region -storageAccount $storageAccount -timeOutSeconds $timeOutSeconds
	}
    if ( $retValue -and $customKernel)
    {
        LogMsg "Custom kernel: $customKernel will be installed on all machines..."
        $kernelUpgradeStatus = InstallCustomKernel -customKernel $customKernel -allVMData $allVMData -RestartAfterUpgrade
        if ( !$kernelUpgradeStatus )
        {
            LogError "Custom Kernel: $customKernel installation FAIL. Aborting tests."
            $retValue = ""
        }
    }
    if ( $retValue -and $customLIS)
    {
        LogMsg "Custom LIS: $customLIS will be installed on all machines..."
        $LISUpgradeStatus = InstallCustomLIS -customLIS $customLIS -allVMData $allVMData -customLISBranch $customLISBranch -RestartAfterUpgrade
        if ( !$LISUpgradeStatus )
        {
            LogError "Custom Kernel: $customKernel installation FAIL. Aborting tests."
            $retValue = ""
        }
    }
    if ( $retValue -and $EnableAcceleratedNetworking)
    {
		$SRIOVStatus = EnableSRIOVInAllVMs -allVMData $allVMData
		if ( !$SRIOVStatus)
		{
            LogError "Failed to enable Accelerated Networking. Aborting tests."
            $retValue = ""
		}
    }



    if ( $retValue -and $resizeVMsAfterDeployment)
    {
		$SRIOVStatus = EnableSRIOVInAllVMs -allVMData $allVMData
		if ( $SRIOVStatus -ne "True" )
		{
            LogError "Failed to enable Accelerated Networking. Aborting tests."
            $retValue = ""
		}
    }
	return $retValue
}

function GetLogsFromProvisionFailedVM ($vmName, $serviceName, $xmlConfig)
{
	try
	{
		LogMsg "Stopping the provision-failed VM : $vmName"
		$tmp = Stop-AzureVM -ServiceName $serviceName -Name $vmName -Force
		LogMsg "Stopped the VM succussfully"
		
		LogMsg "Capturing the provision-failed VM Image"
		$ErrorImageName = "$serviceName-fail"
		$tmp = Save-AzureVMImage -ServiceName $serviceName -Name $vmName -NewImageName $ErrorImageName -NewImageLabel $ErrorImageName
		LogMsg "Successfully captured VM image : $ErrorImageName"
		$vhdLink = (Get-AzureVMImage -ImageName $ErrorImageName).MediaLink

		$debugVMName = "$serviceName-debug"
		$debugVMUser = $xmlConfig.config.Azure.Deployment.Data.UserName
		$debugVMPasswd = $xmlConfig.config.Azure.Deployment.Data.Password

		$debugSshPath = "/home/$debugVMUser/.ssh/authorized_keys"

		LogMsg "Creating debug VM $debugVMName in service $serviceName"
		$newVmConfigCmd = "New-AzureVMConfig -Name $debugVMName -InstanceSize `"Basic_A1`" -ImageName $DebugOsImage | Add-AzureProvisioningConfig -Linux -LinuxUser $debugVMUser -Password $debugVMPasswd -SSHPublicKeys (New-AzureSSHKey -PublicKey -Fingerprint `"690076D4C41C1DE677CD464EA63B44AE94C2E621`" -Path $debugSshPath) | Set-AzureEndpoint -Name `"SSH`" -LocalPort 22 -PublicPort 22 -Protocol `"TCP`""
		$newVmCmd = "New-AzureVM -ServiceName $serviceName -VMs ($newVmConfigCmd)"
		
		$out = RunAzureCmd -AzureCmdlet $newVmCmd

		$isVerified = VerifyAllDeployments -servicesToVerify @($serviceName)
		if ($isVerified -eq "True")
		{
			$isConnected = isAllSSHPortsEnabled -DeployedServices $serviceName
			if ($isConnected -ne "True")
			{
				return
			}
		}

		LogMsg "Removing image $ErrorImageName, keep the VHD $vhdLink"
		Remove-AzureVMImage -ImageName $ErrorImageName

		LogMsg "Attaching VHD $vhdLink to VM $debugVMName"	
		$vm = Get-AzureVM -ServiceName $serviceName -Name $debugVMName
		$vm | Add-AzureDataDisk -ImportFrom -MediaLocation $vhdLink -DiskLabel "main" -LUN 0 | Update-AzureVM

		$ip = (Get-AzureEndpoint -VM $vm)[0].Vip

		$runFile = "remote-scripts\GetLogFromDataDisk.py"
		$out = RemoteCopy -uploadTo $ip -port 22  -files "$runFile" -username $debugVMUser -password $debugVMPasswd -upload

		$out = RunLinuxCmd -ip $ip -port 22 -username $debugVMUser -password $debugVMPasswd -command "chmod +x *" -runAsSudo
		$out = RunLinuxCmd -ip $ip -port 22 -username $debugVMUser -password $debugVMPasswd -command "./GetLogFromDataDisk.py -u $debugVMUser" -runAsSudo

		$dir = "$LogDir\$vmName"
		if (-not (Test-Path $dir))
		{
			mkdir $dir
		}
		LogMsg "Downloading logs from the VHD"
		$out = RemoteCopy -download -downloadFrom $ip -port 22 -files "/home/$debugVMUser/waagent.log" -downloadTo $dir -username $debugVMUser -password $debugVMPasswd
		$out = RemoteCopy -download -downloadFrom $ip -port 22 -files "/home/$debugVMUser/messages.log" -downloadTo $dir -username $debugVMUser -password $debugVMPasswd
		$out = RemoteCopy -download -downloadFrom $ip -port 22 -files "/home/$debugVMUser/dmesg.log" -downloadTo $dir -username $debugVMUser -password $debugVMPasswd

		LogMsg "Stopping VM $debugVMName"
		$tmp = Stop-AzureVM -ServiceName $serviceName -Name $debugVMName -Force

		# Remove the Cloud Service
		LogMsg "Executing: Remove-AzureService -ServiceName $serviceName -Force -DeleteAll"
		Remove-AzureService -ServiceName $serviceName -Force -DeleteAll
	}
	catch
	{
		$ErrorMessage =  $_.Exception.Message
		LogMsg "EXCEPTION in GetLogsFromProvisionFailedVM() : $ErrorMessage"
	}
}
Function Test-TCP($testIP, $testport)
{
	$socket = new-object Net.Sockets.TcpClient
	$isConnected = "False"
	try
	{
		$socket.Connect($testIP, $testPort) 
	}
	catch [System.Net.Sockets.SocketException]
	{
	}
	if ($socket.Connected) 
	{
		$isConnected = "True"
	}
	$socket.Close()
	return $isConnected
}

Function GetOSImageFromDistro($Distro, $xmlConfig)
{
	foreach ($newDistro in $xmlConfig.config.Azure.Deployment.Data.Distro)  #........v-shisav... needed for getting the OS image.. Removed hardcoding...
	{ 
		if ($newDistro.Name -eq $Distro)
		{
			$osImage = $newDistro.OsImage
			break
		}
	}
	return $osImage
}

Function SetOSImageToDistro($Distro, $xmlConfig, $ImageName)
{
	$i = 0
	foreach ($newDistro in $xmlConfig.config.Azure.Deployment.Data.Distro)  #........v-shisav... needed for getting the OS image.. Removed hardcoding...
	{ 
		if ($newDistro.Name -eq $Distro)
		{
			$xmlConfig.config.Azure.Deployment.Data.Distro[$i].OsImage = $ImageName
			break
		}
		$i = $i + 1
	}
	Set-Variable -Name xmlConfig -Value $xmlConfig -Scope Global
	return $true
}

Function GetPort($Endpoints, $usage)
{
	foreach ($port in $Endpoints)
	{
		if ($port.Name -imatch $usage)
		{
			$tcpPort = $port.Port
			return $tcpPort
			break
		}
	}
}

Function isAllSSHPortsEnabled($DeployedServices)
{
	LogMsg "Trying to Connect to deployed VM(s)"

	$TestIPPOrts = ""

	foreach ($hostedservice in $DeployedServices.Split("^"))
	{
		$DeployedVMs = Get-AzureVM -ServiceName $hostedService
		foreach ($testVM in $DeployedVMs)
		{
			$AllEndpoints = Get-AzureEndpoint -VM $testVM
			$HSVIP = GetHsVmVip -servicename $hostedservice
			$HSport = GetPort -Endpoints $AllEndpoints -usage SSH
			if($TestIPPOrts)
			{
				$TestIPPOrts = $TestIPPOrts + "^$HSVIP" + ':' +"$HSport"
			}
			else
			{
				$TestIPPOrts = "$HSVIP" + ':' +"$HSport"
			}


		}
	}
	$timeout = 0
	do
	{
		$WaitingForConnect = 0
		foreach ($IPPORT in $TestIPPOrts.Split("^"))
		{
			$IPPORT = $IPPORT.Split(":")
			$testIP = $IPPORT[0]
			$testPort = $IPPORT[1]
			$out = Test-TCP  -testIP $TestIP -testport $testPort
			if ($out -ne "True")
			{
				LogMsg "Connecting to  $TestIP : $testPort : Failed"
				$WaitingForConnect = $WaitingForConnect + 1
			}
			else
			{
				LogMsg "Connecting to  $TestIP : $testPort : Connected"
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

	return $retValue
}
Function GetVMBootTime($DeployedServices, $TimeoutInSeconds)
{
	$VMBootStarted = Get-Date
	$TestIPPOrts = ""
	$sleepTime = 1
	$maxRetryCount = $TimeoutInSeconds / $sleepTime
	foreach ($hostedservice in $DeployedServices.Split("^"))
	{
		$DeployedVMs = Get-AzureVM -ServiceName $hostedService
		foreach ($testVM in $DeployedVMs)
		{
			$AllEndpoints = Get-AzureEndpoint -VM $testVM
			$HSVIP = GetHsVmVip -servicename $hostedservice
			$HSport = GetPort -Endpoints $AllEndpoints -usage SSH
			if($TestIPPOrts)
			{
				$TestIPPOrts = $TestIPPOrts + "^$HSVIP" + ':' +"$HSport"
			}
			else
			{
				$TestIPPOrts = "$HSVIP" + ':' +"$HSport"
			}
		}
	}
	$timeout = 0
	do
	{
		$WaitingForConnect = 0
		foreach ($IPPORT in $TestIPPOrts.Split("^"))
		{
			$IPPORT = $IPPORT.Split(":")
			$testIP = $IPPORT[0]
			$testPort = $IPPORT[1]
			Write-Host "Connecting to  $TestIP : $testPort" -NoNewline
			$out = Test-TCP  -testIP $TestIP -testport $testPort
			if ($out -ne "True")
			{ 
				Write-Host " : Failed"
				$WaitingForConnect = $WaitingForConnect + 1
			}
			else
			{
				Write-Host " : Connected"
			}
			
		}
		
		if($WaitingForConnect -gt 0)
		{
			$timeout = $timeout + 1
			Write-Host "$WaitingForConnect VM(s) still awaiting to open SSH port.." -NoNewline
			Write-Host "Retry $timeout/$maxRetryCount"
			sleep $sleepTime
			$retValue = "False"
		}
		else
		{
			LogMsg "ALL VM's SSH port is/are open now.."
			$retValue = "True"
		}
	}
	While (($timeout -lt $maxRetryCount) -and ($WaitingForConnect -gt 0))
	$VMBootFinished =  Get-Date
	$VMBootElapsedTime = $VMBootFinished - $VMBootStarted
	return $VMBootElapsedTime
}
Function GetHsVmVip($servicename)
{
	$endpoints = Get-AzureVM  -ServiceName $servicename | Get-AzureEndpoint
	$vip = $endpoints[0].Vip
	return $VIP
}

Function GetProbePort($Endpoints, $usage)
{
	foreach ($port in $Endpoints)
	{
		if ($port.Name -imatch $usage)
		{
			$tcpPort = $port.ProbePort
			return $tcpPort
			break
		}
	}
}

Function ApplyDONOTDISTURBtoHostedServices($DeployedServices)
{
	$DeployedServices = $DeployedServices.split("^")
	foreach ( $serviceName in $DeployedServices )
	{
		Set-AzureService -ServiceName $serviceName -Description "DONOTDISTURB"
	}
}

Function GetPlatfromImages()
{
	$allImages = Get-AzureVMImage
	$count = 1
	foreach ($image in $allImages)
	{
		if((!$image.MediaLink) -and ($image.OS -eq "Linux"))
		{
			Write-Host "$count. " -NoNewline -ForegroundColor Gray
			Write-Host "$($image.ImageName)"
			$count += 1
		}
	}
}	

Function RemoveEmptyHostedServices()
{
	$allServices = Get-AzureService
	$TotalServices = $allServices.Length
	$ServicesRemaining = $TotalServices
	$count = 1
	foreach ($service in $allServices)
	{
		$ServicesRemaining = $ServicesRemaining - 1
		$Percentage = (100 - (($ServicesRemaining/$TotalServices)*100))
		write-progress -Id 47 -activity Cheking.. -Status "$($service.ServiceName) ... " -percentcomplete $Percentage
		Write-Host "Checking $($service.ServiceName) ... " -NoNewline
		$out = Get-AzureDeployment -ServiceName $service.ServiceName 2>&1
		if ($out -imatch  "No deployments were found")
		{
			Write-Host "Deleting now... " -ForegroundColor Red -NoNewline
			write-progress -Id 47 -activity Deleting.. -Status "$($service.ServiceName) ... " -percentcomplete $Percentage
			$out = Remove-AzureService -ServiceName $service.ServiceName -Force
			Write-Host "Deleted!" -ForegroundColor Green
			write-progress -Id 47 -activity Deleted.. -Status "$($service.ServiceName)!" -percentcomplete $Percentage
		}
		else
		{
			write-progress -Id 47 -activity Cheking.. -Status "$($service.ServiceName) ... OK" -percentcomplete $Percentage
			Write-Host "OK!" -ForegroundColor Green
		}
		write-progress -Id 47 -activity SLEEPING -Status "Wait Completed..!" -percentcomplete $Percentage
	}
	write-progress -Id 47 -activity "Empty Services Removed..!"  -percentcomplete 100
}


Function RemoveICAOsImages([switch]$removeUploaded, [switch]$removeCaptured, [switch]$removeVHD)
{
	$allImages = Get-AzureVMImage
	$IcaUploaded = @()
	$IcaCaptured = @()
	$totalCount = 0
	$uploadedCount = 0
	$capturedCount = 0

	foreach ($image in $allImages)
	{
		if ( ($image.ImageName -imatch "ICA-UPLOADED") -or  ($image.ImageName -imatch "ICA-CAPTURED") )
		{
			if ( ($removeUploaded) -and ($image.ImageName -imatch "ICA-UPLOADED") )
			{
				$totalCount += 1
			}
			elseif (($removeCaptured) -and ($image.ImageName -imatch "ICA-CAPTURED"))
			{
				$totalCount += 1
			}
		}
	}
	Write-Host "Total Count =  $totalCount"
	$totalRemaining = $totalCount
	Write-Progress -Activity "Removing ICA OS Images" -Id 50 -PercentComplete 0
	foreach ($image in $allImages)
	{
		$SrNo = $totalCount - $totalRemaining + 1
		$tempImage =   $image.ImageName	  
		if ($image.ImageName -imatch "ICA-UPLOADED")
		{

			if($removeUploaded)
			{
				Write-Progress  -Id 50 -Activity "Removing ICA OS Images" -CurrentOperation "$SrNo/$totalCount. $tempImage" -PercentComplete (100 - (($totalRemaining/$totalCount)*100))
				if ($removeVHD)
				{
					Write-Host "Removing $tempImage with VHD"
					$out = Remove-AzureVMImage -ImageName $tempImage  -DeleteVHD

				}
				else
				{
					Write-Host "Removing $tempImage keeping VHD"
					$out = Remove-AzureVMImage -ImageName $tempImage

				}
				$totalRemaining -= 1
			}
		}
		if ($image.ImageName -imatch "ICA-CAPTURED")
		{
			if($removeCaptured)
			{
				Write-Progress  -Id 50 -Activity "Removing ICA OS Images" -CurrentOperation "$SrNo/$totalCount. $tempImage" -PercentComplete (100 - (($totalRemaining/$totalCount)*100))
				if ($removeVHD)
				{
					Write-Host "Removing $tempImage with VHD"
					$out = Remove-AzureVMImage -ImageName $tempImage  -DeleteVHD

				}
				else
				{
					Write-Host "Removing $tempImage keeping VHD"
					$out = Remove-AzureVMImage -ImageName $tempImage

				}
				$totalRemaining -= 1
			} 
		}
	}
	Write-Progress  -Id 50 -Activity "Removing ICA OS Images" -Completed 
}

Function GetTestVMHardwareDetails ($xmlConfigFile, $setupType, [switch]$VCPU, [switch]$RAM)
{
	$switchCount = 0
	if ($VCPU)
	{
		$switchCount += 1
	}
	if ($RAM)
	{
		$switchCount += 1
	}

	if ($switchCount -lt 1)
	{
		LogError "Use atleast one switch from `$VCPU or `$RAM.."
		$retValue = "Error"
	}
	elseif ($switchCount -gt 1 )
	{
		LogError "Use only one switch from `$VCPU or `$RAM.."
		$retValue = "Error"
	}
	elseif ($switchCount -eq 1)
	{
		try
		{
			$testVMSize = $xmlConfigFile.config.Azure.Deployment.$setupType.HostedService.VirtualMachine.InstanceSize
			foreach ($size in $testVMSize)
			{
				$testVMDetails = $xmlConfigFile.config.Azure.Deployment.Data.VMsizes.$size 
				if ($VCPU)
				{
					if (!$retValue)
					{
						$retValue = $($testVMDetails.VCPU)
					}
					else
					{
						$retValue = "$retValue," + $($testVMDetails.VCPU)
					}
				}
				elseif ($RAM)
				{
					if (!$retValue)
					{
						$retValue = $($testVMDetails.RAM)
					}
					else
					{
						$retValue = "$retValue," + $($testVMDetails.RAM)
					}				
				}
			}
		}
		catch
		{
			LogError "Unable to find $setupType details."
			$retValue = "Unknown"
		}
	}

	return $retValue
}
#endregion

#region Linux Commands Methods
Function RemoteCopy($uploadTo, $downloadFrom, $downloadTo, $port, $files, $username, $password, [switch]$upload, [switch]$download, [switch]$usePrivateKey, [switch]$doNotCompress) #Removed XML config
{
	$retry=1
	$maxRetry=20
	if($upload)
	{
#LogMsg "Uploading the files"
		if ($files)
		{
			$fileCounter = 0
			$tarFileName = ($uploadTo+"@"+$port).Replace(".","-")+".tar"
			foreach ($f in $files.Split(","))
			{
				if ( !$f )
				{
					continue
				}
				else
				{
					if ( ( $f.Split(".")[$f.Split(".").count-1] -eq "sh" ) -or ( $f.Split(".")[$f.Split(".").count-1] -eq "py" ) )
					{
						$out = .\tools\dos2unix.exe $f 2>&1
						LogMsg $out
					}
					$fileCounter ++
				}
			}
			if (($fileCounter -gt 2) -and (!($doNotCompress)))
			{
				$tarFileName = ($uploadTo+"@"+$port).Replace(".","-")+".tar"
				foreach ($f in $files.Split(","))
				{
					if ( !$f )
					{
						continue
					}
					else
					{
						LogMsg "Compressing $f and adding to $tarFileName"
						$CompressFile = .\tools\7za.exe a $tarFileName $f
						if ( $CompressFile -imatch "Everything is Ok" )
						{
							$CompressCount += 1
						}
					}
				}				
				if ( $CompressCount -eq $fileCounter )
				{
					$retry=1
					$maxRetry=10
					while($retry -le $maxRetry)
					{
						if($usePrivateKey)
						{
							LogMsg "Uploading $tarFileName to $username : $uploadTo, port $port using PrivateKey authentication"
							echo y | .\tools\pscp -i .\ssh\$sshKey -q -P $port $tarFileName $username@${uploadTo}:
							$returnCode = $LASTEXITCODE
						}
						else
						{
							LogMsg "Uploading $tarFileName to $username : $uploadTo, port $port using Password authentication"
							$curDir = $PWD
							$uploadStatusRandomFile = "UploadStatusFile" + (Get-Random -Maximum 9999 -Minimum 1111) + ".txt"
							$uploadStartTime = Get-Date
							$uploadJob = Start-Job -ScriptBlock { cd $args[0]; Write-Host $args; Set-Content -Value "1" -Path $args[6]; $username = $args[4]; $uploadTo = $args[5]; echo y | .\tools\pscp -v -pw $args[1] -q -P $args[2] $args[3] $username@${uploadTo}: ; Set-Content -Value $LASTEXITCODE -Path $args[6];} -ArgumentList $curDir,$password,$port,$tarFileName,$username,${uploadTo},$uploadStatusRandomFile
							sleep -Milliseconds 100
							$uploadJobStatus = Get-Job -Id $uploadJob.Id
							$uploadTimout = $false
							while (( $uploadJobStatus.State -eq "Running" ) -and ( !$uploadTimout ))					
							{
								Write-Host "." -NoNewline
								$now = Get-Date
								if ( ($now - $uploadStartTime).TotalSeconds -gt 600 )
								{
									$uploadTimout = $true
									LogError "Upload Timout!"
								}
								sleep -Seconds 1
								$uploadJobStatus = Get-Job -Id $uploadJob.Id
							}
							Write-Host ""
							$returnCode = Get-Content -Path $uploadStatusRandomFile
							Remove-Item -Force $uploadStatusRandomFile | Out-Null
							Remove-Job -Id $uploadJob.Id -Force | Out-Null
						}
						if(($returnCode -ne 0) -and ($retry -ne $maxRetry))
						{
							LogWarn "Error in upload, Attempt $retry. Retrying for upload"
							$retry=$retry+1
							WaitFor -seconds 10
						}
						elseif(($returnCode -ne 0) -and ($retry -eq $maxRetry))
						{
							Write-Host "Error in upload after $retry Attempt,Hence giving up"
							$retry=$retry+1
							Throw "Calling function - $($MyInvocation.MyCommand). Error in upload after $retry Attempt,Hence giving up"
						}
						elseif($returnCode -eq 0)
						{
							LogMsg "Upload Success after $retry Attempt"
							$retry=$maxRetry+1
						}
					}
					LogMsg "Removing compressed file : $tarFileName"
					Remove-Item -Path $tarFileName -Force 2>&1 | Out-Null
					LogMsg "Decompressing files in VM ..."
					if ( $username -eq "root" )
					{
						$out = RunLinuxCmd -username $username -password $password -ip $uploadTo -port $port -command "tar -xf $tarFileName"
					}
					else
					{
						$out = RunLinuxCmd -username $username -password $password -ip $uploadTo -port $port -command "tar -xf $tarFileName" -runAsSudo
					}
					
				}
				else
				{
					Throw "Calling function - $($MyInvocation.MyCommand). Failed to compress $files"
					Remove-Item -Path $tarFileName -Force 2>&1 | Out-Null
				}
			}
			else
			{
				$files = $files.split(",")
				foreach ($f in $files)
				{
					if ( !$f )
					{
						continue
					}
					$retry=1
					$maxRetry=10
					$testFile = $f.trim()
					$recurse = ""
					while($retry -le $maxRetry)
					{
						if($usePrivateKey)
						{
							LogMsg "Uploading $testFile to $username : $uploadTo, port $port using PrivateKey authentication"
							echo y | .\tools\pscp -i .\ssh\$sshKey -q -P $port $testFile $username@${uploadTo}:
							$returnCode = $LASTEXITCODE
						}
						else
						{
							LogMsg "Uploading $testFile to $username : $uploadTo, port $port using Password authentication"
							$curDir = $PWD
							$uploadStatusRandomFile = "UploadStatusFile" + (Get-Random -Maximum 9999 -Minimum 1111) + ".txt"
							$uploadStartTime = Get-Date
							$uploadJob = Start-Job -ScriptBlock { cd $args[0]; Write-Host $args; Set-Content -Value "1" -Path $args[6]; $username = $args[4]; $uploadTo = $args[5]; echo y | .\tools\pscp -v -pw $args[1] -q -P $args[2] $args[3] $username@${uploadTo}: ; Set-Content -Value $LASTEXITCODE -Path $args[6];} -ArgumentList $curDir,$password,$port,$testFile,$username,${uploadTo},$uploadStatusRandomFile
							sleep -Milliseconds 100
							$uploadJobStatus = Get-Job -Id $uploadJob.Id
							$uploadTimout = $false
							while (( $uploadJobStatus.State -eq "Running" ) -and ( !$uploadTimout ))					
							{
								Write-Host "." -NoNewline
								$now = Get-Date
								if ( ($now - $uploadStartTime).TotalSeconds -gt 600 )
								{
									$uploadTimout = $true
									LogError "Upload Timout!"
								}
								sleep -Seconds 1
								$uploadJobStatus = Get-Job -Id $uploadJob.Id
							}
							Write-Host ""
							$returnCode = Get-Content -Path $uploadStatusRandomFile
							Remove-Item -Force $uploadStatusRandomFile | Out-Null
							Remove-Job -Id $uploadJob.Id -Force | Out-Null
						}
						if(($returnCode -ne 0) -and ($retry -ne $maxRetry))
						{
							LogWarn "Error in upload, Attempt $retry. Retrying for upload"
							$retry=$retry+1
							WaitFor -seconds 10
						}
						elseif(($returnCode -ne 0) -and ($retry -eq $maxRetry))
						{
							Write-Host "Error in upload after $retry Attempt,Hence giving up"
							$retry=$retry+1
							Throw "Calling function - $($MyInvocation.MyCommand). Error in upload after $retry Attempt,Hence giving up"
						}
						elseif($returnCode -eq 0)
						{
							LogMsg "Upload Success after $retry Attempt"
							$retry=$maxRetry+1
						}
					}
				}
			}
		}
		else
		{
			LogMsg "No Files to upload...!"
			Throw "Calling function - $($MyInvocation.MyCommand). No Files to upload...!"
		}

	}
	elseif($download)
	{
#Downloading the files
		if ($files)
		{
			$files = $files.split(",")
			foreach ($f in $files)
			{
				$retry=1
				$maxRetry=50
				$testFile = $f.trim()
				$recurse = ""
				while($retry -le $maxRetry)
				{
					if($usePrivateKey)
					{
						LogMsg "Downloading $testFile from $username : $downloadFrom,port $port to $downloadTo using PrivateKey authentication"
						$curDir = $PWD
						$downloadStatusRandomFile = "DownloadStatusFile" + (Get-Random -Maximum 9999 -Minimum 1111) + ".txt"
						$downloadStartTime = Get-Date
						$downloadJob = Start-Job -ScriptBlock { $curDir=$args[0];$sshKey=$args[1];$port=$args[2];$testFile=$args[3];$username=$args[4];${downloadFrom}=$args[5];$downloadTo=$args[6];$downloadStatusRandomFile=$args[7]; cd $curDir; Set-Content -Value "1" -Path $args[6]; echo y | .\tools\pscp -i .\ssh\$sshKey -q -P $port $username@${downloadFrom}:$testFile $downloadTo; Set-Content -Value $LASTEXITCODE -Path $downloadStatusRandomFile;} -ArgumentList $curDir,$sshKey,$port,$testFile,$username,${downloadFrom},$downloadTo,$downloadStatusRandomFile
						sleep -Milliseconds 100
						$downloadJobStatus = Get-Job -Id $downloadJob.Id
						$downloadTimout = $false
						while (( $downloadJobStatus.State -eq "Running" ) -and ( !$downloadTimout ))					
						{
							Write-Host "." -NoNewline
							$now = Get-Date
							if ( ($now - $downloadStartTime).TotalSeconds -gt 600 )
							{
								$downloadTimout = $true
								LogError "Download Timout!"
							}
							sleep -Seconds 1
							$downloadJobStatus = Get-Job -Id $downloadJob.Id
						}
						Write-Host ""
						$returnCode = Get-Content -Path $downloadStatusRandomFile
						Remove-Item -Force $downloadStatusRandomFile | Out-Null
						Remove-Job -Id $downloadJob.Id -Force | Out-Null
					}
					else
					{
						LogMsg "Downloading $testFile from $username : $downloadFrom,port $port to $downloadTo using Password authentication"
						$curDir =  (Get-Item -Path ".\" -Verbose).FullName
						$downloadStatusRandomFile = "DownloadStatusFile" + (Get-Random -Maximum 9999 -Minimum 1111) + ".txt"
						Set-Content -Value "1" -Path $downloadStatusRandomFile;
						$downloadStartTime = Get-Date
						$downloadJob = Start-Job -ScriptBlock { 
							$curDir=$args[0];
							$password=$args[1];
							$port=$args[2];
							$testFile=$args[3];
							$username=$args[4];
							${downloadFrom}=$args[5];
							$downloadTo=$args[6];
							$downloadStatusRandomFile=$args[7];
							cd $curDir; 
							echo y | .\tools\pscp.exe  -v -2 -unsafe -pw $password -q -P $port $username@${downloadFrom}:$testFile $downloadTo 2> $downloadStatusRandomFile; 
							Add-Content -Value "DownloadExtiCode_$LASTEXITCODE" -Path $downloadStatusRandomFile;
						} -ArgumentList $curDir,$password,$port,$testFile,$username,${downloadFrom},$downloadTo,$downloadStatusRandomFile
						sleep -Milliseconds 100
						$downloadJobStatus = Get-Job -Id $downloadJob.Id
						$downloadTimout = $false
						while (( $downloadJobStatus.State -eq "Running" ) -and ( !$downloadTimout ))					
						{
							Write-Host "." -NoNewline
							$now = Get-Date
							if ( ($now - $downloadStartTime).TotalSeconds -gt 600 )
							{
								$downloadTimout = $true
								LogError "Download Timout!"
							}
							sleep -Seconds 1
							$downloadJobStatus = Get-Job -Id $downloadJob.Id
						}
						Write-Host ""
						$downloadExitCode = (Select-String -Path $downloadStatusRandomFile -Pattern "DownloadExtiCode_").Line
						if ( $downloadExitCode )
						{
							$returnCode = $downloadExitCode.Replace("DownloadExtiCode_",'')
						}
						if ( $returnCode -eq 0)
						{
							LogMsg "Download command returned exit code 0"
						}
						else 
						{
							$receivedFiles = Select-String -Path "$downloadStatusRandomFile" -Pattern "Sending file"
							if ($receivedFiles.Count -ge 1)
							{
								LogMsg "Received $($receivedFiles.Count) file(s)"
								$returnCode = 0
							}
							else 
							{
								LogMsg "Download command returned exit code $returnCode"
								LogMsg "$(Get-Content -Path $downloadStatusRandomFile)"
							}
						}
						Remove-Item -Force $downloadStatusRandomFile | Out-Null
						Remove-Job -Id $downloadJob.Id -Force | Out-Null
					}
					if(($returnCode -ne 0) -and ($retry -ne $maxRetry))
					{
						LogWarn "Error in download, Attempt $retry. Retrying for download"
						$retry=$retry+1
					}
					elseif(($returnCode -ne 0) -and ($retry -eq $maxRetry))
					{
						Write-Host "Error in download after $retry Attempt,Hence giving up"
						$retry=$retry+1
						Throw "Calling function - $($MyInvocation.MyCommand). Error in download after $retry Attempt,Hence giving up."
					}
					elseif($returnCode -eq 0)
					{
						LogMsg "Download Success after $retry Attempt"
						$retry=$maxRetry+1
					}
				}
			}
		}
		else
		{
			LogMsg "No Files to download...!"
			Throw "Calling function - $($MyInvocation.MyCommand). No Files to download...!"
		}
	}
	else
	{
		LogMsg "Error: Upload/Download switch is not used!"
	}
}

Function WrapperCommandsToFile([string] $username,[string] $password,[string] $ip,[string] $command, [int] $port)
{
    if ( ( $lastLinuxCmd -eq $command) -and ($lastIP -eq $ip) -and ($lastPort -eq $port) -and ($lastUser -eq $username) )
    {
        #Skip upload if current command is same as last command.
    }
    else
    {
        Set-Variable -Name lastLinuxCmd -Value $command -Scope Global
        Set-Variable -Name lastIP -Value $ip -Scope Global
        Set-Variable -Name lastPort -Value $port -Scope Global
        Set-Variable -Name lastUser -Value $username -Scope Global
	    $command | out-file -encoding ASCII -filepath "$LogDir\runtest.sh"
	    RemoteCopy -upload -uploadTo $ip -username $username -port $port -password $password -files ".\$LogDir\runtest.sh"
	    del "$LogDir\runtest.sh"
    }
}

Function RunLinuxCmd([string] $username,[string] $password,[string] $ip,[string] $command, [int] $port, [switch]$runAsSudo, [Boolean]$WriteHostOnly, [Boolean]$NoLogsPlease, [switch]$ignoreLinuxExitCode, [int]$runMaxAllowedTime = 300, [switch]$RunInBackGround)
{
	if ($detectedDistro -ne "COREOS" )
	{
		WrapperCommandsToFile $username $password $ip $command $port
	}
	$randomFileName = [System.IO.Path]::GetRandomFileName()
	$maxRetryCount = 20
	$currentDir = $PWD.Path
	$RunStartTime = Get-Date
	
	if($runAsSudo)
	{
		$plainTextPassword = $password.Replace('"','');
		if ( $detectedDistro -eq "COREOS" )
		{
			$linuxCommand = "`"export PATH=/usr/share/oem/python/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/share/oem/bin:/opt/bin && echo $plainTextPassword | sudo -S env `"PATH=`$PATH`" $command && echo AZURE-LINUX-EXIT-CODE-`$? || echo AZURE-LINUX-EXIT-CODE-`$?`""
			$logCommand = "`"export PATH=/usr/share/oem/python/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/share/oem/bin:/opt/bin && echo $plainTextPassword | sudo -S env `"PATH=`$PATH`" $command`""
		}
		else
		{
              
			$linuxCommand = "`"echo $plainTextPassword | sudo -S bash -c `'bash runtest.sh ; echo AZURE-LINUX-EXIT-CODE-`$?`' `""
			$logCommand = "`"echo $plainTextPassword | sudo -S $command`""
		}
	}
	else
	{
		if ( $detectedDistro -eq "COREOS" )
		{
			$linuxCommand = "`"export PATH=/usr/share/oem/python/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/share/oem/bin:/opt/bin && $command && echo AZURE-LINUX-EXIT-CODE-`$? || echo AZURE-LINUX-EXIT-CODE-`$?`""
			$logCommand = "`"export PATH=/usr/share/oem/python/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/share/oem/bin:/opt/bin && $command`""		
		}
		else
		{
			$linuxCommand = "`"bash -c `'bash runtest.sh ; echo AZURE-LINUX-EXIT-CODE-`$?`' `""
			$logCommand = "`"$command`""
		}
	}
	LogMsg ".\tools\plink.exe -t -pw $password -P $port $username@$ip $logCommand"
	$returnCode = 1
	$attemptswt = 0
	$attemptswot = 0
	$notExceededTimeLimit = $true
	$isBackGroundProcessStarted = $false
    
	while ( ($returnCode -ne 0) -and ($attemptswt -lt $maxRetryCount -or $attemptswot -lt $maxRetryCount) -and $notExceededTimeLimit)
	{
		if ($runwithoutt -or $attemptswt -eq $maxRetryCount)
		{
			Set-Variable -Name runwithoutt -Value true -Scope Global
			$attemptswot +=1
			$runLinuxCmdJob = Start-Job -ScriptBlock `
			{ `
				$username = $args[1]; $password = $args[2]; $ip = $args[3]; $port = $args[4]; $jcommand = $args[5]; `
				cd $args[0]; `
				#Write-Host ".\tools\plink.exe -t -C -v -pw $password -P $port $username@$ip $jcommand";`
				.\tools\plink.exe -C -v -pw $password -P $port $username@$ip $jcommand;`
			} `
			-ArgumentList $currentDir, $username, $password, $ip, $port, $linuxCommand
		}
		else
		{
			$attemptswt += 1
			$runLinuxCmdJob = Start-Job -ScriptBlock `
			{ `
				$username = $args[1]; $password = $args[2]; $ip = $args[3]; $port = $args[4]; $jcommand = $args[5]; `
				cd $args[0]; `
				#Write-Host ".\tools\plink.exe -t -C -v -pw $password -P $port $username@$ip $jcommand";`
				.\tools\plink.exe -t -C -v -pw $password -P $port $username@$ip $jcommand;`
			} `
			-ArgumentList $currentDir, $username, $password, $ip, $port, $linuxCommand
		}
		$RunLinuxCmdOutput = ""
		$debugOutput = ""
		$LinuxExitCode = ""
		if ( $RunInBackGround )
		{
			While(($runLinuxCmdJob.State -eq "Running") -and ($isBackGroundProcessStarted -eq $false ) -and $notExceededTimeLimit)
			{
				$SSHOut = Receive-Job $runLinuxCmdJob 2> $LogDir\$randomFileName
				$JobOut = Get-Content $LogDir\$randomFileName
				if($jobOut)
				{
					foreach($outLine in $jobOut)
					{
						if($outLine -imatch "Started a shell")
						{
							$LinuxExitCode = $outLine
							$isBackGroundProcessStarted = $true
							$returnCode = 0
						}
						else
						{
							$RunLinuxCmdOutput += "$outLine`n"
						}
					}
				}
				$debugLines = Get-Content $LogDir\$randomFileName
				if($debugLines)
				{
					$debugString = ""
					foreach ($line in $debugLines)
					{
						$debugString += $line
					}
					$debugOutput += "$debugString`n"
				}
				Write-Progress -Activity "Attempt : $attemptswot+$attemptswt : Initiating command in Background Mode : $logCommand on $ip : $port" -Status "Timeout in $($RunMaxAllowedTime - $RunElaplsedTime) seconds.." -Id 87678 -PercentComplete (($RunElaplsedTime/$RunMaxAllowedTime)*100) -CurrentOperation "SSH ACTIVITY : $debugString"
                #Write-Host "Attempt : $attemptswot+$attemptswt : Initiating command in Background Mode : $logCommand on $ip : $port"
				$RunCurrentTime = Get-Date
				$RunDiffTime = $RunCurrentTime - $RunStartTime
				$RunElaplsedTime =  $RunDiffTime.TotalSeconds
				if($RunElaplsedTime -le $RunMaxAllowedTime)
				{
					$notExceededTimeLimit = $true
				}
				else
				{
					$notExceededTimeLimit = $false
					Stop-Job $runLinuxCmdJob
					$timeOut = $true
				}
			}
			WaitFor -seconds 2
			$SSHOut = Receive-Job $runLinuxCmdJob 2> $LogDir\$randomFileName
			if($SSHOut )
			{
				foreach ($outLine in $SSHOut)
				{
					if($outLine -imatch "AZURE-LINUX-EXIT-CODE-")
					{
						$LinuxExitCode = $outLine
						$isBackGroundProcessTerminated = $true
					}
					else
					{
						$RunLinuxCmdOutput += "$outLine`n"
					}
				}
			}
			
			$debugLines = Get-Content $LogDir\$randomFileName
			if($debugLines)
			{
				$debugString = ""
				foreach ($line in $debugLines)
				{
					$debugString += $line
				}
				$debugOutput += "$debugString`n"
			}
			Write-Progress -Activity "Attempt : $attemptswot+$attemptswt : Executing $logCommand on $ip : $port" -Status $runLinuxCmdJob.State -Id 87678 -SecondsRemaining ($RunMaxAllowedTime - $RunElaplsedTime) -Completed
			if ( $isBackGroundProcessStarted -and !$isBackGroundProcessTerminated )
			{
				LogMsg "$command is running in background with ID $($runLinuxCmdJob.Id) ..."
				Add-Content -Path $LogDir\CurrentTestBackgroundJobs.txt -Value $runLinuxCmdJob.Id
				$retValue = $runLinuxCmdJob.Id
			}
			else
			{
				Remove-Job $runLinuxCmdJob 
				if (!$isBackGroundProcessStarted)
				{
					LogError "Failed to start process in background.."
				}
				if ( $isBackGroundProcessTerminated )
				{
					LogError "Background Process terminated from Linux side with error code :  $($LinuxExitCode.Split("-")[4])"
					$returnCode = $($LinuxExitCode.Split("-")[4])
					LogError $SSHOut
				}
				if($debugOutput -imatch "Unable to authenticate")
				{
					LogMsg "Unable to authenticate. Not retrying!"
					Throw "Calling function - $($MyInvocation.MyCommand). Unable to authenticate"

				}
				if($timeOut)
				{
					$retValue = ""
					Throw "Calling function - $($MyInvocation.MyCommand). Tmeout while executing command : $command"
				}
				LogError "Linux machine returned exit code : $($LinuxExitCode.Split("-")[4])"
				if ($attempts -eq $maxRetryCount)
				{
					Throw "Calling function - $($MyInvocation.MyCommand). Failed to execute : $command."
				}
				else
				{
					if ($notExceededTimeLimit)
					{
						LogMsg "Failed to execute : $command. Retrying..."
					}
				}
			}
			Remove-Item $LogDir\$randomFileName -Force | Out-Null   
		}
		else
		{
			While($notExceededTimeLimit -and ($runLinuxCmdJob.State -eq "Running"))
			{
				$jobOut = Receive-Job $runLinuxCmdJob 2> $LogDir\$randomFileName
				if($jobOut)
				{
					foreach ($outLine in $jobOut)
					{
						if($outLine -imatch "AZURE-LINUX-EXIT-CODE-")
						{
							$LinuxExitCode = $outLine
						}
						else
						{
							$RunLinuxCmdOutput += "$outLine`n"
						}
					}
				}
				$debugLines = Get-Content $LogDir\$randomFileName
				if($debugLines)
				{
					$debugString = ""
					foreach ($line in $debugLines)
					{
						$debugString += $line
					}
					$debugOutput += "$debugString`n"
				}
				Write-Progress -Activity "Attempt : $attemptswot+$attemptswt : Executing $logCommand on $ip : $port" -Status "Timeout in $($RunMaxAllowedTime - $RunElaplsedTime) seconds.." -Id 87678 -PercentComplete (($RunElaplsedTime/$RunMaxAllowedTime)*100) -CurrentOperation "SSH ACTIVITY : $debugString"
                #Write-Host "Attempt : $attemptswot+$attemptswt : Executing $logCommand on $ip : $port" 
				$RunCurrentTime = Get-Date
				$RunDiffTime = $RunCurrentTime - $RunStartTime
				$RunElaplsedTime =  $RunDiffTime.TotalSeconds
				if($RunElaplsedTime -le $RunMaxAllowedTime)
				{
					$notExceededTimeLimit = $true
				}
				else
				{
					$notExceededTimeLimit = $false
					Stop-Job $runLinuxCmdJob
					$timeOut = $true
				}
			}
			$jobOut = Receive-Job $runLinuxCmdJob 2> $LogDir\$randomFileName
			if($jobOut)
			{
				foreach ($outLine in $jobOut)
				{
					if($outLine -imatch "AZURE-LINUX-EXIT-CODE-")
					{
						$LinuxExitCode = $outLine
					}
					else
					{
						$RunLinuxCmdOutput += "$outLine`n"
					}
				}
			}
			$debugLines = Get-Content $LogDir\$randomFileName
			if($debugLines)
			{
				$debugString = ""
				foreach ($line in $debugLines)
				{
					$debugString += $line
				}
				$debugOutput += "$debugString`n"
			}
			Write-Progress -Activity "Attempt : $attemptswot+$attemptswt : Executing $logCommand on $ip : $port" -Status $runLinuxCmdJob.State -Id 87678 -SecondsRemaining ($RunMaxAllowedTime - $RunElaplsedTime) -Completed
			#Write-Host "Attempt : $attemptswot+$attemptswt : Executing $logCommand on $ip : $port"
            Remove-Job $runLinuxCmdJob 
			Remove-Item $LogDir\$randomFileName -Force | Out-Null
			if ($LinuxExitCode -imatch "AZURE-LINUX-EXIT-CODE-0") 
			{
				$returnCode = 0
				LogMsg "$command executed successfully in $RunElaplsedTime seconds." -WriteHostOnly $WriteHostOnly -NoLogsPlease $NoLogsPlease
				$retValue = $RunLinuxCmdOutput.Trim()
			}
			else
			{
				if (!$ignoreLinuxExitCode)
				{
					$debugOutput = ($debugOutput.Split("`n")).Trim()
					foreach ($line in $debugOutput)
					{
						if($line)
						{
							LogError $line
						}
					}
				}
				if($debugOutput -imatch "Unable to authenticate")
					{
						LogMsg "Unable to authenticate. Not retrying!"
						Throw "Calling function - $($MyInvocation.MyCommand). Unable to authenticate"

					}
				if(!$ignoreLinuxExitCode)
				{
					if($timeOut)
					{
						$retValue = ""
						LogError "Tmeout while executing command : $command"
					}
					LogError "Linux machine returned exit code : $($LinuxExitCode.Split("-")[4])"
					if ($attemptswt -eq $maxRetryCount -and $attemptswot -eq $maxRetryCount)
					{
						Throw "Calling function - $($MyInvocation.MyCommand). Failed to execute : $command."
					}
					else
					{
						if ($notExceededTimeLimit)
						{
							LogError "Failed to execute : $command. Retrying..."
						}
					}
				}
				else
				{
					LogMsg "Command execution returned return code $($LinuxExitCode.Split("-")[4]) Ignoring.."
					$retValue = $RunLinuxCmdOutput.Trim()
					break
				}
			}
		}
	}
	return $retValue
}
#endregion

#region Test Case Logging
Function DoTestCleanUp($result, $testName, $DeployedServices, $ResourceGroups, [switch]$keepUserDirectory, [switch]$SkipVerifyKernelLogs)
{
	try
	{
		if($DeployedServices -or $ResourceGroups)
		{
			try
			{
				foreach ($vmData in $allVMData)
				{
					$out = RemoteCopy -upload -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files .\remote-scripts\CollectLogFile.sh -username $user -password $password
					$out = RunLinuxCmd -username $user -password $password -ip $vmData.PublicIP -port $vmData.SSHPort -command "bash CollectLogFile.sh" -ignoreLinuxExitCode
					$out = RemoteCopy -downloadFrom $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -files "$($vmData.RoleName)-*.txt" -downloadTo "$LogDir" -download
					$finalKernelVersion = Get-Content "$LogDir\$($vmData.RoleName)-kernelVersion.txt"
					Set-Variable -Name finalKernelVersion -Value $finalKernelVersion -Scope Global
					#region LIS Version
					$tempLIS = (Select-String -Path "$LogDir\$($vmData.RoleName)-lis.txt" -Pattern "^version:").Line
					if ($tempLIS)
					{
						$finalLISVersion = $tempLIS.Split(":").Trim()[1]
					}
					else
					{
						$finalLISVersion = "NA"
					}
					Set-Variable -Name finalLISVersion -Value $finalLISVersion -Scope Global
					Write-Host "Setting : finalLISVersion : $finalLISVersion"
					#endregion
				}
			}
			catch
			{
				$line = $_.InvocationInfo.ScriptLineNumber
				$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
				$ErrorMessage =  $_.Exception.Message
				LogError "EXCEPTION : $ErrorMessage"
				LogError "Source : Line $line in script $script_name."				
				LogError "Ignorable error in collecting final data from VMs."
			}
			$currentTestBackgroundJobs = Get-Content $LogDir\CurrentTestBackgroundJobs.txt -ErrorAction SilentlyContinue
			if ( $currentTestBackgroundJobs )
			{
				$currentTestBackgroundJobs = $currentTestBackgroundJobs.Split()
			}
			foreach ( $taskID in $currentTestBackgroundJobs )
			{
				#Removal of background 
				LogMsg "Removing Background Job ID : $taskID..."
				Remove-Job -Id $taskID -Force
				Remove-Item $LogDir\CurrentTestBackgroundJobs.txt -ErrorAction SilentlyContinue
			}
			$user=$xmlConfig.config.Azure.Deployment.Data.UserName
			if ( !$SkipVerifyKernelLogs )
			{
				try
				{
					$KernelLogOutput=GetAndCheckKernelLogs -allDeployedVMs $allVMData -status "Final" #Collecting kernel logs after execution of test case : v-sirebb
				}
				catch 
				{
					$ErrorMessage =  $_.Exception.Message
					LogMsg "EXCEPTION in GetAndCheckKernelLogs(): $ErrorMessage"	
				}
			}			
			$isClened = @()
			if ( !$UseAzureResourceManager )
			{
				$hsNames = $DeployedServices
				$allDeploymentData = $allVMData
				$hsNames = $hsNames.Split("^")
				$isVMLogsCollected = $false
				foreach ($hs in $hsNames)
				{
					$hsDetails = Get-AzureService -ServiceName $hs
					if (!($hsDetails.Description -imatch "DONOTDISTURB"))
					{
						if($result -eq "PASS")
						{
							if($EconomyMode -and (-not $IsLastCaseInCycle))
							{
								LogMsg "Skipping cleanup of $hs."
								if(!$keepUserDirectory)
								{
									RemoveAllFilesFromHomeDirectory -allDeployedVMs $allVMData
								}
							}
							else
							{
								if ( $hsDetails.Description -imatch $preserveKeyword )
								{
									LogMsg "Skipping cleanup of preserved service."
									LogMsg "Collecting VM logs.."
									if ( !$isVMLogsCollected )
									{
										GetVMLogs -allVMData $allDeploymentData
									}
									$isVMLogsCollected = $true								}
								else
								{
                                	if ( $keepReproInact )
                                	{
										LogMsg "Skipping cleanup due to 'keepReproInact' flag is set."
                                    }
                                    else
									{
										LogMsg "Collecting VM logs of PASS test case.."
										$out = GetVMLogs -allVMData $allVMData
										LogMsg "Cleaning up deployed test virtual machines."
										$isClened = DeleteService -serviceName $hsDetails.ServiceName
										if ($isClened -contains "False")
										{
											#LogMsg "CleanUP unsuccessful for $($hsDetails.ServiceName).. Please delete the services manually."
										}
										else
										{
											#LogMsg "CleanUP Successful for $($hsDetails.ServiceName).."
										}
									}
								}
							}
						}
						else
						{
							LogMsg "Preserving the hosted service(s) $hsNames"
							LogMsg "Integrating Test Case Name in the `"Description`" of preserved setups.."
							$suppressedOut = RetryOperation -operation { RunAzureCmd -AzureCmdlet "Set-AzureService -ServiceName $hs -Description `"Preserving this setup for FAILED/ABORTED test : $testName`"" -maxWaitTimeSeconds 120 } -maxRetryCount 5 -retryInterval 5
							LogMsg "Collecting VM logs.."
							if ( !$isVMLogsCollected )
							{
								GetVMLogs -allVMData $allDeploymentData
							}
							$isVMLogsCollected = $true
							if(!$keepUserDirectory -and !$keepReproInact -and $EconomyMode)
								{
									RemoveAllFilesFromHomeDirectory -allDeployedVMs $allVMData
								}
							if($keepReproInact)
							{
								$xmlConfig.config.Azure.Deployment.$setupType.isDeployed = "NO"
							}
						}
					}
					else
					{
						if ($result -ne "PASS")
						{
							LogMsg "Collecting VM logs.."
							GetVMLogs -allVMData $allDeploymentData
							if($keepReproInact)
							{
								$xmlConfig.config.Azure.Deployment.$setupType.isDeployed = "NO"
							}
						}
						LogMsg "Skipping cleanup, as service is marked as DO NOT DISTURB.."
					}
				}
			}
			else
			{
				$ResourceGroups = $ResourceGroups.Split("^")
				$isVMLogsCollected = $false
				foreach ($group in $ResourceGroups)
				{
					if ($ForceDeleteResources)
					{
						LogMsg "-ForceDeleteResources is Set. Deleting $group."
						$isClened = DeleteResourceGroup -RGName $group
					}
					else 
					{
						if($result -eq "PASS")
						{
							if($EconomyMode -and (-not $IsLastCaseInCycle))
							{
								LogMsg "Skipping cleanup of Resource Group : $group."
								if(!$keepUserDirectory)
								{
									RemoveAllFilesFromHomeDirectory -allDeployedVMs $allVMData
								}
							}
							else
							{
								$RGdetails = Get-AzureRmResourceGroup -Name $group
								if ( $RGdetails.Tags )
								{
									if ( (  $RGdetails.Tags[0].Name -eq $preserveKeyword ) -and (  $RGdetails.Tags[0].Value -eq "yes" ))
									{
										LogMsg "Skipping Cleanup of preserved resource group."
										LogMsg "Collecting VM logs.."
										if ( !$isVMLogsCollected)
										{
											GetVMLogs -allVMData $allVMData
										}
										$isVMLogsCollected = $true
									}
								}
								else
								{
									if ( $keepReproInact )
									{
										LogMsg "Skipping cleanup due to 'keepReproInact' flag is set."
									}
									else
									{
										LogMsg "Cleaning up deployed test virtual machines."
										$isClened = DeleteResourceGroup -RGName $group
										if (!$isClened)
										{
											LogMsg "CleanUP unsuccessful for $group.. Please delete the services manually."
										}
										else
										{
											#LogMsg "CleanUP Successful for $group.."
										}
									}
								}
							}
						}
						else
						{
							LogMsg "Preserving the Resource Group(s) $group"
							LogMsg "Setting tags : preserve = yes; testName = $testName"
							$hash = @{}
							$hash.Add($preserveKeyword,"yes")
							$hash.Add("testName","$testName")
							$out = Set-AzureRmResourceGroup -Name $group -Tag $hash
							LogMsg "Collecting VM logs.."
							if ( !$isVMLogsCollected)
							{
								GetVMLogs -allVMData $allVMData
							}
							$isVMLogsCollected = $true
							if(!$keepUserDirectory -and !$keepReproInact -and $EconomyMode)
								{
									RemoveAllFilesFromHomeDirectory -allDeployedVMs $allVMData
								}
							if($keepReproInact)
							{
								$xmlConfig.config.Azure.Deployment.$setupType.isDeployed = "NO"
							}
						}						
					}
				}
			}
		}
		else
		{
			LogMsg "Skipping cleanup, as No services / resource groups deployed for cleanup!"
		}
	}
	catch
	{
		$ErrorMessage =  $_.Exception.Message
		Write-Host "EXCEPTION in DoTestCleanUp : $ErrorMessage"  
	}
}

Function GetFinalizedResult($resultArr, $checkValues, $subtestValues, $currentTestData)
{
	$result = "", ""
	if (($resultArr -contains "FAIL") -or ($resultArr -contains "Aborted")) {
		$result[0] = "FAIL"
	}
	else{
		$result[0] = "PASS"
	}
	$i = 0
	$subtestLen = $SubtestValues.Length
	while ($i -lt $subtestLen)
	{
		$currentTestValue = $SubtestValues[$i]
		$currentTestResult = $resultArr[$i]
		$currentTestName = $currentTestData.testName
		if ($checkValues -imatch $currentTestResult)
		{				
			$result[1] += "		  $currentTestName : $currentTestValue : $currentTestResult <br />"
		}
		$i = $i + 1
	}

	return $result
}

Function CreateResultSummary($testResult, $checkValues, $testName, $metaData)
{
	if ( $metaData )
	{
		$resultString = "		  $testName : $metaData : $testResult <br />"
	}
	else
	{
		$resultString = "		  $testName : $testResult <br />"
	}
	return $resultString
}

Function GetFinalResultHeader($resultArr){
	if(($resultArr -imatch "FAIL" ) -or ($resultArr -imatch "Aborted"))
	{
		$result = "FAIL"
		if($resultArr -imatch "Aborted")
		{
			$result = "Aborted"
		}

	}
	else
	{
		$result = "PASS"
	}
	return $result
}

Function SetStopWatch()
{
	$sw = [system.diagnostics.stopwatch]::startNew()
	return $sw
}

Function GetStopWatchElapasedTime([System.Diagnostics.Stopwatch]$sw, [string] $format)
{
	if ($format -eq "ss")
	{
		$num=$sw.Elapsed.TotalSeconds
	}
	elseif ($format -eq "hh")
	{
		$num=$sw.Elapsed.TotalHours
	}
	elseif ($format -eq "mm")
	{
		$num=$sw.Elapsed.TotalMinutes
	}
	return [System.Math]::Round($Num, 2)

}

Function GetVMLogs($allVMData)
{
	foreach ($testVM in $allVMData)
	{
		$testIP = $testVM.PublicIP
		$testPort = $testVM.SSHPort
		$LisLogFile = "LIS-Logs" + ".tgz"
		try
		{
			LogMsg "Collecting logs from IP : $testIP PORT : $testPort"	
			RemoteCopy -upload -uploadTo $testIP -username $user -port $testPort -password $password -files '.\remote-scripts\LIS-LogCollector.sh'
			RunLinuxCmd -username $user -password $password -ip $testIP -port $testPort -command 'chmod +x LIS-LogCollector.sh'
			$out = RunLinuxCmd -username $user -password $password -ip $testIP -port $testPort -command './LIS-LogCollector.sh -v' -runAsSudo
			LogMsg $out
			RemoteCopy -download -downloadFrom $testIP -username $user -password $password -port $testPort -downloadTo $LogDir -files $LisLogFile
			LogMsg "Logs collected successfully from IP : $testIP PORT : $testPort"
			Rename-Item -Path "$LogDir\$LisLogFile" -NewName ("LIS-Logs-" + $testVM.RoleName + ".tgz") -Force
		}
		catch
		{
			$ErrorMessage =  $_.Exception.Message
			LogError "EXCEPTION : $ErrorMessage"
			LogError "Unable to collect logs from IP : $testIP PORT : $testPort"  		
		}
	}
}

Function RemoveAllFilesFromHomeDirectory($allDeployedVMs)
{
	foreach ($DeployedVM in $allDeployedVMs)
	{
		$testIP = $DeployedVM.PublicIP
		$testPort = $DeployedVM.SSHPort
		try
		{
			LogMsg "Removing all files logs from IP : $testIP PORT : $testPort"	
			$out = RunLinuxCmd -username $user -password $password -ip $testIP -port $testPort -command 'rm -rf *' -runAsSudo
			LogMsg "All files removed from /home/$user successfully. VM IP : $testIP PORT : $testPort"  
		}
		catch
		{
			$ErrorMessage =  $_.Exception.Message
			Write-Host "EXCEPTION : $ErrorMessage"
			Write-Host "Unable to remove files from IP : $testIP PORT : $testPort"  		
		}
	}
}

Function CaptureVMImage ($ServiceName)
{
	$retryCount = 5
	$retryRequired = $true
		LogMsg "Stopping the Virtual Machine.."
		$tempVM = Get-AzureVM -ServiceName $ServiceName
		$out = $tempVM | Stop-AzureVM -Force -Verbose
		WaitFor -seconds 60
		LogMsg "Capturing the VM image from service : $ServiceName..."
	#LogMsg ".\SetupScripts\CSUploadVHD.ps1 -Destination $Destination -Label $VHDName -LiteralPath $LiteralPath\$VHDName"
		$curtime = Get-Date
		$ImageName = "ICA-CAPTURED-" + $Distro + "-" + $curtime.Month + "-" +  $curtime.Day  + "-" + $curtime.Year + "-" + $curtime.Hour + "-" + $curtime.Minute + ".vhd"
		$ImageDestination =  $DestinationURL + "/" + $ImageName
		$ImageLabel = $ImageName
		While($retryRequired -and ($retryCount -gt 0))
		{
			try
			{
				$retryCount = $retryCount - 1
				$out = $tempVM | Save-AzureVMImage -NewImageLabel $ImageLabel -NewImageName $ImageName -Verbose
				$retryRequired = $false
				LogMsg "VHD captured with Image Name : $ImageName"
			}
			catch
			{
				$retryRequired = $true
			}
		}
		LogMsg "Removing empty service : $ServiceName"
		$out = DeleteService -ServiceName $ServiceName
		
	return $ImageName
}

function ParseAndAddSubtestResultsToDB($resultSummary, $conn, $testCaseRunObj)
{
	$newResultSummary = $resultSummary.Replace(" ","")
	$newResultSummary = $newResultSummary.Replace("<br/>","^")
	$newResultSummary = $newResultSummary.Remove(($newResultSummary.Length - 1))
	$newResultSummary = $newResultSummary.Split("^")
	$tempCounter = 1
	foreach ($testSummary in $newResultSummary)
	{
		$tempCounter += 1
		$testSummary = $testSummary.Split(":")

		$SubtestName = $testSummary[0]
		$SubtestResult = $testSummary[($testSummary.Length - 1)]
		Function GetResultMetadata ($testSummary)
		{
			$metadata = ""
			$counter = 0
			$firstEntry=$true
			foreach ($word in $testSummary)
			{
				if(($counter -ne 0) -and ($counter -ne ($testSummary.Length - 1)))
				{
					if($firstEntry)
					{
						$metadata += $word
						$firstEntry = $false
					}
					else
					{
						$metadata += " : $word"
					}
				}
				$counter += 1
			}
			return $metadata
		}
		$subtestMetadata = GetResultMetadata -testSummary $testSummary
#Write-Host "$SubtestName : $subtestMetadata : $SubtestResult"

#Now Add this subtest data to DB
		$subTestRunObject = CreateSubTestCaseObject -testSuiteRunId $testCaseRunObj.testSuiteRunId -testCaseId $testCaseRunObj.testCaseId -testName "$SubtestName : $subtestMetadata" -result $SubtestResult -startTime $testStartTime -endTime $testCaseRunObj.endTime -SubtestStartTime $SubTestStartTime -SubtestEndTime $SubTestEndTime
		$temp = AddSubTestResultinDB -conn $Conn -subTestCaseObj $subTestRunObject -testSuiteRunId $testCaseRunObj.testSuiteRunId 
	}
}
#endregion

#region Network FTM TestCase Methods
#################################################################
Function IperfClientServertcpNonConnectivity($server,$client)
{
	RemoteCopy -uploadTo $server.ip -port $server.sshPort -files $server.files -username $server.user -password $server.password -upload
	RemoteCopy -uploadTo $client.Ip -port $client.sshPort -files $client.files -username $client.user -password $client.password -upload
	$suppressedOut = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshPort -command "rm -rf *.txt *.log" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshPort -command "rm -rf *.txt *.log" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshPort -command "chmod +x *" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshPort -command "chmod +x *" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshport -command "echo Test Started > iperf-server.txt" -runAsSudo
	StartIperfServer $server
	$isServerStarted = IsIperfServerStarted $server
	if($isServerStarted -eq $true)
	{
		LogMsg "iperf Server started successfully. Listening TCP port $($server.tcpPort) ..."
#>>>On confirmation, of server starting, let's start iperf client...
		$suppressedOut = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshport -command "echo Test Started > iperf-client.txt" -runAsSudo
		StartIperfClient $client
		$isClientStarted = IsIperfClientStarted $client
		$suppressedOut = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshport -command "echo Test Complete >> iperf-client.txt" -runAsSudo
		$suppressedOut = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshport -command "echo Test Complete >> iperf-server.txt" -runAsSudo
		if($isClientStarted -eq $false)
		{
			$serverState = IsIperfServerRunning $server
			if($serverState -eq $false)
			{
#LogMsg "Test Finished..!"
				$testResult = "PASS"
			}
			else
			{
				LogError "Connections observed on server. Test Finished..!"
				$testResult = "FAIL"
			}
		}
		else
		{
			$testResult = "FAIL"
#LogMsg "Failured detected in client connection."
			LogError "Ohh, client connected.. Verifying that it connected to server.."
			$serverState = IsIperfServerRunning $server
#$serverState = $false
			if($serverState -eq $false)
			{
				LogMsg "Not Connected to server. Please check the logs.. where the client was connected. ;-)"
			}
			else
			{
				LogMsg "Connections observed on server. Test Finished..!"
			}
		}
	}
	else
	{
		LogMsg "Unable to start iperf-server. Aborting test."
		$testResult = "Aborted"
	}
	return $testResult
}

Function IperfClientServerUDPNonConnectivity($server,$client)
{
	RemoteCopy -uploadTo $server.ip -port $server.sshPort -files $server.files -username $server.user -password $server.password -upload
	RemoteCopy -uploadTo $client.Ip -port $client.sshPort -files $client.files -username $client.user -password $client.password -upload
	$suppressedOut = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshPort -command "rm -rf *.txt *.log" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshPort -command "rm -rf *.txt *.log" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshPort -command "chmod +x *" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshPort -command "chmod +x *" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshport -command "echo Test Started > iperf-server.txt" -runAsSudo
	StartIperfServer $server
	$isServerStarted = IsIperfServerStarted $server
	if($isServerStarted -eq $true)
	{
		LogMsg "iperf Server started successfully. Listening UDP port $($server.tcpPort) ..."
#>>>On confirmation, of server starting, let's start iperf client...
		$suppressedOut = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshport -command "echo Test Started > iperf-client.txt" -runAsSudo
		StartIperfClient $client
		$isClientStarted = IsIperfClientStarted $client
		$suppressedOut = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshport -command "echo Test Complete >> iperf-client.txt" -runAsSudo
		$suppressedOut = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshport -command "echo Test Complete >> iperf-server.txt" -runAsSudo
		$serverState = IsIperfServerRunning $server
		if($serverState -eq $false)
		{
#LogMsg "Test Finished..!"
			$testResult = "PASS"
		}
		else
		{
			LogError "Connections observed on server. Test Finished..!"
			$testResult = "FAIL"
		}
	}
	else
	{
		LogMsg "Unable to start iperf-server. Aborting test."
		$testResult = "Aborted"
	}
	return $testResult
}

Function IperfClientServerUDPTest($server,$client)
{
	RemoteCopy -uploadTo $server.ip -port $server.sshPort -files $server.files -username $server.user -password $server.password -upload
	RemoteCopy -uploadTo $client.Ip -port $client.sshPort -files $client.files -username $client.user -password $client.password -upload
	$suppressedOut = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshPort -command "rm -rf *.txt *.log" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshPort -command "rm -rf *.txt *.log" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshPort -command "chmod +x *" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshPort -command "chmod +x *" -runAsSudo

	$suppressedOut = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshport -command "echo Test Started > iperf-server.txt" -runAsSudo
	StartIperfServer $server
	$isServerStarted = IsIperfServerStarted $server
	if($isServerStarted -eq $true)
	{
		LogMsg "iperf Server started successfully. Listening UDP port $($server.tcpPort) ..."

#>>>On confirmation, of server starting, let's start iperf client...
		$suppressedOut = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshport -command "echo Test Started > iperf-client.txt" -runAsSudo
		StartIperfClient $client
		$isClientStarted = IsIperfClientStarted $client
		$suppressedOut = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshport -command "echo Test Complete >> iperf-client.txt" -runAsSudo
		$suppressedOut = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshport -command "echo Test Complete >> iperf-server.txt" -runAsSudo
		$serverState = IsIperfServerRunning $server
		if($serverState -eq $true)
		{
#LogMsg "Test Finished..!"
			$testResult = "PASS"
		}
		else
		{
			LogError "Connections not observed on server. Test Finished..!"
			$testResult = "FAIL"
		}
	}
	else
	{
		LogMsg "Unable to start iperf-server. Aborting test."
		$testResult = "Aborted"
	}
	return $testResult
}

Function IperfClientServerTest($server,$client)
{
	RemoteCopy -uploadTo $server.ip -port $server.sshPort -files $server.files -username $server.user -password $server.password -upload
	RemoteCopy -uploadTo $client.Ip -port $client.sshPort -files $client.files -username $client.user -password $client.password -upload
	$out = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshPort -command "rm -rf *.txt *.log" -runAsSudo
	$out = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshPort -command "rm -rf *.txt *.log" -runAsSudo
	$out = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshPort -command "chmod +x *" -runAsSudo
	$out = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshPort -command "chmod +x *" -runAsSudo

	StartIperfServer $server
	$isServerStarted = IsIperfServerStarted $server
	if($isServerStarted -eq $true)
	{
		LogMsg "iperf Server started successfully. Listening TCP port $($client.tcpPort) ..."
#>>>On confirmation, of server starting, let's start iperf client...
		StartIperfClient $client
		$isClientStarted = IsIperfClientStarted $client

		if($isClientStarted -eq $true)
		{
			$serverState = IsIperfServerRunning $server
			if($serverState -eq $true)
			{
				LogMsg "Test Finished..!"
				$testResult = "PASS"
			}
			else
			{
				LogMsg "Test Finished..!"
				$testResult = "FAIL"
			}
		}
		else
		{
			LogError "Failured detected in client connection."
			LogMsg "Test Finished..!"
			$testResult = "FAIL"
		}
	}
	else
	{
		LogMsg "Unable to start iperf-server. Aborting test."
		$testResult = "Aborted"
	}
	return $testResult
}

Function IperfClientServerTestParallel($server,$client)
{
	$out = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshport -command "echo ServerStarted > iperf-server.txt" -runAsSudo
	$out = StartIperfServer $server
	$isServerStarted = IsIperfServerStarted $server
	if($isServerStarted -eq $true)
	{
		LogMsg "iperf Server started successfully. Listening TCP port $($client.tcpPort) ..."
#>>>On confirmation, of server starting, let's start iperf client...
		$out = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshport -command "echo ClientStarted > iperf-client.txt" -runAsSudo
		$out = StartIperfClient $client
		$out = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshport -command "echo ClientStopped >> iperf-client.txt" -runAsSudo
		$out = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshport -command "echo ServerStopped >> iperf-server.txt" -runAsSudo
		$isClientStarted = IsIperfClientStarted $client
		
		if($isClientStarted -eq $true)
		{
			$serverState = IsIperfServerRunning $server
			if($serverState -eq $true)
			{
				LogMsg "Test Finished..!"
				$testResult = "PASS"
			}
			else
			{
				LogError "Test Finished ..!"
				$testResult = "FAIL"
			}
			$clientLog= $client.LogDir + "\iperf-client.txt"
			$isClientConnected = AnalyseIperfClientConnectivity -logFile $clientLog -beg "ClientStarted" -end "ClientStopped"
			$clientConnCount = GetParallelConnectionCount -logFile $clientLog -beg "ClientStarted" -end "ClientStopped"
			If ($isClientConnected) {
				$testResult = "PASS"
				$serverLog= $server.LogDir + "\iperf-server.txt"
				$isServerConnected = AnalyseIperfServerConnectivity $serverLog "ServerStarted" "ServerStopped"
				If ($isServerConnected) {
					$testResult = "PASS"
					$serverConnCount = GetParallelConnectionCount -logFile $serverLog -beg "ServerStarted" -end "ServerStopped"
					LogMsg "Server Parallel Connection Count is $serverConnCount"
					LogMsg "Client Parallel Connection Count is $clientConnCount"
					If ($serverConnCount -eq $clientConnCount) {
						$testResult = "PASS"
						LogMsg "Connection Counts are Same in both Server and Client Logs"
						$clientDt= GetTotalDataTransfer -logFile $clientLog -beg "ClientStarted" -end "ClientStopped"
						$serverDt= GetTotalDataTransfer -logFile $serverLog -beg "ServerStarted" -end "ServerStopped"
						LogMsg "Server Total Data Transfer is $serverDt"
						LogMsg "Client Total Data Transfer is $clientDt"
						If ($serverDt  -eq $clientDt) {
							$testResult = "PASS"
							LogMsg "Total DataTransfer is equal on both Server and Client"
						} else {
							$testResult = "FAIL"
							LogError "Total DataTransfer is NOT equal on both Server and Client"
						}
					} else {
						$testResult = "FAIL"
						LogError "Connection Counts are NOT Same in both Server and Client Logs"
					}
				} else {
					$testResult = "FAIL"
					LogError "Server is not Connected to Client"
				}
			} else {
				$testResult = "FAIL"
				LogError "Client is not Connected to Server"
			}	
		} else {
			LogError "Failures detected in client connection."
			RemoteCopy -download -downloadFrom $server.ip -files "/home/$user/iperf-server.txt" -downloadTo $server.LogDir -port $server.sshPort -username $server.user -password $server.password
			LogMsg "Test Finished..!"
			$testResult = "FAIL"
		}

	} else	{
		LogError "Unable to start iperf-server. Aborting test."
		RemoteCopy -download -downloadFrom $server.ip -files "/home/$user/iperf-server.txt" -downloadTo $server.LogDir -port $server.sshPort -username $server.user -password $server.password
		RemoteCopy -download -downloadFrom $client.ip -files "/home/$user/iperf-server.txt" -downloadTo $client.LogDir -port $client.sshPort -username $client.user -password $client.password
		$testResult = "Aborted"
	}
	return $testResult
}

Function IperfClientServerUDPTestParallel($server,$client)
{
	RemoteCopy -uploadTo $server.ip -port $server.sshPort -files $server.files -username $server.user -password $server.password -upload
	RemoteCopy -uploadTo $client.Ip -port $client.sshPort -files $client.files -username $client.user -password $client.password -upload
	$out = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshPort -command "rm -rf *.txt *.log" -runAsSudo
	$out = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshPort -command "rm -rf *.txt *.log" -runAsSudo
	$out = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshPort -command "chmod +x *" -runAsSudo
	$out = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshPort -command "chmod +x *" -runAsSudo

	$out = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshport -command "echo Test Started > iperf-server.txt" -runAsSudo
	StartIperfServer $server
	$isServerStarted = IsIperfServerStarted $server
	if($isServerStarted -eq $true)
	{
		LogMsg "iperf Server started successfully. Listening UDP port $($client.udpPort) ..."
#>>>On confirmation, of server starting, let's start iperf client...
		$out = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshport -command "echo Test Started > iperf-client.txt" -runAsSudo
		StartIperfClient $client
		$isClientStarted = IsIperfClientStarted $client
		$out = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshport -command "echo TestComplete >> iperf-server.txt" -runAsSudo
		if($isClientStarted -eq $true)
		{
			$serverState = IsIperfServerRunning $server
			if($serverState -eq $true)
			{
				LogMsg "Test Finished..!"
				$testResult = "PASS"
			}
			else
			{
				LogError "Test Finished..!"
				$testResult = "FAIL"
			}
			$clientLog= $client.LogDir + "\iperf-client.txt"
			$isClientConnected = AnalyseIperfClientConnectivity -logFile $clientLog -beg "Test Started" -end "TestComplete"
			$clientConnCount = GetParallelConnectionCount -logFile $clientLog -beg "Test Started" -end "TestComplete"
			If ($isClientConnected) {
				$testResult = "PASS"
				$serverLog= $server.LogDir + "\iperf-server.txt"
				$isServerConnected = AnalyseIperfServerConnectivity $serverLog "Test Started" "TestComplete"
				If ($isServerConnected) {
					$testResult = "PASS"
					$serverConnCount = GetParallelConnectionCount -logFile $serverLog -beg "Test Started" -end "TestComplete"
					LogMsg "Server Parallel Connection Count is $serverConnCount"
					LogMsg "Client Parallel Connection Count is $clientConnCount"
					If ($serverConnCount -eq $clientConnCount) {
						$testResult = "PASS"
						LogMsg "Connection Counts are Same in both Server and Client Logs"
						$clientDt= GetTotalDataTransfer -logFile $clientLog -beg "Test Started" -end "TestComplete"
						$serverDt= GetTotalUdpServerTransfer -logFile $serverLog -beg "Test Started" -end "TestComplete"
						LogMsg "Server Total Data Transfer is $serverDt"
						LogMsg "Client Total Data Transfer is $clientDt"
						$dataLoss = 0
						$diff= (($clientDt.Split("K")[0]) - ($serverDt.Split("K")[0]))
						If ($diff -gt 0) {
							$dataLoss= (($diff/($clientDt.Split("K")[0]))*100)
						}
						If ($dataLoss -lt 30) {
							$testResult = "PASS"
							LogMsg "DataTransfer Loss $dataLoss % is Less Than 30%"
							$udpLoss= GetUdpLoss -logFile $serverLog -beg "Test Started" -end "TestComplete"
							LogMsg "UDP Loss is $udpLoss"
							If ($udpLoss -gt 30) {
								$testResult = "FAIL"
								LogError "UDP Loss $udpLoss is greater than 30%"
							} 
						} else {
							$testResult = "FAIL"
							LogError "DataTransfer Loss $dataLoss % is Less Than 30%"
						}				
					} else {
						$testResult = "FAIL"
						LogError "Connection Counts are NOT Same in both Server and Client Logs"
					}
				} else {
					$testResult = "FAIL"
					LogError "Server is not Connected to Client"
				}
			} else {
				$testResult = "FAIL"
				LogError "Client is not Connected to Client"
			}	
		} else {
			LogError "Failured detected in client connection."
			RemoteCopy -download -downloadFrom $server.ip -files "/home/$user/iperf-server.txt" -downloadTo $server.LogDir -port $server.sshPort -username $server.user -password $server.password
			LogMsg "Test Finished..!"
			$testResult = "FAIL"
		}

	} else	{
		LogError "Unable to start iperf-server. Aborting test."
		RemoteCopy -download -downloadFrom $server.ip -files "/home/$user/iperf-server.txt" -downloadTo $server.LogDir -port $server.sshPort -username $server.user -password $server.password
		RemoteCopy -download -downloadFrom $client.ip -files "/home/$user/iperf-server.txt" -downloadTo $client.LogDir -port $client.sshPort -username $client.user -password $client.password
		$testResult = "Aborted"
	}
	return $testResult
}

Function IperfClientServerUDPDatagramTest($server,$client, [switch] $VNET)
{
	if(!$VNET)
	{
		RemoteCopy -uploadTo $server.ip -port $server.sshPort -files $server.files -username $server.user -password $server.password -upload
		RemoteCopy -uploadTo $client.Ip -port $client.sshPort -files $client.files -username $client.user -password $client.password -upload
		$tmp = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshPort -command "chmod +x *" -runAsSudo
		$tmp = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshPort -command "chmod +x *" -runAsSudo
	}

	$tmp = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshPort -command "rm -rf *.txt && rm -rf *.log" -runAsSudo
	$tmp = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshPort -command "rm -rf *.txt && rm -rf *.log" -runAsSudo
	
	$tmp = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshport -command "echo Test Started > iperf-server.txt" -runAsSudo
	$tmp = StartIperfServer $server
	$isServerStarted = IsIperfServerStarted $server
	if($isServerStarted -eq $true)
	{
		LogMsg "iperf Server started successfully. Listening UDP port $($server.udpPort) ..."
#>>>On confirmation, of server starting, let's start iperf client...
		$tmp = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshport -command "echo Test Started > iperf-client.txt" -runAsSudo
		$tmp = StartIperfClient $client
		$isClientStarted = IsIperfClientStarted $client
		$tmp = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshport -command "echo Test Complete >> iperf-client.txt" -runAsSudo
		$tmp = RunLinuxCmd -username $server.user -password $server.password -ip $server.ip -port $server.sshport -command "echo Test Complete >> iperf-server.txt" -runAsSudo
		if($isClientStarted -eq $true)
		{
			$serverState = IsIperfServerRunning $server
			if($serverState -eq $true)
			{
#LogMsg "Test Finished..!"
				$testResult = "PASS"
				$iperfclientLogPath = $client.logDir + "\iperf-client.txt"
				$iperfserverLogPath = $server.logDir + "\iperf-server.txt"
				$udpLoss = GetUdpLoss  -logfile $iperfclientLogPath -beg "Test Started" -end "TestComplete"
				$isServerConnected = AnalyseIperfServerConnectivity -logfile $iperfserverLogPath -beg "Test Started" -end "Test Complete"
				
				if ($udpLoss -gt  30)
				{
					LogError "UDP loss is greater than 30%"
					$testResult = "FAIL"
				}
				if (!$isServerConnected)
				{
					LogError "Server Not Connected. [Error source : Function IperfClientServerUDPDatagramTest]"
					$testResult = "FAIL"
				}
			}
			else
			{
				LogError "Test Finished..!"
				$testResult = "FAIL"
			}
		}
		else
		{
			LogError "Failured detected in client connection."
			LogMsg "Test Finished..!"
			$testResult = "FAIL"
		}
	}
	else
	{
		LogMsg "Unable to start iperf-server. Aborting test."
		$testResult = "Aborted"
	}
	return $testResult
}

Function VerifyCustomProbe ($server1,$server2, [string] $probe) {
	RemoteCopy -uploadTo $server1.ip -port $server1.sshPort -files $server1.files -username $server1.user -password $server1.password -upload
	RemoteCopy -uploadTo $server2.Ip -port $server2.sshPort -files $server2.files -username $server2.user -password $server2.password -upload

	$suppressedOut = RunLinuxCmd -username $server2.user -password $server2.password -ip $server2.ip -port $server2.sshPort -command "chmod +x *" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $server1.user -password $server1.password -ip $server1.ip -port $server1.sshPort -command "chmod +x *" -runAsSudo

	$suppressedOut = RunLinuxCmd -username $server1.user -password $server1.password -ip $server1.ip -port $server1.sshport -command "echo Test Started > iperf-server.txt" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $server2.user -password $server2.password -ip $server2.ip -port $server2.sshPort -command "echo Test Started > iperf-server.txt" -runAsSudo

	StartIperfServer $server1
	StartIperfServer $server2

	$isServerStarted = IsIperfServerStarted $server1
	$isServerStarted = IsIperfServerStarted $server2
	sleep(60)

	if(($isServerStarted -eq $true) -and ($isServerStarted -eq $true)) {
		LogMsg "Iperf Server1 and Server2 started successfully. Listening TCP port $client.tcpPort ..."

		$suppressedOut = RunLinuxCmd -username $server1.user -password $server1.password -ip $server1.ip -port $server1.sshport -command "echo TestComplete >> iperf-server.txt" -runAsSudo
		$suppressedOut = RunLinuxCmd -username $server2.user -password $server2.password -ip $server2.ip -port $server2.sshPort -command "echo TestComplete >> iperf-server.txt" -runAsSudo
		RemoteCopy -download -downloadFrom $server1.ip -files "/home/$user/iperf-server.txt" -downloadTo $server1.LogDir -port $server1.sshPort -username $server1.user -password $server1.password
		RemoteCopy -download -downloadFrom $server2.ip -files "/home/$user/iperf-server.txt" -downloadTo $server2.LogDir -port $server1.sshPort -username $server2.user -password $server2.password

#	$server1State = IsIperfServerRunning $server1
#	$server2State = IsIperfServerRunning $server2
#	
#	if(($server1State -eq $true) -and ($server2State -eq $true)) {
#		LogMsg "Both Servers Started!"
#		$testResult = "PASS"
#	} else {
#		LogMsg "Both Servers NOT Started!!"
#		$testResult = "FAIL"
#	}
#	
		$server1CpConnCount = 0
		$server2CpConnCount = 0

		$server1Log= $server1.LogDir + "\iperf-server.txt"
		$server2Log= $server2.LogDir + "\iperf-server.txt"

		$isServerConnected1 = AnalyseIperfServerConnectivity $server1Log "Test Started" "TestComplete"
		$isServerConnected2 = AnalyseIperfServerConnectivity $server2Log "Test Started" "TestComplete"

		If ( $probe -eq "no" ) {
			if(!$isServerConnected1) {
				$isServerConnected1=!$isServerConnected1
			}
			if(!$isServerConnected2) {
				$isServerConnected2=!$isServerConnected2
			}
		}
		If (($isServerConnected1) -and ($isServerConnected2)) {
			If ( $probe -eq "yes" ) {
				$testResult = "PASS"
			} elseif ( $probe -eq "no" ) {
				$testResult = "FAIL"
			}
#Verify Custom Probe Messages on both server
			If ( $probe -eq "yes" ) {
				If (( IsCustomProbeMsgsPresent -logFile $server1Log -beg "Test Started" -end "TestComplete") -and (IsCustomProbeMsgsPresent -logFile $server2Log -beg "Test Started" -end "TestComplete")) {
					$server1CpConnCount= GetCustomProbeMsgsCount -logFile $server1Log -beg "Test Started" -end "TestComplete"
					$server2CpConnCount= GetCustomProbeMsgsCount -logFile $server2Log -beg "Test Started" -end "TestComplete"
					LogMsg "$server1CpConnCount Custom Probe Messages observed on Server1"
					LogMsg "$server2CpConnCount Custom Probe Messages observed on Server1"
					$testResult = "PASS"
				} else {
					if (!( IsCustomProbeMsgsPresent -logFile $server1Log -beg "Test Started" -end "TestComplete") ) {
						LogError "NO Custom Probe Messages observed on Server1"
						$testResult = "FAIL"
					}
					if (!(IsCustomProbeMsgsPresent -logFile $server2Log -beg "Test Started" -end "TestComplete")) {
						LogError "NO Custom Probe Messages observed on Server1"
						$testResult = "FAIL"
					} 
				}
			} elseif ( $probe -eq "no" ) {
				If ((!(IsCustomProbeMsgsPresent -logFile $server1Log -beg "Test Started" -end "TestComplete")) -and (!(IsCustomProbeMsgsPresent -logFile $server2Log -beg "Test Started" -end "TestComplete"))) {
					LogMsg "NO Custom Probe Messages observed on Server1"
					LogMsg "NO Custom Probe Messages observed on Server2"
					$testResult = "PASS"
				} else {
					if((IsCustomProbeMsgsPresent -logFile $server1Log -beg "Test Started" -end "TestComplete")) {
						$server1CpConnCount = GetCustomProbeMsgsCount -logFile $server1Log -beg "Test Started" -end "TestComplete"
						LogError "$server1CpConnCount Custom Probe Messages observed on Server1"
						$testResult = "FAIL"
					} 
					if((IsCustomProbeMsgsPresent -logFile $server2Log -beg "Test Started" -end "TestComplete")) {
						$server2CpConnCount = GetCustomProbeMsgsCount -logFile $server2Log -beg "Test Started" -end "TestComplete"
						LogError "$server2CpConnCount Custom Probe Messages observed on Server2"
						$testResult = "FAIL"
					} 
				}	
#		If ( $probe -eq "yes" ) {
#			If ( IsCustomProbeMsgsPresent -logFile $server1Log -beg "Test Started" -end "TestComplete") {
#				$server1CpConnCount = GetCustomProbeMsgsCount -logFile $server1Log -beg "Test Started" -end "TestComplete"
#				LogMsg "$server1CpConnCount Custom Probe Messages observed on Server1"
#				$testResult = "PASS"
#			} else {
#				LogMsg "$server1CpConnCount NO Custom Probe Messages observed on Server1"
#				$testResult = "FAIL"
#			}
#			If ( IsCustomProbeMsgsPresent -logFile $server2Log -beg "Test Started" -end "TestComplete") {
#				$server2CpConnCount = GetCustomProbeMsgsCount -logFile $server2Log -beg "Test Started" -end "TestComplete"
#				LogMsg "$server1CpConnCount Custom Probe Messages observed on Server1"
#				$testResult = "PASS"
#			} else {
#			LogMsg "$server1CpConnCount NO Custom Probe Messages observed on Server1"
#			$testResult = "FAIL"
#			}
#		} elseif ( $probe -eq "no" ) {
#			If ( !(IsCustomProbeMsgsPresent -logFile $server1Log -beg "Test Started" -end "TestComplete")) {
#				$server1CpConnCount = GetCustomProbeMsgsCount -logFile $server1Log -beg "Test Started" -end "TestComplete"
#				LogMsg "$server1CpConnCount NO Custom Probe Messages observed on Server1"
#				$testResult = "PASS"
#			} else {
#				LogMsg "$server1CpConnCount Custom Probe Messages observed on Server1"
#				$testResult = "FAIL"
#			}
#			If (!(IsCustomProbeMsgsPresent -logFile $server2Log -beg "Test Started" -end "TestComplete")) {
#				$server2CpConnCount = GetCustomProbeMsgsCount -logFile $server2Log -beg "Test Started" -end "TestComplete"
#				LogMsg "$server1CpConnCount NO Custom Probe Messages observed on Server1"
#				$testResult = "PASS"
#			} else {
#			LogMsg "$server1CpConnCount Custom Probe Messages observed on Server1"
#			$testResult = "FAIL"
#			}
#		}
			}
		}

		return $testResult
	}
}

Function VerifyLBTCPConnectivity ($server1,$server2, $client, [string] $probe, [string] $pSize) {
	RemoteCopy -uploadTo $server1.ip -port $server1.sshPort -files $server1.files -username $server1.user -password $server1.password -upload
	RemoteCopy -uploadTo $server2.Ip -port $server2.sshPort -files $server2.files -username $server2.user -password $server2.password -upload
	RemoteCopy -uploadTo $client.Ip -port $client.sshPort -files $client.files -username $client.user -password $client.password -upload

	$suppressedOut = RunLinuxCmd -username $server2.user -password $server2.password -ip $server2.ip -port $server2.sshPort -command "chmod +x *" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $server1.user -password $server1.password -ip $server1.ip -port $server1.sshPort -command "chmod +x *" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshPort -command "chmod +x *" -runAsSudo

	$suppressedOut = RunLinuxCmd -username $server1.user -password $server1.password -ip $server1.ip -port $server1.sshport -command "echo Test Started > iperf-server.txt" -runAsSudo
	$suppressedOut = RunLinuxCmd -username $server2.user -password $server2.password -ip $server2.ip -port $server2.sshPort -command "echo Test Started > iperf-server.txt" -runAsSudo
	StartIperfServer $server1
	StartIperfServer $server2
	$isServerStarted = IsIperfServerStarted $server1
	$isServerStarted = IsIperfServerStarted $server2
	sleep(30)
	if(($isServerStarted -eq $true) -and ($isServerStarted -eq $true)) {
		LogMsg "Iperf Server1 and Server2 started successfully. Listening TCP port $client.tcpPort ..."
#>>>On confirmation, of server starting, let's start iperf client...
		$suppressedOut = RunLinuxCmd -username $client.user -password $client.password -ip $client.ip -port $client.sshport -command "echo Test Started > iperf-client.txt" -runAsSudo
		StartIperfClient $client
		$isClientStarted = IsIperfClientStarted $client
		$suppressedOut = RunLinuxCmd -username $server1.user -password $server1.password -ip $server1.ip -port $server1.sshport -command "echo TestComplete >> iperf-server.txt" -runAsSudo
		$suppressedOut = RunLinuxCmd -username $server2.user -password $server2.password -ip $server2.ip -port $server2.sshPort -command "echo TestComplete >> iperf-server.txt" -runAsSudo
		if($isClientStarted -eq $true) {
			$server1State = IsIperfServerRunning $server1
			$server2State = IsIperfServerRunning $server2
			if(($server1State -eq $true) -and ($server2State -eq $true)) {
				LogMsg "Test Finished..!"
				$testResult = "PASS"
			} else {
				LogMsg "Test Finished..!"
				$testResult = "FAIL"
			}
			$clientLog= $client.LogDir + "\iperf-client.txt"
			$isClientConnected = AnalyseIperfClientConnectivity -logFile $clientLog -beg "Test Started" -end "TestComplete"
			$clientConnCount = GetParallelConnectionCount -logFile $clientLog -beg "Test Started" -end "TestComplete"
			$server1CpConnCount = 0
			$server2CpConnCount = 0
			If ($isClientConnected) {
				$testResult = "PASS"
				$server1Log= $server1.LogDir + "\iperf-server.txt"
				$server2Log= $server2.LogDir + "\iperf-server.txt"
				$isServerConnected1 = AnalyseIperfServerConnectivity $server1Log "Test Started" "TestComplete"
				$isServerConnected2 = AnalyseIperfServerConnectivity $server2Log "Test Started" "TestComplete"
				If (($isServerConnected1) -and ($isServerConnected2)) {
					$testResult = "PASS"

					$connectStr1="$($server1.DIP)\sport\s\d*\sconnected with $($client.ip)\sport\s\d"
					$connectStr2="$($server2.DIP)\sport\s\d*\sconnected with $($client.ip)\sport\s\d"

					$server1ConnCount = GetStringMatchCount -logFile $server1Log -beg "Test Started" -end "TestComplete" -str $connectStr1
					$server2ConnCount = GetStringMatchCount -logFile $server2Log -beg "Test Started" -end "TestComplete" -str $connectStr2
#Verify Custom Probe Messages on both server
					If ( $probe -eq "yes" ) {
						If (( IsCustomProbeMsgsPresent -logFile $server1Log -beg "Test Started" -end "TestComplete") -and (IsCustomProbeMsgsPresent -logFile $server2Log -beg "Test Started" -end "TestComplete")) {
							$server1CpConnCount= GetCustomProbeMsgsCount -logFile $server1Log -beg "Test Started" -end "TestComplete"
							$server2CpConnCount= GetCustomProbeMsgsCount -logFile $server2Log -beg "Test Started" -end "TestComplete"
							LogMsg "$server1CpConnCount Custom Probe Messages observed on Server1"
							LogMsg "$server2CpConnCount Custom Probe Messages observed on Server1"
							$testResult = "PASS"
							LogMsg "Server1 Parallel Connection Count is $server1ConnCount"
							LogMsg "Server2 Parallel Connection Count is $server2ConnCount"
							$diff = [Math]::Abs($server1ConnCount - $server2ConnCount)
							If ((($diff/$pSize)*100) -lt 20) {
								$testResult = "PASS"
								LogMsg "Connection Counts are distributed evenly in both Servers"
								LogMsg "Diff between server1 and server2 is $diff"
								$server1Dt= GetTotalDataTransfer -logFile $server1Log -beg "Test Started" -end "TestComplete"
								$server2Dt= GetTotalDataTransfer -logFile $server2Log -beg "Test Started" -end "TestComplete"
								$clientDt= GetTotalDataTransfer -logFile $clientLog -beg "Test Started" -end "TestComplete"
								LogMsg "Server1 Total Data Transfer is $server1Dt"
								LogMsg "Server2 Total Data Transfer is $server2Dt"
								LogMsg "Client Total Data Transfer is $clientDt"
								$totalServerDt = ([int]($server1Dt.Split("K")[0]) + [int]($server2Dt.Split("K")[0]))
								LogMsg "All Servers Total Data Transfer is $totalServerDt"
								If (([int]($clientDt.Split("K")[0])) -eq [int]($totalServerDt)) {
									$testResult = "PASS"
									LogMsg "Total DataTransfer is equal on both Server and Client"
								} else {
									$testResult = "FAIL"
									LogError "Total DataTransfer is NOT equal on both Server and Client"
								}
							} else {
								$testResult = "FAIL"
								LogError "Connection Counts are not distributed correctly"
								LogError "Diff between server1 and server2 is $diff"
							}
						} else {
							if (!( IsCustomProbeMsgsPresent -logFile $server1Log -beg "Test Started" -end "TestComplete") ) {
								LogError "NO Custom Probe Messages observed on Server1"
								$testResult = "FAIL"
							}
							if (!(IsCustomProbeMsgsPresent -logFile $server2Log -beg "Test Started" -end "TestComplete")) {
								$server2CpConnCount= GetCustomProbeMsgsCount -logFile $server2Log -beg "Test Started" -end "TestComplete"
								LogError "$server2CpConnCount Custom Probe Messages observed on Server1"
								$testResult = "FAIL"
							} 
						}
					} elseif ( $probe -eq "no" ) {
						If ((!(IsCustomProbeMsgsPresent -logFile $server1Log -beg "Test Started" -end "TestComplete")) -and (!(IsCustomProbeMsgsPresent -logFile $server2Log -beg "Test Started" -end "TestComplete"))) {
							LogMsg "NO Custom Probe Messages observed on Server1"
							LogMsg "NO Custom Probe Messages observed on Server2"
							$testResult = "PASS"
							LogMsg "Server1 Parallel Connection Count is $server1ConnCount"
							LogMsg "Server2 Parallel Connection Count is $server2ConnCount"
							$diff = [Math]::Abs($server1ConnCount - $server2ConnCount)
							If ((($diff/$pSize)*100) -lt 20) {
								$testResult = "PASS"
								LogMsg "Connection Counts are distributed evenly in both Servers"
								LogMsg "Diff between server1 and server2 is $diff"
								$server1Dt= GetTotalDataTransfer -logFile $server1Log -beg "Test Started" -end "TestComplete"
								$server2Dt= GetTotalDataTransfer -logFile $server2Log -beg "Test Started" -end "TestComplete"
								$clientDt= GetTotalDataTransfer -logFile $clientLog -beg "Test Started" -end "TestComplete"
								LogMsg "Server1 Total Data Transfer is $server1Dt"
								LogMsg "Server2 Total Data Transfer is $server2Dt"
								LogMsg "Client Total Data Transfer is $clientDt"
								$totalServerDt = ([int]($server1Dt.Split("K")[0]) + [int]($server2Dt.Split("K")[0]))
								LogMsg "All Servers Total Data Transfer is $totalServerDt"
								If (([int]($clientDt.Split("K")[0])) -eq [int]($totalServerDt)) {
									$testResult = "PASS"
									LogMsg "Total DataTransfer is equal on both Server and Client"
								} else {
									$testResult = "FAIL"
									LogError "Total DataTransfer is NOT equal on both Server and Client"
								}
							} else {
								$testResult = "FAIL"
								LogError "Connection Counts are not distributed correctly"
								LogError "Diff between server1 and server2 is $diff"
							}
						} else {
							if((IsCustomProbeMsgsPresent -logFile $server1Log -beg "Test Started" -end "TestComplete")) {
								$server1CpConnCount = GetCustomProbeMsgsCount -logFile $server1Log -beg "Test Started" -end "TestComplete"
								LogError "$server1CpConnCount Custom Probe Messages observed on Server1"
								$testResult = "FAIL"
							} 
							if((IsCustomProbeMsgsPresent -logFile $server2Log -beg "Test Started" -end "TestComplete")) {
								$server2CpConnCount = GetCustomProbeMsgsCount -logFile $server2Log -beg "Test Started" -end "TestComplete"
								LogError "$server2CpConnCount Custom Probe Messages observed on Server2"
								$testResult = "FAIL"
							} 
						}
					}

				}	else {
					$testResult = "FAIL"
					LogError "Server is not Connected to Client"
				}
			} else {
				$testResult = "FAIL"
				LogError "Client is not Connected to Client"
			}	
		} else {
			LogError "Failured detected in client connection."
			RemoteCopy -download -downloadFrom $server1.ip -files "/home/$user/iperf-server.txt" -downloadTo $server1.LogDir -port $server1.sshPort -username $server1.user -password $server1.password
			LogMsg "Test Finished..!"
			$testResult = "FAIL"
		}
	} else	{
		LogMsg "Unable to start iperf-server. Aborting test."
		RemoteCopy -download -downloadFrom $server1.ip -files "/home/$user/iperf-server.txt" -downloadTo $server1.LogDir -port $server1.sshPort -username $server1.user -password $server1.password
		RemoteCopy -download -downloadFrom $server2.ip -files "/home/$user/iperf-server.txt" -downloadTo $server2.LogDir -port $server2.sshPort -username $server2.user -password $server2.password
		$testResult = "Aborted"
	}
	return $testResult
}

Function CreateIperfNode
{
	param(
			[string] $nodeIp,
			[string] $nodeSshPort,
			[string] $nodeTcpPort,
			[string] $nodeUdpPort,
			[string] $nodeProbePort,
			[string] $nodeIperfCmd,
			[string] $user,
			[string] $password,
			[string] $files,
			[string] $nodeDip,
			[string] $nodeHostname,
			[string] $nodeUrl,
			[string] $logDir)

	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name ip -Value $nodeIp -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name sshPort -Value $nodeSshPort -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name tcpPort -Value $nodeTcpPort -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name probePort -Value $nodeProbePort -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name cmd -Value $nodeIperfCmd -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name user -Value $user -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name password -Value $password -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name files -Value $files -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name logDir -Value $LogDir -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name DIP -Value $nodeDip -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name Hostname -Value $nodeHostname -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name URL -Value $nodeUrl -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name udpPort -Value $nodeUdpPort -Force
	return $objNode
}

Function CreateIdnsNode
{
	param(
			[string] $nodeIp,
			[string] $nodeSshPort,
			[string] $user,
			[string] $password,
			[string] $nodeDip,
			[string] $nodeUrl,
			[string] $nodeDefaultHostname,
			[string] $nodeNewHostname,
			[string] $fqdn,
			[string] $logDir)

	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name ip -Value $nodeIp -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name sshPort -Value $nodeSshPort -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name user -Value $user -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name password -Value $password -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name logDir -Value $LogDir -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name DIP -Value $nodeDip -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name URL -Value $nodeUrl -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name hostname -Value $nodeDefaultHostname -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name Newhostname -Value $nodeNewHostname -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name fqdn -Value $fqdn -Force
	return $objNode
}

Function CreatePingNode
{
	param(
			[string] $nodeIp,
			[string] $nodeSshPort,
			[string] $user,
			[string] $password,
			[string] $nodeDip,
			[string] $nodeUrl,
			[string] $cmd,
			[string] $files,
			[string] $logDir)


	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name ip -Value $nodeIp -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name sshPort -Value $nodeSshPort -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name user -Value $user -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name password -Value $password -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name logDir -Value $LogDir -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name DIP -Value $nodeDip -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name URL -Value $nodeUrl -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name cmd -Value $cmd -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name files -Value $files -Force
	return $objNode
}

Function StartIperfServer($node)
{	
	$currentDir = $PWD.Path
	LogMsg "Starting iperf Server on $($node.ip)"
	$out = RunLinuxCmd -username $node.user -password $node.password -ip $node.ip -port $node.sshport -command $node.cmd -runAsSudo -RunInBackGround
	sleep 1
}

Function StartIperfClient($node)
{
	LogMsg "Starting iperf Client on $($node.ip)"
	$out = RunLinuxCmd -username $node.user -password $node.password -ip $node.ip -port $node.sshport -command $node.cmd -runAsSudo
	sleep 3
}

Function IsIperfServerStarted($node, $expectedServerInstances = 1)
{
	#RemoteCopy -download -downloadFrom $node.ip -files "/home/$user/start-server.py.log" -downloadTo $node.LogDir -port $node.sshPort -username $node.user -password $node.password
	LogMsg "Verifying if server is started or not.."
	$iperfout = RunLinuxCmd -username $node.user -password $node.password -ip $node.ip -port $node.sshPort -command "ps -ef | grep iperf -s | grep -v grep | wc -l" -runAsSudo
	$iperfout = [int]$iperfout[-1].ToString()
	LogMsg "Total iperf server running instances : $($iperfout)"	
	if($iperfout -ge $expectedServerInstances)
	{
		return $true
	}
	else
	{
		return $false
	}
}

Function IsIperfServerRunning($node)
{
	$out = RunLinuxCmd -username $node.user -password $node.password -ip $node.ip -port $node.sshport -command "$python_cmd check-server.py && mv Runtime.log check-server.py.log -f" -runAsSudo
	RemoteCopy -download -downloadFrom $node.ip -files "/home/$user/check-server.py.log, /home/$user/iperf-server.txt" -downloadTo $node.LogDir -port $node.sshPort -username $node.user -password $node.password
	RemoteCopy -download -downloadFrom $node.ip -files "/home/$user/state.txt, /home/$user/Summary.log" -downloadTo $node.logdir -port $node.sshPort -username $node.user -password $node.password
	$serverState = Get-Content "$($node.Logdir)\state.txt"
	$serverSummary =  Get-Content "$($node.Logdir)\Summary.log"

#>>>Remove Temporary files..
	Remove-Item "$($node.Logdir)\state.txt" -Force
	Remove-Item "$($node.Logdir)\Summary.log" -Force
#>>>Verify client connections appeared on server...
	if($serverState -eq "TestCompleted" -and $serverSummary -eq "PASS"){
		return $true
	}
	else{
		return $false
	}
}

Function IsIperfClientStarted($node, [string]$beginningText, [string]$endText)
{
	sleep 1
	$out = RunLinuxCmd -username $node.user -password $node.password -ip $node.ip -port $node.sshPort -command "mv Runtime.log start-client.py.log -f" -runAsSudo
	RemoteCopy -download -downloadFrom $node.ip -files "/home/$user/start-client.py.log, /home/$user/iperf-client.txt" -downloadTo $node.LogDir -port $node.sshPort -username $node.user -password $node.password
	RemoteCopy -download -downloadFrom $node.ip -files "/home/$user/state.txt, /home/$user/Summary.log" -downloadTo $node.Logdir -port $node.sshPort -username $node.user -password $node.password
	$clientState = Get-Content "$($node.Logdir)\state.txt"
	$clientSummary = Get-Content "$($node.Logdir)\Summary.log"
	Write-Host "Client State : $clientState"
	Write-Host "Client Summary : $clientSummary"
#>>>Remove Temporary files..
	Remove-Item "$($node.Logdir)\state.txt" -Force
	Remove-Item "$($node.Logdir)\Summary.log" -Force
	if ($beginningText -and $endText)
	{
		$connectStingCount = GetStringMatchCount -logFile "$($node.LogDir)\iperf-client.txt" -beg $beginningText -end $endText -str "connected with"
		if ($connectStingCount -gt 0)
		{
			$connFailureCount = GetStringMatchCount -logFile "$($node.LogDir)\iperf-client.txt" -beg $beginningText -end $endText -str "Connection refused"
			$connFailureCount += GetStringMatchCount -logFile "$($node.LogDir)\iperf-client.txt" -beg $beginningText -end $endText -str "connect failed"
			Write-Host "connection failures found:" $connFailureCount
			if($connFailureCount -gt 0)
			{
				$retVal = $false
			}
			else
			{
				$retVal = $true
			}
		}
		else
		{
			$retVal = $false
		}
	}
	else
	{
		if(($clientState -eq "TestCompleted") -and ($clientSummary -eq "PASS")){
			$retVal = $true
		}
		else{

			$retVal = $false
		}
	}
	return $retVal
}

Function DoNslookupTest ($vm1, $vm2)
{
	$out = RunLinuxCmd -username $vm1.user -password $vm1.password -ip $vm1.Ip -port $vm1.SshPort -command "echo TestStarted > nslookup12.log" -runAsSudo
	if ($detectedDistro -eq "COREOS")
	{
		$nslookupCommand = "$python_cmd nslookup.py -n $($vm2.Hostname)"
	}
	else
	{
		$nslookupCommand = "nslookup $($vm2.Hostname)"
	}
	$out = RunLinuxCmd -username $vm1.user -password $vm1.password -ip $vm1.Ip -port $vm1.SshPort -command "echo Executing : $nslookupCommand >> nslookup12.log" -runAsSudo
	$out = RunLinuxCmd -username $vm1.user -password $vm1.password -ip $vm1.Ip -port $vm1.SshPort -command "$nslookupCommand >> nslookup12.log" -runAsSudo -ignoreLinuxExitCode
	$out = RunLinuxCmd -username $vm1.user -password $vm1.password -ip $vm1.Ip -port $vm1.SshPort -command "echo TestCompleted >> nslookup12.log" -runAsSudo
	RemoteCopy -download -downloadTo $vm1.logDir -downloadFrom $vm1.ip -port $vm1.sshport  -username $vm1.user -password $vm1.password -files "nslookup12.log"
	$nslookuplog12 = $vm1.logDir + "\nslookup12.log"
	$nslookupResult = GetStringMatchCount -logFile $nslookuplog12 -beg TestStarted -end TestCompleted -str $vm2.DIP
	$ErrorLine = GetStringMatchCount -logFile $nslookuplog12 -beg TestStarted -end TestCompleted -str "server can`'t find"
	
	$nslookuplog12 = $vm1.logDir + "\nslookup12.log"
	Write-host "Hostname match count : $nslookupResult"
	if(($nslookupResult -gt 0) -and ($ErrorLine -eq 0))
	{
		$testResult = "PASS"
	}
	else
	{
		$testResult = "FAIL"
		$nslookupError = GetStringMatchObject -logFile $nslookuplog12 -beg TestStarted -end TestCompleted -str "server can`'t find"
		LogError "NSLOOKUP FAILED : $nslookupError"
	}
	LogMsg "NSLOOKUP Result : $testResult"
	return $testResult
}

Function DoDigTest ($vm1, $vm2)
{
	$out = RunLinuxCmd -username $vm1.user -password $vm1.password -ip $vm1.Ip -port $vm1.SshPort -command "echo TestStarted > dig12.log" -runAsSudo
	if ($detectedDistro -eq "COREOS")
	{
		$digCommand = "$python_cmd dig.py -n $($vm2.fqdn)"
	}
	else
	{
		$digCommand = "dig $($vm2.fqdn)"
	}
	$out = RunLinuxCmd -username $vm1.user -password $vm1.password -ip $vm1.Ip -port $vm1.SshPort -command "echo Executing : $digCommand >> dig12.log" -runAsSudo
	$out = RunLinuxCmd -username $vm1.user -password $vm1.password -ip $vm1.Ip -port $vm1.SshPort -command "$digCommand >> dig12.log" -runAsSudo -ignoreLinuxExitCode
	$out = RunLinuxCmd -username $vm1.user -password $vm1.password -ip $vm1.Ip -port $vm1.SshPort -command "echo TestCompleted >> dig12.log" -runAsSudo
	RemoteCopy -download -downloadTo $vm1.logDir -downloadFrom $vm1.ip -port $vm1.sshport  -username $vm1.user -password $vm1.password -files "dig12.log"
	$diglog12 = $vm1.logDir + "\dig12.log"
	$digResult = GetStringMatchCount -logFile $diglog12 -beg TestStarted -end TestCompleted -str $vm2.DIP
	if(($digResult -eq 1))
	{
		$testResult = "PASS"
		$digOutput = GetStringMatchObject -logFile $diglog12 -beg TestStarted -end TestCompleted -str $vm2.DIP
		LogMsg "DIG Result : DIP RESOLVED. : PASS"
		LogMsg "DIG Output : $digOutput"
	}
	else
	{
		$testResult = "FAIL"
		LogError "DIG Result : DIP NOT RESOLVED. : FAIL"
	}
	return $testResult
}

Function GetVMFQDN ($vm)
{
	$out = RunLinuxCmd -username $vm.user -password $vm.password -ip $vm.Ip -port $vm.SshPort -command "hostname --fqdn > vmfqdn.txt" -runAsSudo
	RemoteCopy -download -downloadTo $vm.logDir -downloadFrom $vm.ip -port $vm.sshport  -username $vm.user -password $vm.password -files "vmfqdn.txt"
	$vmFQDN = Get-Content "$($vm.LogDir)\vmfqdn.txt"
	if($vmFQDN)
	{
		return $vmFQDN
	}
	else
	{
		Throw "Calling function - $($MyInvocation.MyCommand). Unable to get VM FQDN.."
	}
}

Function DoPingTest ($pingFrom, [switch]$isVNET, [switch]$fromLocal, $intermediateVM)
{
#Skeep the file upload process for VNET test case.
	if(!$isVNET)
	{
		RemoteCopy -upload -uploadTo $pingFrom.IP -port $pingFrom.sshport -username $pingFrom.user -password $pingFrom.password -files $pingFrom.files
	}
	$pingLog = $pingFrom.logDir + "\ping.log"
	if(!$fromLocal)
	{
		$suppressedOut = RunLinuxCmd -username $pingFrom.user -password $pingFrom.password -ip $pingFrom.Ip -port $pingFrom.SshPort -command "echo TestStarted > ping.log" -runAsSudo
		$suppressedOut = RunLinuxCmd -username $pingFrom.user -password $pingFrom.password -ip $pingFrom.Ip -port $pingFrom.SshPort -command "chmod +x *.py" -runAsSudo
		$suppressedOut = RunLinuxCmd -username $pingFrom.user -password $pingFrom.password -ip $pingFrom.Ip -port $pingFrom.SshPort -command "echo Executing : $($pingFrom.cmd) >> ping.log" -runAsSudo
		$suppressedOut = RunLinuxCmd -username $pingFrom.user -password $pingFrom.password -ip $pingFrom.Ip -port $pingFrom.SshPort -command "$($pingFrom.cmd)" -runAsSudo 
		$suppressedOut = RunLinuxCmd -username $pingFrom.user -password $pingFrom.password -ip $pingFrom.Ip -port $pingFrom.SshPort -command "echo TestCompleted >> ping.log" -runAsSudo
		RemoteCopy -download -downloadTo $pingFrom.logDir -downloadFrom $pingFrom.ip -port $pingFrom.sshport  -username $pingFrom.user -password $pingFrom.password -files "ping.log"
	}
	else
	{
		Set-Content -Value "TestStarted" -Path $pingLog
		$out = RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $pingFrom -runAsSudo -remoteCommand "rm -rf ping.log"
		$out = RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $pingFrom -runAsSudo -remoteCommand "chmod +x /home/$user/*.py"		
		#$newPingCmd = ($pingFrom.cmd).Replace(" ","\ ")
		$newPingCmd = $pingFrom.cmd
		$pingoutput = RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $pingFrom -runAsSudo -remoteCommand "$newPingCmd" 
		Write-Host $pingoutput	 
#$out = RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $pingFrom -runAsSudo -remoteCommand "echo\ TestCompleted\ >>\ ping.log"	  
		$pingoutput = RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $pingFrom -runAsSudo -remoteCommand "cat ping.log"	  
		Add-Content -Value $pingoutput  -Path $pingLog 
		Add-Content -Value "TestCompleted" -Path $pingLog 
	}

	$pingResult = GetStringMatchCount -logFile $pinglog -beg TestStarted -end TestCompleted -str "ttl"

	if(($pingResult -ge 1))
	{
		$testResult = "PASS"
#I'm working on adding more checks here like packet loss, time to travel. will do it soon. Just now checking for connectivity.
	}
	else
	{
		$testResult = "FAIL"
	}
	return $testResult
}
#endregion

#region ResultLog Parser Code
###############################################################

Function GetStringMatchCount([string] $logFile,[string] $beg,[string] $end, [string] $str)
{
	$match=GetStringMatchObject -logFile $logFile -beg $beg -end $end -str $str
	return $match.Count
}

Function GetTotalDataTransfer([string] $logFile,[string] $beg,[string] $end)
{
	$dataTransfer=GetDataTxed -logFile $logFile -ptrn "[bits,bytes]/sec$"
	return $dataTransfer
}

Function GetTotalUdpServerTransfer([string] $logFile,[string] $beg,[string] $end)
{
	$dataTransfer=GetDataTxed -logFile $logFile -ptrn "[bits,bytes]/sec"
	return $dataTransfer
}

Function GetTotalUdpServerTransfer([string] $logFile,[string] $beg,[string] $end)
{
	$dataTransfer=GetDataTxed -logFile $logFile -ptrn "[bits,bytes]/sec"
	return $dataTransfer
}

Function GetUdpLoss([string] $logFile, [string] $beg,[string] $end)
{
	$match=GetStringMatchObject -logFile $logFile -beg $beg -end $end -str "\([\d,\d.\d]*%\)$"
	$arr = @()
	foreach ($item in $match) {
		$item = $item.ToString()
		$str2=@($item.Split(" ",[StringSplitOptions]'RemoveEmptyEntries'))
		foreach ($a in $str2) {
			if($a.Contains("%"))
			{
#$i=$str2.IndexOf($a)
#$a=$str2[$i]
				$a= $a.Replace("%", "")
				$a= $a.Replace("(", "")
				$a= $a.Replace(")", "")
#$num=$b[0].Split("(")
				$arr += $a
			}
		}
		$sum = ($arr | Measure-Object -Sum).Sum
	}
	return $sum
}

Function GetDataTxed([string] $logFile,[string] $beg,[string] $end, [string] $ptrn) 
{
	$match=GetStringMatchObject -logFile $logFile -beg $beg -end $end -str $ptrn
	$match= $match | Select-String -Pattern "0.00 KBytes/sec" -NotMatch
	$lastItem=$match[-1]
	$lastItem=$lastItem.ToString()
	$str1=@($lastItem.Split(" ",[StringSplitOptions]'RemoveEmptyEntries'))
	foreach ($a in $str1) {
		if($a.Contains("Bytes") -and !($a.Contains("Bytes/sec")))
		{
			$i=$str1.IndexOf($a)
			$result=$str1[$i-1]+$str1[$i]
		}
	}
	return $result
}

Function AnalyseIperfServerConnectivity([string] $logFile,[string] $beg,[string] $end)
{
	$connectStr="\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\sport\s\d*\sconnected with \d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\sport\s\d"
	$match=IsContainString -logFile $logFile -beg $beg -end $end -str $connectStr
	$failure = 0
	If($match) {
		$RefusedConnections = GetStringMatchCount -logFile $logFile -beg $beg -end $end -str "Connection refused"
		if($RefusedConnections -gt 0){
			LogError "Server connected to client. But `"Connection Refused`" observed $RefusedConnections times in the logs. Marking test as FAIL."
			return $false
		}
		else{
			LogMsg "Server Connected successfully"
			return $true
		}
	}
	else {
		LogError "Server connection Fails!"
		return $false
	}
}

Function AnalyseIperfClientConnectivity([string] $logFile,[string] $beg,[string] $end)
{
	$connectStr="\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\sport\s\d*\sconnected with \d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\sport\s\d"
	$match=IsContainString -logFile $logFile -beg $beg -end $end -str $connectStr
	$failure = 0
	If ($match) 
	{
		$match = IsContainString -logFile $logFile -beg $beg -end $end -str "failed"
		If($match) 
		{
			$failure = $failure + 1
			LogError "Client connected with some failed connections!"
		}	
		$match = IsContainString -logFile $logFile -beg $beg -end $end -str "error"	
		If($match)
		{
			$failure = $failure + 1
			LogError "There were some errors in the connections!"
		}
		$match = IsContainString -logFile $logFile -beg $beg -end $end -str "refused"	
		If($match)
		{
			$failure = $failure + 1
			LogError "Some connections were refused!" 
		}
		$match = IsContainString -logFile $logFile -beg $beg -end $end -str "Broken pipe"	
		If($match)
		{
			$failure = $failure + 1
			LogError "Broken Pipe Message observed in Iperf Client Output" 
		}
		$match = IsContainString -logFile $logFile -beg $beg -end $end -str "TestIncomplete"	
		If($match)
		{
			$failure = $failure + 1
			LogError "Client was successfully connected to server but, client process failed to exit!" 
		}
		if ($failure -eq 0)
		{
			LogMsg "Client was successfully connected to server"
			return $true
		} else {
			LogError "Client connection fails"
			return $false
		}
	} 
	else
	{
		$match = IsContainString -logFile $logFile -beg $beg -end $end -str "No address associated"	
		If($match) {
			LogError "Client was not connected to server!"
			LogError "No address associated with hostname"
			return $false
		} 
		elseif (($match= IsContainString -logFile $logFile -beg $beg -end $end -str "Connection refused"))
		{
			LogError "Client was not connected to server."
			LogError "Connection refused by the server."
			return $false
		}
		elseif (($match= IsContainString -logFile $logFile -beg $beg -end $end -str "Name or service not known"))
		{
			LogError "Client was not connected to server."
			LogError "Name or service not known."
			return $false
		} 
		else
		{
			LogError "Client was not connected to server."
			LogError "Unlisted error. Check logs for more information...!."
			return $false
		}
	}
}

Function IsContainString([string] $logFile,[string] $beg,[string] $end, [string] $str)
{
	$match=GetStringMatchObject -logFile $logFile -beg $beg -end $end -str $str
	If ($match.count -gt 0) {
		return $true
	} else {
		return $false
	}
}

Function GetStringMatchObject([string] $logFile,[string] $beg,[string] $end, [string] $str) 
{
	if ($beg -eq "0") {
		$begPos = 1
		$match=Select-String -Pattern $end -Path $logFile
		$endPos= $match.LineNumber
		$lineArr = ($begPos-1)..($endPos-1)
		$match=Get-Content -Path $logFile | Select-Object -Index $lineArr | Select-String -Pattern $str
	} elseif ($beg -ne ""  -and $end -ne "") {
		$match=Select-String -Pattern $beg -Path $logFile
		$begPos= $match.LineNumber
		$match=Select-String -Pattern $end -Path $logFile
		$endPos= $match.LineNumber
		$lineArr = ($begPos-1)..($endPos-1)
		$match=Get-Content -Path $logFile | Select-Object -Index $lineArr | Select-String -Pattern $str
	} else {
		$match=Select-String -Pattern $str -Path $logFile
	}
	return $match
}

Function GetAllStringMatchObject([string] $logFile,[string] $beg,[string] $end)
{
	if ($beg -eq "0") {
		$begPos = 1
		$match=Select-String -Pattern $end -Path $logFile
		$endPos= $match.LineNumber
		$lineArr = ($begPos-1)..($endPos-1)
		$match=Get-Content -Path $logFile | Select-Object -Index $lineArr | Select-String
	} elseif ($beg -ne ""  -and $end -ne "") {
		$match=Select-String -Pattern $beg -Path $logFile
		$begPos= $match.LineNumber
		$match=Select-String -Pattern $end -Path $logFile
		$endPos= $match.LineNumber
		$lineArr = ($begPos-1)..($endPos-1)
		$match=Get-Content -Path $logFile | Select-Object -Index $lineArr | Select-String
	} else {
		$match=Select-String -Path $logFile
	}
	return $match
}

Function GetParallelConnectionCount([string] $logFile,[string] $beg,[string] $end)
{
	$connectStr1 = $allVMData[0].InternalIP+"\sport\s\d*\sconnected with " +$allVMData[1].InternalIP + "\sport\s\d"
	$p1=GetStringMatchCount -logFile $logFile -beg $beg -end $end -str $connectStr1

	$connectStr2 = $allVMData[0].PublicIP+"\sport\s\d*\sconnected with " +$allVMData[1].PublicIP + "\sport\s\d"
	$p2=GetStringMatchCount -logFile $logFile -beg $beg -end $end -str $connectStr2

	$connectStr3 = $allVMData[0].InternalIP+"\sport\s\d*\sconnected with " +$allVMData[1].PublicIP + "\sport\s\d"
	$p3=GetStringMatchCount -logFile $logFile -beg $beg -end $end -str $connectStr3

	$connectStr4 = $allVMData[0].PublicIP+"\sport\s\d*\sconnected with " +$allVMData[1].InternalIP + "\sport\s\d"
	$p4=GetStringMatchCount -logFile $logFile -beg $beg -end $end -str $connectStr4

	$connectStr5 = $allVMData[1].InternalIP+"\sport\s\d*\sconnected with " +$allVMData[0].InternalIP + "\sport\s\d"
	$p5=GetStringMatchCount -logFile $logFile -beg $beg -end $end -str $connectStr5

	$connectStr6 = $allVMData[1].PublicIP+"\sport\s\d*\sconnected with " +$allVMData[0].PublicIP + "\sport\s\d"
	$p6=GetStringMatchCount -logFile $logFile -beg $beg -end $end -str $connectStr6

	$connectStr7 = $allVMData[1].InternalIP+"\sport\s\d*\sconnected with " +$allVMData[0].PublicIP + "\sport\s\d"
	$p7=GetStringMatchCount -logFile $logFile -beg $beg -end $end -str $connectStr7

	$connectStr8 = $allVMData[1].PublicIP+"\sport\s\d*\sconnected with " +$allVMData[0].InternalIP + "\sport\s\d"
	$p8=GetStringMatchCount -logFile $logFile -beg $beg -end $end -str $connectStr8

	return $p1+$p2+$p3+$p4+$p5+$p6+$p7+$p8
}

Function GetMSSSize([string] $logFile,[string] $beg,[string] $end)
{
	$match=GetStringMatchObject -logFile $logFile -beg $beg -end $end -str "MSS size \d*\sbytes"
	If ($match.Length -gt 1) {
		$lastItem=$match.Item($match.Length-1) 
	} else {
		$lastItem=$match
	}
	$lastItem=$lastItem.ToString()
#$str1=@($lastItem.Split(']'))
	$str2=@($lastItem.Split(" ",[StringSplitOptions]'RemoveEmptyEntries'))
	foreach ($a in $str2) {
		if($a.Contains("size"))
		{
			$i=$str2.IndexOf($a)
			$result=$str2[$i+1]+$str2[$i+2]
		}
	}
	return $result
}

Function GetParallelConnectionsCount($iperfClientoutput)
{
	$iperfClientOutput = $iperfClientOutput.Split("")
	$uniqueIds = @()
	$AllConnectedIDs = @()
	$NoofUniqueIds = 0
	foreach ($word in $iperfClientOutput)
	{
		if ($word -imatch "]")
		{
			$word = $word.Replace("]","")
			$word = $word.Replace("[","")
			$word = $word -as [int]
			if ($word)
			{
				$AllConnectedIDs += $word
				$NotUnique = 0
				foreach ($id in $uniqueIds)
				{
					if ($word -eq $id)
					{
						$NotUnique = $NotUnique + 1
					}
				}
				if ($NotUnique -eq 0)
				{
					$uniqueIds += $word
				}
			}

		}
	}
	$NoofUniqueIds = $uniqueIds.Count
#return $AllConnectedIDs, $uniqueIds, $NoofUniqueIds
	return $NoofUniqueIds
}

Function GetCustomProbeMsgsCount([string] $logFile,[string] $beg,[string] $end) 
{
	$match=GetStringMatchObject -logFile $logFile -beg $beg -end $end -str "0.00 KBytes  0.00 KBytes/sec"
	return $match.Count
}

Function IsCustomProbeMsgsPresent ([string] $logFile,[string] $beg,[string] $end) 
{
	$cpStr="0.00 KBytes  0.00 KBytes/sec"
	$match=IsContainString -logFile $logFile -beg $beg -end $end -str $cpStr
	return $match
}

Function GetAllStringMatchObject([string] $logFile,[string] $beg,[string] $end)
{
	if ($beg -eq "0") {
		$begPos = 1
		$match=Select-String -Pattern $end -Path $logFile
		$endPos= $match.LineNumber
		$lineArr = ($begPos-1)..($endPos-1)
		$match=Get-Content -Path $logFile | Select-Object -Index $lineArr
	} elseif ($beg -ne ""  -and $end -ne "") {
		$match=Select-String -Pattern $beg -Path $logFile 
		$begPos=  $match.LineNumber
		$match=Select-String -Pattern $end -Path $logFile
		$endPos= $match.LineNumber
		$lineArr = ($begPos-1)..($endPos-1)
		$match=Get-Content -Path $logFile | Select-Object -Index $lineArr
	} else {
		$match=Select-String -Path $logFile
	}
	return $match
}

Function GetUdpDatagramSize ([string] $logFile,[string] $beg,[string] $end)
{
	$datagramLine = GetStringMatchObject -beg $beg -end $end -logFile $logFile -str Sending
	$datagramLine = $datagramLine.ToString()
	$datagramLine = $datagramLine.Split(" ")
	$datagramSize = $datagramLine[1]
	return $datagramSize
}
#endregion

#region PerfTest Methods
Function GetIozoneResultAllValues 
{
	param
	(
	 [Parameter(Mandatory=$true)]
	 [string] $logFile
	)
	$iozoneData= @{"write"="";"rewrite"="";"read"="";"reread"="";"randread"="";"randwrite"="";"bkwdread"="";"recrewrite"="";"strideread"="";}
	foreach ($key in @($iozoneData.keys))
	{
		$iozoneData[$key]=GetIozoneResult $logFile $key
	}
	return $iozoneData
}

Function GetIozoneResult ([string] $logFile,[string] $str)
{
	$str="^"+$str
	$match=GetStringMatchObject -logFile $logFile -str $str
	$match=$match.ToString()
	$value=$match.Split(" ")
	return $value[$value.lenght-1]
}
#endregion

#region VNET TESTS Methods

Function Get-AllVMHostnameAndDIP($DeployedServices)
{
	foreach ($hostedservice in $DeployedServices.Split("^"))
	{
		$DeployedVMs = Get-AzureVM -ServiceName $hostedService
		foreach ($testVM in $DeployedVMs)
		{
			$VMhostname = $testVM.InstanceName
			$VMDIP = $testVM.IpAddress
			if($HostnameDIP)
			{
				$HostnameDIP = $HostnameDIP + "^$VMhostname" + ':' +"$VMDIP"
			}
			else
			{
				$HostnameDIP = "$VMhostname" + ':' +"$VMDIP"
			}
		}
	}

	return $HostnameDIP
}

Function Get-SSHDetailofVMs($DeployedServices, $ResourceGroups)
{
	if ( $DeployedServices )
	{
		foreach ($hostedservice in $DeployedServices.Split("^"))
		{
			$DeployedVMs = Get-AzureVM -ServiceName $hostedService
			foreach ($testVM in $DeployedVMs)
			{
				$AllEndpoints = Get-AzureEndpoint -VM $testVM
				$HSVIP = GetHsVmVip -servicename $hostedservice
				$HSport = GetPort -Endpoints $AllEndpoints -usage SSH
				if($TestIPPOrts)
				{
					$TestIPPOrts = $TestIPPOrts + "^$HSVIP" + ':' +"$HSport"
				}
				else
				{
					$TestIPPOrts = "$HSVIP" + ':' +"$HSport"
				}


			}
		}
	}
	elseif ($ResourceGroups)
	{
		foreach ($ResourceGroup in $ResourceGroups.Split("^"))
		{
			$RGIPdata = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/publicIPAddresses" -ExpandProperties -Verbose
			$RGVMs = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Compute/virtualMachines" -ExpandProperties -Verbose
			foreach ($testVM in $RGVMs)
			{
				$AllEndpoints = $testVM.Properties.NetworkProfile.InputEndpoints
				foreach ($endPoint in $AllEndpoints)
				{
					if ($endPoint.EndpointName -eq "SSH")
					{
						if($TestIPPOrts)
						{
							$TestIPPOrts = $TestIPPOrts + "^$($RGIPdata.Properties.IpAddress)" + ':' +"$($endPoint.PublicPort)"
						}
						else
						{
							$TestIPPOrts = "$($RGIPdata.Properties.IpAddress)" + ':' +"$($endPoint.PublicPort)"
						}
					}
				}
			}
		}		
	}
	return $TestIPPOrts
}

Function GetAllDeployementData($DeployedServices, $ResourceGroups)
{
	$allDeployedVMs = @()
	function CreateQuickVMNode()
	{
		$objNode = New-Object -TypeName PSObject
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name ServiceName -Value $ServiceName -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name ResourceGroupName -Value $ResourceGroupName -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name Location -Value $ResourceGroupName -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name RoleName -Value $RoleName -Force 
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name PublicIP -Value $PublicIP -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name PublicIPv6 -Value $PublicIP -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name InternalIP -Value $InternalIP -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name URL -Value $URL -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name URLv6 -Value $URL -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name Status -Value $Status -Force
		Add-Member -InputObject $objNode -MemberType NoteProperty -Name InstanceSize -Value $InstanceSize -Force
		return $objNode
	}

	if ( $UseAzureResourceManager )
	{
		foreach ($ResourceGroup in $ResourceGroups.Split("^"))
		{
			LogMsg "Collecting $ResourceGroup data.."

			$allRGResources = (Get-AzureRmResource | where { $_.ResourceGroupName -eq $ResourceGroup } | Select ResourceType).ResourceType
			LogMsg "    Microsoft.Network/publicIPAddresses data collection in progress.."
			$RGIPdata = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/publicIPAddresses" -Verbose -ExpandProperties
			LogMsg "    Microsoft.Compute/virtualMachines data collection in progress.."
			$RGVMs = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Compute/virtualMachines" -Verbose -ExpandProperties
			LogMsg "    Microsoft.Network/networkInterfaces data collection in progress.."
			$NICdata = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/networkInterfaces" -Verbose -ExpandProperties
			$currentRGLocation = (Get-AzureRmResourceGroup -ResourceGroupName $ResourceGroup).Location
			$numberOfVMs = 0
			foreach ($testVM in $RGVMs)
			{
				$numberOfVMs += 1
			}
			if ( ($numberOfVMs -gt 1) -or (($RGIPData | where { $_.Properties.publicIPAddressVersion -eq "IPv6" }).Properties.ipAddress) -or ($allRGResources -contains "Microsoft.Network/loadBalancers"))
			{
				LogMsg "    Microsoft.Network/loadBalancers data collection in progress.."
				$LBdata = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceType "Microsoft.Network/loadBalancers" -ExpandProperties -Verbose
			}
			foreach ($testVM in $RGVMs)
			{
				$QuickVMNode = CreateQuickVMNode
				if ( ( $numberOfVMs -gt 1 ) -or (($RGIPData | where { $_.Properties.publicIPAddressVersion -eq "IPv6" }).Properties.ipAddress)  -or ($allRGResources -contains "Microsoft.Network/loadBalancers"))
				{
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
				}
				else
				{
					LogMsg "    Microsoft.Network/networkSecurityGroups data collection in progress.."
					$SGData = Get-AzureRmResource -ResourceGroupName $ResourceGroup -ResourceName "SG-$($testVM.ResourceName)" -ResourceType "Microsoft.Network/networkSecurityGroups" -ExpandProperties
					foreach ($securityRule in $SGData.Properties.securityRules)
					{
						Add-Member -InputObject $QuickVMNode -MemberType NoteProperty -Name "$($securityRule.name)Port" -Value $securityRule.properties.destinationPortRange -Force
					}
					if($AllEndpoints.Length -eq 0)
					{
						$sg = Get-AzureRmNetworkSecurityGroup -ResourceGroupName $testVM.ResourceGroupName
						foreach($rule in $sg.SecurityRules)
						{
							Add-Member -InputObject $QuickVMNode -MemberType NoteProperty -Name "$($rule.Name)Port" -Value $rule.DestinationPortRange[0] -Force
						}
					}
				}
				foreach ( $nic in $NICdata )
				{
					if ( $nic.Name -imatch $testVM.ResourceName)
					{
						$QuickVMNode.InternalIP = "$($nic.Properties.IpConfigurations[0].Properties.PrivateIPAddress)"
					}
				}
				$QuickVMNode.ResourceGroupName = $ResourceGroup
                
				$QuickVMNode.PublicIP = ($RGIPData | where { $_.Properties.publicIPAddressVersion -eq "IPv4" }).Properties.ipAddress
				$QuickVMNode.PublicIPv6 = ($RGIPData | where { $_.Properties.publicIPAddressVersion -eq "IPv6" }).Properties.ipAddress
				$QuickVMNode.URL = ($RGIPData | where { $_.Properties.publicIPAddressVersion -eq "IPv4" }).Properties.dnsSettings.fqdn
				$QuickVMNode.URLv6 = ($RGIPData | where { $_.Properties.publicIPAddressVersion -eq "IPv6" }).Properties.dnsSettings.fqdn
				$QuickVMNode.RoleName = $testVM.ResourceName
				$QuickVMNode.Status = $testVM.Properties.ProvisioningState
				$QuickVMNode.InstanceSize = $testVM.Properties.hardwareProfile.vmSize
				$QuickVMNode.Location = $currentRGLocation
				$allDeployedVMs += $QuickVMNode
			}
			LogMsg "Collected $ResourceGroup data!"		
		}
	}
	else
	{
		$allDeployedVMs = @()
		foreach ($hostedservice in $DeployedServices.Split("^"))
		{
			LogMsg "Collecting $hostedservice data..."
			$testServiceData = Get-AzureService -ServiceName $hostedservice
			$DeployedVMs = Get-AzureVM -ServiceName $hostedService
			foreach ($testVM in $DeployedVMs)
			{
				$QuickVMNode = CreateQuickVMNode
				$AllEndpoints = Get-AzureEndpoint -VM $testVM
				$QuickVMNode.ServiceName = $hostedservice
				$QuickVMNode.RoleName = $testVM.InstanceName
				$QuickVMNode.PublicIP = $AllEndpoints[0].Vip
				$QuickVMNode.InternalIP = $testVM.IpAddress
				$QuickVMNode.InstanceSize = $testVM.InstanceSize
				foreach ($endpoint in $AllEndpoints)
				{
					Add-Member -InputObject $QuickVMNode -MemberType NoteProperty -Name "$($endpoint.Name)Port" -Value $endpoint.Port -Force
					if ( $endpoint.ProbePort )
					{
						Add-Member -InputObject $QuickVMNode -MemberType NoteProperty -Name "$($endpoint.Name)ProbePort" -Value $endpoint.ProbePort -Force
					}
				}
				$QuickVMNode.URL = ($testVM.DNSName).Replace("http://","").Replace("/","")
				$QuickVMNode.Status = $testVM.InstanceStatus
				$allDeployedVMs += $QuickVMNode
			}
			LogMsg "Collected $hostedservice data!"
		}
	}
	return $allDeployedVMs
}

Function CreateVMNode
{
	param(
			[string] $nodeIp,
			[string] $nodeSshPort,
			[string] $user,
			[string] $password,
			[string] $nodeDip,
			[string] $nodeHostname,
			[string] $cmd,
			[string] $files,
			[string] $logDir)


	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name ip -Value $nodeIp -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name sshPort -Value $nodeSshPort -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name user -Value $user -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name password -Value $password -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name logDir -Value $LogDir -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name DIP -Value $nodeDip -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name Hostname -Value $nodeHostname -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name URL -Value $nodeUrl -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name cmd -Value $cmd -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name files -Value $files -Force
	return $objNode
}

Function ConfigureDnsServer($intermediateVM, $DnsServer, $HostnameDIPDetails, $vnetDomainDBFilePath, $vnetDomainREVFilePath)
{
#Get VNETVM details using - Get-AllVMHostnameAndDIP() function. This will generate the string of all VMs IP and hostname.
	$HostnameDIP = $HostnameDIPDetails
	$DnsConfigureCommand = "echo $($dnsServer.password) | sudo -S python /home/$user/ConfigureDnsServer.py -v `"$HostnameDIP`" -D $vnetDomainDBFilePath -r $vnetDomainREVFilePath" 
	$out = RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $DnsServer -remoteCommand $DnsConfigureCommand
	#Add time interval for changes to take effect
	sleep 60
	if($out -imatch 'CONFIGURATION_SUCCESSFUL')
	{
		LogMsg  "DNS server configured successfully."
	}
	else
	{
		Throw "Calling function - $($MyInvocation.MyCommand). DNS server configuration failed."
	}
}

Function UploadFilesToAllDeployedVMs($SSHDetails,$files)
{
	$TestIPPOrts = $SSHDetails

	foreach ($IPPORT in $TestIPPOrts.Split("^"))
	{
		$IPPORT = $IPPORT.Split(":")
		$testIP = $IPPORT[0]
		$testPort = $IPPORT[1]
		RemoteCopy -upload -uploadTo $testIP  -port $testPort -username $user -password $password -files $files
	}
}

Function RunLinuxCmdOnAllDeployedVMs($SSHDetails,$command)
{
	$TestIPPOrts = $SSHDetails

	foreach ($IPPORT in $TestIPPOrts.Split("^"))
	{
		$IPPORT = $IPPORT.Split(":")
		$testIP = $IPPORT[0]
		$testPort = $IPPORT[1]
		$suppressedOut = RunLinuxCmd -ip $testIP -port $testPort -username $user -password $password -command "$command" -runAsSudo
	}
}

Function RunLinuxCmdOnRemoteVM($intermediateVM,$remoteVM, [switch] $runAsSudo, $remoteCommand, [switch]$hostnameMode, [switch]$RunInBackGround, $RunMaxAllowedTime=300)
{
#Assuming that all py scripts  will be in the remoteVM
	$newPass = ($remoteVM.password).Replace("`"","")
#RunLinuxCmd -intermediateVM -c 'RunSSHcmd.py -remoteVM'
#RunLinuxCmd -intermediateVM -c 'RemoteCopy.py' -files 'isConnected.txt'
#RemoteCopy -from intermediateVM -isConnected.txt to automation server.
#if(isConnected = true)
# {
#RunLinuxCmd -intermediateVM -c 'RemoteCopy.py' -files 'RunSSHcmd-out.txt, RunSSHcmd-err.txt'
#RemoteCopy -from intermediateVM -isConnected.txt to automation server.
# }

#Decide whether desired work is accomplished or not.. and return true or false.

#Generate the Full command that will be actually executed on intermediate VM.
	if(!$hostnameMode)
	{
		$RunSSHremoteCommand = "$python_cmd /home/$user/RunSSHCmd.py -s `'$($remoteVM.ip)`' -u $($remoteVM.user) -p`'$newPass`' -P$($remoteVM.sshPort) -c `'$remoteCommand`'"
	}
	else
	{
		$RunSSHremoteCommand = "$python_cmd /home/$user/RunSSHCmd.py -s `'$($remoteVM.Hostname)`' -u $($remoteVM.user) -p`'$newPass`' -P$($remoteVM.sshPort) -c `'$remoteCommand`'"
	}
	if($runAsSudo)
	{
		$RunSSHremoteCommand = $RunSSHremoteCommand  + " -o yes"
	}
#Write-Host $RunSSHremoteCommand
#Now Run this command..
	if ( $RunInBackGround )
	{
		$remoteOutput = RunLinuxCmd -ip $intermediateVM.ip -username $intermediateVM.user -password $intermediateVM.password -port $intermediateVM.SSHport -command $RunSSHremoteCommand -runAsSudo -RunInBackGround
	}
	else
	{
		$remoteOutput = RunLinuxCmd -ip $intermediateVM.ip -username $intermediateVM.user -password $intermediateVM.password -port $intermediateVM.SSHport -command $RunSSHremoteCommand -runAsSudo -runMaxAllowedTime $RunMaxAllowedTime
		#Write-Host $remoteOutput
		if($remoteOutput -imatch 'ExitCode : 0')
		{
			LogMsg "$remoteCommand executed successfully on $($remoteVM.ip)."
		}
		else
		{
			Write-host $remoteOutput
			Throw "Calling function - $($MyInvocation.MyCommand). $remoteCommand Failed to execute on $($remoteVM.ip)."
		}
	}
	return $remoteOutput
}

Function RemoteCopyRemoteVM($intermediateVM,$remoteVM,$remoteFiles, [switch]$upload, [switch]$download, [switch]$hostnameMode )
{
	$remoteFiles = $remoteFiles.Replace(" ","").Replace(" ","").Replace(" ","").Replace(" ","").Replace(" ","")
	$tempFiles = $remoteFiles.Split(",")
	$fileCount = $tempFiles.Length
	($remoteVM.password) = ($remoteVM.password).Replace("`"","")
	if($upload)
	{
#$allFiles = "/home/$user/azuremodules.py,/home/$user/ConfigureDnsServer.py,/home/$user/CleanupDnsServer.py,/home/$user/ConfigureResolvConf.py,/home/$user/RunSSHCmd.py,/home/$user/RemoteCopy.py"
		if($hostnameMode)
		{
			$uploadCommand = "$python_cmd RemoteCopy.py  -m upload -c `'$($remoteVM.Hostname)`' -u $($remoteVM.user) -p `'$($remoteVM.password)`' -P$($remoteVM.sshPort) -r `'/home/$user`' -f `'$remoteFiles`'"
		}
		else
		{
			$uploadCommand = "$python_cmd RemoteCopy.py  -m upload -c `'$($remoteVM.ip)`' -u $($remoteVM.user) -p `'$($remoteVM.password)`' -P$($remoteVM.sshPort) -r `'/home/$user`' -f `'$remoteFiles`'"
		}
		$remoteFiles = $remoteFiles.Replace(" ",'')
		$uploadOutput = RunLinuxCmd -ip $intermediateVM.ip -port $intermediateVM.sshPort -username $intermediateVM.user -password $intermediateVM.password -command $uploadCommand -runAsSudo
		$uploadCount = ($uploadOutput.Split("`n") -match "...OK!").Length
		LogMsg "Uploaded $uploadCount files to $($remoteVM.ip)"
		$uploadErrorCount = ($uploadOutput.Split("`n") -match "...Error!").Length

		if ($uploadErrorCount -gt 0)
		{
			LogError $uploadOutput
			Throw "Calling function - $($MyInvocation.MyCommand). Failed to upload $uploadErrorCount files to $($remoteVM.ip)"
		}
		elseif ($uploadCount -ne $fileCount)
		{
			LogError $uploadOutput
			Throw "Calling function - $($MyInvocation.MyCommand). File count doensn't match"
		}
		else
		{
			$retValue = "True"
		}
	}
	if($download)
	{
#$allFiles = "/home/$user/azuremodules.py,/home/$user/ConfigureDnsServer.py,/home/$user/CleanupDnsServer.py,/home/$user/ConfigureResolvConf.py,/home/$user/RunSSHCmd.py,/home/$user/RemoteCopy.py"
		if($hostnameMode)
		{
			$downloadCommand = "$python_cmd RemoteCopy.py  -m download -c `'$($remoteVM.Hostname)`' -u $($remoteVM.user) -p `'$($remoteVM.password)`' -P$($remoteVM.sshPort) -l `'/home/$user`' -f `'$remoteFiles`'"
		}
		else
		{
			$downloadCommand = "$python_cmd RemoteCopy.py  -m download -c `'$($remoteVM.ip)`' -u $($remoteVM.user) -p `'$($remoteVM.password)`' -P$($remoteVM.sshPort) -l `'/home/$user`' -f `'$remoteFiles`'"
		}
		$remoteFiles = $remoteFiles.Replace(" ",'')
		$downloadOutput = RunLinuxCmd -ip $intermediateVM.ip -port $intermediateVM.sshPort -username $intermediateVM.user -password $intermediateVM.password -command $downloadCommand -runAsSudo
		$downloadCount = ($downloadOutput.Split("`n") -match "...OK!").Length
		LogMsg "downloaded $downloadCount files from $($remoteVM.ip)"
		$downloadErrorCount = ($downloadOutput.Split("`n") -match "...Error!").Length
		if ($downloadErrorCount -gt 0)
		{
			LogError $downloadOutput
			Throw "Calling function - $($MyInvocation.MyCommand). Failed to download $downloadErrorCount files to $($remoteVM.ip)"
		}
		elseif ($downloadCount -ne $fileCount)
		{
			LogError $downloadOutput
			Throw "Calling function - $($MyInvocation.MyCommand). File count doensn't match"
		}
		else
		{
			$retValue = "True"
		}
	}
	return $retValue
}

Function ConfigureVNETVMs($SSHDetails,$vnetDomainDBFilePath,$dnsServerIP)
{
	UploadFilesToAllDeployedVMs -SSHDetails $SSHDetails -files ".\remote-scripts\ConfigureVnetVM.py,.\remote-scripts\azuremodules.py"
	$suppressedOut = RunLinuxCmdOnAllDeployedVMs -SSHDetails $SSHDetails -command "chmod +x /home/$user/*.py"
	$TestIPPOrts = $SSHDetails
	foreach ($IPPORT in $TestIPPOrts.Split("^"))
	{
		$IPPORT = $IPPORT.Split(":")
		$testIP = $IPPORT[0]
		$testPort = $IPPORT[1]
		LogMsg "$testIP : $testPort configuration in progress.."
		$out = RunLinuxCmd -ip $testIP -port $testPort -username $user -password $password -command "$python_cmd /home/$user/ConfigureVnetVM.py -d $dnsServerIP -D $vnetDomainDBFilePath -R /etc/resolv.conf -H /etc/hosts" -runAsSudo
		if ($out -imatch 'CONFIGURATION_SUCCESSFUL')
		{
			LogMsg $out -LinuxConsoleOuput
		}
		else
		{
			LogError $out
			Throw "Calling function - $($MyInvocation.MyCommand). $testIP : $testPort ConfigureResolvConf.py failed..."
		}

#Enable TCP MTU probing, requried for using WS2012 RRAS as VPN device
#TODO how to check the return value?
		$suppressedOut = RunLinuxCmd -ip $testIP -port $testPort -username $user -password $password -command "sh -c 'echo 1 >/proc/sys/net/ipv4/tcp_mtu_probing'" -runAsSudo

		LogMsg "$testIP : $testPort configuration finished"
	}
}

Function ConvertFileNames([switch]$ToLinux, [switch]$ToWindows, $currentWindowsFiles, $currentLinuxFiles, $expectedLinuxPath, $expectedWindowsPath)
{
	if ($ToLinux)
	{
		$remotefiles = ""
		$files = $currentWindowsFiles.Split(',')
		foreach ($newFile in $files)
		{
			$newFile = $newFile.Split("\")
			$newFileLen = $newFile.Length
			$exactFile= $newFile[$newFileLen -1]
			if(!$remotefiles)
			{
				$remotefiles = $expectedLinuxPath + "/" +$exactFile
			}
			else
			{
				$remotefiles = $remotefiles + ", $expectedLinuxPath" + "/" +$exactFile
			}
		}
		return $remotefiles
	}

	if ($ToWindows)
	{
		$remotefiles = ""
		$files = $currentLinuxFiles.Split(',')
		foreach ($newFile in $files)
		{
			$newFile = $newFile.Split("/")
			$newFileLen = $newFile.Length
			$exactFile= $newFile[$newFileLen -1]

			if(!$remotefiles)
			{
				$remotefiles = $expectedWindowsPath + "\" +$exactFile
			}
			else
			{
				$remotefiles = $remotefiles + ", $expectedWindowsPath" + "\" +$exactFile
			}
		}
		return $remotefiles
	}

}

Function VerifyDIPafterInitialDeployment($DeployedServices)
{
	$hsNames = $DeployedServices.Split('^')

	foreach ($hsName in $hsNames)
	{
		$ErrCount = 0
		$hsDetails =  Get-AzureService -ServiceName $hsName
		$VMs =  Get-AzureVM -ServiceName $hsName

		foreach ($VM in $VMs)
		{
			LogMsg "Checking : $($VM.Name)"

			$VMEndpoints = Get-AzureEndpoint -VM $VM
			$VMSSHPort = GetPort -Endpoints $VMEndpoints -usage "SSH"
			$out = RunLinuxCmd -ip $VMEndpoints[0].Vip -port $VMSSHPort -username $user -password $password -command "$ifconfig_cmd -a" -runAsSudo
			if ($out -imatch $VM.IpAddress)
			{
				LogMsg "Expected DIP : $($VM.IpAddress); Recorded DIP : $($VM.IpAddress);"
				LogMsg "$($VM.Name) has correct DIP.."
			}
			else
			{
				LogError "INCORRECT DIP DETAIL : $($VM.Name)"
				$ErrCount = $ErrCount + 1
			}
		}

		if ($ErrCount -eq 0)
		{
			$testRusult = "True"
		}
		else 
		{
			$testRusult = "False"
		}
	}
	return $testRusult
}

Function VerifyDNSServerInResolvConf($DeployedServices, $dnsServerIP)
{
	$hsNames = $DeployedServices.Split('^')

	foreach ($hsName in $hsNames)
	{
		$ErrCount = 0
		$hsDetails =  Get-AzureService -ServiceName $hsName
		$VMs =  Get-AzureVM -ServiceName $hsName

		foreach ($VM in $VMs)
		{
			LogMsg "Checking resolv.conf file of : $($VM.Name)"

			$VMEndpoints = Get-AzureEndpoint -VM $VM
			$VMSSHPort = GetPort -Endpoints $VMEndpoints -usage "SSH"
			$out = RunLinuxCmd -ip $VMEndpoints[0].Vip -port $VMSSHPort -username $user -password $password -command "cat /etc/resolv.conf" -runAsSudo
			if ($out -imatch $dnsServerIP)
			{
				LogMsg "Expected DNS IP : $dnsServerIP; Recorded DNS IP : $dnsServerIP;"
				LogMsg "$($VM.Name) has correct DNS SERVER IP.."
			}
			else
			{
				LogError "INCORRECT DNS SERVER IP : $($VM.Name)"
				$ErrCount = $ErrCount + 1
			}
		}

		if ($ErrCount -eq 0)
		{
			$testRusult = "True"
		}
		else 
		{
			$testRusult = "False"
		}
	}
	return $testRusult
}

Function RestartAllDeployments($allVMData)
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

Function ResizeAllVMs($allVMData, $newVMSize)
{
	foreach ( $vmData in $AllVMData )
	{
		if ( $UseAzureResourceManager)
		{
			$currentVM = Get-AzureRmVM -ResourceGroupName $vmData.ResourceGroupName -Name $vmData.RoleName -Verbose
            $oldSize = $currentVM.HardwareProfile.VmSize 
            $currentVM.HardwareProfile.VmSize = $newVMSize
            $resizeVM = Update-AzureRmVM -VM $currentVM -ResourceGroupName $vmData.ResourceGroupName -Verbose
			if ( $resizeVM.StatusCode -eq "OK" )
			{
				LogMsg "Resized $($vmData.RoleName) from $oldSize --> $newVMSize : $($vmData.RoleName)"
			}
			else
			{
				LogError "FAILED TO RESIZE : $($vmData.RoleName)"
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
		else
		{
            #TBD
		}
	}
	$isSSHOpened = isAllSSHPortsEnabledRG -AllVMDataObject $AllVMData
	return $isSSHOpened
}


Function StopAllDeployments($DeployedServices)
{
	$hsNames = $DeployedServices.Split('^')

	foreach ($hsName in $hsNames)
	{
		$ErrCount = 0
		$hsDetails =  Get-AzureService -ServiceName $hsName
		$VMs =  Get-AzureVM -ServiceName $hsName

		foreach ($VM in $VMs)
		{
			$isStopped = ""
			$retryCount = 3
			While(($retryCount -gt 0) -and !($isStopped))
			{
				LogMsg "Stopping : $($VM.Name)"
				$out = Stop-AzureVM -ServiceName $hsName -Name $VM.Name -StayProvisioned -Force
				$isStopped = $?
				if ($isStopped)
				{
					LogMsg "Stopped : $($VM.Name)"
					$retValue = $true
				}
				else
				{
					LogError "FAILED TO STOP : $($VM.Name)"
					$retryCount = $retryCount + 1
					if ($retryCount -gt 0)
					{
						LogMsg "Retrying..."
					}
					if ($retryCount -eq 0)
					{
						$retValue = $false
						Throw "Calling function - $($MyInvocation.MyCommand). Unable to Restart : $($VM.Name)"
					}
				}
			}
		}
	}
	return $retValue
}

Function StartAllDeployments($DeployedServices)
{
	$hsNames = $DeployedServices.Split('^')

	foreach ($hsName in $hsNames)
	{
		$ErrCount = 0
		$hsDetails =  Get-AzureService -ServiceName $hsName
		$VMs =  Get-AzureVM -ServiceName $hsName

		foreach ($VM in $VMs)
		{
			$isRestarted = ""
			$retryCount = 3
			While(($retryCount -gt 0) -and !($isRestarted))
			{
				LogMsg "Starting : $($VM.Name)"
				$out = Start-AzureVM -ServiceName $hsName -Name $VM.Name
				$isRestarted = $?
				if ($isRestarted)
				{
					LogMsg "Started : $($VM.Name)"
				}
				else
				{
					LogError "FAILED TO START : $($VM.Name)"
					$retryCount = $retryCount + 1
					if ($retryCount -gt 0)
					{
						LogMsg "Retrying..."
					}
					if ($retryCount -eq 0)
					{
						Throw "Calling function - $($MyInvocation.MyCommand). Unable to Start : $($VM.Name)"
					}
				}
			}
		}
	}

	$isAllVerified = VerifyAllDeployments -servicesToVerify $hsNames
	if ($isAllVerified -eq "True")
	{
		$isAllConnected = isAllSSHPortsEnabled -DeployedServices $deployedServices
		if ($isAllConnected -eq "True")
		{
#Set-Content .\temp\DeployedServicesFile.txt "$deployedServices"
			$retValue = "True"
		}
		else
		{
			LogError "Unable to connect Some/All SSH ports.."
			$retValue = "False"  
		}
	}
	else
	{
		LogError "Provision Failed for one or more VMs"
		$retValue = "False"
	}

	return $retValue
}

Function Get-IPV4NetworkStartIP ($IpAddressCIDR)
{
#source = http://blog.tyang.org/2011/05/01/powershell-functions-get-ipv4-network-start-and-end-address/

	$StrNetworkAddress = ($IpAddressCIDR.split("/"))[0]
	$NetworkIP = ([System.Net.IPAddress]$StrNetworkAddress).GetAddressBytes()
	[Array]::Reverse($NetworkIP)
	$NetworkIP = ([System.Net.IPAddress]($NetworkIP -join ".")).Address
	$StartIP = $NetworkIP + 0
#Convert To Double
	If (($StartIP.Gettype()).Name -ine "double")
	{
		$StartIP = [Convert]::ToDouble($StartIP)
	}
	$StartIP = [System.Net.IPAddress]$StartIP
	Return $StartIP
}

Function Get-IPV4NetworkEndIP ($IpAddressCIDR)
{
#source = http://blog.tyang.org/2011/05/01/powershell-functions-get-ipv4-network-start-and-end-address/

	$StrNetworkAddress = ($IpAddressCIDR.split("/"))[0]
	[int]$NetworkLength = ($IpAddressCIDR.split("/"))[1]
	$IPLength = 32-$NetworkLength
	$NumberOfIPs = ([System.Math]::Pow(2, $IPLength)) -1
	$NetworkIP = ([System.Net.IPAddress]$StrNetworkAddress).GetAddressBytes()
	[Array]::Reverse($NetworkIP)
	$NetworkIP = ([System.Net.IPAddress]($NetworkIP -join ".")).Address
	$EndIP = $NetworkIP + $NumberOfIPs
	If (($EndIP.Gettype()).Name -ine "double")
	{
		$EndIP = [Convert]::ToDouble($EndIP)
	}
	$EndIP = [System.Net.IPAddress]$EndIP
	Return $EndIP
}

Function Get-IPV4NetworkRange($IpAddressCIDR)
{
	$startIP = Get-IPV4NetworkStartIP -IpAddressCIDR $IpAddressCIDR
	$EndIP = Get-IPV4NetworkEndIP -IpAddressCIDR $IpAddressCIDR
	$ipStream = ''
# created by Dr. Tobias Weltner, MVP PowerShell source = http://ficility.net/tag/ip-address-powershell/
	$ip1 = ([System.Net.IPAddress]$startIP).GetAddressBytes()
	[Array]::Reverse($ip1)
	$ip1 = ([System.Net.IPAddress]($ip1 -join '.')).Address
	$ip2 = ([System.Net.IPAddress]$EndIP).GetAddressBytes()
	[Array]::Reverse($ip2)
	$ip2 = ([System.Net.IPAddress]($ip2 -join '.')).Address
	for ($x=$ip1; $x -le $ip2; $x++) 
	{
		$ip = ([System.Net.IPAddress]$x).GetAddressBytes()
		[Array]::Reverse($ip)
		$ip = $ip -join '.'
		$ipStr = $ip.ToString()
		if(!$ipStream)
		{
			$ipStream = $ipStr
		}
		else
		{
			$ipStream = $ipStream + "^" + $ipStr
		}
	}
	return $ipStream
}

Function DetectSubnet($inputString,$subnet1CIDR,$subnet2CIDR)
{

	$subnet1Range = Get-IPV4NetworkRange -IpAddressCIDR $subnet1CIDR
	$subnet2Range = Get-IPV4NetworkRange -IpAddressCIDR $subnet2CIDR

	$subnet1Range = $subnet1Range.split('^')
	$subnet2Range = $subnet2Range.split('^')

	$isDetected = 'False'

	if ($isDetected = "false")
	{
		foreach ($IP in $subnet1Range)
		{
			if ($inputString -imatch $IP)
			{
				$isDetected = "True"
				$detectedSubnet = "subnet1"
				break
			}
		}
	}
	if ($isDetected = "false")
	{
		foreach ($IP in $subnet2Range)
		{
			if ($inputString -imatch $IP)
			{
				$isDetected = "True"
				$detectedSubnet = "subnet2"
				break
			}
		}
	}
	return $detectedSubnet
}

Function VerifyGatewayVMsInHostedService($DeployedServices)
{
	$hsNames = $DeployedServices.Split('^')

	foreach ($hsName in $hsNames)
	{
		$ErrCount = 0
		$hsDetails =  Get-AzureService -ServiceName $hsName
		$VMs =  Get-AzureVM -ServiceName $hsName

		foreach ($VM in $VMs)
		{
			LogMsg "Checking Gateway : $($VM.Name)"

			$VMEndpoints = Get-AzureEndpoint -VM $VM
			$VMSSHPort = GetPort -Endpoints $VMEndpoints -usage "SSH"
			$currentVMGateway = RunLinuxCmd -ip $VMEndpoints[0].Vip -port $VMSSHPort -username $user -password $password -command "route" -runAsSudo
			$currentVMDIP = $VM.IpAddress
			$currentVMDIPSubnet = DetectSubnet -inputString $currentVMDIP
			$currentVMGatewaySubnet = DetectSubnet -inputString $currentVMGateway
			LogMsg "DIP subnet subnet detected : $currentVMDIPSubnet"
			LogMsg "Gateway subnet detected	: $currentVMGatewaySubnet"

			if ($currentVMDIPSubnet -eq $currentVMGatewaySubnet)
			{
				LogMsg "PASS"
			}
			else
			{
				LogError "FAIL"
				$ErrCount = $ErrCount + 1
			}
		}

		if ($ErrCount -eq 0)
		{
			$testRusult = "True"
		}
		else 
		{
			$testRusult = "False"
		}
	}
	return $testRusult
}

Function DoSSHTest($fromVM, $toVM, $command, [switch]$runAsSudo, [switch]$hostnameMode)
{
	if($runAsSudo)
	{
		if($hostnameMode)
		{
			$sshOutput = RunLinuxCmdOnRemoteVM -intermediateVM $fromVM -remoteVM $toVM -remoteCommand $command -runAsSudo -hostnameMode
		}
		else
		{
			$sshOutput = RunLinuxCmdOnRemoteVM -intermediateVM $fromVM -remoteVM $toVM -remoteCommand $command -runAsSudo 
		}
	}
	else
	{
		if($hostnameMode)
		{
			$sshOutput = RunLinuxCmdOnRemoteVM -intermediateVM $fromVM -remoteVM $toVM -remoteCommand $command -hostnameMode
		}
		else
		{
			$sshOutput = RunLinuxCmdOnRemoteVM -intermediateVM $fromVM -remoteVM $toVM -remoteCommand $command
		}
	}
#Write-host "Printing output"

#Write-Host "$sshOutput"
	if ($sshOutput -imatch "ExitCode : 0")
	{
		return "PASS"
	}
	else
	{
		return "FAIL"
	}
}

Function DoSCPTest($fromVM, $toVM, $filesToCopy, [switch]$hostnameMode)
{
	if($hostnameMode)
	{
		$scpUpload = RemoteCopyRemoteVM -intermediateVM $fromVM -remoteVM $toVM -remoteFiles $filesToCopy -upload -hostnameMode
#Write-Host $scpUpload
	}
	else
	{
		$scpUpload = RemoteCopyRemoteVM -intermediateVM $fromVM -remoteVM $toVM -remoteFiles $filesToCopy -upload
#Write-Host $scpUpload
	}

	if(($scpUpload -eq "True"))
	{
		return "PASS"
	}
	else
	{
		return "FAIL"
	}
}

Function RunMysqlCmd ($intermediateVM, $mysqlServer, $MysqlUsername, $MysqlPassword, $mysqlCommand, [switch]$HostnameMode)
{
	if($HostnameMode)

	{
		$mysqlOutput = RunLinuxCmd -username $intermediateVM.user -password $intermediateVM.password -ip $intermediateVM.ip -port $intermediateVM.sshPort -command "mysql -u`'$MysqlUsername`' -p`'$MysqlPassword`' -h `'$($mysqlServer.hostname)`' -e `'$mysqlCommand`'" -runAsSudo
	}
	else
	{
		$mysqlOutput = RunLinuxCmd -username $intermediateVM.user -password $intermediateVM.password -ip $intermediateVM.ip -port $intermediateVM.sshPort -command "mysql -u`'$MysqlUsername`' -p`'$MysqlPassword`' -h`'$($mysqlServer.ip)`' -e `'$mysqlCommand`'" -runAsSudo

	}
	return $mysqlOutput
}

Function DoMysqlAccessTest ($fromVM, $mysqlServer, $MysqlUsername, $MysqlPassword, [switch]$HostnameMode)
{
	try
	{
		if($HostnameMode)
		{
			$mysqlOutput = RunMysqlCmd -intermediateVM $fromVM -mysqlServer $mysqlServer -MysqlUsername $MysqlUsername -MysqlPassword $MysqlPassword -mysqlCommand "\s" -HostnameMode
		}
		else
		{
			$mysqlOutput = RunMysqlCmd -intermediateVM $fromVM -mysqlServer $mysqlServer -MysqlUsername $MysqlUsername -MysqlPassword $MysqlPassword -mysqlCommand "\s"
		}
		if ($mysqlOutput -imatch "TCP/IP")
		{
			$retValue = "PASS"
		}
		else
		{
			$retValue = "FAIL"
		}
	}
	catch
	{
		$retValue = "FAIL"
	}
	$logfilepath  = "$($FromVM.LogDir)\mysqlOutput.log"
	Set-Content -Path $logfilepath -Value $mysqlOutput
	return $retValue
}

Function DoMysqlOperationsTest ($fromVM, $mysqlServer, $MysqlUsername, $MysqlPassword, [switch]$HostnameMode)
{
	$logfilepath  = "$($FromVM.LogDir)\mysqlOutput.log"

	$mySqlOperations = @()
	$mySqlOperations = $mySqlOperations + "use test;"
	$mySqlOperations = $mySqlOperations + "CREATE TABLE IF NOT EXISTS products (productID	INT UNSIGNED  NOT NULL AUTO_INCREMENT,productCode  CHAR(3)	   NOT NULL DEFAULT `"`",name		 VARCHAR(30)   NOT NULL DEFAULT `"`",quantity	 INT UNSIGNED  NOT NULL DEFAULT 0,price		DECIMAL(7,2)  NOT NULL DEFAULT 99999.99,PRIMARY KEY  (productID));"
	$mySqlOperations = $mySqlOperations + "SHOW TABLES;"
	$mySqlOperations = $mySqlOperations + "DESCRIBE products;"
	$mySqlOperations = $mySqlOperations + "INSERT INTO products VALUES (1001, `"PEN`", `"Pen Red`", 5000, 1.23);"
	$mySqlOperations = $mySqlOperations + "INSERT INTO products VALUES (NULL, `"PEN`", `"Pen Blue`",  8000, 1.25),(NULL, `"PEN`", `"Pen Black`", 2000, 1.25);"
	$mySqlOperations = $mySqlOperations + "INSERT INTO products (productCode, name, quantity, price) VALUES (`"PEC`", `"Pencil 2B`", 10000, 0.48), (`"PEC`", `"Pencil 2H`", 8000, 0.49);"
	$mySqlOperations = $mySqlOperations + "SELECT * FROM products;"
	$mySqlOperations = $mySqlOperations + "DELETE FROM products;"
	$mySqlOperations = $mySqlOperations + "SHOW TABLES;"
	$mySqlOperations = $mySqlOperations + "DROP TABLE products;"
	$allOperations = ''
	foreach ($mysqlCommand in $mySqlOperations)
	{
		$allOperations = "use test; SHOW TABLES; SHOW DATABASES; describe products"
	}
	$allOperations =  $allOperations 
	if($HostnameMode)
	{
		Add-Content -Path $logfilepath -Value "Executing : $allOperations"
		$mysqlOutput = RunMysqlCmd -intermediateVM $fromVM -mysqlServer $mysqlServer -MysqlUsername $MysqlUsername -MysqlPassword $MysqlPassword -mysqlCommand $allOperations -HostnameMode
		set-Content -Path $logfilepath -Value "$mysqlOutput"
	}
	else
	{
		Add-Content -Path $logfilepath -Value "Executing : $allOperations"
		$mysqlOutput = RunMysqlCmd -intermediateVM $fromVM -mysqlServer $mysqlServer -MysqlUsername $MysqlUsername -MysqlPassword $MysqlPassword -mysqlCommand $allOperations
		set-Content -Path $logfilepath -Value "$mysqlOutput"
	}

	$CompleteMysqlOutput = Get-Content -Path $logfilepath
	if ($CompleteMysqlOutput -imatch "Error")
	{
		$retValue = "FAIL"
	}
	else
	{
		$retValue = "PASS"
	}
	return $retValue
}

Function DoNfsShareAccessTest ($fromVM, $nfsServer, $nfsServerDirctory, [switch]$HostnameMode)
{
	try
	{
		if($HostnameMode)
		{
			LogMsg "Mounting $($nfsServer.Hostname):$nfsServerDirctory to home directory .."
			$suppressedOut = RunLinuxCmd -ip $fromVM.ip -port $fromVM.sshport -username $fromVM.user -password $fromVM.password -command "mount $($nfsServer.Hostname):$nfsServerDirctory ~" -runAsSudo 
			LogMsg "Unmounting.."
			$suppressedOut = RunLinuxCmd -ip $fromVM.ip -port $fromVM.sshport -username $fromVM.user -password $fromVM.password -command "umount ~ -lf" -runAsSudo
																																											$retValue = "PASS"
		}

		else
		{
			LogMsg "Mounting $($nfsServer.ip):$nfsServerDirctory to home directory .."
			$suppressedOut = RunLinuxCmd -ip $fromVM.ip -port $fromVM.sshport -username $fromVM.user -password $fromVM.password -command "mount $($nfsServer.ip):$nfsServerDirctory ~" -runAsSudo																								LogMsg "Unmounting.."
			$suppressedOut = RunLinuxCmd -ip $fromVM.ip -port $fromVM.sshport -username $fromVM.user -password $fromVM.password -command "umount ~ -lf" -runAsSudo
			$retValue = "PASS"
		}
	}
	catch
	{
		LogError "Failed."
		$retValue = "FAIL"
	}
	return $retValue
}

Function DoNfsShareFileTranferTest ($fromVM, $nfsServer, $nfsServerDirctory, [switch]$HostnameMode)
{
	$logfilepath = "$($fromVM.LogDir)\nfsFileCreate.log"
	try
	{
		if($HostnameMode)
		{
			LogMsg "Mounting $($nfsServer.Hostname):$nfsServerDirctory to home directory .."
			$output = RunLinuxCmd -ip $fromVM.ip -port $fromVM.sshport -username $fromVM.user -password $fromVM.password -command "mount $($nfsServer.Hostname):$nfsServerDirctory ~" -runAsSudo 2>&1 
		}

		else
		{
			LogMsg "Mounting $($nfsServer.ip):$nfsServerDirctory to home directory .."
			$output =  RunLinuxCmd -ip $fromVM.ip -port $fromVM.sshport -username $fromVM.user -password $fromVM.password -command "mount $($nfsServer.ip):$nfsServerDirctory ~" -runAsSudo 2>&1 
		}
		LogMsg "Tranferring 1MB data.."
		$suppressedOut = RunLinuxCmd -ip $fromVM.ip -port $fromVM.sshport -username $fromVM.user -password $fromVM.password -command "dd if=/dev/zero of=~/testfile bs=1M count=1" -runAsSudo
		LogMsg "Unmounting.."
		$suppressedOut = RunLinuxCmd -ip $fromVM.ip -port $fromVM.sshport -username $fromVM.user -password $fromVM.password -command "umount ~ -lf" -runAsSudo
		$retValue = "PASS"
	}
	catch
	{
		LogError "Failed."
		$retValue = "FAIL"
	}
	return $retValue
}

Function DoSSHTestFromLocalVM($intermediateVM, $LocalVM, $toVM,[switch]$hostnameMode)
{

	if($hostnameMode)
	{
		LogMsg "Executing - date - command on $($toVM.Hostname) .."
		$sshOutput = RunLinuxCmd -username $intermediateVM.user -password $intermediateVM.password -ip $intermediateVM.ip -port $intermediateVM.sshport -runAsSudo -command "$python_cmd /home/$user/RunSSHCmd.py -s `'$($LocalVM.ip)`' -u $($LocalVM.user) -p`'$($LocalVM.password)`' -P $($LocalVM.sshPort) -c `'echo $($LocalVM.password) | sudo -S python /home/$user/RunSSHCmd.py -s `"$($toVM.hostname)`" -u $user -p $($toVM.password)  -P 22 -c `"date`" -o yes`'"

	}
	else
	{
		LogMsg "Executing - date - command on $($toVM.DIP) .."
		$sshOutput = RunLinuxCmd -username $intermediateVM.user -password $intermediateVM.password -ip $intermediateVM.ip -port $intermediateVM.sshport -runAsSudo -command "$python_cmd /home/$user/RunSSHCmd.py -s `'$($LocalVM.ip)`' -u $($LocalVM.user) -p`'$($LocalVM.password)`' -P $($LocalVM.sshPort) -c `'echo $($LocalVM.password) | sudo -S python /home/$user/RunSSHCmd.py -s `"$($toVM.dip)`" -u $user -p $($toVM.password)  -P 22 -c `"date`" -o yes`'"
	}
	LogMsg "Verifying output.."
	$logfilepath = $toVM.logDir + "\sshOutput.log"
	LogMsg "Writing output to $logfilepath ..."
	Set-Content -Path $logfilepath -Value $sshOutput
#Write-host "Printing output"

#Write-Host "$sshOutput"
	if ($sshOutput -imatch (Get-Date).Year)
	{
		return "PASS"
	}
	else
	{
		return "FAIL"
	}
}

Function DoSCPTestFromLocalVM( $intermediateVM, $LocalVM, $toVM, [switch]$hostnameMode)
{
	$logFilepath = $toVM.logDir + "\scpOutput.log"
	LogMsg "Creating 1MB file on local VM..."
	$out = RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $LocalVM -remoteCommand "`'dd\ if=/dev/zero\ of=/home/$user/testfile\ bs=1M\ count=1`'" -runAsSudo

	if($hostnameMode)
	{
		LogMsg "File Created. Now copying it to $($toVM.Hostname) ..."
		$scpOutput = RunLinuxCmd -username $intermediateVM.user -password $intermediateVM.password -ip $intermediateVM.ip -port $intermediateVM.sshport -runAsSudo -command "$python_cmd /home/$user/RunSSHCmd.py -s `'$($LocalVM.ip)`' -u $($LocalVM.user) -p`'$($LocalVM.password)`' -P $($LocalVM.sshPort) -c `'echo $($LocalVM.password) | sudo -S python /home/$user/RemoteCopy.py -c `"$($toVM.Hostname)`" -m upload -u `"$($toVM.user)`" -p $($toVM.password) -P 22 -r `"/home/$user`" -f `"/home/$user/testfile`"`'"
	}
	else
	{
		LogMsg "File Created. Now copying it to $($toVM.DIP) ..."
		$scpOutput = RunLinuxCmd -username $intermediateVM.user -password $intermediateVM.password -ip $intermediateVM.ip -port $intermediateVM.sshport -runAsSudo -command "$python_cmd /home/$user/RunSSHCmd.py -s `'$($LocalVM.ip)`' -u $($LocalVM.user) -p`'$($LocalVM.password)`' -P $($LocalVM.sshPort) -c `'echo $($LocalVM.password) | sudo -S python /home/$user/RemoteCopy.py -c `"$($toVM.DIP)`" -m upload -u `"$($toVM.user)`" -p $($toVM.password) -P 22 -r `"/home/$user`" -f `"/home/$user/testfile`"`'"
	}
	LogMsg "Writing output to $logfilepath ..."
	Set-Content -Path $logFilepath -Value $scpOutput

	if(($scpOutput -imatch "OK!") -and ($scpOutput -imatch "Connected"))
	{
		LogMsg "File transferred successfully."
		return "PASS"
	}
	else
	{
		return "FAIL"
	}
}

Function StartIperfServerOnRemoteVM($remoteVM, $intermediateVM, $expectedServerInstances=1 )
{
	#$NewremoteVMcmd = ($remoteVM.cmd).Replace(" ","\ ")
	$NewremoteVMcmd = $remoteVM.cmd
	Write-Host $NewremoteVMcmd 
	LogMsg "Deleting any previous server logs ..."
	$DeletePreviousLogs = RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $remoteVM -remoteCommand "rm -rf /home/$($remoteVM.User)/*.txt /home/$($remoteVM.User)/*.log" -runAsSudo
	$CommandOutput = RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $remoteVM -remoteCommand $NewremoteVMcmd -runAsSudo -RunInBackGround
	LogMsg "Checking if server started successfully or not ..."
	$isServerStarted = RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $remoteVM -remoteCommand "ps -ef | grep iperf -s | grep -v grep | wc -l" -runAsSudo
    $outlist = $isServerStarted.Split("`n")
    $index_value_seek = $outlist.IndexOf("OutputStart") + 1
	$isServerStarted = [int]$outlist[$index_value_seek]
	LogMsg "Total iperf server running instances : $($isServerStarted)"
	if($isServerStarted -ge $expectedServerInstances)
	{
		LogMsg "Server started successfully ..."
		$retValue = "True"
	}
	else
	{
		$retValue = "False"
		LogError "Server Failed to start ..."
	}

	<#if(($isServerStarted -imatch "yes") -and ($CommandOutput -imatch "ExitCode : 0"))
	{
		LogMsg "Server started successfully ..."
		$retValue = "True"
	}
	else
	{
		$retValue = "False"
		LogError "Server Failed to start ..."
	}#>
	return $retValue
}

Function StartIperfClientOnRemoteVM($remoteVM, $intermediateVM)
{
	#$NewremoteVMcmd = ($remoteVM.cmd).Replace(" ","\ ")
	$NewremoteVMcmd = $remoteVM.cmd
	Write-Host $NewremoteVMcmd 
	LogMsg "Deleting any previous client logs ..."
	$DeletePreviousLogs = RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $remoteVM -remoteCommand "rm -rf /home/$($remoteVM.User)/*.txt /home/$($remoteVM.User)/*.log" -runAsSudo
	$CommandOutput = RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $remoteVM -remoteCommand $NewremoteVMcmd -runAsSudo
	LogMsg "Checking if client connected successfully or not ..."

	$DeletePreviousLogs = RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $remoteVM -remoteCommand "cp /home/$($remoteVM.User)/Runtime.log /home/$($remoteVM.User)/start-client.py.log" -runAsSudo

	Set-Content -Value (RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $remoteVM -remoteCommand "cat /home/$($remoteVM.User)/start-client.py.log" -runAsSudo -RunMaxAllowedTime 60) -Path ("$($remoteVM.logDir)" + "\start-client.py.log")
	Set-Content -Value (RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $remoteVM -remoteCommand "cat /home/$($remoteVM.User)/state.txt" -runAsSudo -RunMaxAllowedTime 60 ) -Path ("$($remoteVM.logDir)" + "\state.txt")
	Set-Content -Value (RunLinuxCmdOnRemoteVM -intermediateVM $intermediateVM -remoteVM $remoteVM -remoteCommand "cat /home/$($remoteVM.User)/Summary.log" -runAsSudo -RunMaxAllowedTime 60 ) -Path ("$($remoteVM.logDir)" + "\Summary.log")


	$clientState = Get-Content "$($remoteVM.Logdir)\state.txt"
	$clientSummary = Get-Content "$($remoteVM.Logdir)\Summary.log"
	Write-Host $clientState 
	Write-Host $clientSummary
#>>>Remove Temporary files..
	Remove-Item "$($remoteVM.Logdir)\state.txt" -Force
	Remove-Item "$($remoteVM.Logdir)\Summary.log" -Force
	if($clientState -imatch "TestCompleted" -and $clientSummary -imatch "PASS")
	{
		return $true
	}
	else
	{
		return $false
	}
}

Function IperfLocalToVNETUdpTest ($vnetAsServer, $localAsClient, $intermediateVM)
{
	LogMsg "Removing any previous Server logs.."
	$suppressedOut = RunLinuxCmd -username $vnetAsServer.user -password $vnetAsServer.password -ip $vnetAsServer.ip -port $vnetAsServer.sshPort -command "rm -rf *.txt *.log"  -runAsSudo
	StartIperfServer -node $vnetAsServer
	$isServerStarted = IsIperfServerStarted -node $vnetAsServer
	if($isServerStarted -eq $true)
	{
		LogMsg "Starting iperf client ..."
		$isClientConnected = StartIperfClientOnRemoteVM -remoteVM $localAsClient -intermediateVM $intermediateVM

		if ($isClientConnected -eq $true)
		{
			LogMsg "Checking if server received connections from client of not ..."
			$checkServer = IsIperfServerRunning -node $vnetAsServer
			if($checkServer -eq $true)
			{
				LogMsg "Server was successfully connected to client.."
				$retValue = "PASS"
			}
			else
			{
				LogMsg "Failures detected on server .."
				$retValue = "FAIL"
			}
		}
		else
		{
			LogError "Client failed to connect to server..."
			$retValue = "Fail"
		}
	}
	else
	{
		LogError "Failed to start iperf server."
		$retValue = "Fail"
	}
	return $retValue
}

Function IperfVnetToLocalUdpTest ($vnetAsClient, $localAsServer)
{

	$isServerStarted = StartIperfServerOnRemoteVM -remoteVM $localAsServer -intermediateVM $vnetAsClient
	if($isServerStarted -eq "True")
	{
		LogMsg "Starting iperf client ..."
		LogMsg "Removing any previous client logs.."
		$suppressedOut = RunLinuxCmd -username $vnetAsClient.user -password $vnetAsClient.password -ip $vnetAsClient.ip -port $vnetAsClient.sshPort -command "rm -rf *.txt *.log"  -runAsSudo
		StartIperfClient -node $vnetAsClient
		$isClientConnected = IsIperfClientStarted -node $vnetAsClient
		if ($isClientConnected -eq $true)
		{
			LogMsg "Checking if server received connections from client of not ..."
			$temp = RunLinuxCmdOnRemoteVM -intermediateVM $vnetAsClient -remoteVM $localAsServer -runAsSudo -remoteCommand "cp /home/$($localAsServer.user)/iperf-server.txt /home/$user/"
			$checkServer = RunLinuxCmdOnRemoteVM -intermediateVM $vnetAsClient -remoteVM $localAsServer -runAsSudo -remoteCommand "/home/$user/check-server.py"
			$checkServerSummary = RunLinuxCmdOnRemoteVM -intermediateVM $vnetAsClient -remoteVM $localAsServer -runAsSudo -remoteCommand "cat ~/Summary.log"		
			if($checkServerSummary -imatch "PASS")
			{
				LogMsg "Server was successfully connected to client.."
				$retValue = "PASS"
			}
			else
			{
				LogMsg "Failures detected on server .."
				$retValue = "FAIL"
			}
		}
		else
		{
			LogError "Client failed to connect to server..."
			$retValue = "Fail"
		}
	}
	else
	{
		LogError "Failed to start iperf server."
		$retValue = "Fail"
	}
	return $retValue
}
#endregion

#region E2E Feature Tests Methods

Function GetTotalPhysicalDisks($FdiskOutput)
{
	$physicalDiskNames = ("sda","sdb","sdc","sdd","sde","sdf","sdg","sdh","sdi","sdj","sdk","sdl","sdm","sdn",
			"sdo","sdp","sdq","sdr","sds","sdt","sdu","sdv","sdw","sdx","sdy","sdz", "sdaa", "sdab", "sdac", "sdad","sdae", "sdaf", "sdag", "sdah", "sdai")
	$diskCount = 0
	foreach ($physicalDiskName in $physicalDiskNames)
	{
		if ($FdiskOutput -imatch "Disk /dev/$physicalDiskName")
		{
			$diskCount += 1
		}
	}
	return $diskCount
}

Function GetNewPhysicalDiskNames($FdiskOutputBeforeAddingDisk, $FdiskOutputAfterAddingDisk)
{
	$availableDisksBeforeAddingDisk = ""
	$availableDisksAfterAddingDisk = ""
	$physicalDiskNames = ("sda","sdb","sdc","sdd","sde","sdf","sdg","sdh","sdi","sdj","sdk","sdl","sdm","sdn",
			"sdo","sdp","sdq","sdr","sds","sdt","sdu","sdv","sdw","sdx","sdy","sdz", "sdaa", "sdab", "sdac", "sdad","sdae", "sdaf", "sdag", "sdah", "sdai")
	foreach ($physicalDiskName in $physicalDiskNames)
	{
		if ($FdiskOutputBeforeAddingDisk -imatch "Disk /dev/$physicalDiskName")
		{
			if ( $availableDisksBeforeAddingDisk -eq "" )
			{
				$availableDisksBeforeAddingDisk = "/dev/$physicalDiskName"
			}
			else
			{
				$availableDisksBeforeAddingDisk = $availableDisksBeforeAddingDisk + "^" + "/dev/$physicalDiskName"
			}
		}
	}
	foreach ($physicalDiskName in $physicalDiskNames)
	{
		if ($FdiskOutputAfterAddingDisk -imatch "Disk /dev/$physicalDiskName")
		{
			if ( $availableDisksAfterAddingDisk -eq "" )
			{
				$availableDisksAfterAddingDisk = "/dev/$physicalDiskName"
			}
			else
			{
				$availableDisksAfterAddingDisk = $availableDisksAfterAddingDisk + "^" + "/dev/$physicalDiskName"
			}
		}
	}
	$newDisks = ""
	foreach ($afterDisk in $availableDisksAfterAddingDisk.Split("^"))
	{
		if($availableDisksBeforeAddingDisk -imatch $afterDisk)
		{

		}
		else
		{
			if($newDisks -eq "")
			{
				$newDisks = $afterDisk
			}
			else
			{
				$newDisks = $newDisks + "^" + $afterDisk
			}
		}
	}
	return $newDisks
}
Function CreateHotAddRemoveDataDiskNode
{
	param(
			[string] $ServiceName,
			[string] $nodeIp,
			[string] $nodeSshPort,
			[string] $user,
			[string] $password,
			[string] $files,
			[int] $Lun,
			[string] $InstanceSize,
			[string] $ExistingDiskMediaLink,
			$allExistingDisks,
			[string] $logDir)

	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name ServiceName -Value $ServiceName -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name ip -Value $nodeIp -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name sshPort -Value $nodeSshPort -Force 
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name user -Value $user -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name password -Value $password -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name files -Value $files -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name logDir -Value $LogDir -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name Lun -Value $Lun -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name InstanceSize -Value $InstanceSize -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name AttachedDisks -Value @() -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name ExistingDiskMediaLink -Value $ExistingDiskMediaLink -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name allExistingDisks -Value $allExistingDisks -Force
	return $objNode
}

Function PerformIOTestOnDisk($testVMObject, [string]$attachedDisk, [string]$diskFileSystem)
{
	$retValue = "Aborted"
   	$testVMSSHport = $testVMObject.sshPort
	$testVMVIP = $testVMObject.ip
	$testVMUsername = $testVMObject.user 
	$testVMPassword = $testVMObject.password
	if ( $diskFileSystem -imatch "xfs" )
	{
		 $diskFileSystem = "xfs -f"
	}
	$isVMAlive = Test-TCP -testIP $testVMVIP -testport $testVMSSHport
	if ($isVMAlive -eq "True")
	{
		$retValue = "FAIL"
		$mountPoint = "/mnt/datadisk"
		LogMsg "Performing I/O operations on $attachedDisk.."
		$LogPath = "$LogDir\VerifyIO$($attachedDisk.Replace('/','-')).txt"
		$dmesgBefore = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "dmesg" -runMaxAllowedTime 30 -runAsSudo
		#CREATE A MOUNT DIRECTORY
		$out = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "mkdir -p $mountPoint" -runAsSudo 
		$partitionNumber=1
		$PartitionDiskOut = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "./ManagePartitionOnDisk.sh -diskName $attachedDisk -create yes -forRaid no" -runAsSudo 
		$FormatDiskOut = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "time mkfs.$diskFileSystem $attachedDisk$partitionNumber" -runAsSudo -runMaxAllowedTime 2400 
		$out = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "mount -o nobarrier $attachedDisk$partitionNumber $mountPoint" -runAsSudo 
		Add-Content -Value $formatDiskOut -Path $LogPath -Force
		$ddOut = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "dd if=/dev/zero bs=1024 count=1000000 of=$mountPoint/file_1GB" -runAsSudo -runMaxAllowedTime 1200
		WaitFor -seconds 10
		Add-Content -Value $ddOut -Path $LogPath
		try
		{
			$out = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "umount $mountPoint" -runAsSudo 
		}
		catch
		{
			LogMsg "umount failed. Trying umount -l"
			$out = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "umount -l $mountPoint" -runAsSudo 
		}
		$dmesgAfter = RunLinuxCmd -username $testVMUsername -password $testVMPassword -ip $testVMVIP -port $testVMSSHport -command "dmesg" -runMaxAllowedTime 30 -runAsSudo
		$addedLines = $dmesgAfter.Replace($dmesgBefore,$null)
		LogMsg "Kernel Logs : $($addedLines.Replace('[32m','').Replace('[0m[33m','').Replace('[0m',''))" -LinuxConsoleOuput
		$retValue = "PASS"	
	}
	else
	{
		LogError "VM is not Alive."
		LogError "Aborting Test."
		$retValue = "Aborted"
	}
	return $retValue
}
Function DoHotAddNewDataDiskTest ($testVMObject, [int]$diskSizeInGB )
{
	
	$testVMSSHport = $testVMObject.sshPort
	$testVMVIP = $testVMObject.ip
	$testVMServiceName = $testVMObject.ServiceName
	$testVMUsername = $testVMObject.user 
	$testVMPassword = $testVMObject.password
	$testLun = $testVMObject.Lun
	$HotAddLogFile = "$($testVMObject.logDir)\Hot-Add-Disk.log"
	$isVMAlive = Test-TCP -testIP $testVMVIP -testport $testVMSSHport
	$retValue = "ABORTED"
	if ($isVMAlive -eq "True")
	{
		Add-Content  -Value "--------------------ADD DISK TO LUN $testLun : START----------------------" -Path $HotAddLogFile -Encoding UTF8
#GetCurrentDiskInfo

		$fdiskOutputBeforeAddingDisk = RunLinuxCmd -username $testVMUsername -password $testVMpassword -ip $testVMVIP -port $testVMSSHport -command "$fdisk -l" -runAsSudo
		Add-Content  -Value "Before Adding New Disk : " -Path $HotAddLogFile -Encoding UTF8
		Add-Content  -Value $fdiskOutputBeforeAddingDisk -Path $HotAddLogFile -Encoding UTF8
		$disksBeforeAddingNewDisk = GetTotalPhysicalDisks -FdiskOutput $fdiskOutputBeforeAddingDisk
		

#Add datadisk to VM
		$supressedOut = RetryOperation -operation { Get-AzureVM -ServiceName $testVMServiceName | Add-AzureDataDisk -CreateNew -DiskSizeInGB $diskSizeInGB -DiskLabel "TestDisk-$testLun" -LUN $testLun | Update-AzureVM  } -maxRetryCount 5 -retryInterval 5 -description "Attaching $diskSizeInGB GB disk to LUN : $testLun."
		if ( ( $supressedOut.OperationDescription -eq "Update-AzureVM"  ) -and ( $supressedOut.OperationStatus -eq "Succeeded" ))
		{
			LogMsg "Disk Attached Successfully.."
			WaitFor -seconds 10
			LogMsg "Checking VM status.."
			$isVMAlive = Test-TCP -testIP $testVMVIP -testport $testVMSSHport
			if ($isVMAlive -eq "True")
			{
				LogMsg "VM Status : RUNNING."
				$retryCount = 1
				$MaxRetryCount = 20
				$newDiskAdded = "FAIL"
				While (($retryCount -le $MaxRetryCount) -and ($newDiskAdded -eq "FAIL"))
				{
					LogMsg "Attempt : $retryCount : Checking for new disk."
					$fdiskOutputAfterAddingDisk = RunLinuxCmd -username $testVMUsername -password $testVMpassword -ip $testVMVIP -port $testVMSSHport -command "$fdisk -l" -runAsSudo -ignoreLinuxExitCode
					$disksafterAddingNewDisk = GetTotalPhysicalDisks -FdiskOutput $fdiskOutputAfterAddingDisk
					if ( ($disksBeforeAddingNewDisk + 1) -eq $disksafterAddingNewDisk )
					{
						$newDiskAdded = "PASS"
						LogMsg "New Disk detected."
						$newDisknames = GetNewPhysicalDiskNames -FdiskOutputBeforeAddingDisk $fdiskOutputBeforeAddingDisk -FdiskOutputAfterAddingDisk $fdiskOutputAfterAddingDisk
						if($detectedDistro -imatch "SLES" )
						{
							$extResult =  PerformIOTestOnDisk -testVMObject $testVMObject -attachedDisk $newDisknames -diskFileSystem "ext3"
						}
						else
						{
							$extResult =  PerformIOTestOnDisk -testVMObject $testVMObject -attachedDisk $newDisknames -diskFileSystem "ext4"
						}
						$xfsResult =  PerformIOTestOnDisk -testVMObject $testVMObject -attachedDisk $newDisknames -diskFileSystem "xfs"
						if ( ($extResult  -eq "PASS") -and ($xfsResult  -eq "PASS") )
						{
							$retValue = "PASS"
						}
						else
						{
							$retValue = "FAIL"
						}
					}
					else
					{
						Write-Host "New disk not detected."
						WaitFor -seconds 10
						$newDiskAdded = "FAIL"
						$retryCount += 1
					}
				}
				Add-Content  -Value "After Adding New Disk : " -Path $HotAddLogFile -Encoding UTF8
				Add-Content  -Value $fdiskOutputAfterAddingDisk -Path $HotAddLogFile -Encoding UTF8
			}
			else
			{
				LogError "VM Status : OFF."
				LogError "VM is not Alive after adding new disk."
				$retValue = "FAIL"
			}
		}
		else
		{
			LogError "Failed to Attach disk."
			$retValue = "FAIL"
		}
	}
	else
	{
		LogError "VM is not Alive."
		LogError "Aborting Test."
		$retValue = "Aborted"
	}
	Add-Content  -Value "--------------------ADD DISK TO LUN $testLun : END : $retValue----------------------" -Path $HotAddLogFile 
	return $retValue
}
Function DoHotRemoveDataDiskTest ($testVMObject)
{

	$testVMSSHport = $testVMObject.sshPort
	$testVMVIP = $testVMObject.ip
	$testVMServiceName = $testVMObject.ServiceName
	$testVMUsername = $testVMObject.user 
	$testVMPassword = $testVMObject.password
	$testLun = $testVMObject.Lun
	$HotRemoveLogFile = "$($testVMObject.logDir)\Hot-Remove-Disk.log"
	$isVMAlive = Test-TCP -testIP $testVMVIP -testport $testVMSSHport
	$retValue = "ABORTED"
	if ($isVMAlive -eq "True")
	{
		Add-Content  -Value "--------------------REMOVE DISK FROM LUN $testLun : START----------------------" -Path $HotRemoveLogFile -Encoding UTF8
#GetCurrentDiskInfo

		$out = RunLinuxCmd -username $testVMUsername -password $testVMpassword -ip $testVMVIP -port $testVMSSHport -command "$fdisk -l" -runAsSudo
		$disksBeforeRemovingDisk = GetTotalPhysicalDisks -FdiskOutput $out
		Add-Content  -Value "Before Removing Disk : " -Path $HotRemoveLogFile -Encoding UTF8
		Add-Content  -Value $out -Path $HotRemoveLogFile  -Encoding UTF8
#Add datadisk to VM
		$supressedOut = RetryOperation -operation { Get-AzureVM -ServiceName $testVMServiceName | Remove-AzureDataDisk -LUN $testLun | Update-AzureVM } -maxRetryCount 5 -retryInterval 5 -description "Removing disk from LUN : $testLun."
		if ( ( $supressedOut.OperationDescription -eq "Update-AzureVM"  ) -and ( $supressedOut.OperationStatus -eq "Succeeded" ))
		{
			LogMsg "Disk Removed Successfully.."
			WaitFor -seconds 10
			$isVMAlive = RetryOperation -operation {Test-TCP -testIP $testVMVIP -testport $testVMSSHport} -description "Checking VM status.." -expectResult "True"
			if ($isVMAlive -eq "True")
			{
				LogMsg "VM Status : RUNNING."
				$retryCount = 1
				$MaxRetryCount = 20
				$retValue = "FAIL"
				While (($retryCount -le $MaxRetryCount) -and ($retValue -eq "FAIL"))
				{
					$out = ""
					LogMsg "Attempt : $retryCount : Verifying removal of disk."
					$out = RunLinuxCmd -username $testVMUsername -password $testVMpassword -ip $testVMVIP -port $testVMSSHport -command "$fdisk -l" -runAsSudo -ignoreLinuxExitCode
					$disksafterRemovingDisk = GetTotalPhysicalDisks -FdiskOutput $out
					if ( ($disksBeforeRemovingDisk - 1) -eq $disksafterRemovingDisk )
					{
						LogMsg "Disk removed successfully.."
						$retValue = "PASS"
					}
					else
					{
						LogError "Disk can be still visible in VM."
						WaitFor -seconds 10
						$retValue = "FAIL"
						$retryCount += 1
					}
				}
				Add-Content  -Value "After removing Disk : " -Path $HotRemoveLogFile -Encoding UTF8
				Add-Content  -Value $out -Path $HotRemoveLogFile -Encoding UTF8
			}
			else
			{
				LogMsg "VM Status : OFF."
				LogError "VM is not Alive after removing new disk."
				$retValue = "FAIL"
			}
		}
		else
		{
			LogError "Failed to remove disk."
			$retValue = "FAIL"
		}
	}
	else
	{
		LogError "VM is not Alive."
		LogError "Aborting Test."
		$retValue = "Aborted"
	}
	Add-Content  -Value "--------------------REMOVE DISK FROM LUN $testLun : END : $retValue----------------------" -Path $HotRemoveLogFile -Encoding UTF8
	return $retValue
}

Function DoHotAddNewDataDiskTestParallel ($testVMObject, $TotalLuns)
{

	$testVMSSHport = $testVMObject.sshPort
	$testVMVIP = $testVMObject.ip
	$testVMServiceName = $testVMObject.ServiceName
	$testVMUsername = $testVMObject.user 
	$testVMPassword = $testVMObject.password
	$testLun = $testVMObject.Lun
	$retValue = "ABORTED"
	$HotAddLogFile = "$($testVMObject.logDir)\Hot-Add-Disk.log"
#$HotAddLogFile = ".\temp\Hot-Add-Disk.log"
	$isVMAlive = Test-TCP -testIP $testVMVIP -testport $testVMSSHport

	if ($isVMAlive -eq "True")
	{
		Add-Content  -Value "--------------------ADD $TotalLuns DISKS : START----------------------" -Path $HotAddLogFile -Encoding UTF8
#GetCurrentDiskInfo

		$FdiskOutputBeforeAddingDisk = RunLinuxCmd -username $testVMUsername -password $testVMpassword -ip $testVMVIP -port $testVMSSHport -command "$fdisk -l" -runAsSudo
		Add-Content  -Value "Before Adding Disks : " -Path $HotAddLogFile -Encoding UTF8
		Add-Content  -Value $FdiskOutputBeforeAddingDisk -Path $HotAddLogFile -Encoding UTF8
		$disksBeforeAddingNewDisk = GetTotalPhysicalDisks -FdiskOutput $FdiskOutputBeforeAddingDisk

#Add datadisk to VM
		$lunCounter = 0
		$HotAddCommand = "Get-AzureVM -ServiceName $testVMServiceName"
		while ($lunCounter -lt $TotalLuns)
		{
			$diskSizeInGB = ($lunCounter+1)*10
			$HotAddCommand += " | Add-AzureDataDisk -CreateNew -DiskSizeInGB $diskSizeInGB -DiskLabel `"TestDisk-$lunCounter`" -LUN $lunCounter"
			$lunCounter += 1
		}
		$HotAddCommand += " | Update-AzureVM"
		
		$suppressedOut = RetryOperation -operation {Invoke-Expression $HotAddCommand } -maxRetryCount 5 -retryInterval 5 -description "Attaching $TotalLuns disks parallely."
		if(($suppressedOut.OperationDescription -eq "Update-AzureVM") -and ( $suppressedOut.OperationStatus -eq "Succeeded"))
		{
			LogMsg "$TotalLuns Disks Attached Successfully.."

			WaitFor -seconds 10
			$isVMAlive = RetryOperation -operation {Test-TCP -testIP $testVMVIP -testport $testVMSSHport} -description "Checking VM status.." -expectResult "True"
			if ($isVMAlive -eq "True")
			{
				LogMsg "VM Status : RUNNING."
				$retryCount = 1
				$MaxRetryCount = 20
				$isAllDiskDetected = "FAIL"
				While (($retryCount -le $MaxRetryCount) -and ($isAllDiskDetected -eq "FAIL"))
				{
					$out = ""
					LogMsg "Attempt : $retryCount : Checking for new disk."
					$FdiskOutputAfterAddingDisk = RunLinuxCmd -username $testVMUsername -password $testVMpassword -ip $testVMVIP -port $testVMSSHport -command "$fdisk -l" -runAsSudo -ignoreLinuxExitCode
					$disksafterAddingNewDisk = GetTotalPhysicalDisks -FdiskOutput $FdiskOutputAfterAddingDisk
					if ( ($disksBeforeAddingNewDisk + $TotalLuns) -eq $disksafterAddingNewDisk )
					{
						LogMsg "All $TotalLuns New Disks detected."
						$newDisks = GetNewPhysicalDiskNames -FdiskOutputBeforeAddingDisk $FdiskOutputBeforeAddingDisk -FdiskOutputAfterAddingDisk $FdiskOutputAfterAddingDisk
						$isAllDiskDetected = "PASS"
						$successCount = 0
						$errorCount = 0
						foreach ( $newDisk in $newDisks.split("^"))
						{
							$extResult = $null
							$xfsResult = $null
							if($detectedDistro -imatch "SLES" )
							{
								$extResult =  PerformIOTestOnDisk -testVMObject $testVMObject -attachedDisk $newDisk -diskFileSystem "ext3"
							}
							else
							{
								$extResult =  PerformIOTestOnDisk -testVMObject $testVMObject -attachedDisk $newDisk -diskFileSystem "ext4"
							}
							$xfsResult = PerformIOTestOnDisk -testVMObject $testVMObject -attachedDisk $newDisk -diskFileSystem "xfs"
							if ( ($extResult  -eq "PASS") -and ($xfsResult  -eq "PASS") )
							{
								$successCount += 1
							}
							else
							{
								LogError "IO Operations failed for $newDisk"
								$errorCount += 1
							}
						}
						if ($successCount -eq $TotalLuns)
						{
							$retValue = "PASS"
						}
						else
						{
							$retValue = "FAIL"
							LogError "I/O operations on $errorCount disks."
						}
					}
					else
					{
						$NotDetectedDisks = ( ($disksBeforeAddingNewDisk + $TotalLuns) - $disksafterAddingNewDisk )
						LogError "Total undetected disks : $NotDetectedDisks"
						WaitFor -seconds 10
						$isAllDiskDetected = "FAIL"
						$retryCount += 1
					}

				}
				Add-Content  -Value "After Adding New Disk : " -Path $HotAddLogFile -Encoding UTF8
				Add-Content  -Value $FdiskOutputAfterAddingDisk -Path $HotAddLogFile -Encoding UTF8
			}
			else
			{
				LogMsg "VM Status : OFF."
				LogError "VM is not Alive after adding new disk."
				$retValue = "FAIL"
			}
		}
		else
		{
			LogError "Failed to attach disks."
			$retValue = "FAIL"
		}
	}
	else
	{
		LogError "VM is not Alive."
		LogError "Aborting Test."
		$retValue = "Aborted"
	}
	Add-Content  -Value "--------------------ADD DISK TO LUN $testLun : END : $retValue----------------------" -Path $HotAddLogFile 
	return $retValue
}
Function DoHotRemoveNewDataDiskTestParallel ($testVMObject, $TotalLuns)
{

	$testVMSSHport = $testVMObject.sshPort
	$testVMVIP = $testVMObject.ip
	$testVMServiceName = $testVMObject.ServiceName
	$testVMUsername = $testVMObject.user 
	$testVMPassword = $testVMObject.password
	$testLun = $testVMObject.Lun
	$retValue = "ABORTED"
	$HotRemoveLogFile = "$($testVMObject.logDir)\Hot-Remove-Disk.log"
#$HotRemoveLogFile = ".\temp\Hot-Remove-Disk.log"
	$isVMAlive = Test-TCP -testIP $testVMVIP -testport $testVMSSHport

	if ($isVMAlive -eq "True")
	{
		Add-Content  -Value "--------------------REMOVE $TotalLuns DISKS : START----------------------" -Path $HotRemoveLogFile -Encoding UTF8
#GetCurrentDiskInfo

		$out = RunLinuxCmd -username $testVMUsername -password $testVMpassword -ip $testVMVIP -port $testVMSSHport -command "$fdisk -l" -runAsSudo
		Add-Content  -Value "Before Adding Disks : " -Path $HotRemoveLogFile -Encoding UTF8
		Add-Content  -Value $out -Path $HotRemoveLogFile -Encoding UTF8
		$disksBeforeRemovingNewDisk = GetTotalPhysicalDisks -FdiskOutput $out

#Add datadisk to VM
		
		$lunCounter = 0
		$HotRemoveCommand = "Get-AzureVM -ServiceName $testVMServiceName"
		while ($lunCounter -lt $TotalLuns)
		{
			$diskSizeInGB = ($lunCounter+1)*10
			$HotRemoveCommand += " | Remove-AzureDataDisk -LUN $lunCounter"
			$lunCounter += 1
		}
		$HotRemoveCommand += " | Update-AzureVM"
		LogMsg $HotRemoveCommand
		#$supressedOut = ( Invoke-Expression $HotAddCommand )
		$RemoveOut = RetryOperation -operation {Invoke-Expression $HotRemoveCommand}  -maxRetryCount 5 -retryInterval 5 -description "Removing $TotalLuns disks parallely."
		if($RemoveOut.OperationStatus -eq "Succeeded")
		{
			LogMsg "$TotalLuns Disks removed Successfully.."

			WaitFor -seconds 10
			$isVMAlive = RetryOperation -operation {Test-TCP -testIP $testVMVIP -testport $testVMSSHport} -description "Checking VM status.." -expectResult "True"
			if ($isVMAlive -eq "True")
			{
				LogMsg "VM Status : RUNNING."
				$retryCount = 1
				$MaxRetryCount = 20
				$retValue = "FAIL"
				While (($retryCount -le $MaxRetryCount) -and ($retValue -eq "FAIL"))
				{
					$out = ""
					LogMsg "Attempt : $retryCount : Checking for new disk."
					$out = RunLinuxCmd -username $testVMUsername -password $testVMpassword -ip $testVMVIP -port $testVMSSHport -command "$fdisk -l" -runAsSudo -ignoreLinuxExitCode
					$disksafterRemovingNewDisk = GetTotalPhysicalDisks -FdiskOutput $out
					if ( ($disksBeforeRemovingNewDisk - $TotalLuns) -eq $disksafterRemovingNewDisk )
					{
						LogMsg "All Disks removed."
						$retValue = "PASS"

					}
					else
					{
						$UnexpectedDisks = ( $disksafterRemovingNewDisk - ($disksBeforeRemovingNewDisk - $TotalLuns) )
						LogError "Total unexpected disks : $UnexpectedDisks"
						WaitFor -seconds 10
						$retValue = "FAIL"
						$retryCount += 1
					}

				}
				Add-Content  -Value "After removing Disks : " -Path $HotRemoveLogFile -Encoding UTF8
				Add-Content  -Value $out -Path $HotRemoveLogFile -Encoding UTF8
			}
			else
			{
				LogMsg "VM Status : OFF."
				LogError "VM is not Alive after adding new disk."
				$retValue = "FAIL"
			}
		}
		else
		{
			LogError "Error in  removing disks."
			LogError "Aborting Test."
			$retValue = "Aborted"
		}
	}
	else
	{
		LogError "VM is not Alive."
		LogError "Aborting Test."
		$retValue = "Aborted"
	}
	Add-Content  -Value "--------------------REMOVE $testLun DISKS : END : $retValue----------------------" -Path $HotRemoveLogFile 
	return $retValue
}
Function DoHotAddExistingDataDiskTest($testVMObject)
{
	$retValue = "ABORTED"
	$testVMSSHport = $testVMObject.sshPort
	$testVMVIP = $testVMObject.ip
	$testVMServiceName = $testVMObject.ServiceName
	$testVMUsername = $testVMObject.user 
	$testVMPassword = $testVMObject.password
	$testLun = $testVMObject.Lun
	$testExistingDisk = $testVMObject.ExistingDiskMediaLink
	$HotAddLogFile = "$($testVMObject.logDir)\Hot-Add-Existing-Disk.log"
	$isVMAlive = Test-TCP -testIP $testVMVIP -testport $testVMSSHport
	if ($isVMAlive -eq "True")
	{
		Add-Content  -Value "--------------------ADD EXISTING DISK TO LUN $testLun : START----------------------" -Path $HotAddLogFile -Encoding UTF8
#GetCurrentDiskInfo
		$fdiskOutputBeforeAddingDisk =  RunLinuxCmd -username $testVMUsername -password $testVMpassword -ip $testVMVIP -port $testVMSSHport -command "$fdisk -l" -runAsSudo
		Add-Content  -Value "Before Adding Existing Disk : " -Path $HotAddLogFile -Encoding UTF8
		Add-Content  -Value $fdiskOutputBeforeAddingDisk -Path $HotAddLogFile -Encoding UTF8
		$disksBeforeAddingNewDisk = GetTotalPhysicalDisks -FdiskOutput $fdiskOutputBeforeAddingDisk
#Add datadisk to VM
		$addExistingDisk = RetryOperation -operation { Get-AzureVM -ServiceName $testVMServiceName | Add-AzureDataDisk  -ImportFrom -MediaLocation $testExistingDisk -DiskLabel "TestDisk-$testLun" -LUN $testLun | Update-AzureVM  } -maxRetryCount 15 -retryInterval 10 -Description "Attaching $testExistingDisk disk to LUN : $testLun."
		if ( ( $addExistingDisk.OperationDescription -eq "Update-AzureVM"  ) -and ( $addExistingDisk.OperationStatus -eq "Succeeded" ))
		{
			LogMsg "Disk Attached Successfully.."
			WaitFor -seconds 10
			LogMsg "Checking VM status.."
			$isVMAlive = Test-TCP -testIP $testVMVIP -testport $testVMSSHport
			if ($isVMAlive -eq "True")
			{
				LogMsg "VM Status : RUNNING."
				$retryCount = 1
				$MaxRetryCount = 20
				$newDiskAdded = "FAIL"
				While (($retryCount -le $MaxRetryCount) -and ($newDiskAdded -eq "FAIL"))
				{
					$fdiskOutputAfterAddingDisk = ""
					LogMsg "Attempt : $retryCount : Checking for new disk."
					$fdiskOutputAfterAddingDisk = RunLinuxCmd -username $testVMUsername -password $testVMpassword -ip $testVMVIP -port $testVMSSHport -command "$fdisk -l" -runAsSudo -ignoreLinuxExitCode
					$disksafterAddingNewDisk = GetTotalPhysicalDisks -FdiskOutput $fdiskOutputAfterAddingDisk
					if ( ($disksBeforeAddingNewDisk + 1) -eq $disksafterAddingNewDisk )
					{
						LogMsg "Existing Disk detected."
						$newDiskAdded = "PASS"
						$newDisknames = GetNewPhysicalDiskNames -FdiskOutputBeforeAddingDisk $fdiskOutputBeforeAddingDisk -FdiskOutputAfterAddingDisk $fdiskOutputAfterAddingDisk
						if($detectedDistro -imatch "SLES" )
						{
							$extResult =  PerformIOTestOnDisk -testVMObject $testVMObject -attachedDisk $newDisknames -diskFileSystem "ext3"
						}
						else
						{
							$extResult =  PerformIOTestOnDisk -testVMObject $testVMObject -attachedDisk $newDisknames -diskFileSystem "ext4"
						}
						$xfsResult =  PerformIOTestOnDisk -testVMObject $testVMObject -attachedDisk $newDisknames -diskFileSystem "xfs"
						if ( ($extResult -eq "PASS") -and ($xfsResult -eq "PASS"))
						{
							$retValue = "PASS"
						}
						else
						{
							$retValue = "FAIL"
						}
					}
					else
					{
						LogError "Existing disk not detected."
						WaitFor -seconds 10
						$newDiskAdded = "FAIL"
						$retryCount += 1
					}

				}
				Add-Content  -Value "After Adding Existing Disk : " -Path $HotAddLogFile -Encoding UTF8
				Add-Content  -Value $fdiskOutputAfterAddingDisk -Path $HotAddLogFile -Encoding UTF8
			}
			else
			{
				LogMsg "VM Status : OFF."
				LogError "VM is not Alive after adding new disk."
				$retValue = "FAIL"
			}
		}
		else
		{
			LogError "Error while attaching disk."
			LogError "Aborting Test."
			$retValue = "Aborted"
		}
	}
	else
	{
		LogError "VM is not Alive."
		LogError "Aborting Test."
		$retValue = "Aborted"
	}
	Add-Content  -Value "--------------------ADD EXISTING DISK TO LUN $testLun : END : $retValue----------------------" -Path $HotAddLogFile 
	return $retValue
}
Function DoHotAddExistingDataDiskTestParallel ($testVMObject, $TotalLuns)
{

	$testVMSSHport = $testVMObject.sshPort
	$testVMVIP = $testVMObject.ip
	$testVMServiceName = $testVMObject.ServiceName
	$testVMUsername = $testVMObject.user 
	$testVMPassword = $testVMObject.password
	$testLun = $testVMObject.Lun
	$existingDisks = $testVMObject.AllExistingDisks
	$retValue = "ABORTED"
	$HotAddLogFile = "$($testVMObject.logDir)\Hot-Add-Disk.log"
#$HotAddLogFile = ".\temp\Hot-Add-Disk.log"
	$isVMAlive = Test-TCP -testIP $testVMVIP -testport $testVMSSHport

	if ($isVMAlive -eq "True")
	{
		Add-Content  -Value "--------------------ADD EXISTING $TotalLuns DISKS : START----------------------" -Path $HotAddLogFile -Encoding UTF8
#GetCurrentDiskInfo

		$FdiskOutputBeforeAddingDisk = RunLinuxCmd -username $testVMUsername -password $testVMpassword -ip $testVMVIP -port $testVMSSHport -command "$fdisk -l" -runAsSudo
		Add-Content  -Value "Before Adding Disks : " -Path $HotAddLogFile -Encoding UTF8
		Add-Content  -Value $FdiskOutputBeforeAddingDisk -Path $HotAddLogFile -Encoding UTF8
		$disksBeforeAddingNewDisk = GetTotalPhysicalDisks -FdiskOutput $FdiskOutputBeforeAddingDisk

#Add datadisk to VM
		$lunCounter = 0
		$HotAddCommand = "Get-AzureVM -ServiceName $testVMServiceName"
		while ($lunCounter -lt $TotalLuns)
		{
			$HotAddCommand += " | Add-AzureDataDisk -ImportFrom -MediaLocation $($existingDisks[$lunCounter]) -DiskLabel TestDisk-$lunCounter -LUN $lunCounter "
			$lunCounter += 1
		}
		$HotAddCommand += " | Update-AzureVM"
		LogMsg "$HotAddCommand"
		$AttachDiskOut = RetryOperation -operation {Invoke-Expression $HotAddCommand } -maxRetryCount 10 -retryInterval 10 -description "Attaching $TotalLuns disks parallely."
		if ($AttachDiskOut.OperationStatus -eq "Succeeded")
		{
			LogMsg "$TotalLuns Disks Attached Successfully.."
			WaitFor -seconds 10
			$isVMAlive = RetryOperation -operation {Test-TCP -testIP $testVMVIP -testport $testVMSSHport} -description "Checking VM status.." -expectResult "True"
			if ($isVMAlive -eq "True")
			{
				LogMsg "VM Status : RUNNING."
				$retryCount = 1
				$MaxRetryCount = 20
				$isAllDiskDetected = "FAIL"
				While (($retryCount -le $MaxRetryCount) -and ($isAllDiskDetected -eq "FAIL"))
				{
					$FdiskOutputAfterAddingDisk = ""
					LogMsg "Attempt : $retryCount : Checking for existing disk."
					$FdiskOutputAfterAddingDisk = RunLinuxCmd -username $testVMUsername -password $testVMpassword -ip $testVMVIP -port $testVMSSHport -command "$fdisk -l" -runAsSudo -ignoreLinuxExitCode
					$disksafterAddingNewDisk = GetTotalPhysicalDisks -FdiskOutput $FdiskOutputAfterAddingDisk
					if ( ($disksBeforeAddingNewDisk + $TotalLuns) -eq $disksafterAddingNewDisk )
					{
						LogMsg "All $TotalLuns existing Disks detected."
						$isAllDiskDetected = "PASS"
						$newDisks = GetNewPhysicalDiskNames -FdiskOutputBeforeAddingDisk $FdiskOutputBeforeAddingDisk -FdiskOutputAfterAddingDisk $FdiskOutputAfterAddingDisk
						$isAllDiskDetected = "PASS"
						$successCount = 0
						$errorCount = 0
						foreach ( $newDisk in $newDisks.split("^"))
						{
							$extResult = $null
							$xfsResult = $null
							if($detectedDistro -imatch "SLES" )
							{
								$extResult =  PerformIOTestOnDisk -testVMObject $testVMObject -attachedDisk $newDisk -diskFileSystem "ext3"
							}
							else
							{
								$extResult =  PerformIOTestOnDisk -testVMObject $testVMObject -attachedDisk $newDisk -diskFileSystem "ext4"
							}
							$xfsResult = PerformIOTestOnDisk -testVMObject $testVMObject -attachedDisk $newDisk -diskFileSystem "xfs"
							if (($extResult -eq "PASS") -and ($xfsResult -eq "PASS"))
							{
								$successCount += 1
							}
							else
							{
								LogError "IO Operations failed for $newDisk"
								$errorCount += 1
							}
						}
						if ($successCount -eq $TotalLuns)
						{
							$retValue = "PASS"
						}
						else
						{
							$retValue = "FAIL"
							LogError "I/O operations on $errorCount disks."
						}
					}
					else
					{
						$NotDetectedDisks = ( ($disksBeforeAddingNewDisk + $TotalLuns) - $disksafterAddingNewDisk )
						LogError "Total undetected disks : $NotDetectedDisks"
						WaitFor -seconds 10
						$isAllDiskDetected = "FAIL"
						$retryCount += 1
					}

				}
				Add-Content  -Value "After Adding New Disk : " -Path $HotAddLogFile -Encoding UTF8
				Add-Content  -Value $FdiskOutputAfterAddingDisk -Path $HotAddLogFile -Encoding UTF8
			}
			else
			{
				LogMsg "VM Status : OFF."
				LogError "VM is not Alive after adding new disk."
				$retValue = "FAIL"
			}
		}
		else
		{
			LogError "Error in Attaching disks.."
			LogError "Aborting Test."
			$retValue = "Aborted"
		}
	}
	else
	{
		LogError "VM is not Alive."
		LogError "Aborting Test."
		$retValue = "Aborted"
	}
	Add-Content  -Value "--------------------ADD EXISTING $TotalLuns DISKS : END : $retValue----------------------" -Path $HotAddLogFile 
	return $retValue
}
Function CleanUpExistingDiskReferences($ExistingDiskMediaLinks)
{
	$existingDisks = $ExistingDiskMediaLinks
	$RetryCount2 = 1
	$falseDetections = 1
	$RetryCount3 = 0
	#Get information about all disks..
	do
	{
		$RetryCount3 += 1
		LogMsg "ATTEMPT : $RetryCount3 : Checking if Existing Disks are attached to any VM or not.."
		while(($RetryCount2 -le 20) -and ($falseDetections -gt 0))
		{
			$disksToBreakRefrences = @()
			$UnableToDetachDisks =  @()
			$UnableToBreakDisks = @()
			$BreakReferenceFailCounter = 0
			$DetachFailCounter = 0
			$totalAttachedDisks = 0
			$diskReferenceCounter = 0
			$totalOrphanedDisks = 0
			$falseAlarm = $true
			$falseDetections = 0
			WaitFor -seconds 15
			$allDiskReferences = Get-AzureDisk
			$RetryCount2 += 1
			foreach ($diskReference in $allDiskReferences)
			{
				if($existingDisks -match $diskReference.MediaLink.AbsoluteUri)
				{
					$diskReferenceCounter += 1
					if ($diskReference.AttachedTo -ne $null)
					{
						LogMsg "$(($diskReference.MediaLink.AbsoluteUri).ToUpper()) is in use by $(($diskReference.AttachedTo.HostedServiceName).ToUpper())"
						$targetVM = Get-AzureVM -ServiceName $diskReference.AttachedTo.HostedServiceName -Name $diskReference.AttachedTo.RoleName 
						$attachedDisks = $targetVM | Get-AzureDataDisk
						foreach ($disk in $attachedDisks)
						{
							if($diskReference.MediaLink.AbsoluteUri -imatch $disk.MediaLink.AbsoluteUri)
							{
								$diskToRemove = $disk
							}
						}
						if ($diskToRemove -ne $null)
						{
							$totalAttachedDisks += 1
							$falseAlarm = $false
							LogMsg "Disk is attached to $(($targetVM.Name).ToUpper()) at LUN : $($diskToRemove.Lun)"
							$outDetachDisk = RetryOperation -operation { Remove-AzureDataDisk -VM $targetVM -LUN $diskToRemove.Lun -Verbose | Update-AzureVM -Verbose } -description "Operation : Remove Disk : STARTED" -maxRetryCount 10 -retryInterval 5
							if ( $outDetachDisk.OperationStatus -eq "Succeeded" )
							{
							
								LogMsg "Operation : Remove Disk : FINISHED"
								$disksToBreakRefrences += $diskToRemove.DiskName
							}
							else
							{
								LogMsg "Operation : Remove Disk : FAIED"
								$DetachFailCounter += 1
								$UnableToDetachDisks += $diskToRemove.MediaLink.AbsoluteUri
							}
						}
						else
						{
							$falseAlarm = $true
						}
						if($falseAlarm)
						{
							LogMsg "False Detection. Disk is not in use by any VM in service $(($diskReference.AttachedTo.HostedServiceName).ToUpper())."
							$falseDetections += 1
					
						}
					}
					if ($diskReference.AttachedTo -eq $null)
					{
						$falseAlarm = $false
						$totalOrphanedDisks += 1
						LogMsg "$(($diskReference.MediaLink.AbsoluteUri).ToUpper()) is referenced as $(($diskReference.DiskName).ToUpper()) but not in use."
						$disksToBreakRefrences += $diskReference.DiskName
					}
				}
			}	
		}
		if($diskReferenceCounter -gt 0)
		{
			WaitFor -seconds 30
			foreach ($diskToBreakReference in $disksToBreakRefrences)
			{
				$RetryCount = 0
				do
				{
					$RetryCount += 1
					LogMsg "Operation : Break Reference of Disk : $(($diskToBreakReference).ToUpper()) : STARTED"
					try
					{
						$outBreak = Remove-AzureDisk -DiskName $diskToBreakReference
						$exceptionGenerated = $false
					}
					catch
					{
						LogError "Operation : Break Reference : FAILED"
						$exceptionGenerated = $true
					}
				}
				while ((($outBreak.OperationStatus -ne "Succeeded") -or $exceptionGenerated) -and ($RetryCount -lt 10) )
			
				if($outBreak.OperationStatus -eq "Succeeded") 
				{
					LogMsg "Operation : Break Reference : FINISHED"
				}
				else
				{
					LogError "Operation : Break Reference : FAILED"
					$BreakReferenceFailCounter += 1
					$UnableToBreakDisks += $diskToBreakReference
				}
			}
			if (($BreakReferenceFailCounter -eq 0) -and ($DetachFailCounter -eq 0))
			{
				LogMsg "All existing disks are free to use now."
				$retValue = $true
			}
			else
			{
				$retValue = $false
				foreach ($detachDisk in $UnableToDetachDisks)
				{
					LogError "Unable to detach : $(($detachDisk).ToUpper())"
				}
				foreach ($breakDisk in $UnableToBreakDisks)
				{
					LogError "Unable to Break Reference : $(($breakDisk).ToUpper())"
				}
				WaitFor -seconds 15
			}

		}
		else
		{
			LogMsg "All Existing Disks are already free to use."
			$retValue = $true
		}
	}
	while(($retValue -eq $false) -and ($RetryCount3 -lt 3))
	return $retValue
}


<#
.SYNOPSIS 
Retry to do the operation until it is executed successfully or has reached the maximum number of retry attempts. It returns the result of the operation if success. Otherwise, it returns null.
.PARAMETER operation
Specifies the operation which you want to retry. It is a script block. The format shoulde be {OPERATION}.
.PARAMETER description
Specifies the description of the operation.
.PARAMETER expectResult
Specifies the expect result. The default value is "$null" and it means not to check the result.
.PARAMETER maxRetryCount
Specifies the maximum retry count. The default value is 18.
.PARAMETER retryInterval
Specifies the retry interval. The default value is 10 seconds.
#>
Function RetryOperation($operation, $description, $expectResult=$null, $maxRetryCount=10, $retryInterval=10, [switch]$NoLogsPlease)
{
	$retryCount = 1
	
	do
	{
		LogMsg "Attempt : $retryCount/$maxRetryCount : $description" -NoLogsPlease $NoLogsPlease
		$ret = $null
		$oldErrorActionValue = $ErrorActionPreference
		$ErrorActionPreference = "Stop"
		
		try
		{
			$ret = Invoke-Command -ScriptBlock $operation
			if ($expectResult -ne $null)
			{
				if ($ret -match $expectResult)
				{
					return $ret
				}
				else
				{
					$ErrorActionPreference = $oldErrorActionValue
					$retryCount ++
					WaitFor -seconds $retryInterval
				}
			}
			else
			{
				return $ret
			}
		}
		catch
		{
			$retryCount ++
			WaitFor -seconds $retryInterval
			if ( $retryCount -le $maxRetryCount )
			{
				continue
			}
		}
		finally
		{
			$ErrorActionPreference = $oldErrorActionValue
		}
		if ($retryCount -ge $maxRetryCount)
		{
			LogError "Opearation Failed." 
			break;
		}
	} while ($True)
	
	return $null
}

Function GetStorageAccountKey ($xmlConfig)
{
	if ( $UseAzureResourceManager )
	{
		$storageAccountName =  $xmlConfig.config.Azure.General.ARMStorageAccount
		$StorageAccounts = Get-AzureRmStorageAccount
		foreach ($SA in $StorageAccounts)
		{
			if ( $SA.StorageAccountName -eq $storageAccountName )
			{
				LogMsg "Getting $storageAccountName storage account key..."
				$storageAccountKey = (Get-AzureRmStorageAccountKey -ResourceGroupName $SA.ResourceGroupName -Name $SA.StorageAccountName).Value[0]
				break
			}
		}
	}
	else
	{
		$storageAccountName =  $xmlConfig.config.Azure.General.StorageAccount
		LogMsg "Getting $storageAccountName storage account key..."
		$storageAccountKey = (Get-AzureStorageKey -StorageAccountName $storageAccountName).Primary
	}
	return $storageAccountKey
}

Function GetVNETDetailsFromXMLDeploymentData([string]$deploymentType)
{
	$allVnetData = $xmlConfig.config.Azure.Deployment.$deploymentType.HostedService[0]
	if ( $UseAzureResourceManager )
	{
		$vnetName = $allVnetData.ARMVnetName
		$subnet1Range = $allVnetData.ARMSubnet1Range
		$subnet2Range = $allVnetData.ARMSubnet2Range
		$vnetDomainDBFilePath = $allVnetData.ARMVnetDomainDBFilePath
		$vnetDomainRevFilePath = $allVnetData.ARMVnetDomainRevFilePath
		$dnsServerIP = $allVnetData.ARMDnsServerIP
	}
	else
	{
		$vnetName = $allVnetData.VnetName
		$subnet1Range = $allVnetData.Subnet1Range
		$subnet2Range = $allVnetData.Subnet2Range
		$vnetDomainDBFilePath = $allVnetData.VnetDomainDBFilePath
		$vnetDomainRevFilePath = $allVnetData.VnetDomainRevFilePath
		$dnsServerIP = $allVnetData.DnsServerIP
	}
	return $vnetName,$subnet1Range,$subnet2Range,$vnetDomainDBFilePath,$vnetDomainRevFilePath,$dnsServerIP
}
#endregion  

#region LinuxUtilities
Function GetFilePathsFromLinuxFolder ([string]$folderToSearch, $IpAddress, $SSHPort, $username, $password, $maxRetryCount=20, [string]$expectedFiles)
{
	$parentFolder = $folderToSearch.Replace("/" + $folderToSearch.Split("/")[($folderToSearch.Trim().Split("/").Count)-1],"")
	$LogFilesPaths = ""
	$LogFiles = ""
	$retryCount = 1
	while (($LogFilesPaths -eq "") -and ($retryCount -le $maxRetryCount ))
	{
		LogMsg "Attempt $retryCount/$maxRetryCount : Getting all file paths inside $folderToSearch"
		$lsOut = RunLinuxCmd -username $username -password $password -ip $IpAddress -port $SSHPort -command "ls -lR $parentFolder > /home/$user/listDir.txt" -runAsSudo -ignoreLinuxExitCode
		RemoteCopy -downloadFrom $IpAddress -port $SSHPort -files "/home/$user/listDir.txt" -username $username -password $password -downloadTo $LogDir -download
		$lsOut = Get-Content -Path "$LogDir\listDir.txt" -Force
		Remove-Item "$LogDir\listDir.txt"  -Force | Out-Null
		foreach ($line in $lsOut.Split("`n") )
		{
			$line = $line.Trim()
			if ($line -imatch $parentFolder)
			{
				$currentFolder = $line.Replace(":","")
			}
			if ( ( ($line.Split(" ")[0][0])  -eq "-" ) -and ($currentFolder -imatch $folderToSearch) )
			{
				while ($line -imatch "  ")
				{
					$line = $line.Replace("  "," ")
				}
				$currentLogFile = $line.Split(" ")[8]
				if ( $expectedFiles )
				{
					if ( $expectedFiles.Split(",") -contains $currentLogFile )
					{
						if ($LogFilesPaths)
						{
							$LogFilesPaths += "," + $currentFolder + "/" + $currentLogFile
							$LogFiles += "," + $currentLogFile
						}
						else
						{
							$LogFilesPaths = $currentFolder + "/" + $currentLogFile
							$LogFiles += $currentLogFile
						}
						LogMsg "Found Expected File $currentFolder/$currentLogFile"
					}
					else
					{
						LogMsg "Ignoring File $currentFolder/$currentLogFile"
					}
				}
				else
				{
					if ($LogFilesPaths)
					{
						$LogFilesPaths += "," + $currentFolder + "/" + $currentLogFile
						$LogFiles += "," + $currentLogFile
					}
					else
					{
						$LogFilesPaths = $currentFolder + "/" + $currentLogFile
						$LogFiles += $currentLogFile
					}
				}
			}
		}
        if ($LogFilesPaths -eq "")
        {
            WaitFor -seconds 10
        }
		$retryCount += 1
	}
	if ( !$LogFilesPaths )
	{
		LogMsg "No files found in $folderToSearch"
	}
	return $LogFilesPaths, $LogFiles
}

function ZipFiles( $zipfilename, $sourcedir )
{
    $currentDir = (Get-Location).Path
    $7z = (Get-ChildItem .\tools\7za.exe).FullName
    $sourcedir = $sourcedir.Trim('\')
    cd $sourcedir
    $out = Invoke-Expression "$7z a -mx5 $currentDir\$zipfilename * -r"
    cd $currentDir
    if ($out -match "Everything is Ok")
    {
        Write-Host "$currentDir\$zipfilename created successfully."
    }
}
#endregion
