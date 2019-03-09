# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

param([object] $AllVmData, [object] $CurrentTestData)

$testScript = "nested_hyperv_ntttcp_different_l1_nat.sh"
$IP_MATCH = "\b(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b"

function New-CustomScript() {
	Write-LogInfo "Create the content of custom script"
	$customScriptName = "myCustomScript.ps1"
	$customScriptContent = @"
netsh advfirewall firewall add rule name="WinRM HTTP" dir=in action=allow protocol=TCP localport=5985 profile=public
"@
	Set-Content  "$LogDir\$customScriptName"  $customScriptContent
	$rgName = $AllVMData.ResourceGroupName[0]
	$containerName = "vhds"
	$storageName = (Get-AzureRmStorageAccount -ResourceGroupName $rgName).StorageAccountName
	if(-not $storageName) {
		$randomNum = Get-Random -Maximum 999 -Minimum 100
		$storageName = "temp" + [string]$randomNum
		$location = $global:TestLocation
		New-AzureRmStorageAccount -ResourceGroupName $rgName -AccountName $storageName -Location $location -SkuName "Standard_GRS" | Out-Null
	}
	$StorageKey = (Get-AzurermStorageAccountKey  -Name $storageName -ResourceGroupName $rgName).Value[0]
	$sourceContext = New-AzureStorageContext -StorageAccountName $storageName -StorageAccountKey $StorageKey
	$blobContainer = Get-AzureStorageContainer -Name $containerName -Context $sourceContext 2>$null
	if($null -eq $blobContainer) {
		Write-LogInfo "The container $containerName doesn't exist, so create it."
		New-AzureStorageContainer -Name $containerName -Context $sourceContext   | Out-Null
		Start-Sleep 3
		$blobContainer = Get-AzureStorageContainer -Name $containerName -Context $sourceContext
	}
	Write-LogInfo "Upload the custom script to $blobContainer"
	Set-AzureStorageBlobContent -File "$LogDir\$customScriptName" -Container $containerName  -Context $sourceContext | Out-Null
	$customScriptURI = $blobContainer.CloudBlobContainer.Uri.ToString() + "/" + $customScriptName
	return $customScriptURI
}

function Invoke-CustomScript($fileUri)
{
	Write-LogInfo "Run custom script: $fileUri"
	$myVM = $AllVMData.RoleName
	$rgName = $AllVMData.ResourceGroupName[0]
	$cutomeFile = $fileUri.Split("/")[-1]
	$stNameSavedScript = $fileUri.split("//")[2].split(".")[0]
	$customeFileUri = @("$fileUri")
	$settings = @{"fileUris" = $customeFileUri}
	$rgNameSavedScript = Get-AzureRmStorageAccount | Where-Object {$_.StorageAccountName -eq $stNameSavedScript} | Select-Object -ExpandProperty ResourceGroupName
	$stKeySavedScript = (Get-AzurermStorageAccountKey  -Name $stNameSavedScript -ResourceGroupName $rgNameSavedScript).Value[0]
	$proSettings = @{"storageAccountName" = $stNameSavedScript; "storageAccountKey" = $stKeySavedScript; "commandToExecute" = "powershell -ExecutionPolicy Unrestricted -File $cutomeFile"};
	$publisher = "Microsoft.Compute"
	$type = "CustomScriptExtension"
	$name = "CustomScriptExtension"
	$location = $global:TestLocation
	foreach($vm in $myVM) {
		$sts=Set-AzureRmVMExtension -ResourceGroupName $rgName -Location $location -VMName $vm  -Name $name -Publisher $publisher -ExtensionType $type  -TypeHandlerVersion "1.9"  -Settings $settings  -ProtectedSettings $proSettings
		if($sts.IsSuccessStatusCode) {
			Write-LogInfo "Run custom script against $vm successfully."
		} else {
			Write-LogErr "Run custom script against $vm failed."
		}
	}
}

function Get-DNSAddress($session)
{
	Write-LogInfo "Get DNS Server IP"
	$ips=Invoke-Command -Session $session -ScriptBlock {
		Get-DnsClientServerAddress | Select-Object -ExpandProperty ServerAddresses
	}
	return $ips | Where-Object {$_ -imatch "\b(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b"}
}

