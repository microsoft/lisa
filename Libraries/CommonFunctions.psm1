##############################################################################################
# CommonFunctions.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation.
	Common functions for running LISAv2 tests.

.PARAMETER
	<Parameters>

.INPUTS

.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE

#>
###############################################################################################

Function Import-TestParameters($ParametersFile)
{
	$paramTable = @{}
	Write-LogInfo "Import test parameters from provided XML file $ParametersFile ..."
	try {
		$LISAv2Parameters = [xml](Get-Content -Path $ParametersFile)
		$ParameterNames = ($LISAv2Parameters.TestParameters.ChildNodes | Where-Object {$_.NodeType -eq "Element"}).Name
		foreach ($ParameterName in $ParameterNames) {
			if ($LISAv2Parameters.TestParameters.$ParameterName) {
				if ($LISAv2Parameters.TestParameters.$ParameterName -eq "true") {
					Write-LogInfo "Setting boolean parameter: $ParameterName = true"
					$paramTable.Add($ParameterName, $true)
				}
				else {
					Write-LogInfo "Setting parameter: $ParameterName = $($LISAv2Parameters.TestParameters.$ParameterName)"
					$paramTable.Add($ParameterName, $LISAv2Parameters.TestParameters.$ParameterName)
				}
			}
		}
	} catch {
		$line = $_.InvocationInfo.ScriptLineNumber
		$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
		$ErrorMessage =  $_.Exception.Message

		Write-LogErr "EXCEPTION : $ErrorMessage"
		Write-LogErr "Source : Line $line in script $script_name."
	}
	return $paramTable
}

#
# This function will filter and collect all qualified test cases from XML files.
#
# TestCases will be filtered by (see definition in the test case XML file):
# 1) TestCase "Scope", which is defined by the TestCase hierarchy of:
#    "Platform", "Category", "Area", "TestNames"
# 2) TestCase "Attribute", which can be "Tags", or "Priority"
#
# Before entering this function, $TestPlatform has been verified as "valid" in Run-LISAv2.ps1.
# So, here we don't need to check $TestPlatform
#
Function Select-TestCases($TestXMLs, $TestCategory, $TestArea, $TestNames, $TestTag, $TestPriority, $ExcludeTests, $TestSetup)
{
    $AllLisaTests =  [System.Collections.ArrayList]::new()
    $WildCards = @('^','.','[',']','?','+','*')
    $ExcludedTestsCount = 0
    $testCategoryArray = $testAreaArray = $testNamesArray = $testTagArray = $testPriorityArray = $testSetupTypeArray = $excludedTestsArray = @()
    # if the expected filter parameter is 'All' (case insensitive), empty or $null, the actual filter used in this function will be '*', except for '$ExcludedTests'
    if (!$TestCategory -or ($TestCategory -eq "All")) {
        $TestCategory = "*"
    }
    else {
        $testCategoryArray = @($TestCategory.Trim(', ').Split(',').Trim())
    }
    if (!$TestArea -or ($TestArea -eq "All")) {
        $TestArea = "*"
    }
    else {
        $testAreaArray = @($TestArea.Trim(', ').Split(',').Trim())
    }
    if (!$TestNames -or ($TestNames -eq "All")) {
        $TestNames = "*"
    }
    else {
        $testNamesArray = @($TestNames.Trim(', ').Split(',').Trim())
    }
    if (!$TestTag -or ($TestTag -eq "All")) {
        $TestTag = "*"
    }
    else {
        $testTagArray = @($TestTag.Trim(', ').Split(',').Trim())
    }
    if (!$TestPriority -or ($TestPriority -eq "All")) {
        $TestPriority = "*"
    }
    else {
        $testPriorityArray = @($TestPriority.Trim(', ').Split(',').Trim())
    }
    if (!$TestSetup -or ($TestSetup -eq "All")) {
        $TestSetup = "*"
    }
    else {
        $testSetupTypeArray = @($TestSetup.Trim(', ').Split(',').Trim())
    }
    if ($ExcludeTests) {
        $excludedTestsArray = @($ExcludeTests.Trim(', ').Split(',').Trim())
    }

    # Filter test cases based on the criteria
    foreach ($file in $TestXMLs.FullName) {
        $currentTests = ([xml]( Get-Content -Path $file)).TestCases
        foreach ($test in $currentTests.test) {
            $platformMatched = $false
            if ($TestPlatform -eq "Ready") {
                $platformMatched = $true
            } else {
                $platforms = $test.Platform.Split(",")
                for ($i=0; $i -lt $platforms.length; $i++) {
                    if ($TestPlatform.Contains($platforms[$i]) -or $platforms[$i].Contains($TestPlatform)) {
                        $platformMatched = $true
                        break
                    }
                }
            }
            if (!$platformMatched) {
                continue
            }

            # If TestName is provided and contains the current case name, then pick the case, unless it's in excluded tests. Otherwise, check other filter conditions.
            if ($testNamesArray -notcontains $test.testName) {
                # if TestCategory not provided, or test case has Category completely matching one of expected TestCategory (case insensitive 'contains'), otherwise continue (skip this test case)
                if (($TestCategory -ne "*") -and ($testCategoryArray -notcontains $test.Category)) {
                    continue
                }
                # if TestArea not provided, or test case has Area completely matching one of expected TestArea (case insensitive 'contains'), otherwise continue (skip this test case)
                if (($TestArea -ne "*") -and ($testAreaArray -notcontains $test.Area)) {
                    continue
                }
                # if TestSetup not provided, or test case has SetupType value defined which could insensitively match one of expected Setup pattern, otherwise continue (skip this test case)
                if (($TestSetup -ne "*") -and !$($testSetupTypeArray | Where-Object {$test.SetupConfig.SetupType -and ("$($test.SetupConfig.SetupType)" -imatch $_)})) {
                    continue
                }

                # if TestTag not provided, or test case has Tags not defined (backward compatible), or test case has defined Tags scope and this Tags scope has value completely matching one of expected TestTag (case insensitive 'contains'), otherwise continue (skip this test case)
                if (($TestTag -ne "*")) {
                    if (!$test.Tags) {
                        Write-LogWarn "Test Tags of $($test.TestName) is not defined; include this test case by default."
                    }
                    elseif (!$($testTagArray | Where-Object {$test.Tags.Trim(', ').Split(',').Trim() -contains $_})) {
                        continue
                    }
                }
                # if TestPriority not provided, or test case has Priority defined which equals to one of expected TestPriority, otherwise continue (skip this test case)
                if (($TestPriority -ne "*") -and !$($testPriorityArray | Where-Object {$test.Priority -and ($test.Priority -eq $_)})) {
                    if (!$test.Priority) {
                        Write-LogWarn "Priority of $($test.TestName) is not defined."
                    }
                    continue
                }

                # If none of the group filter condition is specified, skip this test case
                if ($TestCategory -eq "*" -and $TestArea -eq "*" -and $TestTag -eq "*" -and $TestSetup -eq "*" -and $TestPriority -eq "*") {
                    continue
                }
            }

            if ($ExcludeTests) {
                $ExcludeTestMatched = $false
                foreach ($TestString in $excludedTestsArray) {
                    if (($TestString.IndexOfAny($WildCards))-ge 0) {
                        if ($TestString.StartsWith('*')) {
                            $TestString = ".$TestString"
                        }
                        if ($test.TestName -imatch $TestString) {
                            Write-LogInfo "Excluded Test  : $($test.TestName) [Wildcards match]"
                            $ExcludeTestMatched = $true
                        }
                    } elseif ($TestString -eq $test.TestName) {
                        Write-LogInfo "Excluded Test  : $($test.TestName) [Exact match]"
                        $ExcludeTestMatched = $true
                    }
                }
                if ($ExcludeTestMatched) {
                    $ExcludedTestsCount += 1
                    continue
                }
            }

            if (!($AllLisaTests | Where-Object {$_.TestName -eq $test.TestName})) {
                Write-LogInfo "Collected test: $($test.TestName) from $file"
                $null = $AllLisaTests.Add($test)
            } else {
                Write-LogWarn "Ignore duplicated test: $($test.TestName) from $file"
            }
        }
    }
    if ($ExcludeTests) {
        Write-LogInfo "$ExcludedTestsCount Test Cases have been excluded"
    }
    return ,[System.Collections.ArrayList]@($AllLisaTests | Sort-Object -Property @{Expression = {if ($_.Priority) {$_.Priority} else {'9'}}}, TestName)
}

Function Add-SetupConfig {
    param ([System.Collections.ArrayList]$AllTests, [string]$ConfigName, [string]$ConfigValue, [string]$DefaultConfigValue, [string]$SplitBy = ',', [bool]$Force = $false, [switch]$UpdateName)

    $AddSplittedConfigValue = {
        param ([System.Collections.ArrayList]$TestCollections, [string]$ConfigName, [string]$ConfigValue, [bool]$Force = $false)
        $newConfigValue = $ConfigValue
        foreach ($test in $TestCollections) {
            if (!$test.SetupConfig.$ConfigName) {
                # if the $ConfigValue contains certain characters as below, use [System.Security.SecurityElement]::Escape() to avoid exception
                if ($ConfigValue -imatch "&|<|>|'|""") {
                    $newConfigValue = [System.Security.SecurityElement]::Escape($ConfigValue)
                }
                if ($null -eq $test.SetupConfig.$ConfigName) {
                    $test.SetupConfig.InnerXml += "<$ConfigName>$newConfigValue</$ConfigName>"
                }
                else {
                    $test.SetupConfig.$ConfigName = $newConfigValue
                }
            }
            elseif ($Force) {
                $test.SetupConfig.$ConfigName = $newConfigValue
            }
        }
    }

    $IfNotContains = {
        param ([string]$OriginalConfigValue, [string]$ToBeCheckedConfigValue, [string]$SplitBy)

        $originalConfigValueArr = @($OriginalConfigValue.Trim("$SplitBy ").Split($SplitBy).Trim())
        if (($originalConfigValueArr.Count -eq 0) -or !$ToBeCheckedConfigValue) {
            return $True
        }
        elseif ($originalConfigValueArr -contains $ToBeCheckedConfigValue) {
            return $False
        }
        else {
            $matchedPattern = $null
            $originalConfigValueArr | ForEach-Object {
                if (!$matchedPattern -and $_.Contains("=~")) {
                    $pattern = $_.SubString($_.IndexOf("=~") + 2)
                    if ($ToBeCheckedConfigValue -imatch $pattern) {
                        $matchedPattern = $pattern
                    }
                }
            }
            return !$matchedPattern
        }
    }

    if ($DefaultConfigValue) {
        $expandedConfigValues = @($DefaultConfigValue.Trim("$SplitBy ").Split($SplitBy).Trim())
        if ($expandedConfigValues.Count -gt 1) {
            Write-LogErr "Only support singular value (spliting by '$SplitBy') as default value. '$DefaultConfigValue' is invalid."
        }
        else {
            $DefaultConfigValue = $DefaultConfigValue.Trim()
        }
    }
    $ConfigValue = $ConfigValue.Trim()
    if ($ConfigValue) {
        $messageKeySet = @{}
        $expandedConfigValues = @($ConfigValue.Trim("$SplitBy ").Split($SplitBy).Trim() | Sort-Object)
        if ($expandedConfigValues.Count -gt 1) {
            $updatedTests = [System.Collections.ArrayList]@()
            foreach ($singleConfigValue in $expandedConfigValues) {
                $clonedTests = [System.Collections.ArrayList]@()
                foreach ($singleTest in $AllTests) {
                    # If not pre-defined in TestXml, or -ForceCustom used, duplicate
                    if (!$singleTest.SetupConfig.$ConfigName -or $Force) {
                        $clonedTest = ([System.Xml.XmlElement]$singleTest).CloneNode($true)
                        if ($UpdateName) {
                            $clonedTest.testName = $clonedTest.testName + "-" + $singleConfigValue.Replace(" ","")
                        }
                        $null = $clonedTests.Add($clonedTest)
                    }
                    elseif ($singleConfigValue) {
                        # If pre-defined, let's decide skip or not
                        if (&$IfNotContains -OriginalConfigValue "$($singleTest.SetupConfig.$ConfigName)" -ToBeCheckedConfigValue "$singleConfigValue" -SplitBy $SplitBy) {
                            $messageKey = "$ConfigName,$($singleTest.TestName),$singleConfigValue"
                            if (!$messageKeySet.ContainsKey($messageKey)) {
                                Write-LogWarn "Pre-defined '<$ConfigName>' of test case '$($singleTest.TestName)'  with value '$($singleTest.SetupConfig.$ConfigName)' does not contains '$singleConfigValue', skip this custom setup for '$($singleTest.TestName)'"
                                $messageKeySet[$messageKey] = $null
                            }
                        }
                        else {
                            $clonedTest = ([System.Xml.XmlElement]$singleTest).CloneNode($true)
                            $clonedTest.SetupConfig.$ConfigName = [string]$singleConfigValue
                            if ($UpdateName) {
                                $clonedTest.testName = $clonedTest.testName + "-" + $singleConfigValue.Replace(" ","")
                            }
                            $null = $clonedTests.Add($clonedTest)
                        }
                    }
                }
                &$AddSplittedConfigValue -TestCollections $clonedTests -ConfigName $ConfigName -ConfigValue $singleConfigValue -Force $Force
                $clonedTests | Foreach-Object {$null = $updatedTests.Add($_)}
                if ($Force) {
                    Write-LogWarn "Force customized '<$ConfigName>' with value '$singleConfigValue' for all selected Test Cases."
                }
            }
            $AllTests.Clear()
            $AllTests.AddRange($updatedTests)
            # Set-Variable -Name ExpandedSetupConfig -Value $true -Scope Global
        }
        else {
            $toBeSkippedTests = [System.Collections.ArrayList]@()
            foreach ($singleTest in $AllTests) {
                # If there's pre-defined value in TestXml, let's decide skip or not
                if ($singleTest.SetupConfig.$ConfigName) {
                    if ((&$IfNotContains -OriginalConfigValue "$($singleTest.SetupConfig.$ConfigName)" -ToBeCheckedConfigValue "$ConfigValue" -SplitBy $SplitBy) -and !$Force) {
                        $messageKey = "$ConfigName,$($singleTest.TestName),$ConfigValue"
                        if (!$messageKeySet.ContainsKey($messageKey)) {
                            Write-LogWarn "Pre-defined '<$ConfigName>' of test case '$($singleTest.TestName)' with value '$($singleTest.SetupConfig.$ConfigName)' does not contains '$ConfigValue', skip this custom setup for '$($singleTest.TestName)'"
                            $messageKeySet[$messageKey] = $null
                        }
                        $null = $toBeSkippedTests.Add($singleTest)
                    }
                    else {
                        $singleTest.SetupConfig.$ConfigName = [string]$ConfigValue
                    }
                }
            }
            $toBeSkippedTests | Foreach-Object {$AllTests.RemoveAt($AllTests.IndexOf($_))}
            &$AddSplittedConfigValue -TestCollections $AllTests -ConfigName $ConfigName -ConfigValue $ConfigValue -Force $Force
            if ($Force) {
                Write-LogWarn "Force customized '<$ConfigName>' with value '$ConfigValue' for all selected Test Cases."
            }
        }
    }
    else {
        # If no Config Value provided, check self pre-defined value, and expand it as custom setup configurations
        $toBeSkippedTests = [System.Collections.ArrayList]@()
        $toBeAddedTests = [System.Collections.ArrayList]@()
        $messageKeySet = @{}
        foreach ($singleTest in $AllTests) {
            # If there's pre-defined value in TestXml, let's expand and apply as custom setup for current TestCase only
            if ($singleTest.SetupConfig.$ConfigName) {
                $originalConfigValueArr = @($singleTest.SetupConfig.$ConfigName.Trim("$SplitBy ").Split($SplitBy).Trim() | Where-Object {$_ -inotmatch "^=~"} | Sort-Object)
                if ($originalConfigValueArr.Count -gt 1) {
                    $null = $toBeSkippedTests.Add($singleTest)
                    foreach ($singleConfigValue in $originalConfigValueArr) {
                        $clonedTest = ([System.Xml.XmlElement]$singleTest).CloneNode($true)
                        $clonedTest.SetupConfig.$ConfigName = [string]$singleConfigValue
                        $null = $toBeAddedTests.Add($clonedTest)
                    }
                    $messageKey = "$ConfigName,$($singleTest.TestName),$($singleTest.SetupConfig.$ConfigName)"
                    if (!$messageKeySet.ContainsKey($messageKey)) {
                        Write-LogInfo "Pre-defined '<$ConfigName>' of test case '$($singleTest.TestName)' with '$SplitBy' separated value '$($singleTest.SetupConfig.$ConfigName)' has been expanded and applied according to SetupConfig"
                        $messageKeySet[$messageKey] = $null
                    }
                }
                elseif ($originalConfigValueArr.Count -eq 1) {
                    $singleTest.SetupConfig.$ConfigName = [string]$originalConfigValueArr[0]
                }
                elseif ($originalConfigValueArr.Count -eq 0) {
                    # Keep silent for ConfigName that all starts with '=~', silent with no warning message, and try the $DefaultConfigValue
                    if (!(&$IfNotContains -OriginalConfigValue "$($singleTest.SetupConfig.$ConfigName)" -ToBeCheckedConfigValue "$DefaultConfigValue" -SplitBy $SplitBy)) {
                        $singleTest.SetupConfig.$ConfigName = [string]$DefaultConfigValue
                    }
                    else {
                        # if none of pattern matches the DefaultConfigValue, skip this TestCase
                        $null = $toBeSkippedTests.Add($singleTest)
                    }
                }
            }
            elseif ($DefaultConfigValue) {
                $singleTest.SetupConfig.InnerXml += "<$ConfigName>$DefaultConfigValue</$ConfigName>"
            }
        }
        $toBeSkippedTests | Foreach-Object {$AllTests.RemoveAt($AllTests.IndexOf($_))}
        $toBeAddedTests | Foreach-Object {$null = $AllTests.Add($_)}
    }
}

function Get-SecretParams {
    <#
    .DESCRIPTION
    Used only if the "SECRET_PARAMS" parameter exists in the test definition xml.
    Used to specify parameters that should be passed to test script but cannot be
    present in the xml test definition or are unknown before runtime.
    #>

    param(
        [array] $ParamsArray,
        [xml] $GlobalConfig,
        [object] $AllVMData
    )

    $testParams = @{}

    foreach ($param in $ParamsArray.Split(',')) {
        switch ($param) {
            "Password" {
                $value = $($GlobalConfig.Global.$global:TestPlatform.TestCredentials.LinuxPassword)
                $testParams["PASSWORD"] = $value
            }
            "RoleName" {
                $value = $AllVMData.RoleName | Where-Object {$_ -notMatch "dependency"}
                $testParams["ROLENAME"] = $value
            }
            "Distro" {
                $value = $detectedDistro
                $testParams["DETECTED_DISTRO"] = $value
            }
            "Ipv4" {
                $value = $AllVMData.PublicIP
                $testParams["ipv4"] = $value
            }
            "VM2Name" {
                $value = $DependencyVmName
                $testParams["VM2Name"] = $value
            }
            "CheckpointName" {
                $value = "ICAbase"
                $testParams["CheckpointName"] = $value
            }
        }
    }

    return $testParams
}