function New-NestedVMNetPerf ($session, $vmMem, $osVHD, $processors, $switchName="") {
	Write-LogInfo "Create the VM with mem:$vmMem, processors:$processors"
			Invoke-Command -Session $session -ScriptBlock {
				param([Int32]$processors, [Int64]$vmMem, $osVHD="", $switchName="")
				$externalSwitchName = "External"
				$vmName = "test"
				$savePath = "C:\Users\"
				$CurrentVMosVHDPath = $savePath + $vmName + ".vhd"
				New-VHD -ParentPath "$osVHD" -Path $CurrentVMosVHDPath
				$vmMem = [Int64]$vmMem * 1024 * 1024

				if($switchName) {
					$NewVM = New-VM -Name $vmName -MemoryStartupBytes $vmMem -BootDevice VHD -VHDPath $CurrentVMosVHDPath -Generation 1 -Switch $switchName
				} else {
					$adapters = Get-NetAdapter
					foreach($adapter in $adapters) {
						if($adapter.LinkSpeed.ToString().Contains("10") -and !$adapter.InterfaceDescription.ToString().Contains("Virtual")) {
							New-VMSwitch  -Name $externalSwitchName -NetAdapterName $adapter.Name
						}
					}
					$NewVM = New-VM -Name $vmName -MemoryStartupBytes $vmMem -BootDevice VHD -VHDPath $CurrentVMosVHDPath -Generation 1 -Switch $externalSwitchName
					Add-VMNetworkAdapter -VMName $vmName -SwitchName "MySwitch"
				}
				Set-VM -VM $NewVM -ProcessorCount $processors -StaticMemory -CheckpointType Disabled

				Start-VM -Name $vmName

				$VMNicProperties= Get-VMNetworkAdapter -VMName $vmName

				return $VMNicProperties.IPAddresses | Where-Object {$_ -imatch $IP_MATCH}
			} -ArgumentList $processors,$vmMem,$osVHD,$switchName
}

function Get-NestedVMIPAdress ($session, $vmName="test") {
	#Start the nested vm if it's not running
	Write-LogInfo "Get the IPv4 address of the nested VM $vmName"
	Invoke-Command -Session $session -ScriptBlock {
		param($vmName)

		$status = Get-VM -Name $vmName
		if ($($status.State) -ne "running") {
			Start-VM -Name $vmName
			Start-Sleep 10
		}
	} -ArgumentList $vmName

	$MaxCount = 20
	$i=0
	do
	{
		$i++
		Start-Sleep 30
		$VMNicProperties = Invoke-Command -Session $session -ScriptBlock {
			param($vmName)

			Get-VMNetworkAdapter -VMName $vmName
		} -ArgumentList $vmName

		$nestedVmIP = $VMNicProperties.IPAddresses | Where-Object {$_ -imatch "\b(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}\b"}
	}while(($i -lt $MaxCount) -and (!$nestedVmIP))

	return $nestedVmIP
}

function Get-OSvhd ($session, $srcPath, $dstPath) {
	Write-LogInfo "Downloading vhd from $srcPath to $dstPath ..."
	if($srcPath.Trim().StartsWith("http")) {
		Invoke-Command -Session $session -ScriptBlock {
			param($srcPath, $dstPath)
			Import-Module BitsTransfer
			$displayName = "MyBitsTransfer" + (Get-Date)
			Start-BitsTransfer `
				-Source $srcPath `
				-Destination $dstPath `
				-DisplayName $displayName `
				-Asynchronous
			$btjob = Get-BitsTransfer $displayName
			$lastStatus = $btjob.JobState
			do{
				if($lastStatus -ne $btjob.JobState) {
					$lastStatus = $btjob.JobState
				}

				if($lastStatus -like "*Error*") {
					Remove-BitsTransfer $btjob
					Write-Output "Error connecting $srcPath to download."
					return 1
				}
			} while ($lastStatus -ne "Transferring")

			do{
				Write-Output (Get-Date) $btjob.BytesTransferred $btjob.BytesTotal ($btjob.BytesTransferred/$btjob.BytesTotal*100)
				Start-Sleep -s 10
			} while ($btjob.BytesTransferred -lt $btjob.BytesTotal)

			Write-Output (Get-Date) $btjob.BytesTransferred $btjob.BytesTotal ($btjob.BytesTransferred/$btjob.BytesTotal*100)
			Complete-BitsTransfer $btjob
		}  -ArgumentList $srcPath, $dstPath
	} else {
		Copy-Item $srcPath -Destination $dstPath -ToSession $session
	}
}

function Install-Hyperv ($session, $ip, $port=3389) {
	Write-LogInfo "Install Hyper-V and restart the host"
	Invoke-Command -Session $session -ScriptBlock { Install-WindowsFeature -Name Hyper-V -IncludeManagementTools -Restart}
	Write-LogInfo "Restart VMs to make sure Hyper-V install completely"

	$maxRetryTimes=10
	$retryTimes=1
	do {
		Start-Sleep 20
		$null = Test-TCP  -testIP $ip -testport $port
	} while(($? -ne $true) -and ($retryTimes++ -lt $maxRetryTimes))
	if($retryTimes -eq 10) {
		throw "Can't connect to server anymore."
	}
}

function New-NetworkSwitch ($session, $switchName)  {
	Write-LogInfo "Start to create a network switch named $switchName"
	Invoke-Command -Session $session -ScriptBlock {
		param($switchName)
		$switchNames = (Get-VMSwitch).name
		foreach ($vmswitchName in $switchNames) {
			Remove-VMSwitch $vmswitchName -Force
		}

		$netAdapterNames  = (Get-NetAdapter).name
		foreach ($netAdapterName in $netAdapterNames) {
			if($netAdapterName -like "*vEthernet*") {
				continue
			} else {
				New-VMSwitch -name $switchName -NetAdapterName $netAdapterName -AllowManagementOS $true
				break
			}
		}

	} -ArgumentList $switchName
}

function New-NAT ($session, $switchName, $natName) {
	Write-LogInfo "Start to create a network NAT named $natName"
	Invoke-Command -Session $session -ScriptBlock {
		param($switchName, $natName)
		New-VMSwitch -Name $switchName -SwitchType Internal
		$interfaceIndex =  (Get-NetAdapter -Name "*$switchName*").ifindex
		New-NetIPAddress -IPAddress "192.168.0.1" -PrefixLength 24 -InterfaceIndex $interfaceIndex
		New-NetNat -Name $natName -InternalIPInterfaceAddressPrefix "192.168.0.0/24"
	} -ArgumentList $switchName, $natName

	Write-LogInfo "Create the network NAT named $natName completed."
}

function Add-NestedNatStaticMapping ($session, $natName, $ip_addr, $internalPort, $externalPort) {
	Write-LogInfo "Mapping $ip_addr internal port $internalPort external port $externalPort "
	Invoke-Command -Session $session -ScriptBlock {
		param($natName, $ip_addr, $internalPort, $externalPort)
		Add-NetNatStaticMapping -NatName $natName -Protocol TCP -ExternalIPAddress "0.0.0.0" -InternalIPAddress $ip_addr -InternalPort $internalPort -ExternalPort $externalPort
	} -ArgumentList $natName, $ip_addr, $internalPort, $externalPort
}

function Create-NestedVMNode()
{
	$objNode = New-Object -TypeName PSObject
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name PublicIP -Value $null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name RoleName -Value $null -Force
	Add-Member -InputObject $objNode -MemberType NoteProperty -Name SSHPort -Value 22 -Force
	return $objNode
}

function Start-TestExecution ($ip, $port, $cmd) {
	Copy-RemoteFiles -uploadTo $ip -port $port -files $currentTestData.files -username $nestedUser -password $nestedPassword -upload
	Run-LinuxCmd -username $nestedUser -password $nestedPassword -ip $ip -port $port -command "chmod +x *" -runAsSudo
	Write-LogInfo "Executing : ${cmd}"
	Run-LinuxCmd -username $nestedUser -password $nestedPassword -ip $ip -port $port -command $cmd -runAsSudo -RunInBackground
	$currentStatus = Run-LinuxCmd -username $nestedUser -password $nestedPassword -ip $ip -port $port -command "cat /home/$nestedUser/state.txt"
	while ($currentStatus -eq "TestRunning") {
		$currentStatus = Run-LinuxCmd -username $nestedUser -password $nestedPassword -ip $ip -port $port -command "cat /home/$nestedUser/state.txt"
		Write-LogInfo "Current Test Staus : $currentStatus"
		Wait-Time -seconds 20
	}
}