function Parse-TestParameters {
    <#
    .DESCRIPTION
    Converts the parameters specified in the test definition into a hashtable
    to be used later in test.
    #>

    param(
        $XMLParams,
        $GlobalConfig,
        $AllVMData
    )

    $testParams = @{}
    foreach ($param in $XMLParams.param) {
        $name = $param.split("=")[0]
        if ($name -eq "SECRET_PARAMS") {
            $paramsArray = $param.split("=")[1].trim("(",")"," ").split(" ")
            $testParams += Get-SecretParams -ParamsArray $paramsArray `
                 -GlobalConfig $GlobalConfig -AllVMData $AllVMData
        } else {
            $value = $param.Substring($param.IndexOf("=")+1)
            $testParams[$name] = $value
        }
    }

    return $testParams
}

function Run-SetupScript {
    <#
    .DESCRIPTION
    Executes a PowerShell script specified in the <setupscript> tag
    Used to further prepare environment/VM
    #>

    param(
        [string] $Script,
        [hashtable] $Parameters,
        [object] $VMData,
        [object] $CurrentTestData,
        [object] $TestProvider
    )
    $workDir = Get-Location
    $scriptLocation = Join-Path $workDir $Script
    $scriptParameters = ""
    foreach ($param in $Parameters.Keys) {
        $scriptParameters += "${param}=$($Parameters[$param]);"
    }
    $msg = ("Test setup/cleanup started using script:{0} with parameters:{1}" `
             -f @($Script,$scriptParameters))
    Write-LogInfo $msg
    $result = & "${scriptLocation}" -TestParams $scriptParameters -AllVMData $VMData -CurrentTestData $CurrentTestData -TestProvider $TestProvider
    return $result
}

function Is-VmAlive {
    <#
    .SYNOPSIS
        Checks if a VM responds to TCP connections to the SSH or RDP port.
        If the VM is a Linux on Azure, it also checks the serial console log for kernel panics.

    .OUTPUTS
        Returns "True" or "False"
    #>
    param(
        $AllVMDataObject,
        $MaxRetryCount = 50
    )
	if ((!$AllVMDataObject) -or (!$AllVMDataObject.RoleName)) {
		Write-LogWarn "Empty/Invalid collection of AllVMDataObject."
		return "False"
	}

    Write-LogInfo "Trying to connect to deployed VMs."

    $retryCount = 0
    $kernelPanicPeriod = 3

    do {
        $deadVms = 0
        $retryCount += 1
        foreach ( $vm in $AllVMDataObject) {
            if ($vm.IsWindows) {
                $port = $vm.RDPPort
            } else {
                $port = $vm.SSHPort
            }

            $out = Test-TCP -testIP $vm.PublicIP -testport $port
            if ($out -ne "True") {
                Write-LogInfo "Connecting to $($vm.PublicIP) : $port failed."
                $deadVms += 1

                if (($retryCount % $kernelPanicPeriod -eq 0) -and ($TestPlatform -eq "Azure") `
                    -and (!$vm.IsWindows) -and (Check-AzureVmKernelPanic $vm)) {
                    Write-LogErr "Linux VM $($vm.RoleName) failed to boot because of a kernel panic."
                    return "False"
                }
            } else {
                Write-LogInfo "Connecting to $($vm.PublicIP) : $port succeeded."
            }
        }

        if ($deadVms -gt 0) {
            Write-LogInfo "$deadVms VM(s) still waiting for port $port open."
            Write-LogInfo "Retrying $retryCount/$MaxRetryCount in 3 seconds."
            Start-Sleep -Seconds 3
        } else {
            Write-LogInfo "The remote ports for all VMs are open."
            return "True"
        }
    } While (($retryCount -lt $MaxRetryCount) -and ($deadVms -gt 0))

    return "False"
}

Function Provision-VMsForLisa($allVMData, $installPackagesOnRoleNames)
{
	$keysGenerated = $false
	foreach ( $vmData in $allVMData )
	{
		Write-LogInfo "Configuring $($vmData.RoleName) for LISA test..."
		Copy-RemoteFiles -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\Testscripts\Linux\utils.sh,.\Testscripts\Linux\enable_root.sh,.\Testscripts\Linux\enable_passwordless_root.sh" -username $user -password $password -upload
		$Null = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "chmod +x /home/$user/*.sh" -runAsSudo
		$cmd_To_Execution = ("/home/{0}/enable_root.sh -usesshkey {1} -user {2} -password {3}" -f @($user, !([string]::IsNullOrEmpty($global:sshPrivateKey)), $user, $password.Replace('"','')))
		$rootPasswordSet = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort `
			-username $user -password $password -runAsSudo `
			-command $cmd_To_Execution
		Write-LogInfo $rootPasswordSet
		if (( $rootPasswordSet -imatch "ROOT_PASSWRD_SET" ) -and ( $rootPasswordSet -imatch "SSHD_RESTART_SUCCESSFUL" ))
		{
			Write-LogInfo "root user enabled for $($vmData.RoleName) and password set to $password"
		}
		else
		{
			Throw "Failed to enable root password / starting SSHD service. Please check logs. Aborting test."
		}
		$Null = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "cp -ar /home/$user/*.sh ."
		if ( $keysGenerated )
		{
			Copy-RemoteFiles -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files "$LogDir\sshFix.tar" -username "root" -password $password -upload
			$keyCopyOut = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "./enable_passwordless_root.sh"
			Write-LogInfo $keyCopyOut
			if ( $keyCopyOut -imatch "KEY_COPIED_SUCCESSFULLY" )
			{
				$keysGenerated = $true
				Write-LogInfo "SSH keys copied to $($vmData.RoleName)"
				$md5sumCopy = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "md5sum .ssh/id_rsa"
				if ( $md5sumGen -eq $md5sumCopy )
				{
					Write-LogInfo "md5sum check success for .ssh/id_rsa."
				}
				else
				{
					Throw "md5sum check failed for .ssh/id_rsa. Aborting test."
				}
			}
			else
			{
				Throw "Error in copying SSH key to $($vmData.RoleName)"
			}
		}
		else
		{
			$Null = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "rm -rf /root/sshFix*"
			$keyGenOut = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "./enable_passwordless_root.sh"
			Write-LogInfo $keyGenOut
			if ( $keyGenOut -imatch "KEY_GENERATED_SUCCESSFULLY" )
			{
				$keysGenerated = $true
				Write-LogInfo "SSH keys generated in $($vmData.RoleName)"
				Copy-RemoteFiles -download -downloadFrom $vmData.PublicIP -port $vmData.SSHPort  -files "/root/sshFix.tar" -username "root" -password $password -downloadTo $LogDir
				$md5sumGen = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "md5sum .ssh/id_rsa"
			}
			else
			{
				Throw "Error in generating SSH key in $($vmData.RoleName)"
			}
		}
	}

	$packageInstallJobs = @()
	foreach ( $vmData in $allVMData )
	{
		if ( $installPackagesOnRoleNames )
		{
			if ( $installPackagesOnRoleNames -imatch $vmData.RoleName )
			{
				Write-LogInfo "Executing $scriptName ..."
				$jobID = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "/root/$scriptName" -RunInBackground
				$packageInstallObj = New-Object PSObject
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name ID -Value $jobID
				if ($vmData.RoleName.Contains($vmData.ResourceGroupName)) {
					Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name RoleName -Value $vmData.RoleName
				} else {
					Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name RoleName -Value $($($vmData.ResourceGroupName) + "-" + $($vmData.RoleName))
				}
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name PublicIP -Value $vmData.PublicIP
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name SSHPort -Value $vmData.SSHPort
				$packageInstallJobs += $packageInstallObj
				#endregion
			}
			else
			{
				Write-LogInfo "$($vmData.RoleName) is set to NOT install packages. Hence skipping package installation on this VM."
			}
		}
		else
		{
			Write-LogInfo "Executing $scriptName ..."
			$jobID = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "/root/$scriptName" -RunInBackground
			$packageInstallObj = New-Object PSObject
			Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name ID -Value $jobID
			if ($vmData.RoleName.Contains($vmData.ResourceGroupName)) {
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name RoleName -Value $vmData.RoleName
			} else {
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name RoleName -Value $($($vmData.ResourceGroupName) + "-" + $($vmData.RoleName))
			}
			Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name PublicIP -Value $vmData.PublicIP
			Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name SSHPort -Value $vmData.SSHPort
			$packageInstallJobs += $packageInstallObj
			#endregion
		}
	}

	$packageInstallJobsRunning = $true
	while ($packageInstallJobsRunning)
	{
		$packageInstallJobsRunning = $false
		foreach ( $job in $packageInstallJobs )
		{
			if ( (Get-Job -Id $($job.ID)).State -eq "Running" )
			{
				$currentStatus = Run-LinuxCmd -ip $job.PublicIP -port $job.SSHPort -username "root" -password $password -command "tail -n 1 /root/provisionLinux.log"
				Write-LogInfo "Package Installation Status for $($job.RoleName) : $currentStatus"
				$packageInstallJobsRunning = $true
			}
			else
			{
				Copy-RemoteFiles -download -downloadFrom $job.PublicIP -port $job.SSHPort -files "/root/provisionLinux.log" `
					-username "root" -password $password -downloadTo $LogDir
				Rename-Item -Path "$LogDir\provisionLinux.log" -NewName "$($job.RoleName)-provisionLinux.log" -Force | Out-Null
			}
		}
		if ( $packageInstallJobsRunning )
		{
			Wait-Time -seconds 10
		}
	}
}

function Install-CustomKernel ($CustomKernel, $allVMData, [switch]$RestartAfterUpgrade, $TestProvider) {
	try {
		$currentKernelVersion = ""
		$global:FinalKernelVersion = ""
		$CustomKernel = $CustomKernel.Trim()
		# when adding new kernels here, also update script customKernelInstall.sh
		$SupportedKernels = "ppa", "proposed", "proposed-azure", "proposed-edge",
			"latest", "linuxnext", "netnext", "upstream-stable"

		if ( ($CustomKernel -notin $SupportedKernels) -and !($CustomKernel.EndsWith(".deb")) -and `
		!($CustomKernel.EndsWith(".rpm")) -and !($CustomKernel.EndsWith(".tar.gz")) -and !($CustomKernel.EndsWith(".tar")) ) {
			Write-LogErr "Only following kernel types are supported: $SupportedKernels.`
			Or use -CustomKernel <link to deb file>, -CustomKernel <link to rpm file>"
		} else {
			$scriptName = "customKernelInstall.sh"
			$jobCount = 0
			$kernelSuccess = 0
			$packageInstallJobs = @()
			$CustomKernelLabel = $CustomKernel
			foreach ( $vmData in $allVMData ) {
				Copy-RemoteFiles -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\Testscripts\Linux\$scriptName,.\Testscripts\Linux\utils.sh" -username $user -password $password -upload
				if ( $CustomKernel.StartsWith("localfile:")) {
					$customKernelFilePath = $CustomKernel.Replace('localfile:','')
					$customKernelFilePath = (Resolve-Path $customKernelFilePath).Path
					if ($customKernelFilePath -and (Test-Path $customKernelFilePath)) {
						Copy-RemoteFiles -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files $customKernelFilePath `
							-username $user -password $password -upload
					} else {
						Write-LogErr "Failed to find kernel file ${customKernelFilePath}"
						return $false
					}
					$CustomKernelLabel = "localfile:{0}" -f @((Split-Path -Leaf $CustomKernel.Replace('localfile:','')))
				}

				$Null = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "chmod +x *.sh" -runAsSudo
				$currentKernelVersion = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "uname -r"
				Write-LogInfo "Executing $scriptName ..."
				$jobID = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user `
					-password $password -command "/home/$user/$scriptName -CustomKernel '$CustomKernelLabel' -logFolder /home/$user" `
					-RunInBackground -runAsSudo
				$packageInstallObj = New-Object PSObject
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name ID -Value $jobID
				if ($vmData.RoleName.Contains($vmData.ResourceGroupName)) {
					Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name RoleName -Value $vmData.RoleName
				} else {
					Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name RoleName -Value $($($vmData.ResourceGroupName) + "-" + $($vmData.RoleName))
				}
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name PublicIP -Value $vmData.PublicIP
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name SSHPort -Value $vmData.SSHPort
				$packageInstallJobs += $packageInstallObj
				$jobCount += 1
				#endregion
			}
			$kernelInstalledSkipped = $false
			$kernelMatchSuccess = "CUSTOM_KERNEL_SUCCESS"
			$customKernelAlreadyInstall="CUSTOM_KERNEL_ALREADY_INSTALLED"
			$timeout = New-Timespan -Minutes 180
			$sw = [diagnostics.stopwatch]::StartNew()
			while ($sw.elapsed -lt $timeout) {
				$packageInstallJobsRunning = $false
				foreach ( $job in $packageInstallJobs ) {
					if ( (Get-Job -Id $($job.ID)).State -eq "Running" ) {
						$currentStatus = Run-LinuxCmd -ip $job.PublicIP -port $job.SSHPort -username $user -password $password -command "tail -n 1 build-CustomKernel.txt"
						Write-LogInfo "Package Installation Status for $($job.RoleName) : $currentStatus"
						$packageInstallJobsRunning = $true
						if ($currentStatus -imatch $kernelMatchSuccess) {
							Remove-Job -Id $job.ID -Force -ErrorAction SilentlyContinue
						}
					} else {
						if ( !(Test-Path -Path "$LogDir\$($job.RoleName)-build-CustomKernel.txt" ) ) {
							Copy-RemoteFiles -download -downloadFrom $job.PublicIP -port $job.SSHPort -files "build-CustomKernel.txt" `
								-username $user -password $password -downloadTo $LogDir
							Rename-Item -Path "$LogDir\build-CustomKernel.txt" -NewName "$($job.RoleName)-build-CustomKernel.txt" -Force | Out-Null
							if ( ( Get-Content "$LogDir\$($job.RoleName)-build-CustomKernel.txt" ) -imatch $kernelMatchSuccess ) {
								$kernelSuccess += 1
							}
							elseif ( ( Get-Content "$LogDir\$($job.RoleName)-build-CustomKernel.txt" ) -imatch $customKernelAlreadyInstall ) {
								Write-LogInfo "Kernel upgrade is skipped in VM."
								$kernelInstalledSkipped = $true
								$kernelSuccess +=1
							}
						}
					}
				}
				if ( $packageInstallJobsRunning ) {
					Wait-Time -seconds 5
				} else {
					break
				}
			}
			if ( $kernelSuccess -eq $jobCount ) {
				if ( $RestartAfterUpgrade -and !$kernelInstalledSkipped ) {
					Write-LogInfo "Kernel upgraded to `"$CustomKernel`" successfully in $jobCount VM(s)."
					Write-LogInfo "Now restarting VMs..."
					if ( $TestProvider.RestartAllDeployments($allVMData) ) {
						$retryAttempts = 5
						$isKernelUpgraded = $false
						while ( !$isKernelUpgraded -and ($retryAttempts -gt 0) ) {
							$retryAttempts -= 1
							$global:FinalKernelVersion = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "uname -r"
							Write-LogInfo "Old kernel: $currentKernelVersion"
							Write-LogInfo "New kernel: $global:FinalKernelVersion"
							if ($currentKernelVersion -eq $global:FinalKernelVersion) {
								Write-LogErr "Kernel version is same after restarting VMs."
								if ( ($CustomKernel -eq "latest") -or ($CustomKernel -eq "ppa") -or ($CustomKernel -eq "proposed") ) {
									Write-LogInfo "Continuing the tests as default kernel is same as $CustomKernel."
									$isKernelUpgraded = $true
								} else {
									$isKernelUpgraded = $false
								}
							} else {
								$isKernelUpgraded = $true
							}
							Add-Content -Value "Old kernel: $currentKernelVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
							Add-Content -Value "New kernel: $global:FinalKernelVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
							return $isKernelUpgraded
						}
					} else {
						return $false
					}
				}
				return $true
			} else {
				Write-LogErr "Kernel upgrade failed in $($jobCount-$kernelSuccess) VMs."
				return $false
			}
		}
	} catch {
		Write-LogErr "Exception in Install-CustomKernel."
		return $false
	}
}

function Install-CustomLIS ($CustomLIS, $customLISBranch, $allVMData, [switch]$RestartAfterUpgrade, $TestProvider)
{
	try
	{
		$CustomLIS = $CustomLIS.Trim()
		if ( ($CustomLIS -ne "lisnext") -and !($CustomLIS.EndsWith("tar.gz")) -and ($CustomLIS -ne "LatestLIS"))
		{
			Write-LogErr "Only lisnext, LatestLIS and *.tar.gz links are supported. Use -CustomLIS lisnext -LISbranch <branch name>. Or use -CustomLIS <link to tar.gz file>. Or use -CustomLIS LatestLIS"
		}
		else
		{
			Provision-VMsForLisa -allVMData $allVMData -installPackagesOnRoleNames none
			$scriptName = "customLISInstall.sh"
			$jobCount = 0
			$lisSuccess = 0
			$packageInstallJobs = @()
			foreach ( $vmData in $allVMData )
			{
				Copy-RemoteFiles -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\Testscripts\Linux\$scriptName,.\Testscripts\Linux\DetectLinuxDistro.sh" -username "root" -password $password -upload
				$Null = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "chmod +x *.sh" -runAsSudo
				$currentlisVersion = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
				Write-LogInfo "Executing $scriptName ..."
				$jobID = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "/root/$scriptName -CustomLIS $CustomLIS -LISbranch $customLISBranch" -RunInBackground -runAsSudo
				$packageInstallObj = New-Object PSObject
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name ID -Value $jobID
				if ($vmData.RoleName.Contains($vmData.ResourceGroupName)) {
					Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name RoleName -Value $vmData.RoleName
				} else {
					Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name RoleName -Value $($($vmData.ResourceGroupName) + "-" + $($vmData.RoleName))
				}
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name PublicIP -Value $vmData.PublicIP
				Add-member -InputObject $packageInstallObj -MemberType NoteProperty -Name SSHPort -Value $vmData.SSHPort
				$packageInstallJobs += $packageInstallObj
				$jobCount += 1
				#endregion
			}

			$packageInstallJobsRunning = $true
			while ($packageInstallJobsRunning)
			{
				$packageInstallJobsRunning = $false
				foreach ( $job in $packageInstallJobs )
				{
					if ( (Get-Job -Id $($job.ID)).State -eq "Running" )
					{
						$currentStatus = Run-LinuxCmd -ip $job.PublicIP -port $job.SSHPort -username "root" -password $password -command "tail -n 1 build-CustomLIS.txt"
						Write-LogInfo "Package Installation Status for $($job.RoleName) : $currentStatus"
						$packageInstallJobsRunning = $true
					}
				}
				if ( $packageInstallJobsRunning )
				{
					Wait-Time -seconds 10
				}
			}

			foreach ($vmData in $allVMData) {
				Copy-RemoteFiles -download -downloadFrom $vmData.PublicIP -port $vmData.SSHPort -files "build-CustomLIS.txt" -username "root" -password $password -downloadTo $LogDir
				if ((Get-Content "$LogDir\build-CustomLIS.txt") -imatch "CUSTOM_LIS_SUCCESS") {
					$lisSuccess += 1
				}
				Move-Item -Path "$LogDir\build-CustomLIS.txt" -Destination "${LogDir}\$($vmData.RoleName)-build-CustomLIS.txt" -Force | Out-Null
			}

			if ( $lisSuccess -eq $jobCount )
			{
				Write-LogInfo "LIS upgraded to `"$CustomLIS`" successfully in all VMs."
				if ( $RestartAfterUpgrade )
				{
					Write-LogInfo "Now restarting VMs..."
					if ( $TestProvider.RestartAllDeployments($allVMData) )
					{
						$upgradedlisVersion = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username "root" -password $password -command "modinfo hv_vmbus"
						Write-LogInfo "Old LIS: $currentlisVersion"
						Write-LogInfo "New LIS: $upgradedlisVersion"
						Add-Content -Value "Old LIS: $currentlisVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
						Add-Content -Value "New LIS: $upgradedlisVersion" -Path ".\Report\AdditionalInfo-$TestID.html" -Force
						if ($upgradedlisVersion -eq $currentlisVersion) {
							Write-LogErr "LIS Version is not changed even after successful LIS RPMs installation."
							return $false
						}
						return $true
					}
					else
					{
						return $false
					}
				}
				return $true
			}
			else
			{
				Write-LogErr "LIS upgrade failed in $($jobCount-$lisSuccess) VMs."
				return $false
			}
		}
	}
	catch
	{
		Write-LogErr "Exception in Install-CustomLIS."
		return $false
	}
}

function Verify-MellanoxAdapter($vmData)
{
	$maxRetryAttemps = 50
	$retryAttempts = 1
	$mellanoxAdapterDetected = $false
	while ( !$mellanoxAdapterDetected -and ($retryAttempts -lt $maxRetryAttemps))
	{
		Write-LogInfo "Install package pciutils to use lspci command."
		Copy-RemoteFiles -uploadTo $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -file ".\Testscripts\Linux\utils.sh" -upload
		Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "which lspci || (. ./utils.sh && install_package pciutils)" -runAsSudo | Out-Null
		$pciDevices = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "lspci" -runAsSudo
		if ( $pciDevices -imatch "Mellanox")
		{
			Write-LogInfo "[Attempt $retryAttempts/$maxRetryAttemps] Mellanox Adapter detected in $($vmData.RoleName)."
			$mellanoxAdapterDetected = $true
		}
		else
		{
			Write-LogErr "[Attempt $retryAttempts/$maxRetryAttemps] Mellanox Adapter NOT detected in $($vmData.RoleName)."
			$retryAttempts += 1
		}
	}
	return $mellanoxAdapterDetected
}

function Enable-SRIOVInAllVMs($allVMData, $TestProvider)
{
	try
	{
		$scriptName = "ConfigureSRIOV.sh"
		$sriovDetectedCount = 0
		$vmCount = 0

		foreach ( $vmData in $allVMData )
		{
			$vmCount += 1
			$currentMellanoxStatus = Verify-MellanoxAdapter -vmData $vmData
			if ( $currentMellanoxStatus )
			{
				Write-LogInfo "Mellanox Adapter detected in $($vmData.RoleName)."
				Copy-RemoteFiles -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\Testscripts\Linux\$scriptName" -username $user -password $password -upload
				$Null = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "chmod +x *.sh" -runAsSudo
				$sriovOutput = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "/home/$user/$scriptName" -runAsSudo
				$sriovDetectedCount += 1
			}
			else
			{
				Write-LogErr "Mellanox Adapter not detected in $($vmData.RoleName)."
			}
			#endregion
		}

		if ($sriovDetectedCount -gt 0)
		{
			if ($sriovOutput -imatch "SYSTEM_RESTART_REQUIRED")
			{
				Write-LogInfo "Updated SRIOV configuration. Now restarting VMs..."
				$restartStatus = $TestProvider.RestartAllDeployments($allVMData)
			}
			if ($sriovOutput -imatch "DATAPATH_SWITCHED_TO_VF")
			{
				$restartStatus=$true
			}
		}
		$vmCount = 0
		$bondSuccess = 0
		$bondError = 0
		if ( $restartStatus )
		{
			foreach ( $vmData in $allVMData )
			{
				$vmCount += 1
				if ($sriovOutput -imatch "DATAPATH_SWITCHED_TO_VF")
				{
					$AfterInterfaceStatus = $null
					$AfterInterfaceStatus = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "dmesg" -runMaxAllowedTime 30 -runAsSudo
					if ($AfterInterfaceStatus -imatch "Data path switched to VF")
					{
						Write-LogInfo "Data path already switched to VF in $($vmData.RoleName)"
						$bondSuccess += 1
					} else {
						Write-LogErr "Data path not switched to VF in $($vmData.RoleName)"
						$bondError += 1
					}
				} else {
					$AfterInterfaceStatus = $null
					$AfterInterfaceStatus = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -command "ip addr show" -runAsSudo
					if ($AfterInterfaceStatus -imatch "bond")
					{
						Write-LogInfo "New bond detected in $($vmData.RoleName)"
						$bondSuccess += 1
					} else {
						Write-LogErr "New bond not detected in $($vmData.RoleName)"
						$bondError += 1
					}
				}
			}
		}
		else
		{
			return $false
		}
		if ($vmCount -eq $bondSuccess)
		{
			return $true
		}
		else
		{
			return $false
		}
	}
	catch
	{
		$line = $_.InvocationInfo.ScriptLineNumber
		$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
		$ErrorMessage =  $_.Exception.Message
		Write-LogErr "EXCEPTION : $ErrorMessage"
		Write-LogErr "Source : Line $line in script $script_name."
		return $false
	}
}

Function Register-RhelSubscription {
	param (
		$AllVMData,
		[string] $RedhatNetworkUsername,
		[string] $RedhatNetworkPassword
	)
	try {
		foreach ($vmData in $allVMData) {
			$scriptName = "Register-Redhat.sh"
			Copy-RemoteFiles -uploadTo $vmData.PublicIP -port $vmData.SSHPort -files ".\Testscripts\Linux\$scriptName" -username $user -password $password -upload
			$RegistrationStatus = Run-LinuxCmd -ip $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password `
			-command "bash $scriptName -Username '$RedhatNetworkUsername' -Password '$RedhatNetworkPassword'" -runAsSudo `
			-MaskStrings "$RedhatNetworkUsername,$RedhatNetworkPassword"
			if ($RegistrationStatus -imatch "RHEL_REGISTERED") {
				Write-LogInfo "$($vmData.Rolename): RHN Network Registration: Succeeded."
			} elseif ($RegistrationStatus -imatch "RHEL_REGISTRATION_FAILED") {
				Write-LogErr "$($vmData.Rolename): RHN Network Registration: Failed."
			} elseif ($RegistrationStatus -imatch "RHEL_REGISTRATION_SKIPPED") {
				Write-LogInfo "$($vmData.Rolename): RHN Network Registration: Skipped."
			}
		}
	} catch {
		Raise-Exception($_)
	}
}

Function Set-CustomConfigInVMs($CustomKernel, $CustomLIS, $EnableSRIOV, $AllVMData, $TestProvider, [switch]$RegisterRhelSubscription) {
	$retValue = $true

	# Check the registration of the RHEL VHDs
	# RedhatNetworkUsername and #RedhatNetworkPassword should be present in $XMLSecrets file at below location -
	# RedhatNetworkUsername = $XMLSecrets.secrets.RedhatNetwork.Username
	# RedhatNetworkPassword = $XMLSecrets.secrets.RedhatNetwork.Password
	if ($RegisterRhelSubscription) {
		$RedhatNetworkUsername = $Global:XMLSecrets.secrets.RedhatNetwork.Username
		$RedhatNetworkPassword = $Global:XMLSecrets.secrets.RedhatNetwork.Password
		if ($RedhatNetworkUsername -and $RedhatNetworkPassword) {
		Register-RhelSubscription -AllVMData $AllVMData -RedhatNetworkUsername $RedhatNetworkUsername `
			-RedhatNetworkPassword $RedhatNetworkPassword
		} else {
			if (-not $RedhatNetworkUsername) { Write-LogInfo "RHN username is not available in secrets file." }
			if (-not $RedhatNetworkPassword) { Write-LogInfo "RHN password is not available in secrets file." }
			Write-LogWarn "Skipping Register-RhelSubscription()."
		}
	}

	# Solution for resolve download file issue "Fatal: Received unexpected end-of-file from server" for clear-os-linux
	foreach ($vm in $AllVMData) {
        # Detect Linux Distro
        if (!$global:detectedDistro -and !$vm.IsWindows) {
            $detectedDistro = Detect-LinuxDistro -VIP $AllVMData[0].PublicIP -SSHport $AllVMData[0].SSHPort `
                -testVMUser $global:user -testVMPassword $global:password
        }
		if($global:detectedDistro -imatch "CLEARLINUX") {
			Run-LinuxCmd -Username $global:user -password $global:password -ip $vm.PublicIP -Port $vm.SSHPort `
				-Command "echo 'Subsystem sftp internal-sftp' >> /etc/ssh/sshd_config && sed -i 's/.*ExecStart=.*/ExecStart=\/usr\/sbin\/sshd -D `$OPTIONS -f \/etc\/ssh\/sshd_config/g' /usr/lib/systemd/system/sshd.service && systemctl daemon-reload && systemctl restart sshd.service" -runAsSudo
		}
	}

	if ($CustomKernel) {
		Write-LogInfo "Custom kernel: $CustomKernel will be installed on all machines..."
		$kernelUpgradeStatus = Install-CustomKernel -CustomKernel $CustomKernel -allVMData $AllVMData -RestartAfterUpgrade -TestProvider $TestProvider
		if (!$kernelUpgradeStatus) {
			Write-LogErr "Custom Kernel: $CustomKernel installation FAIL. Aborting tests."
			$retValue = $false
		}
	}
	if ($retValue -and $CustomLIS) {
		# LIS is only available Redhat, CentOS and Oracle image which uses Redhat kernel.
		if(@("REDHAT", "ORACLELINUX", "CENTOS").contains($global:detectedDistro)) {
			Write-LogInfo "Custom LIS: $CustomLIS will be installed on all machines..."
			$LISUpgradeStatus = Install-CustomLIS -CustomLIS $CustomLIS -allVMData $AllVMData `
				-customLISBranch $customLISBranch -RestartAfterUpgrade -TestProvider $TestProvider
			if (!$LISUpgradeStatus) {
				Write-LogErr "Custom LIS: $CustomLIS installation FAIL. Aborting tests."
				$retValue = $false
			}
		} else {
			Write-LogErr "Custom LIS: $CustomLIS installation stopped because UNSUPPORTED distro - $global:detectedDistro"
			$retValue = $false
		}
	}
	if ($retValue -and $EnableSRIOV) {
		$SRIOVStatus = Enable-SRIOVInAllVMs -allVMData $AllVMData -TestProvider $TestProvider
		if (!$SRIOVStatus) {
			Write-LogErr "Failed to enable Accelerated Networking. Aborting tests."
			$retValue = $false
		}
	}
	return $retValue
}

Function Detect-LinuxDistro() {
	param(
		[Parameter(Mandatory=$true)][string]$VIP,
		[Parameter(Mandatory=$true)][string]$SSHPort,
		[Parameter(Mandatory=$true)][string]$testVMUser,
		[string]$testVMPassword
	)

	$global:InitialKernelVersion = Run-LinuxCmd -ip $VIP -port $SSHPort -username $testVMUser -password $testVMPassword -command "uname -r"
	Write-LogInfo "Initial Kernel Version: $global:InitialKernelVersion"
	$null = Copy-RemoteFiles  -upload -uploadTo $VIP -port $SSHport -files ".\Testscripts\Linux\DetectLinuxDistro.sh" -username $testVMUser -password $testVMPassword 2>&1 | Out-Null
	$null = Run-LinuxCmd -username $testVMUser -password $testVMPassword -ip $VIP -port $SSHport -command "chmod +x *.sh" -runAsSudo 2>&1 | Out-Null

	$DistroName = Run-LinuxCmd -username $testVMUser -password $testVMPassword -ip $VIP -port $SSHport -command "bash ./DetectLinuxDistro.sh" -runAsSudo

	if (!$DistroName -or ($DistroName -imatch "Unknown")) {
		Write-LogErr "Linux distro detected : $DistroName"
		# Instead of throw, it sets 'Unknown' if it does not exist
		$CleanedDistroName = "Unknown"
	} else {
		# DistroName must be cleaned of unwanted sudo output
		# like 'sudo: unable to resolve host'
		$CleanedDistroName = $DistroName.Split("`r`n").Trim() | Select-Object -Last 1
		Set-Variable -Name detectedDistro -Value $CleanedDistroName -Scope Global
		Set-DistroSpecificVariables -detectedDistro $detectedDistro
		Write-LogInfo "Linux distro detected: $CleanedDistroName"
	}

	return $CleanedDistroName
}

Function Remove-AllFilesFromHomeDirectory($AllDeployedVMs, $User, $Password)
{
	foreach ($DeployedVM in $AllDeployedVMs)
	{
		$testIP = $DeployedVM.PublicIP
		$testPort = $DeployedVM.SSHPort
		try
		{
			Write-LogInfo "Removing all files logs from IP : $testIP PORT : $testPort"
			$Null = Run-LinuxCmd -username $User -password $Password -ip $testIP -port $testPort -command 'rm -rf *' -runAsSudo
			Write-LogInfo "All files removed from current user $User home folder successfully. VM IP : $testIP PORT : $testPort"
		}
		catch
		{
			$ErrorMessage =  $_.Exception.Message
			Write-Output "EXCEPTION : $ErrorMessage"
			Write-Output "Unable to remove files from IP : $testIP PORT : $testPort"
		}
	}
}

function Get-VMFeatureSupportStatus {
	<#
	.Synopsis
		Check if VM supports a feature or not.
	.Description
		Check if VM supports one feature or not based on comparison
			of current kernel version with feature supported kernel version.
		If the current version is lower than feature supported version,
			return false, otherwise return true.
	.Parameter Ipv4
		IPv4 address of the Linux VM.
	.Parameter SSHPort
		SSH port used to connect to VM.
	.Parameter Username
		Username used to connect to the Linux VM.
	.Parameter Password
		Password used to connect to the Linux VM.
	.Parameter Supportkernel
		The kernel version number starts to support this feature, e.g. supportkernel = "3.10.0.383"
	.Example
		Get-VMFeatureSupportStatus $ipv4 $SSHPort $Username $Password $Supportkernel
	#>

	param (
		[String] $Ipv4,
		[String] $SSHPort,
		[String] $Username,
		[String] $Password,
		[String] $SupportKernel
	)

	Write-Output "yes" | .\Tools\plink.exe -C -pw $Password -P $SSHPort $Username@$Ipv4 'exit 0'
	$currentKernel = Write-Output "yes" | .\Tools\plink.exe -C -pw $Password -P $SSHPort $Username@$Ipv4  "uname -r"
	if ( $LASTEXITCODE -ne 0 ) {
		Write-LogInfo "Warning: Could not get kernel version".
	}
	$sKernel = $SupportKernel.split(".-")
	$cKernel = $currentKernel.split(".-")

	for ($i=0; $i -le 3; $i++) {
		if ($cKernel[$i] -lt $sKernel[$i] ) {
			$cmpResult = $false
			break;
		}
		if ($cKernel[$i] -gt $sKernel[$i] ) {
			$cmpResult = $true
			break
		}
		if ($i -eq 3) { $cmpResult = $True }
	}
	return $cmpResult
}

function Get-SelinuxAVCLog() {
	<#
	.Synopsis
		Check selinux audit.log in Linux VM for avc denied log.
	.Description
		Check audit.log in Linux VM for avc denied log.
		If get avc denied log for hyperv daemons, return $true, else return $false.
	#>

	param (
		[String] $Ipv4,
		[String] $SSHPort,
		[String] $Username,
		[String] $Password
	)
	$result = $null
	$result = Run-LinuxCmd -username $Username -password $Password -ip $Ipv4 -command "[ -f /var/log/audit/audit.log ] || echo 1"  -port $SSHPort -runAsSudo -ignoreLinuxExitCode
	if ($result -eq 1) {
		Write-LogWarn "File audit.log not exist."
		return $false
	}
	$result = $null
	$result = Run-LinuxCmd -username $Username -password $Password -ip $Ipv4 -command "[ -f /var/log/audit/audit.log ] && cat /var/log/audit/audit.log | grep -i 'avc' | grep -E 'hyperv|hv' | wc -l"  -port $SSHPort -runAsSudo -ignoreLinuxExitCode
	if (!$result -and ($result -gt 0)) {
		Write-LogErr "Get the avc denied log"
		return $true
	}

	Write-LogInfo "No avc denied log in audit log as expected"
	return $false
}

function Check-FileInLinuxGuest {
	param (
		[String] $vmPassword,
		[String] $vmPort,
		[string] $vmUserName,
		[string] $ipv4,
		[string] $fileName,
		[boolean] $checkSize = $False ,
		[boolean] $checkContent = $False
	)
	<#
	.Synopsis
		Checks if test file is present or not
	.Description
		Checks if test file is present or not, if set $checkSize as $True, return file size,
		if set checkContent as $True, will return file content.
   #>

	$check = Run-LinuxCmd -username $vmUserName -password $vmPassword -port $vmPort -ip $ipv4 -command "[ -f ${fileName} ] && echo 1 || echo 0"
	if (-not [convert]::ToInt32($check)) {
		Write-Loginfo "File $fileName does not exist."
		return $False
	}
	if ($checkSize) {
		$size = Run-LinuxCmd -username $vmUserName -password $vmPassword -port $vmPort -ip $ipv4 -command "wc -c < $fileName"
		return "$size"
	}
	if ($checkContent) {
		$content = Run-LinuxCmd -username $vmUserName -password $vmPassword -port $vmPort -ip $ipv4 -command "cat ${fileName}"
		return "$content"
	}
	return $True
}

function Mount-Disk{
	param(
		[string] $vmUsername,
		[string] $vmPassword,
		[string] $vmPort,
		[string] $ipv4
	)
<#
	.Synopsis
	Mounts and formats to ext4 a disk on vm
	.Description
	Mounts and formats to ext4 a disk on vm

	#>

	# Get the data disk device name
	$deviceName = Get-DeviceName -ip $ipv4 -port $vmPort -username $vmUsername -password $vmPassword

	$cmdToVM = @"
	#!/bin/bash

	(echo d;echo;echo w)|fdisk $deviceName
	(echo n;echo p;echo 1;echo;echo;echo w)|fdisk $deviceName
	if [ `$? -ne 0 ];then
		echo "Failed to create partition..."
		exit 1
	fi
	mkfs.ext4 ${deviceName}1
	mkdir -p /mnt/test
	mount ${deviceName}1 /mnt/test
	if [ `$? -ne 0 ];then
		echo "Failed to mount partition to /mnt/test..."
		exit 1
	fi
"@
	$filename = "MountDisk.sh"
	if (Test-Path ".\${filename}") {
		Remove-Item ".\${filename}"
	}
	Add-Content $filename "$cmdToVM"
	Copy-RemoteFiles -uploadTo $ipv4 -port $vmPort -files $filename -username $vmUsername -password $vmPassword -upload
	$null = Run-LinuxCmd -username $vmUsername -password $vmPassword -ip $ipv4 -port $vmPort -command  `
	"chmod u+x ${filename} && ./${filename}" -runAsSudo
	if ($?) {
		Write-LogInfo "Mounted ${deviceName}1 to /mnt/test"
		return $True
	}
}

function Remove-TestFile {
	param(
		[String] $pathToFile,
		[String] $testfile
	)
<#
	.Synopsis
	Delete temporary test file
	.Description
	Delete temporary test file

	#>

	Remove-Item -Path $pathToFile -Force
	if ($? -ne "True") {
		Write-LogErr "cannot remove the test file '${testfile}'!"
		return $False
	}
}

function Get-RemoteFileInfo {
	param (
		[String] $filename,
		[String] $server
	)

	$fileInfo = $null

	if (-not $filename)
	{
		return $null
	}

	if (-not $server)
	{
		return $null
	}

	$remoteFilename = $filename.Replace("\", "\\")
	$fileInfo = Get-WmiObject -query "SELECT * FROM CIM_DataFile WHERE Name='${remoteFilename}'" -computer $server

	return $fileInfo
}

function Check-Systemd {
	param (
		[String] $Ipv4,
		[String] $SSHPort,
		[String] $Username,
		[String] $Password
	)

	$check1 = $true
	$check2 = $true

	Write-Output "yes" | .\Tools\plink.exe -C -pw $Password -P $SSHPort $Username@$Ipv4 "ls -l /sbin/init | grep systemd"
	if ($LASTEXITCODE -gt "0") {
	Write-LogInfo "Systemd not found on VM"
	$check1 = $false
	}
	Write-Output "yes" | .\Tools\plink.exe -C -pw $Password -P $SSHPort $Username@$Ipv4 "systemd-analyze --help"
	if ($LASTEXITCODE -gt "0") {
		Write-LogInfo "Systemd-analyze not present on VM."
		$check2 = $false
	}

	return ($check1 -and $check2)
}


function Wait-ForVMToStartSSH {
	#  Wait for a Linux VM to start SSH. This is done by testing
	# if the target machine is listening on port 22.
	param (
		[String] $Ipv4addr,
		[int] $StepTimeout
	)
	$retVal = $False

	$waitTimeOut = $StepTimeout
	while ($waitTimeOut -gt 0) {
		$sts = Test-Port -ipv4addr $Ipv4addr -timeout 5
		if ($sts) {
			return $True
		}

		$waitTimeOut -= 15  # Note - Test Port will sleep for 5 seconds
		Start-Sleep -Seconds 10
	}

	if (-not $retVal) {
		Write-LogErr "Wait-ForVMToStartSSH: VM did not start SSH within timeout period ($StepTimeout)"
	}

	return $retVal
}

function Test-Port {
	# Test if a remote host is listening on a specific TCP port
	# Wait only timeout seconds.
	param (
		[String] $Ipv4addr,
		[String] $PortNumber=22,
		[int] $Timeout=5
	)

	$retVal = $False
	$to = $Timeout * 1000

	# Try an async connect to the specified machine/port
	$tcpClient = New-Object system.Net.Sockets.TcpClient
	$iar = $tcpclient.BeginConnect($Ipv4addr,$PortNumber,$null,$null)

	# Wait for the connect to complete. Also set a timeout
	# so we don't wait all day
	$connected = $iar.AsyncWaitHandle.WaitOne($to,$false)

	# Check to see if the connection is done
	if ($connected) {
		# Close our connection
		try {
			$Null = $tcpclient.EndConnect($iar)
			$retVal = $true
		} catch {
			Write-LogInfo $_.Exception.Message
		}
	}
	$tcpclient.Close()

	return $retVal
}

Function Test-SRIOVInLinuxGuest {
	param (
		#Required
		[string]$username,
		[string]$password,
		[string]$IpAddress,
		[int]$SSHPort,

		#Optional
		[int]$ExpectedSriovNics
	)

	$MaximumAttempts = 10
	$Attempts = 1
	$VerificationCommand = "lspci | grep Mellanox | wc -l"
	$retValue = $false
	while ($retValue -eq $false -and $Attempts -le $MaximumAttempts) {
		Write-LogInfo "[Attempt $Attempts/$MaximumAttempts] Detecting Mellanox NICs..."
		$DetectedSRIOVNics = Run-LinuxCmd -username $username -password $password -ip $IpAddress -port $SSHPort -command $VerificationCommand -runAsSudo
		$DetectedSRIOVNics = [int]$DetectedSRIOVNics[-1].ToString()
		if ($ExpectedSriovNics -ge 0) {
			if ($DetectedSRIOVNics -eq $ExpectedSriovNics) {
				$retValue = $true
				Write-LogInfo "$DetectedSRIOVNics Mellanox NIC(s) detected in VM. Expected: $ExpectedSriovNics."
			} else {
				$retValue = $false
				Write-LogErr "$DetectedSRIOVNics Mellanox NIC(s) detected in VM. Expected: $ExpectedSriovNics."
				Start-Sleep -Seconds 20
			}
		} else {
			if ($DetectedSRIOVNics -gt 0) {
				$retValue = $true
				Write-LogInfo "$DetectedSRIOVNics Mellanox NIC(s) detected in VM."
			} else {
				$retValue = $false
				Write-LogErr "$DetectedSRIOVNics Mellanox NIC(s) detected in VM."
				Start-Sleep -Seconds 20
			}
		}
		$Attempts += 1
	}
	return $retValue
}

Function Set-SRIOVInVMs {
    param (
        [object]$AllVMData,
        [string]$VMNames,
        [switch]$Enable,
        [switch]$Disable
    )

    if ( $TestPlatform -eq "Azure") {
        Write-LogInfo "Set-SRIOVInVMs running in 'Azure' mode."
        if ($Enable) {
            if ($VMNames) {
                $retValue = Set-SRIOVinAzureVMs -AllVMData $AllVMData -VMNames $VMNames -Enable
            }
            else {
                $retValue = Set-SRIOVinAzureVMs -AllVMData $AllVMData -Enable
            }
        }
        elseif ($Disable) {
            if ($VMNames) {
                $retValue = Set-SRIOVinAzureVMs -AllVMData $AllVMData -VMNames $VMNames -Disable
            }
            else {
                $retValue = Set-SRIOVinAzureVMs -AllVMData $AllVMData -Disable
            }
        }
    }
    elseif ($TestPlatform -eq "HyperV") {
        <#
        ####################################################################
        # Note: Function Set-SRIOVinHypervVMs needs to be implemented in HyperV.psm1.
        # It should allow the same parameters as implemented for Azure.
        #   -HyperVGroup [string]
        #   -VMNames [string] ... comma separated VM names. [Optional]
        #        If no VMNames is provided, it should pick all the VMs from HyperVGroup
        #   -Enable
        #   -Disable
        ####################################################################
        Write-LogInfo "Set-SRIOVInVMs running in 'HyperV' mode."
        if ($Enable) {
            if ($VMNames) {
                $retValue = Set-SRIOVinHypervVMs -HyperVGroup $VirtualMachinesGroupName -VMNames $VMNames -Enable
            }
            else {
                $retValue = Set-SRIOVinHypervVMs -HyperVGroup $VirtualMachinesGroupName -Enable
            }
        }
        elseif ($Disable) {
            if ($VMNames) {
                $retValue = Set-SRIOVinHypervVMs -HyperVGroup $VirtualMachinesGroupName -VMNames $VMNames -Disable
            }
            else {
                $retValue = Set-SRIOVinHypervVMs -HyperVGroup $VirtualMachinesGroupName -Disable
            }
        }
        #>
        $retValue = $false
    }
    return $retValue
}


# Returns an unused random MAC capable
# The address will be outside of the dynamic MAC pool
# Note that the Manufacturer bytes (first 3 bytes) are also randomly generated
function Get-RandUnusedMAC {
    param (
        [String] $HvServer,
        [Char] $Delim
    )
    # First get the dynamic pool range
    $dynMACStart = (Get-VMHost -ComputerName $HvServer).MacAddressMinimum
    $validMac = Is-ValidMAC $dynMACStart
    if (-not $validMac) {
        return $false
    }

    $dynMACEnd = (Get-VMHost -ComputerName $HvServer).MacAddressMaximum
    $validMac = Is-ValidMAC $dynMACEnd
    if (-not $validMac) {
        return $false
    }

    [uint64]$lowerDyn = "0x$dynMACStart"
    [uint64]$upperDyn = "0x$dynMACEnd"
    if ($lowerDyn -gt $upperDyn) {
        return $false
    }

    # leave out the broadcast address
    [uint64]$maxMac = 281474976710655 #FF:FF:FF:FF:FF:FE

    # now random from the address space that has more macs
    [uint64]$belowPool = $lowerDyn - [uint64]1
    [uint64]$abovePool = $maxMac - $upperDyn

    if ($belowPool -gt $abovePool) {
        [uint64]$randStart = [uint64]1
        [uint64]$randStop = [uint64]$lowerDyn - [uint64]1
    } else {
        [uint64]$randStart = $upperDyn + [uint64]1
        [uint64]$randStop = $maxMac
    }

    # before getting the random number, check all VMs for static MACs
    $staticMacs = (get-VM -computerName $hvServer | Get-VMNetworkAdapter | Where-Object { $_.DynamicMacAddressEnabled -like "False" }).MacAddress
    do {
        # now get random number
        [uint64]$randDecAddr = Get-Random -minimum $randStart -maximum $randStop
        [String]$randAddr = "{0:X12}" -f $randDecAddr

        # Now set the unicast/multicast flag bit.
        [Byte] $firstbyte = "0x" + $randAddr.substring(0,2)
        # Set low-order bit to 0: unicast
        $firstbyte = [Byte] $firstbyte -band [Byte] 254 #254 == 11111110

        $randAddr = ("{0:X}" -f $firstbyte).padleft(2,"0") + $randAddr.substring(2)

    } while ($staticMacs -contains $randAddr) # check that we didn't random an already assigned MAC Address

    # randAddr now contains the new random MAC Address
    # add delim if specified
    if ($Delim) {
        for ($i = 2 ; $i -le 14 ; $i += 3) {
            $randAddr = $randAddr.insert($i,$Delim)
        }
    }

    $validMac = Is-ValidMAC $randAddr
    if (-not $validMac) {
        return $false
    }

    return $randAddr
}

function Start-VMandGetIP {
    param (
        $VMName,
        $HvServer,
        $VMPort,
        $VMUserName,
        $VMPassword
    )
    $newIpv4 = $null

    Start-VM -Name $VMName -ComputerName $HvServer
    if (-not $?) {
        Write-LogErr "Failed to start VM $VMName on $HvServer"
        return $False
    } else {
        Write-LogInfo "$VMName started on $HvServer"
    }

    # Wait for VM to boot
    $newIpv4 = Get-Ipv4AndWaitForSSHStart $VMName $HvServer $VMPort $VMUserName `
                $VMPassword 300
    if ($null -ne $newIpv4) {
        Write-LogInfo "$VMName IP address: $newIpv4"
        return $newIpv4
    } else {
        Write-LogErr "Failed to get IP of $VMName on $HvServer"
        return $False
    }
}

# Generates an unused IP address based on an old IP address.
function Generate-IPv4{
    param (
        $TempIpv4,
        $OldIpv4
    )
    [int]$check = $null

    if ($null -eq $OldIpv4) {
        [int]$octet = 102
    } else {
        $oldIpPart = $OldIpv4.Split(".")
        [int]$octet  = $oldIpPart[3]
    }

    $ipPart = $TempIpv4.Split(".")
    $newAddress = ($ipPart[0]+"."+$ipPart[1]+"."+$ipPart[2])

    while ($check -ne 1 -and $octet -lt 255) {
        $octet = 1 + $octet
        if (!(Test-Connection "$newAddress.$octet" -Count 1 -Quiet)) {
            $splitIp = $newAddress + "." + $octet
            $check = 1
        }
    }

    return $splitIp.ToString()
}

# CIDR to netmask
function Convert-CIDRtoNetmask{
    param (
        [int]$CIDR
    )
    $mask = ""

    for ($i=0; $i -lt 32; $i+=1) {
        if ($i -lt $CIDR) {
            $ip+="1"
        }else{
            $ip+= "0"
        }
    }
    for ($byte=0; $byte -lt $ip.Length/8; $byte+=1) {
        $decimal = 0
        for ($bit=0;$bit -lt 8; $bit+=1) {
            $poz = $byte * 8 + $bit
            if ($ip[$poz] -eq "1") {
                $decimal += [math]::Pow(2, 8 - $bit -1)
            }
        }
        $mask +=[convert]::ToString($decimal)
        if ($byte -ne $ip.Length /8 -1) {
             $mask += "."
        }
    }
    return $mask
}

function Set-GuestInterface {
    param (
        $VMUser,
        $VMIpv4,
        $VMPort,
        $VMPassword,
        $InterfaceMAC,
        $VMStaticIP,
        $Bootproto,
        $Netmask,
        $VMName,
        $VlanID
    )

    Copy-RemoteFiles -upload -uploadTo $VMIpv4 -Port $VMPort `
        -files ".\Testscripts\Linux\utils.sh" -Username $VMUser -password $VMPassword
    if (-not $?) {
        Write-LogErr "Failed to send utils.sh to VM!"
        return $False
    }

    # Configure NIC on the guest
    Write-LogInfo "Configuring test interface ($InterfaceMAC) on $VMName ($VMIpv4)"
    # Get the interface name that corresponds to the MAC address
    $cmdToSend = "testInterface=`$(grep -il ${InterfaceMAC} /sys/class/net/*/address) ; basename `"`$(dirname `$testInterface)`""
    $testInterfaceName = Run-LinuxCmd -username $VMUser -password $VMPassword -ip $VMIpv4 -port $VMPort `
        -command $cmdToSend -runAsSudo
    if (-not $testInterfaceName) {
        Write-LogErr "Failed to get the interface name that has $InterfaceMAC MAC address"
        return $False
    } else {
        Write-LogInfo "The interface that will be configured on $VMName is $testInterfaceName"
    }
    $configFunction = "CreateIfupConfigFile"
    if ($VlanID) {
        $configFunction = "CreateVlanConfig"
    }

    # Configure the interface
    $cmdToSend = ". utils.sh; $configFunction $testInterfaceName $Bootproto $VMStaticIP $Netmask $VlanID"
    Run-LinuxCmd -username $VMUser -password $VMPassword -ip $VMIpv4 -port $VMPort -command $cmdToSend `
    -runAsSudo
    if (-not $?) {
        Write-LogErr "Failed to configure $testInterfaceName NIC on vm $VMName"
        return $False
    }
    Write-LogInfo "Successfully configured $testInterfaceName on $VMName"
    return $True
}

function Test-GuestInterface {
    param (
        $VMUser,
        $AddressToPing,
        $VMIpv4,
        $VMPort,
        $VMPassword,
        $InterfaceMAC,
        $PingVersion,
        $PacketNumber,
        $Vlan
    )

    $nicPath = "/sys/class/net/*/address"
    if ($Vlan -eq "yes") {
        $nicPath = "/sys/class/net/*.*/address"
    }
    $cmdToSend = "testInterface=`$(grep -il ${InterfaceMAC} ${nicPath}) ; basename `"`$(dirname `$testInterface)`""
    $testInterfaceName = Run-LinuxCmd -username $VMUser -password $VMPassword -ip $VMIpv4 -port $VMPort `
        -command $cmdToSend -runAsSudo

    $cmdToSend = "$PingVersion -I $testInterfaceName $AddressToPing -c $PacketNumber -p `"cafed00d00766c616e0074616700`""
    $pingResult = Run-LinuxCmd -username $VMUser -password $VMPassword -ip $VMIpv4 -port $VMPort `
        -command $cmdToSend -ignoreLinuxExitCode:$true -runAsSudo

    if ($pingResult -notMatch "$PacketNumber received") {
        return $False
    }
    return $True
}

#Check if stress-ng is installed
Function Is-StressNgInstalled {
    param (
        [String] $VMIpv4,
        [String] $VMSSHPort
    )

    $cmdToVM = @"
#!/bin/bash
        command -v stress-ng
        sts=`$?
        exit `$sts
"@
    #"pingVMs: sending command to vm: $cmdToVM"
    $FILE_NAME  = "CheckStress-ng.sh"
    Set-Content $FILE_NAME "$cmdToVM"
    # send file
    Copy-RemoteFiles -uploadTo $VMIpv4 -port $VMSSHPort -files $FILE_NAME -username $user -password $password -upload
    # execute command
    $retVal = Run-LinuxCmd -username $user -password $password -ip $VMIpv4 -port $VMSSHPort `
        -command "echo $password | cd /home/$user && chmod u+x ${FILE_NAME} && sed -i 's/\r//g' ${FILE_NAME} && ./${FILE_NAME}" -runAsSudo
    return $retVal
}

# function for starting stress-ng
Function Start-StressNg {
    param (
        [String] $VMIpv4,
        [String] $VMSSHPort
    )
    Write-LogInfo "IP is $VMIpv4"
    Write-LogInfo "port is $VMSSHPort"
      $cmdToVM = @"
#!/bin/bash
        __freeMem=`$(cat /proc/meminfo | grep -i MemFree | awk '{ print `$2 }')
        __freeMem=`$((__freeMem/1024))
        echo ConsumeMemory: Free Memory found `$__freeMem MB >> /home/$user/HotAdd.log 2>&1
        __threads=32
        __chunks=`$((`$__freeMem / `$__threads))
        echo "Going to start `$__threads instance(s) of stress-ng every 2 seconds, each consuming 128MB memory" >> /home/$user/HotAdd.log 2>&1
        stress-ng -m `$__threads --vm-bytes `${__chunks}M -t 120 --backoff 1500000
        echo "Waiting for jobs to finish" >> /home/$user/HotAdd.log 2>&1
        wait
        exit 0
"@
    #"pingVMs: sending command to vm: $cmdToVM"
    $FILE_NAME = "ConsumeMem.sh"
    Set-Content $FILE_NAME "$cmdToVM"
    # send file
    Copy-RemoteFiles -uploadTo $VMIpv4 -port $VMSSHPort -files $FILE_NAME `
        -username $user -password $password -upload
    # execute command as job
    $retVal = Run-LinuxCmd -username $user -password $password -ip $VMIpv4 -port $VMSSHPort `
        -command "echo $password | cd /home/$user && chmod u+x ${FILE_NAME} && sed -i 's/\r//g' ${FILE_NAME} && ./${FILE_NAME}" -runAsSudo -RunInBackground
    return $retVal
}
# This function runs the remote script on VM.
# It checks the state of execution of remote script
Function Invoke-RemoteScriptAndCheckStateFile
{
    param (
        $remoteScript,
        $VMUser,
        $VMPassword,
        $VMIpv4,
        $VMPort
        )
    $stateFile = "${remoteScript}.state.txt"
    $Hypervcheck = "echo '${VMPassword}' | sudo -S -s eval `"export HOME=``pwd``;bash ${remoteScript} > ${remoteScript}.log`""
    Run-LinuxCmd -username $VMUser -password $VMPassword -ip $VMIpv4 -port $VMPort $Hypervcheck -runAsSudo
    Copy-RemoteFiles -download -downloadFrom $VMIpv4 -files "./state.txt" `
        -downloadTo $LogDir -port $VMPort -username $VMUser -password $password
    Copy-RemoteFiles -download -downloadFrom $VMIpv4 -files "./${remoteScript}.log" `
        -downloadTo $LogDir -port $VMPort -username $VMUser -password $VMPassword
    Move-Item -Path "${LogDir}\state.txt" -Destination "${LogDir}\$stateFile" -Force
    $contents = Get-Content -Path $LogDir\$stateFile
    if (($contents -eq "TestAborted") -or ($contents -eq "TestFailed")) {
        return $False
    }
    return $True
}


#This function does hot add/remove of Max NICs
function Test-MaxNIC {
    param(
    $vmName,
    $hvServer,
    $switchName,
    $actionType,
    [int] $nicsAmount
    )
    for ($i=1; $i -le $nicsAmount; $i++)
    {
    $nicName = "External" + $i

    if ($actionType -eq "add")
    {
        Write-LogInfo "Ensure the VM does not have a Synthetic NIC with the name '${nicName}'"
        $null = Get-VMNetworkAdapter -vmName $vmName -Name "${nicName}" -ComputerName $hvServer -ErrorAction SilentlyContinue
        if ($?)
        {
        Write-LogErr "VM '${vmName}' already has a NIC named '${nicName}'"
        }
    }

    Write-LogInfo "Hot '${actionType}' a synthetic NIC with name of '${nicName}' using switch '${switchName}'"
    Write-LogInfo "Hot '${actionType}' '${switchName}' to '${vmName}'"
    if ($actionType -eq "add")
    {
        Add-VMNetworkAdapter -VMName $vmName -SwitchName $switchName -ComputerName $hvServer -Name ${nicName} #-ErrorAction SilentlyContinue
    }
    else
    {
        Remove-VMNetworkAdapter -VMName $vmName -Name "${nicName}" -ComputerName $hvServer -ErrorAction SilentlyContinue
    }
    if (-not $?)
    {
        Write-LogErr "Unable to Hot '${actionType}' NIC to VM '${vmName}' on server '${hvServer}'"
        }
    }
}

# This function is used for generating load using Stress NG tool
function Get-MemoryStressNG([String]$VMIpv4, [String]$VMSSHPort, [int]$timeoutStress, [int64]$memMB, [int]$duration, [int64]$chunk)
{
    Write-LogInfo "Get-MemoryStressNG started to generate memory load"
    $cmdToVM = @"
#!/bin/bash
        if [ ! -e /proc/meminfo ]; then
          echo "ConsumeMemory: no meminfo found. Make sure /proc is mounted" >> /home/$user/HotAdd.log 2>&1
          exit 100
        fi

        rm ~/HotAddErrors.log -f
        __totalMem=`$(cat /proc/meminfo | grep -i MemTotal | awk '{ print `$2 }')
        __totalMem=`$((__totalMem/1024))
        echo "ConsumeMemory: Total Memory found `$__totalMem MB" >> /home/$user/HotAdd.log 2>&1
        declare -i __chunks
        declare -i __threads
        declare -i duration
        declare -i timeout
        if [ $chunk -le 0 ]; then
            __chunks=128
        else
            __chunks=512
        fi
        __threads=`$(($memMB/__chunks))
        if [ $timeoutStress -eq 0 ]; then
            timeout=10000000
            duration=`$((10*__threads))
        elif [ $timeoutStress -eq 1 ]; then
            timeout=5000000
            duration=`$((5*__threads))
        elif [ $timeoutStress -eq 2 ]; then
            timeout=1000000
            duration=`$__threads
        else
            timeout=1
            duration=30
            __threads=4
            __chunks=2048
        fi

        if [ $duration -ne 0 ]; then
            duration=$duration
        fi
        echo "Stress-ng info: `$__threads threads :: `$__chunks MB chunk size :: `$((`$timeout/1000000)) seconds between chunks :: `$duration seconds total stress time" >> /root/HotAdd.log 2>&1
        stress-ng -m `$__threads --vm-bytes `${__chunks}M -t `$duration --backoff `$timeout
        echo "Waiting for jobs to finish" >> /home/$user/HotAdd.log 2>&1
        wait
        exit 0
"@

    $FILE_NAME = "ConsumeMem.sh"
    Set-Content $FILE_NAME "$cmdToVM"
    # send file
    Copy-RemoteFiles -uploadTo $VMIpv4 -port $VMSSHPort -files $FILE_NAME -username $user -password $password -upload
    Write-LogInfo "Copy-RemoteFiles done"
    # execute command
    $sendCommand = "echo $password | cd /home/$user && chmod u+x ${FILE_NAME} && sed -i 's/\r//g' ${FILE_NAME} && ./${FILE_NAME}"
    $retVal = Run-LinuxCmd -username $user -password $password -ip $VMIpv4 -port $VMSSHPort -command $sendCommand -runAsSudo -RunInBackground
    return $retVal
}

# This function installs Stress NG/Stress APP
Function Publish-App([string]$appName, [string]$customIP, [string]$appGitURL, [string]$appGitTag,[String] $VMSSHPort)
{
    # check whether app is already installed
    if ($null -eq $appGitURL) {
        Write-LogErr "$appGitURL is not set"
        return $False
    }
    # Install dependencies
    Copy-RemoteFiles -upload -uploadTo $customIP -port $VMSSHPort -files ".\Testscripts\Linux\utils.sh" `
        -username $user -password $password 2>&1
    $cmd = ". utils.sh && update_repos && install_package 'make build-essential'"
    if (($global:detectedDistro -imatch "CENTOS") -or ($global:detectedDistro -imatch "REDHAT") ) {
        $cmd = ". utils.sh && update_repos && install_package 'make kernel-devel gcc-c++'"
    }
    $null = Run-LinuxCmd -username $user -password $password -ip $customIP -port $VMSSHPort -command $cmd -runAsSudo
    $retVal = Run-LinuxCmd -username $user -password $password -ip $customIP -port $VMSSHPort `
        -command "echo $password | sudo -S cd /root; git clone $appGitURL $appName > /dev/null 2>&1"
    if ($appGitTag) {
        $retVal = Run-LinuxCmd -username $user -password $password -ip $customIP -port $VMSSHPort `
        -command "cd $appName; git checkout tags/$appGitTag > /dev/null 2>&1"
    }
    if ($appName -eq "stress-ng") {
        $appInstall = "cd $appName; echo '${password}' | sudo -S make install"
        $retVal = Run-LinuxCmd -username $user -password $password -ip $customIP -port $VMSSHPort `
             -command $appInstall
    }
    else {
    $appInstall = "cd $appName;./configure;make;echo '${password}' | sudo -S make install"
    $retVal = Run-LinuxCmd -username $user -password $password -ip $customIP -port $VMSSHPort `
        -command $appInstall
    }
    Write-LogInfo "App $appName installation is completed"
    return $retVal
}

#######################################################################
# Fix snapshots. If there are more than one remove all except latest.
#######################################################################
function Restore-LatestVMSnapshot($vmName, $hvServer)
{
    # Get all the snapshots
    $vmsnapshots = Get-VMSnapshot -VMName $vmName -ComputerName $hvServer
    $snapnumber = ${vmsnapshots}.count
    # Get latest snapshot
    $latestsnapshot = Get-VMSnapshot -VMName $vmName -ComputerName $hvServer | Sort-Object CreationTime | Select-Object -Last 1
    $LastestSnapName = $latestsnapshot.name
    # Delete all snapshots except the latest
    if (1 -lt $snapnumber) {
        Write-LogInfo "$vmName has $snapnumber snapshots. Removing all except $LastestSnapName"
        foreach ($snap in $vmsnapshots) {
            if ($snap.id -ne $latestsnapshot.id) {
                $snapName = ${snap}.Name
                $sts = Remove-VMSnapshot -Name $snap.Name -VMName $vmName -ComputerName $hvServer
                if (-not $?) {
                    Write-LogErr "Unable to remove snapshot $snapName of ${vmName}: `n${sts}"
                    return $False
                }
                Write-LogInfo "Removed snapshot $snapName"
            }
        }
    }
    # If there are no snapshots, create one.
    ElseIf (0 -eq $snapnumber) {
        Write-LogInfo "There are no snapshots for $vmName. Creating one..."
        $sts = Checkpoint-VM -VMName $vmName -ComputerName $hvServer
        if (-not $?) {
           Write-LogErr "Unable to create snapshot of ${vmName}: `n${sts}"
           return $False
        }
    }
    return $True
}

function Compare-KernelVersion {
    param (
        [string] $KernelVersion1,
        [string] $KernelVersion2
    )

    if ($KernelVersion1 -eq $KernelVersion2) {
        return 0
    }

    $KernelVersion1Array = $KernelVersion1 -split "[\.\-]+"
    $KernelVersion2Array = $KernelVersion2 -split "[\.\-]+"
    for($i=0; $i -lt $KernelVersion1Array.Length; $i++) {
        try {
                $KernelVersion1Array[$i] = [int]$KernelVersion1Array[$i]
            } catch {
                $KernelVersion1Array[$i] = 0
                continue
            }
    }
    for($i=0; $i -lt $KernelVersion2Array.Length;$i++) {
        try {
                $KernelVersion2Array[$i] = [int]$KernelVersion2Array[$i]
            } catch {
                $KernelVersion2Array[$i] = 0
                continue
            }
    }

    $array_count = $KernelVersion1Array.Length
    if ($KernelVersion1Array.Length -gt $KernelVersion2Array.Length) {
        $array_count = $KernelVersion2Array.Length
    }

    for($i=0; $i -lt $array_count;$i++) {
        if ([int]$KernelVersion1Array[$i] -eq [int]$KernelVersion2Array[$i]) {
            continue
        } elseif ([int]$KernelVersion1Array[$i] -lt [int]$KernelVersion2Array[$i]) {
            return -1
        } else {
            return 1
        }
    }

    return -1
}


function Is-DpdkCompatible() {
    param (
        [string] $KernelVersion,
        [string] $DetectedDistro,
        [string] $CompatibleDistro
    )

    if ($CompatibleDistro) {
        if ($CompatibleDistro.Contains($DetectedDistro)) {
            Write-LogInfo "Confirmed supported distro: $DetectedDistro"
            return $true
        } else {
            Write-LogWarn "Unsupported distro: $DetectedDistro"
            return $false
        }
    } else {
        # Supported Distro and kernel version for DPDK on Azure
        # https://docs.microsoft.com/en-us/azure/virtual-network/setup-dpdk
        $SUPPORTED_DISTRO_KERNEL = @{
            "UBUNTU" = "4.15.0-1015-azure";
            "SLES 15" = "4.12.14-5.5-azure";
            "SUSE" = "4.12.14-5.5-azure";
            "REDHAT" = "3.10.0-862.9.1.el7";
            "CENTOS" = "3.10.0-862.3.3.el7";
        }

        if ($SUPPORTED_DISTRO_KERNEL.Keys -contains $DetectedDistro) {
            if ((Compare-KernelVersion $KernelVersion $SUPPORTED_DISTRO_KERNEL[$DetectedDistro]) -ge 0) {
                return $true
            } else {
                 return $false
            }
        } else {
            Write-LogWarn "Unsupported Distro: $DetectedDistro"
            return $false
        }
    }
}

Function Download-File {
    param (
        [string] $URL,
        [string] $FilePath
    )
    try {
        $DownloadID = New-TestID
        if ($FilePath) {
            $FileName = $FilePath | Split-Path -Leaf
            $ParentFolder = $FilePath | Split-Path -Parent
        } else {
            $FileName = $URL | Split-Path -Leaf
            $ParentFolder = ".\DownloadedFiles"
            $FilePath = Join-Path $ParentFolder $FileName
        }
        $TempFilePath = "$FilePath.$DownloadID.LISAv2Download"
        if (!(Test-Path $ParentFolder)) {
            [void](New-Item -Path $ParentFolder -Type Directory)
        }
        Write-LogInfo "Downloading '$URL' to '$TempFilePath'"
        try {
            $DownloadJob = Start-BitsTransfer -Source "$URL" -Asynchronous -Destination "$TempFilePath" `
                -TransferPolicy Unrestricted -TransferType Download -Priority Foreground
            $BitsStarted = $true
        } catch {
            $BitsStarted = $false
        }
        if ( $BitsStarted ) {
            $jobStatus = Get-BitsTransfer -JobId $DownloadJob.JobId
            Start-Sleep -Seconds 1
            Write-LogInfo "JobID: $($DownloadJob.JobId)"
            while ($jobStatus.JobState -eq "Connecting" -or $jobStatus.JobState -eq "Transferring" -or `
                    $jobStatus.JobState -eq "Queued" -or $jobStatus.JobState -eq "TransientError" ) {
                $DownloadProgress = 100 - ((($jobStatus.BytesTotal - $jobStatus.BytesTransferred) / $jobStatus.BytesTotal) * 100)
                $DownloadProgress = [math]::Round($DownloadProgress, 2)
                if (($DownloadProgress % 5) -lt 1) {
                    Write-LogInfo "Download '$($jobStatus.JobState)': $DownloadProgress%"
                }
                Start-Sleep -Seconds 1
            }
            if ($jobStatus.JobState -eq "Transferred") {
                Write-LogInfo "Download '$($jobStatus.JobState)': 100%"
                Write-LogInfo "Finalizing downloaded file..."
                Complete-BitsTransfer -BitsJob $DownloadJob
                Write-LogInfo "Renaming $($TempFilePath | Split-Path -Leaf) --> $($FilePath | Split-Path -Leaf)..."
                if ( -not ( Rename-File -OriginalFilePath $TempFilePath -NewFilePath $FilePath ) ) {
                    Throw "Unable to rename downloaded file."
                } else {
                    Write-LogInfo "Download Status: Completed."
                }
            } else {
                Write-LogInfo "Download status : $($jobStatus.JobState)"
                [void](Remove-Item -Path $TempFilePath -ErrorAction SilentlyContinue -Force)
            }
        } else {
            Write-LogInfo "BITS service is not available. Downloading via HTTP request."
            $request = [System.Net.HttpWebRequest]::Create($URL)
            $request.set_Timeout(5000) # 5 second timeout
            $response = $request.GetResponse()
            $TotalBytes = $response.ContentLength
            $ResponseStream = $response.GetResponseStream()

            $buffer = New-Object -TypeName byte[] -ArgumentList 256KB
            $TargetStream = [System.IO.File]::Create($TempFilePath)

            $timer = New-Object -TypeName timers.timer
            $timer.Interval = 1000 # Update progress every second
            $TimerEvent = Register-ObjectEvent -InputObject $timer -EventName Elapsed -Action {
                $Global:UpdateProgress = $true
                if ( $Global:UpdateProgress ) {
                    # $Global:UpdateProgress is used below but still PSScriptAnalyser is giving error -
                    # Unused variable : "$Global:UpdateProgress".
                    # Hence added this blank if condition to suppress the error.
                }
            }
            $timer.Start()

            do {
                $count = $ResponseStream.Read($buffer, 0, $buffer.length)
                $TargetStream.Write($buffer, 0, $count)
                $downloaded_bytes = $downloaded_bytes + $count
                $percent = $downloaded_bytes / $TotalBytes
                if ($Global:UpdateProgress) {
                    $status = @{
                        completed  = "{0,6:p2} Completed" -f $percent
                        downloaded = "{0:n0} MB of {1:n0} MB" -f ($downloaded_bytes / 1MB), ($TotalBytes / 1MB)
                        speed      = "{0,7:n0} KB/s" -f (($downloaded_bytes - $prev_downloaded_bytes) / 1KB)
                        eta        = "ETA {0:hh\:mm\:ss}" -f (New-TimeSpan -Seconds (($TotalBytes - $downloaded_bytes) / ($downloaded_bytes - $prev_downloaded_bytes)))
                    }
                    $progress_args = @{
                        Activity        = "Downloading $URL"
                        Status          = "$($status.completed) ($($status.downloaded)) $($status.speed) $($status.eta)"
                        PercentComplete = [math]::Round( ($percent * 100),2)
                    }
                    if (($progress_args.PercentComplete % 5)-lt 1) {
                        Write-LogInfo "Download Status: $($progress_args.PercentComplete)% ($($status.downloaded)) $($status.speed) $($status.eta)"
                    }
                    $prev_downloaded_bytes = $downloaded_bytes
                    $Global:UpdateProgress = $false
                }
            } while ($count -gt 0)
            if (Test-Path $TempFilePath) {
                Write-LogInfo "Download Status: 100%"
                if ($TargetStream) { $TargetStream.Dispose() }
                if ($response) { $response.Dispose() }
                if ($ResponseStream) { $ResponseStream.Dispose() }
                Write-LogInfo "Renaming $($TempFilePath | Split-Path -Leaf) --> $($FilePath | Split-Path -Leaf)..."
                if ( -not ( Rename-File -OriginalFilePath $TempFilePath -NewFilePath $FilePath ) ) {
                    Throw "Unable to rename downloaded file."
                } else {
                    Write-LogInfo "Download Status: Completed."
                }
            } else {
                Throw "Unable to find downloaded file $TempFilePath."
            }
        }
    }
    catch {
        $line = $_.InvocationInfo.ScriptLineNumber
        $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
        $ErrorMessage = $_.Exception.Message
        Write-LogErr "EXCEPTION : $ErrorMessage"
        Write-LogErr "Source : Download-File() Line $line in script $script_name."
    }
    finally {
        if ($BitsStarted) {
            if ($jobStatus.JobState -eq "Connecting" -or $jobStatus.JobState -eq "Transferring" -or `
            $jobStatus.JobState -eq "Queued" -or $jobStatus.JobState -eq "TransientError" ) {
                Write-LogErr "User aborted the download process. Removing unfinished BITS job : $($jobStatus.JobId)"
                $jobStatus | Remove-BitsTransfer
            }
        } else {
            if ($timer) { $timer.Stop() }
            if ($TimerEvent) {
                Get-EventSubscriber | Where-Object { $_.SourceIdentifier -eq $TimerEvent.Name} `
                    | Unregister-Event -Force
            }
            if ($TargetStream) { $TargetStream.Dispose() }
            # If file exists and $count is not zero or $null, then script was interrupted by user
            if ((Test-Path $TempFilePath) -and $count) {
                Write-LogErr "User aborted the download process. Removing unfinished file $TempFilePath"
                [void] (Remove-Item -Path $TempFilePath -Force -ErrorAction SilentlyContinue)
            }
            if ($response) { $response.Dispose() }
            if ($ResponseStream) { $ResponseStream.Dispose() }
        }
    }
}