function Send-ResultToDatabase ($GlobalConfig, $logDir, $session) {
	Write-LogInfo "Uploading the test results.."
	$dataSource = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.server
	$user = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.user
	$password = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.password
	$database = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.dbname
	$dataTableName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.dbtable
	$TestCaseName = $GlobalConfig.Global.$TestPlatform.ResultsDatabase.testTag
	if ($dataSource -And $user -And $password -And $database -And $dataTableName) {
		# Get host info
		$HostType	= $global:TestPlatform
		$HostBy	= $TestLocation

		if ($TestPlatform -eq "hyperV") {
			$HyperVMappedSizes = [xml](Get-Content .\XML\AzureVMSizeToHyperVMapping.xml)
			$L1GuestCpuNum = $HyperVMappedSizes.HyperV.$HyperVInstanceSize.NumberOfCores
			$L1GuestMemMB = $HyperVMappedSizes.HyperV.$HyperVInstanceSize.MemoryInMB
			$L1GuestSize = $L1GuestCpuNum.ToString() +"Cores "+($L1GuestMemMB/1024).ToString()+"G"
			$HostOS = (Get-WmiObject -Class Win32_OperatingSystem -ComputerName $GlobalConfig.Global.$TestPlatform.Hosts.ChildNodes[0].ServerName).Version
		} else {
			$L1GuestSize = $AllVMData.InstanceSize
			$keys = "HostingSystemOsMajor", "HostingSystemOsMinor", "HostingSystemEditionId"
			$registryEntry =  'HKLM:\SOFTWARE\Microsoft\Virtual Machine\Guest\Parameters'
			$values = @()
			foreach ( $key in  $keys) {
				$val = Invoke-Command -Session $session -ScriptBlock {
					param($registryEntry, $key)
					(get-item $registryEntry).GetValue("$key")
				} -ArgumentList $registryEntry, $key
				$values += $val
			}
			$HostOS = [string]$values[0]+ "." + [string]$values[1] + "." + [string]$values[2]
		}

		# Get L1 guest info
		$L1GuestKernelVersion = Get-Content "$LogDir\nested_properties.csv" | Select-String "Host Version"| ForEach-Object{$_ -replace ",Host Version,",""}
		$computerInfo = Invoke-Command -Session $session -ScriptBlock {Get-ComputerInfo}
		$L1GuestDistro	= $computerInfo.OsName
		$L1GuestOSType	= "Windows"

		# Get L2 guest info
		$L2GuestDistro	= Get-Content "$LogDir\nested_properties.csv" | Select-String "OS type"| ForEach-Object{$_ -replace ",OS type,",""}
		$L2GuestKernelVersion	= Get-Content "$LogDir\nested_properties.csv" | Select-String "Kernel version"| ForEach-Object{$_ -replace ",Kernel version,",""}
		$flag=1
		if($TestLocation.split(',').Length -eq 2) {
			$flag=0
		}
		foreach ( $param in $currentTestData.TestParameters.param) {
			if ($param -match "NestedCpuNum") {
				$L2GuestCpuNum = [int]($param.split("=")[1])
			}
			if ($param -match "NestedMemMB") {
				$L2GuestMemMB = [int]($param.split("=")[1])
			}
		}

		$IPVersion = "IPv4"
		$ProtocolType = "TCP"
		$connectionString = "Server=$dataSource;uid=$user; pwd=$password;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
		$LogContents = Get-Content -Path "$LogDir\report.log"
		$SQLQuery = "INSERT INTO $dataTableName (TestCaseName,TestDate,HostType,HostBy,HostOS,L1GuestOSType,L1GuestDistro,L1GuestSize,L1GuestKernelVersion,L2GuestDistro,L2GuestKernelVersion,L2GuestMemMB,L2GuestCpuNum,IPVersion,ProtocolType,NumberOfConnections,Throughput_Gbps,Latency_ms,TestPlatform,DataPath,SameHost) VALUES "

		for($i = 1; $i -lt $LogContents.Count; $i++) {
			$Line = $LogContents[$i].Trim() -split '\s+'
			$SQLQuery += "('$TestCaseName','$(Get-Date -Format yyyy-MM-dd)','$HostType','$HostBy','$HostOS','$L1GuestOSType','$L1GuestDistro','$L1GuestSize','$L1GuestKernelVersion','$L2GuestDistro','$L2GuestKernelVersion','$L2GuestMemMB','$L2GuestCpuNum','$IPVersion','$ProtocolType',$($Line[0]),$($Line[1]),$($Line[2]),'$HostType','Synthetic','$flag'),"
		}
		$SQLQuery = $SQLQuery.TrimEnd(',')
		Write-LogInfo $SQLQuery

		$connection = New-Object System.Data.SqlClient.SqlConnection
		$connection.ConnectionString = $connectionString
		$connection.Open()

		$command = $connection.CreateCommand()
		$command.CommandText = $SQLQuery
		$command.executenonquery()
		$connection.Close()
		Write-LogInfo "Uploading the test results done."
	} else {
		Write-LogInfo "Database details are not provided. Results will not be uploaded to database!"
	}
}