Function Test-FileLock {
    param (
        [parameter(Mandatory = $true)][string]$Path
    )
    $OpenFile = New-Object System.IO.FileInfo $Path
    if ((Test-Path -Path $Path) -eq $false) {
        return $false
    }
    try {
        $FileStream = $OpenFile.Open([System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        if ($FileStream) {
            $FileStream.Close()
        }
        return $false
    } catch {
        # file is locked by a process.
        return $true
    }
}

Function Rename-File {
    param (
        [parameter(Mandatory = $true)]
        [string]$OriginalFilePath,
        [parameter(Mandatory = $true)]
        [string]$NewFilePath
    )

    $maxRetryAttemps = 10
    $retryAttempts = 0
    if (Test-Path $OriginalFilePath) {
        while ((Test-FileLock -Path $OriginalFilePath) -and ($retryAttempts -lt $maxRetryAttemps)) {
            $retryAttempts += 1
            Write-LogInfo "[$retryAttempts / $maxRetryAttemps ] $OriginalFilePath is locked. Waiting 5 seconds..."
            Start-Sleep -Seconds 5
        }
        if (Test-FileLock -Path $OriginalFilePath) {
            Write-LogErr "Unable to rename due to locked file."
            return $false
        }
    }
    $retryAttempts = 0
    if (Test-Path $NewFilePath) {
        Write-LogInfo "$NewFilePath already exists. Will be overwritten."
        while ((Test-FileLock -Path $NewFilePath) -and ($retryAttempts -lt $maxRetryAttemps)) {
            $retryAttempts += 1
            Write-LogInfo "[$retryAttempts / $maxRetryAttemps ] $NewFilePath is locked. Waiting 5 seconds..."
        }
        if (Test-FileLock -Path $NewFilePath) {
            Write-LogErr "Unable to rename due to locked file."
            return $false
        }
    }
    [void](Move-Item -Path $OriginalFilePath -Destination $NewFilePath -Force)
    if (Test-Path -Path $NewFilePath) {
        return $true
    } else {
        return $false
    }
}

function Collect-GcovData {
    param (
        [String] $ip,
        [String] $port,
        [String] $username,
        [String] $password,
        [String] $logDir
    )
    $status = $false
    $fileName = "gcov-data.tar.gz"

    Copy-RemoteFiles -upload -uploadTo $ip -username $username -port $port -password $password `
        -files '.\Testscripts\Linux\collect_gcov_data.sh' | Out-Null

    $Null = Run-LinuxCmd -ip $ip -port $port -username $username -password $password `
        -command "bash ./collect_gcov_data.sh --dest ./$fileName --result ./result.txt" -runAsSudo

    $result = Run-LinuxCmd -ip $ip -port $port -username $username -password $password `
        -command "cat ./result.txt"

    Write-LogInfo "GCOV collect result: $result"

    if ($result -match "GCOV_COLLECTED") {
        $logDirName = Split-Path -Path $logDir -Leaf
        if (Test-Path ".\CodeCoverage\logs\${logDirName}") {
            Remove-Item -Path ".\CodeCoverage\logs\${logDirName}" -Recurse -Force
        }
        New-Item -Type directory -Path ".\CodeCoverage\logs\${logDirName}"
        $logDest = Resolve-Path ".\CodeCoverage\logs\${logDirName}"

        Copy-RemoteFiles -download -downloadFrom $ip -port $port -files "/home/$username/$fileName" `
            -downloadTo $logDest -username $username -password $password | Out-Null

        if (Test-Path "${logDir}\${fileName}") {
            $status = $true
        }
    }

    return $status
}

Function Restart-VMFromShell($VMData, [switch]$SkipRestartCheck) {
    try {
        Write-LogInfo "Restarting $($VMData.RoleName) from shell..."
        $Null = Run-LinuxCmd -ip $VMData.PublicIP -port $VMData.SSHPort -username $user -password $password -command "sleep 2 && reboot" -runAsSudo -RunInBackground
        Start-Sleep -Seconds 5
        if ($SkipRestartCheck) {
            return $true
        } else {
            if ((Is-VmAlive -AllVMDataObject $VMData) -eq "True") {
                return $true
            }
            return $false
        }
    }
    catch {
        Write-LogErr "Restarting $($VMData.RoleName) from shell failed with exception."
        return $false
    }
}

Function Wait-AzVMBackRunningWithTimeOut($AllVMData, [scriptblock]$AzVMScript) {
    if (!$AllVMData -or !$AllVMData.InstanceSize -or !$AllVMData.ResourceGroupName -or !$AllVMData.RoleName) {
        return $false
    }
    $VMCoresArray = @()
    $AzureVMSizeInfo = Get-AzVMSize -Location $AllVMData[0].Location
    foreach ($vmData in $AllVMData) {
        $AzVMScript.Invoke($vmData)
        if (-not $?) {
            Write-LogErr "Failed in AzVM operation for $($vmData.RoleName)"
            return $false
        }
        $VMCoresArray += ($AzureVMSizeInfo | Where-Object { $_.Name -eq $vmData.InstanceSize }).NumberOfCores
    }
    $MaximumCores = ($VMCoresArray | Measure-Object -Maximum).Maximum

    Write-LogDbg "MaximumCores is $MaximumCores."
    # Calculate timeout depending on VM size.
    # We're adding timeout of 10 minutes (default timeout) + 1 minute/10 cores (additional timeout).
    # So For D64 VM, timeout = 10 + int[64/10] = 16 minutes.
    # M128 VM, timeout = 10 + int[128/10] = 23 minutes.
    $Timeout = New-Timespan -Minutes ([int]($MaximumCores / 10) + 10)
    $sw = [diagnostics.stopwatch]::StartNew()
    foreach ($vmData in $AllVMData) {
        $vm = Get-AzVM -ResourceGroupName $vmData.ResourceGroupName -Name $vmData.RoleName -Status
        while (($vm.Statuses[-1].Code -ne "PowerState/running") -and ($sw.elapsed -lt $Timeout)) {
            Write-LogInfo "VM $($vmData.RoleName) is in $($vm.Statuses[-1].Code) state, still not in running state"
            Start-Sleep -Seconds 20
            $vm = Get-AzVM -ResourceGroupName $vmData.ResourceGroupName -Name $vmData.RoleName -Status
        }
    }
    if ($sw.elapsed -ge $Timeout) {
        Write-LogErr "VMs are not in PowerState/running status after $Timeout minutes (estimated timespan based on maximum NumberOfCores of VM size)"
        return $false
    }
    else {
        $VMDataWithPublicIP = Get-AllDeploymentData -ResourceGroups $AllVMData.ResourceGroupName
        foreach ($vmData in $AllVMData) {
            $vmData.PublicIP = ($VMDataWithPublicIP | Where-Object {$_.RoleName -eq $vmData.RoleName}).PublicIP
        }
        # the core is more, the boot time is longer
        $MaxRetryCount = [int]($MaximumCores / 10) + 10
        Write-LogDbg "MaxRetryCount is $MaxRetryCount."
        if ((Is-VmAlive -AllVMDataObject $AllVMData -MaxRetryCount $MaxRetryCount) -eq "True") {
            return $true
        }
        return $false
    }
}

# This function get a data disk name on the guest
# Background:
#    If the vm has more than one disk controller, the order in which their corresponding device nodes are added is arbitrary.
#    This may result in device names like /dev/sda and /dev/sdc switching around on each boot.
# Note:
#    If the size of data disk is the same as the resource disk (default size: 1GB), the return value may the device name of resource disk.
#    It's recommended that the data disk size is more than 1GB to call this function.
Function Get-DeviceName
{
    param (
        [String] $ip,
        [String] $port,
        [String] $username,
        [String] $password
    )

    Copy-RemoteFiles -upload -uploadTo $ip -username $username -port $port -password $password `
        -files '.\Testscripts\Linux\get_data_disk_dev_name.sh' | Out-Null
    $ret = Run-LinuxCmd -ip $ip -port $port -username $username -password $password `
        -command "bash get_data_disk_dev_name.sh" -runAsSudo
    return $ret
}

# This function will return expected devices count and keyword which part of output from command lspci based on provided device type
# NVME - Disk count = vCPU/8
#    size Standard_L8s_v2, vCPU 8, NVMe Disk 1
#    size Standard_L16s_v2, vCPU 16, NVMe Disk 2
#    size Standard_L32s_v2, vCPU 32, NVMe Disk 4
#    size Standard_L64s_v2, vCPU 64, NVMe Disk 8
#    size Standard_L80s_v2, vCPU 80, NVMe Disk 10
# GPU
#    The expected GPU ratio is different from VM sizes
#    NC, NC_v2, NC_v3, NV, NV_v2, and ND: 6
#    NV_v3: 12
#    ND_v2: 5
#    Due to hyperthreading option, NV12s_v3 has 1GPU, 24s_v3 has 2 and 48s_v3 has 4 GPUs
#    Source: https://docs.microsoft.com/en-us/azure/virtual-machines/linux/sizes-gpu
# SRIOV
#    Get current VM's nic which enable accelerated networking
Function Get-ExpectedDevicesCount {
    param (
        [Object] $vmData,
        [String] $username,
        [String] $password,
        [String] $type
    )
    $vmCPUCount = Run-LinuxCmd -username $username -password $password -ip $vmData.PublicIP -port $vmData.SSHPort -command "nproc" -ignoreLinuxExitCode
    $size = $vmData.InstanceSize
    if ($vmCPUCount) {
        Write-LogDbg "Successfully fetched nproc result: $vmCPUCount"
    } else {
        Write-LogErr "Could not fetch the nproc command result."
    }
    [int]$expectedCount = 0
    switch ($type) {
        "NVME" {
            [int]$expectedCount = $($vmCPUCount/8)
            $keyWord = "Non-Volatile memory controller"
            break
        }
        "GPU" {
            if ($size -imatch "Standard_ND96asr") {
                [int]$expectedCount = $($vmCPUCount/12)
            } elseif ($size -match "Standard_NDv2") {
                [int]$expectedCount = $($vmCPUCount/5)
            } elseif (($size -imatch "Standard_ND" -or $size -imatch "Standard_NV") -and $size -imatch "v3") {
                [int]$expectedCount = $($vmCPUCount/12)
            } else {
                [int]$expectedCount = $($vmCPUCount/6)
            }
            $keyWord = "NVIDIA"
            break
        }
        "SRIOV" {
            $keyWord = "Mellanox"
            foreach($nic in (Get-AzVM -Name $vmData.RoleName).NetworkProfile.NetworkInterfaces) {
                if((Get-AzNetworkInterface -ResourceId $nic.Id).EnableAcceleratedNetworking) {
                    $expectedcount++
                }
            }
            break
        }
        Default {}
    }

    return $expectedCount,$keyWord
}

# Extract values from file between two lines which has specified start pattern
Function ExtractSSHPublicKeyFromPPKFile {
    param (
        [String] $filePath,
        [String] $startLinePattern="Public-Lines",
        [String] $endLinePattern="private-Lines"
    )
        if (![string]::IsNullOrEmpty($filePath)) {
            $fromHereStartingLine = Select-String $filePath -pattern $startLinePattern | Select-Object LineNumber
            $uptoHereStartingLine = Select-String $filePath -pattern $endLinePattern | Select-Object LineNumber
            $extractedValue = ""
            for($i=$fromHereStartingLine.LineNumber; $i -lt $uptoHereStartingLine.LineNumber-1; $i+=1) {
                $extractedValue += Get-Content -Path $FilePath | Foreach-Object { ($_  -replace "`r*`n*","") } | Select-Object -Index $i
            }

            return "ssh-rsa $extractedValue"
        } else {
            return $null
        }
}