function Main () {
	$CurrentTestResult = Create-TestResultObject
	$testResult = $resultAborted
	$resultArr = @()
	$constantsFile = "$PWD\constants.sh"
	try {
		$cred = Get-Cred $user $password
		foreach ( $param in $currentTestData.TestParameters.param) {
			if ($param -match "NestedCpuNum") {
				$L2GuestCpuNum = [int]($param.split("=")[1])
			}
			if ($param -match "NestedMemMB") {
				$L2GuestMemMB = [int]($param.split("=")[1])
			}
			if ($param -match "NestedImageUrl") {
				$L2ImageUrl = $param.split("=")[1]
			}
			if ($param -match "NestedUser=") {
				$nestedUser = $param.split("=")[1]
			}
			if ($param -match "NestedUserPassword") {
				$nestedPassword = $param.split("=")[1].Split("'")[1]
			}
		}


		if ($testPlatform -eq "Azure") {
			$customScriptUri = New-CustomScript
			Invoke-CustomScript -fileUri $customScriptUri
			foreach($vm in $AllVMData) {
				Write-LogInfo "Install Hyper-V role on $($vm.RoleName), IP - $($vm.PublicIP)"
				$session=$null
				$connectionURL = "http://$($vm.PublicIP):$($vm.SessionPort)"
				Write-LogInfo "Session connection URL: $connectionURL"
				$session = New-PSSession -ConnectionUri $connectionURL -Credential $cred -SessionOption (New-PSSessionOption -SkipCACheck -SkipCNCheck -SkipRevocationCheck)
				Install-Hyperv -session $session -ip $vm.PublicIP
			}

			foreach($vm in $AllVMData) {
				$maxRetryTimes=10
				$retryTimes=1
				do {
					Start-Sleep 20
					$connectionURL = "http://$($vm.PublicIP):$($vm.SessionPort)"
					Write-LogInfo "Session connection URL: $connectionURL"
					if($vm.RoleName.Contains("role-0")) {
						$hs1VIP = $vm.PublicIP
						$serverSession = New-PSSession -ConnectionUri $connectionURL -Credential $cred -SessionOption (New-PSSessionOption -SkipCACheck -SkipCNCheck -SkipRevocationCheck)
						$serverInnerIP = $vm.InternalIP
					} else {
						$hs2VIP = $vm.PublicIP
						$clientSession = New-PSSession -ConnectionUri $connectionURL -Credential $cred -SessionOption (New-PSSessionOption -SkipCACheck -SkipCNCheck -SkipRevocationCheck)
					}
				} while(($? -ne $true) -and ($retryTimes++ -lt $maxRetryTimes))

				if($retryTimes -eq 10) {
					throw "Can't connect to server anymore."
				}
			}
		} else {
			Add-Content $constantsFile "nicName=eth1"
			foreach($vm in $AllVMData) {
				Write-LogInfo "Install Hyper-V role on $($vm.RoleName), IP - $($vm.PublicIP)"
				$session=$null
				if($vm.RoleName.Contains("role-0")) {
					$hs1VIP = $vm.PublicIP
					$session = New-PSSession -ComputerName $hs1VIP -Credential $cred
				}
				if($vm.RoleName.Contains("role-1")) {
					$hs2VIP = $vm.PublicIP
					$session = New-PSSession -ComputerName $hs2VIP -Credential $cred
				}
				Install-Hyperv -session $session -ip $vm.PublicIP
			}
			$maxRetryTimes=10
			$retryTimes=1
			do {
				Start-Sleep 20
				$serverSession = New-PSSession -ComputerName $hs1VIP -Credential $cred
			} while(($? -ne $true) -and ($retryTimes++ -lt $maxRetryTimes))
			if($retryTimes -eq 10) {
				throw "Can't connect to server anymore."
			}

			$retryTimes=1
			do {
				Start-Sleep 20
				$clientSession = New-PSSession -ComputerName $hs2VIP -Credential $cred
			} while(($? -ne $true) -and ($retryTimes++ -lt $maxRetryTimes))
			if($retryTimes -eq 10) {
				throw "Can't connect to client any more."
			}
		}

		if($L2ImageUrl.Trim().StartsWith("http")) {
			Write-LogInfo "Download vhd from $L2ImageUrl --- begin"
			$curtime = ([string]((Get-Date).Ticks / 1000000)).Split(".")[0]
			$nestOSVHD = "C:\Users\test_" + "$curtime" +".vhd"
			Get-OSvhd -session $serverSession -srcPath $L2ImageUrl -dstPath $nestOSVHD
			Get-OSvhd -session $clientSession -srcPath $L2ImageUrl -dstPath $nestOSVHD
			Write-LogInfo "Download vhd from $L2ImageUrl --- end"
		} else {
			Write-LogInfo "Use local vhd --- $L2ImageUrl"
			$nestOSVHD = $L2ImageUrl
		}

		$nestedVMSwithName = "MySwitch"
		$nestedNATName = "MyNATNet"

		Write-LogInfo "Get L1 DNS server ip, write it into L2's /etc/resolv.conf file to make L2 resolve DNS name"
		$serverDNS = Get-DNSAddress -session $serverSession
		for($i=0; $i -lt $serverDNS.length;$i++) {
			Add-Content $constantsFile "dns_server_ip${i}=$($serverDNS[$i])"
		}
		$clientDNS = Get-DNSAddress -session $clientSession
		for($i=0; $i -lt $clientDNS.length;$i++) {
			Add-Content $constantsFile "dns_client_ip${i}=$($clientDNS[$i])"
		}

		$allDeployedNestedVMs = @()
		$nestVMServerSSHPort = 22
		$nestVMClientSSHPort = 22
		foreach($vm in $AllVMData) {
			$IPAddresses = ""
			if($vm.RoleName.Contains("role-0")) {
				New-NAT -session $serverSession -switchName $nestedVMSwithName -natName $nestedNATName
				if ($testPlatform -ne "Azure") {
					New-NestedVMNetPerf -session $serverSession -vmMem $L2GuestMemMB -osVHD $nestOSVHD -processors $L2GuestCpuNum
					$IPAddresses = Get-NestedVMIPAdress -session $serverSession -vmName "test"
				} else {
					Write-LogInfo "Install and configure DHCP against role $($vm.RoleName)"
					Invoke-Command -Session $serverSession -ScriptBlock {Install-WindowsFeature DHCP -IncludeManagementTools}
					Invoke-Command -Session $serverSession -ScriptBlock {Add-DhcpServerV4Scope -Name "DHCP Scope" -StartRange 192.168.0.100 -EndRange 192.168.0.200 -SubnetMask 255.255.255.0 }
					Invoke-Command -Session $serverSession -ScriptBlock {Set-DhcpServerV4OptionValue -Router 192.168.0.1}
					Invoke-Command -Session $serverSession -ScriptBlock {Restart-Service dhcpserver}
					New-NestedVMNetPerf -session $serverSession -vmMem $L2GuestMemMB -osVHD $nestOSVHD -processors $L2GuestCpuNum -switchName $nestedVMSwithName
				}
			}
			if($vm.RoleName.Contains("role-1")) {
				New-NAT -session $clientSession -switchName $nestedVMSwithName -natName $nestedNATName
				if ($testPlatform -ne "Azure") {
					New-NestedVMNetPerf -session $clientSession -vmMem $L2GuestMemMB -osVHD $nestOSVHD -processors $L2GuestCpuNum
					$IPAddresses = Get-NestedVMIPAdress -session $clientSession -vmName "test"
				} else {
					Write-LogInfo "Install and configure DHCP against role $($vm.RoleName)"
					Invoke-Command -Session $clientSession -ScriptBlock {Install-WindowsFeature DHCP -IncludeManagementTools}
					Invoke-Command -Session $clientSession -ScriptBlock {Add-DhcpServerV4Scope -Name "DHCP Scope" -StartRange 192.168.0.100 -EndRange 192.168.0.200 -SubnetMask 255.255.255.0 }
					Invoke-Command -Session $clientSession -ScriptBlock {Set-DhcpServerV4OptionValue -Router 192.168.0.1}
					Invoke-Command -Session $clientSession -ScriptBlock {Restart-Service dhcpserver}
					New-NestedVMNetPerf -session $clientSession -vmMem $L2GuestMemMB -osVHD $nestOSVHD -processors $L2GuestCpuNum -switchName $nestedVMSwithName
				}
			}
			if ($testPlatform -ne "Azure") {
				Run-LinuxCmd -username $nestedUser -password $nestedPassword -ip $IPAddresses -port $nestVMServerSSHPort -command "echo $($vm.RoleName) > /etc/hostname" -runAsSudo -maxRetryCount 5
				Copy-RemoteFiles -uploadTo $IPAddresses -port $nestVMServerSSHPort -files "$constantsFile" -username $nestedUser -password $nestedPassword -upload
				Run-LinuxCmd -username $nestedUser -password $nestedPassword -ip $IPAddresses -port $nestVMServerSSHPort -command "reboot" -runAsSudo -RunInBackGround
			}
		}

		foreach($vm in $AllVMData) {
			$NestedVMNode = Create-NestedVMNode
			if($vm.RoleName.Contains("role-0")) {
				$IPAddresses = Get-NestedVMIPAdress -session $serverSession
				$NestedVMNode.PublicIP = $IPAddresses
				$NestedVMNode.RoleName = "ntttcp-server"
				$nttcpServerIP = $IPAddresses
				if ($testPlatform -ne "Azure") {
					$NestedVMNode.SSHPort = $nestVMServerSSHPort
				} else {
					$NestedVMNode.SSHPort = $vm.NestedSSHPort
					$nestVMServerSSHPort = $vm.NestedSSHPort
				}
			}
			if($vm.RoleName.Contains("role-1")) {
				$IPAddresses = Get-NestedVMIPAdress -session $clientSession
				$NestedVMNode.PublicIP = $IPAddresses
				$NestedVMNode.RoleName = "ntttcp-client"
				$nttcpClientIP = $IPAddresses
				if ($testPlatform -ne "Azure") {
					$NestedVMNode.SSHPort = $nestVMClientSSHPort
				} else {
					$NestedVMNode.SSHPort=$vm.NestedSSHPort
					$nestVMClientSSHPort=$vm.NestedSSHPort
				}
			}
			$allDeployedNestedVMs += $NestedVMNode
		}
		if($testPlatform -ne "Azure") {
			Set-Variable -Name IsWindowsImage -Value $false -Scope Global
			Is-VmAlive $allDeployedNestedVMs
			Set-Variable -Name IsWindowsImage -Value $true -Scope Global

			Write-LogInfo "Map port for SSH and ntttcp"
			$nestedVmIP="192.168.0.3"
			Add-NestedNatStaticMapping  -session $serverSession -natName $nestedNATName -ip_addr $nestedVmIP -internalPort 22 -externalPort 22
			Add-NestedNatStaticMapping  -session $clientSession -natName $nestedNATName -ip_addr $nestedVmIP -internalPort 22 -externalPort 22
			for($i=5000;$i -lt 5060;$i++) {
				Add-NestedNatStaticMapping  -session $serverSession -natName $nestedNATName -ip_addr $nestedVmIP -internalPort $i -externalPort $i
				Add-NestedNatStaticMapping  -session $clientSession -natName $nestedNATName -ip_addr $nestedVmIP -internalPort $i -externalPort $i
			}
		} else {
			foreach($nestedvm in $allDeployedNestedVMs) {
				$session=$null
				if($nestedvm.RoleName -eq "ntttcp-server") {
					$session = $serverSession
					$nttcpServerIP = $hs1VIP
					$port = $nestedvm.SSHPort
				}
				if($nestedvm.RoleName -eq "ntttcp-client") {
					$session = $clientSession
					$nttcpServerIP = $hs2VIP
					$nestedVmIP = $nestedvm.PublicIP
					$port = $nestedvm.SSHPort
				}
				Write-LogInfo "Map port for SSH and ntttcp"
				Add-NestedNatStaticMapping  -session $session -natName $nestedNATName -ip_addr $nestedvm.PublicIP -internalPort 22 -externalPort $port
				for($i=5000;$i -lt 5060;$i++) {
					Add-NestedNatStaticMapping  -session $session -natName $nestedNATName -ip_addr $nestedvm.PublicIP -internalPort $i -externalPort $i
				}
			}
		}

		if($testPlatform -ne "Azure") {
			Run-LinuxCmd -username $nestedUser -password $nestedPassword -ip $nttcpServerIP -port $nestVMServerSSHPort `
				-command "ip addr add $nestedVmIP/24 dev eth1 && ip link set eth1 up && route add default gw 192.168.0.1 && ip link set eth0 down" `
				-runAsSudo -RunInBackGround
			Run-LinuxCmd -username $nestedUser -password $nestedPassword -ip $nttcpClientIP -port $nestVMServerSSHPort `
				-command "ip addr add $nestedVmIP/24 dev eth1 && ip link set eth1 up && route add default gw 192.168.0.1 && ip link set eth0 down" `
				-runAsSudo -RunInBackGround
		} else {
			Add-Content $constantsFile "nicName=eth0"
			Copy-RemoteFiles -uploadTo $hs1VIP -port $nestVMServerSSHPort -files "$constantsFile" -username $nestedUser -password $nestedPassword -upload
			Copy-RemoteFiles -uploadTo $hs2VIP -port $nestVMClientSSHPort -files "$constantsFile" -username $nestedUser -password $nestedPassword -upload
		}
		Copy-RemoteFiles -uploadTo $hs1VIP -port $nestVMServerSSHPort -files $currentTestData.files -username $nestedUser -password $nestedPassword -upload
		Run-LinuxCmd -username $nestedUser -password $nestedPassword -ip $hs1VIP -port $nestVMServerSSHPort -command "chmod +x *" -runAsSudo

		if($testPlatform -ne "Azure") {
			$server_cmd = "/home/$nestedUser/${testScript} -role server -level1ClientIP $nestedVmIP -level1ServerIP $hs1VIP -logFolder /home/$nestedUser > /home/$nestedUser/TestExecutionConsole.log"
			$cient_cmd = "/home/$nestedUser/${testScript} -role client -level1ClientIP $nestedVmIP -level1ServerIP $hs1VIP -logFolder /home/$nestedUser > /home/$nestedUser/TestExecutionConsole.log"
		} else {
			$server_cmd = "/home/$nestedUser/${testScript} -role server -level1ClientIP $nestedVmIP -level1ServerIP $serverInnerIP -logFolder /home/$nestedUser > /home/$nestedUser/TestExecutionConsole.log"
			$cient_cmd = "/home/$nestedUser/${testScript} -role client -level1ClientIP $nestedVmIP -level1ServerIP $serverInnerIP -logFolder /home/$nestedUser > /home/$nestedUser/TestExecutionConsole.log"
		}

		Write-LogInfo "Executing : $($server_cmd)"
		Run-LinuxCmd -username $nestedUser -password $nestedPassword -ip $hs1VIP -port $nestVMServerSSHPort -command $server_cmd -runAsSudo
		Copy-RemoteFiles -download -downloadFrom $hs1VIP -files "/tmp/sshFix.tar" -downloadTo $LogDir -port $nestVMServerSSHPort -username $nestedUser -password $nestedPassword

		Copy-RemoteFiles -uploadTo $hs2VIP -port $nestVMClientSSHPort -files "$LogDir/sshFix.tar" -username $nestedUser -password $nestedPassword -upload
		Start-TestExecution -ip $hs2VIP -port $nestVMClientSSHPort -cmd $cient_cmd

		# Download test logs
		Copy-RemoteFiles -download -downloadFrom $hs2VIP -files "/home/$nestedUser/state.txt, /home/$nestedUser/TestExecutionConsole.log" -downloadTo $LogDir -port $nestVMClientSSHPort -username $nestedUser -password $nestedPassword
		$finalStatus = Get-Content $LogDir\state.txt
		if ($finalStatus -imatch "TestFailed") {
			Write-LogErr "Test failed. Last known status : $currentStatus."
			$testResult = $resultFail
		}
		elseif ($finalStatus -imatch "TestAborted") {
			Write-LogErr "Test Aborted. Last known status : $currentStatus."
			$testResult = $resultAborted
		}
		elseif ($finalStatus -imatch "TestCompleted") {
			$testResult = $resultPass
		}
		elseif ($finalStatus -imatch "TestRunning") {
			Write-LogInfo "Powershell background job for test is completed but VM is reporting that test is still running. Please check $LogDir\zkConsoleLogs.txt"
			$testResult = $resultAborted
		}

		Copy-RemoteFiles -download -downloadFrom $hs2VIP -files "/home/$nestedUser/nested_properties.csv" -downloadTo $LogDir -port $nestVMClientSSHPort -username $nestedUser -password $nestedPassword

		if ($testResult -imatch $resultPass) {
			Copy-RemoteFiles -download -downloadFrom $hs2VIP -files "/home/$nestedUser/ntttcpConsoleLogs, /home/$nestedUser/ntttcpTest.log" -downloadTo $LogDir -port $nestVMClientSSHPort -username $nestedUser -password $nestedPassword
			Copy-RemoteFiles -download -downloadFrom $hs2VIP -files "/home/$nestedUser/nested_properties.csv, /home/$nestedUser/report.log" -downloadTo $LogDir -port $nestVMClientSSHPort -username $nestedUser -password $nestedPassword
			Copy-RemoteFiles -download -downloadFrom $hs2VIP -files "/home/$nestedUser/ntttcp-test-logs-receiver.tar, /home/$nestedUser/ntttcp-test-logs-sender.tar" -downloadTo $LogDir -port $nestVMClientSSHPort -username $nestedUser -password $nestedPassword

			$ntttcpReportLog = Get-Content -Path "$LogDir\report.log"
			if (!$ntttcpReportLog) {
				$testResult = $resultFail
				throw "Invalid NTTTCP report file"
			}
			$uploadResults = $true
			$checkValues = "$resultPass,$resultFail,$resultAborted"
			foreach ($line in $ntttcpReportLog) {
				if ( $line -imatch "test_connections" ){
					continue;
				}
				try {
					$splits = $line.Trim() -split '\s+'
					$testConnections = $splits[0]
					$throughputGbps = $splits[1]
					$cyclePerByte = $splits[2]
					$averageTcpLatency = $splits[3]
					$metadata = "Connections=$testConnections"
					$connResult = "throughput=$throughputGbps`Gbps cyclePerBytet=$cyclePerByte Avg_TCP_lat=$averageTcpLatency"
					$currentTestResult.TestSummary +=  New-ResultSummary -testResult $connResult -metaData $metaData -checkValues $checkValues -testName $currentTestData.testName
					if ([string]$throughputGbps -eq "0.00") {
						$testResult = $resultFail
						$uploadResults = $false
					}
				} catch {
					$currentTestResult.TestSummary +=  New-ResultSummary -testResult "Error in parsing logs." -metaData "NTTTCP" -checkValues $checkValues -testName $currentTestData.testName
				}
			}

			Write-LogInfo $currentTestResult.TestSummary
			if (!$uploadResults) {
				Write-LogInfo "Zero throughput for some connections, results will not be uploaded to database!"
			} else {
				Send-ResultToDatabase -GlobalConfig $GlobalConfig -logDir $LogDir -session $serverSession
			}
			Remove-PSSession -Session $serverSession
			Remove-PSSession -Session $clientSession
		}
	} catch {
		$errorMessage =  $_.Exception.Message
		Write-LogInfo "EXCEPTION : $errorMessage"
	}

	$resultArr += $testResult
	Write-LogInfo "Test result : $testResult"
	$currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
	return $currentTestResult.TestResult
}

Main