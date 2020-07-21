##############################################################################################
# TestController.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# Operations :
#
<#
.SYNOPSIS
	PS modules for LISAv2 test automation
	This module drives the test generally

.PARAMETER
	<Parameters>

.INPUTS


.NOTES
	Creation Date:
	Purpose/Change:

.EXAMPLE


#>
###############################################################################################
using Module "..\TestProviders\TestProvider.psm1"
using Module "..\Libraries\TestReport.psm1"

Class TestController
{
	# setupType,vmSize,networking,diskType,osDiskType,switchName -> Test Case List
	[Hashtable] $SetupTypeToTestCases
	# setupType Name -> setupType XML
	[Hashtable] $SetupTypeTable
	[TestProvider] $TestProvider

	# For report and summary
	[JUnitReportGenerator] $JunitReport
	[TestSummary] $TestSummary
	[int] $TotalCaseNum

	# Test configuration xml
	[xml] $XMLSecrets
	[string] $GlobalConfigurationFilePath
	[xml] $GlobalConfig

	# passed from LISAv2 parameters
	[string] $TestPlatform
	[string] $TestLocation
	[string] $VmUsername
	[string] $VmPassword
	[string] $SSHPrivateKey
	[string] $RGIdentifier
	[string] $OsVHD
	[string] $TestCategory
	[string] $TestNames
	[string] $TestArea
	[string] $TestTag
	[string] $ExcludeTests
	[string] $TestPriority
	[int] $TestIterations
	[bool] $EnableTelemetry
	[string] $OverrideVMSize
	[string] $ResourceCleanup
	[bool] $DeployVMPerEachTest
	[string] $ResultDBTable
	[string] $ResultDBTestTag
	[bool] $UseExistingRG
	[array] $TestCaseStatus
	[array] $TestCasePassStatus
	[bool] $EnableCodeCoverage
	[Hashtable] $CustomParams
	[string] $VMGeneration
	[bool] $ForceCustom # For overwrite custom parameters or not

	[void] SyncEquivalentCustomParameters([string] $Key, [string] $Value) {
		if ($Value) {
			if ($this.CustomParams.$Key) {
				Write-LogWarn "Custom Parameter of '$Key' has been updated with Value: '$Value', previous value is '$($this.CustomParams.$Key)'"
			}
			$this.CustomParams[$Key] = $Value
		}
		else {
			if ($this.CustomParams.$Key) {
				$this.$Key = $this.CustomParams.$Key
				Write-LogWarn "'$($this.GetType()).$Key' is equivalent updated with Value'$($this.CustomParams.$Key)'"
			}
		}
	}

	[string[]] ParseAndValidateParameters([Hashtable]$ParamTable) {
		$this.TestLocation = $ParamTable["TestLocation"]
		$this.RGIdentifier = $ParamTable["RGIdentifier"]
		$this.OsVHD = $ParamTable["OsVHD"]
		$this.TestCategory = $ParamTable["TestCategory"]
		$this.TestNames = $ParamTable["TestNames"]
		$this.TestArea = $ParamTable["TestArea"]
		$this.TestTag = $ParamTable["TestTag"]
		$this.ExcludeTests = $ParamTable["ExcludeTests"]
		$this.TestPriority = $ParamTable["TestPriority"]
		$this.ResourceCleanup = $ParamTable["ResourceCleanup"]
		$this.EnableTelemetry = $ParamTable["EnableTelemetry"]
		$this.TestIterations = $ParamTable["TestIterations"]
		$this.OverrideVMSize = $ParamTable["OverrideVMSize"]
		$this.DeployVMPerEachTest = $ParamTable["DeployVMPerEachTest"]
		$this.ResultDBTable = $ParamTable["ResultDBTable"]
		$this.ResultDBTestTag = $ParamTable["ResultDBTestTag"]
		$this.UseExistingRG = $ParamTable["UseExistingRG"]
		$this.EnableCodeCoverage = $ParamTable["EnableCodeCoverage"]
		$this.VMGeneration = $ParamTable["VMGeneration"]

		$this.TestProvider.CustomKernel = $ParamTable["CustomKernel"]
		$this.TestProvider.CustomLIS = $ParamTable["CustomLIS"]
		$this.TestProvider.ReuseVmOnFailure = ($ParamTable.ContainsKey("ReuseVmOnFailure"))
		$this.CustomParams = @{}
		if ( $ParamTable.ContainsKey("CustomParameters") ) {
			$ParamTable["CustomParameters"].Split(';').Trim() | ForEach-Object {
				$key = $_.Split('=')[0].Trim()
				$value = $_.Substring($_.IndexOf("=")+1)
				$this.CustomParams[$key] = $value
			}
		}
		$this.ForceCustom = ($ParamTable.ContainsKey("ForceCustom"))
		$GlobalConfigurationFile = "$PSScriptRoot\..\XML\GlobalConfigurations.xml"
		if (Test-Path -Path $GlobalConfigurationFile) {
			$this.GlobalConfigurationFilePath = $GlobalConfigurationFile
			$this.GlobalConfig = [xml](Get-Content $GlobalConfigurationFile)
		} else {
			throw "Global configuration '$GlobalConfigurationFile' file does not exist"
		}
		$this.SyncEquivalentCustomParameters("TestLocation", $this.TestLocation)
		$this.SyncEquivalentCustomParameters("OsVHD", $this.OsVHD)
		$this.SyncEquivalentCustomParameters("OverrideVMSize", $this.OverrideVMSize)
		$this.SyncEquivalentCustomParameters("RGIdentifier", $this.RGIdentifier)
		# Sync VMGeneration with whatever values it got from command parameter;
		# if $null/empty, inherited controller will update it with default value
		$this.SyncEquivalentCustomParameters("VMGeneration", $this.VMGeneration)

		$parameterErrors = @()
		# Validate general parameters
		return $parameterErrors
	}

	[void] UpdateXMLStringsFromSecretsFile()
	{
		if ($this.XMLSecrets) {
			$TestXMLs = Get-ChildItem -Path "$PSScriptRoot\..\XML\TestCases\*.xml"

			foreach ($file in $TestXMLs)
			{
				$CurrentXMLText = Get-Content -Path $file.FullName
				foreach ($Replace in $this.XMLSecrets.secrets.ReplaceTestXMLStrings.Replace)
				{
					if ($Replace.InnerText) {
						$Replace.InnerText = [System.Security.SecurityElement]::Escape($Replace.InnerText)
						$ReplaceString, $ReplaceWith = $Replace.InnerText -split '=',2
					} else {
						$ReplaceString, $ReplaceWith = $Replace -split '=',2
					}
					if ($CurrentXMLText -imatch $ReplaceString)
					{
						$content = [System.IO.File]::ReadAllText($file.FullName).Replace($ReplaceString,$ReplaceWith)
						[System.IO.File]::WriteAllText($file.FullName, $content)
						Write-LogInfo "$ReplaceString replaced in $($file.FullName)"
					}
				}
			}
			Write-LogInfo "Updated Test Case xml files."
		}
	}

	[void] UpdateRegionAndStorageAccountsFromSecretsFile()
	{
		if ($this.XMLSecrets.secrets.RegionAndStorageAccounts) {
			$FilePath = "$PSScriptRoot\..\XML\RegionAndStorageAccounts.xml"
			$CurrentStorageXML = [xml](Get-Content $FilePath)
			$CurrentStorageXML.AllRegions.InnerXml = $this.XMLSecrets.secrets.RegionAndStorageAccounts.InnerXml
			$CurrentStorageXML.Save($FilePath)
			Write-LogInfo "Updated $FilePath from secrets file."
		}
	}

	[void] PrepareTestEnvironment($XMLSecretFile) {
		if ($XMLSecretFile) {
			if (Test-Path -Path $XMLSecretFile) {
				$this.XmlSecrets = ([xml](Get-Content $XMLSecretFile))
				# Download the tools required for LISAv2 execution.
				Get-LISAv2Tools -XMLSecretFile $XMLSecretFile
				$this.UpdateXMLStringsFromSecretsFile()
				$this.UpdateRegionAndStorageAccountsFromSecretsFile()
			} else {
				Write-LogErr "The Secret file provided: '$XMLSecretFile' does not exist"
			}
		} else {
			Write-LogErr "Failed to update configuration files. '-XMLSecretFile [FilePath]' is not provided."
		}
		$this.GlobalConfig = [xml](Get-Content $this.GlobalConfigurationFilePath)
	}

	[void] SetGlobalVariables() {
		# Used in CAPTURE-VHD-BEFORE-TEST.ps1, and Create-HyperVGroupDeployment
		Set-Variable -Name BaseOsVHD -Value $this.OsVHD -Scope Global -Force
		Set-Variable -Name TestPlatform -Value $this.TestPlatform -Scope Global -Force
		# Used in test cases
		Set-Variable -Name user -Value $this.VmUsername -Scope Global -Force
		Set-Variable -Name password -Value $this.VmPassword -Scope Global -Force
		Set-Variable -Name sshPrivateKey -Value $this.SSHPrivateKey -Scope Global -Force
		# Global config
		Set-Variable -Name GlobalConfig -Value $this.GlobalConfig -Scope Global -Force
		# XML secrets, used in Upload-TestResultToDatabase
		Set-Variable -Name XmlSecrets -Value $this.XmlSecrets -Scope Global -Force
		# Test results
		Set-Variable -Name ResultPass -Value "PASS" -Scope Global
		Set-Variable -Name ResultSkipped -Value "SKIPPED" -Scope Global
		Set-Variable -Name ResultFail -Value "FAIL" -Scope Global
		Set-Variable -Name ResultAborted -Value "ABORTED" -Scope Global
		$this.TestCaseStatus = @($global:ResultPass, $global:ResultSkipped, $global:ResultFail, $global:ResultAborted)
		$this.TestCasePassStatus = @($global:ResultPass, $global:ResultSkipped)
	}

	[void] PrepareSetupTypeToTestCases([hashtable]$SetupTypeToTestCases, [object[]]$AllTests) {
		# The multiple TestLocation may be separated by ','
		# and in most cases, the multiple TestLocations should always stick together for certain one TestCase.
		# So, use a fake SplitBy ';' to avoid TestLocations being Splitted into multi single ConfigValues for $AllTests.
		Add-SetupConfig -AllTests ([ref]$AllTests) -ConfigName "TestLocation" -ConfigValue $this.CustomParams["TestLocation"] -SplitBy ';' -Force $this.ForceCustom
		Add-SetupConfig -AllTests ([ref]$AllTests) -ConfigName "OsVHD" -ConfigValue $this.CustomParams["OsVHD"] -Force $this.ForceCustom
		if ($this.TestIterations -gt 1) {
			$testIterationsParamValue = @(1..$this.TestIterations) -join ','
			Add-SetupConfig -AllTests ([ref]$AllTests) -ConfigName "TestIteration" -ConfigValue $testIterationsParamValue -Force $this.ForceCustom
		}

		foreach ($test in $AllTests) {
			# Put test case to hashtable, per setupType, TestLocation, OsVHD
			$key = "$($test.SetupConfig.SetupType),$($test.SetupConfig.TestLocation),$($test.SetupConfig.OsVHD)"
			if ($test.SetupConfig.SetupType) {
				if ($SetupTypeToTestCases.ContainsKey($key)) {
					$SetupTypeToTestCases[$key] += $test
				} else {
					$SetupTypeToTestCases.Add($key, @($test))
				}
			}
		}
		$this.TotalCaseNum = @($AllTests).Count
	}

	[void] LoadTestCases($WorkingDirectory, $CustomTestParameters) {
		$this.SetupTypeToTestCases = @{}
		$this.SetupTypeTable = @{}
		$TestXMLs = Get-ChildItem -Path "$WorkingDirectory\XML\TestCases\*.xml"
		$SetupTypeXMLs = Get-ChildItem -Path "$WorkingDirectory\XML\VMConfigurations\*.xml"
		$ReplaceableTestParameters = [xml](Get-Content -Path "$WorkingDirectory\XML\Other\ReplaceableTestParameters.xml")

		$allTests = Select-TestCases -TestXMLs $TestXMLs -TestCategory $this.TestCategory -TestArea $this.TestArea `
			-TestNames $this.TestNames -TestTag $this.TestTag -TestPriority $this.TestPriority -ExcludeTests $this.ExcludeTests

		if (!$allTests) {
			Throw "Not able to collect any test cases from XML files"
		}
		Write-LogInfo "$(@($allTests).Length) Test Cases have been collected"

		$SetupTypes = $allTests.SetupConfig.SetupType | Sort-Object -Unique
		foreach ($file in $SetupTypeXMLs.FullName) {
			$setupXml = [xml]( Get-Content -Path $file)
			foreach ($SetupType in $SetupTypes) {
				if ($setupXml.TestSetup.$SetupType) {
					$this.SetupTypeTable[$SetupType] = $setupXml.TestSetup.$SetupType
				}
			}
		}

		# Inject custom parameters
		if ($CustomTestParameters) {
			Write-LogInfo "Checking custom parameters ..."
			$CustomTestParameters = @($CustomTestParameters.Trim("; ").Split(";").Trim())
			foreach ($CustomParameter in $CustomTestParameters)
			{
				$ReplaceThis = $CustomParameter.Split("=")[0]
				$ReplaceWith = $CustomParameter.Substring($CustomParameter.IndexOf("=")+1)

				$OldValue = ($ReplaceableTestParameters.ReplaceableTestParameters.Parameter | Where-Object `
					{ $_.ReplaceThis -eq $ReplaceThis }).ReplaceWith
				($ReplaceableTestParameters.ReplaceableTestParameters.Parameter | Where-Object `
					{ $_.ReplaceThis -eq $ReplaceThis }).ReplaceWith = $ReplaceWith
				Write-LogInfo "Custom Parameter: $ReplaceThis=$OldValue --> $ReplaceWith"
			}
			Write-LogInfo "Custom parameter(s) are ready to be injected along with default parameters, if any."
		}

		foreach ( $test in $allTests) {
			# Inject replaceable parameters
			foreach ($ReplaceableParameter in $ReplaceableTestParameters.ReplaceableTestParameters.Parameter) {
				$replaceWith = [System.Security.SecurityElement]::Escape($ReplaceableParameter.ReplaceWith)
				$FindReplaceArray = @(
					("=$($ReplaceableParameter.ReplaceThis)<" ,"=$($replaceWith)<" ),
					("=`"$($ReplaceableParameter.ReplaceThis)`"" ,"=`"$($replaceWith)`""),
					(">$($ReplaceableParameter.ReplaceThis)<" ,">$($replaceWith)<")
				)
				foreach ($item in $FindReplaceArray) {
					$Find = $item[0]
					$Replace = $item[1]
					if ($test.InnerXml -imatch $Find) {
						$test.InnerXml = $test.InnerXml.Replace($Find,$Replace)
						Write-LogInfo "$($ReplaceableParameter.ReplaceThis)=$($ReplaceableParameter.ReplaceWith) injected to case $($test.testName)"
					}
				}
			}
			# Check whether the case if for Windows images
			$IsWindowsImage = $false
			if(($test.AdditionalHWConfig.OSType -contains "Windows")) {
				$IsWindowsImage = $true
			}
			Set-Variable -Name IsWindowsImage -Value $IsWindowsImage -Scope Global
		}

		$this.PrepareSetupTypeToTestCases($this.SetupTypeToTestCases, $allTests)
	}

	[void] PrepareTestImage() {}

	[object] RunTestScript (
		[object]$CurrentTestData,
		[hashtable]$Parameters,
		[string]$LogDir,
		[object]$VMData,
		[string]$Username,
		[string]$Password,
		[string]$TestLocation,
		[int]$Timeout,
		[xml]$GlobalConfig,
		[object]$TestProvider) {

		$workDir = Get-Location
		$script = $CurrentTestData.TestScript
		$scriptName = $Script.split(".")[0]
		$scriptExtension = $Script.split(".")[1]
		$constantsPath = Join-Path $workDir "constants.sh"
		$testName = $currentTestData.TestName
		$currentTestResult = Create-TestResultObject

		Create-ConstantsFile -FilePath $constantsPath -Parameters $Parameters
		if (!$global:IsWindowsImage) {
			foreach ($VM in $VMData) {
				Copy-RemoteFiles -upload -uploadTo $VM.PublicIP -Port $VM.SSHPort `
					-files $constantsPath -Username $Username -password $Password
				Write-LogInfo "Constants file uploaded to: $($VM.RoleName)"
			}
		}
		if ($CurrentTestData.files -imatch ".py") {
			$pythonPath = Run-LinuxCmd -Username $Username -password $Password -ip $VMData.PublicIP -Port $VMData.SSHPort `
				-Command "which python 2> /dev/null || which python2 2> /dev/null || which python3 2> /dev/null || (which /usr/libexec/platform-python && ln -s /usr/libexec/platform-python /sbin/python)" -runAsSudo
			if (!$pythonPath.Contains("platform-python") -and (($pythonPath -imatch "python2") -or ($pythonPath -imatch "python3"))) {
				$pythonPathSymlink  = $pythonPath.Substring(0, $pythonPath.LastIndexOf("/") + 1)
				$pythonPathSymlink  += "python"
				Run-LinuxCmd -Username $Username -password $Password -ip $VMData.PublicIP -Port $VMData.SSHPort `
					 -Command "ln -s $pythonPath $pythonPathSymlink" -runAsSudo
			}
		}
		Write-LogInfo "Test script: ${Script} started."
		$testVMData = $VMData | Where-Object { !($_.RoleName -like "*dependency-vm*") } | Select-Object -First 1
		# PowerShell scripts can have a side effect of changing the
		# $CurrentTestData global variable.
		# Bash and Python scripts write a string in the state.txt log file with the test result,
		# which is parsed and returned by the Collect-TestLogs method.
		$psScriptTestResult = $null
		if ($scriptExtension -eq "sh") {
			Run-LinuxCmd -Command "bash ${Script} > ${TestName}_summary.log 2>&1" `
				 -Username $Username -password $Password -ip $testVMData.PublicIP -Port $testVMData.SSHPort `
				 -runMaxAllowedTime $Timeout -runAsSudo
		} elseif ($scriptExtension -eq "py") {
			Run-LinuxCmd -Username $Username -password $Password -ip $testVMData.PublicIP -Port $testVMData.SSHPort `
				 -Command "python ${Script}" -runMaxAllowedTime $Timeout -runAsSudo
			Run-LinuxCmd -Username $Username -password $Password -ip $testVMData.PublicIP -Port $testVMData.SSHPort `
				 -Command "mv Runtime.log ${TestName}_summary.log" -runAsSudo
		} elseif ($scriptExtension -eq "ps1") {
			$scriptDir = Join-Path $workDir "Testscripts\Windows"
			$scriptLoc = Join-Path $scriptDir $Script
			$scriptParameters = ""
			foreach ($param in $Parameters.Keys) {
				$scriptParameters += (";{0}={1}" -f ($param,$($Parameters[$param])))
			}
			Write-LogInfo "${scriptLoc} -TestParams $scriptParameters -AllVmData $VmData -TestProvider $TestProvider -CurrentTestData $CurrentTestData"
			$psScriptTestResult = & "${scriptLoc}" -TestParams $scriptParameters -AllVmData `
				$VmData -TestProvider $TestProvider -CurrentTestData $CurrentTestData
		}

		if ($scriptExtension -ne "ps1") {
			$currentTestResult = Collect-TestLogs -LogsDestination $LogDir -ScriptName $scriptName `
				-TestType $scriptExtension -PublicIP $testVMData.PublicIP -SSHPort $testVMData.SSHPort `
				-Username $Username -password $Password -TestName $TestName
		} else {
			if ($psScriptTestResult.TestResult) {
				$currentTestResult = $psScriptTestResult
			} else {
				$currentTestResult.TestResult = $psScriptTestResult
			}
		}
		if (!$this.TestCaseStatus.contains($currentTestResult.TestResult)) {
			Write-LogInfo "Test case script result does not match known ones: $($currentTestResult.TestResult)"
			$currentTestResult.TestResult = Get-FinalResultHeader -resultArr $psScriptTestResult
			if (!$this.TestCaseStatus.contains($currentTestResult.TestResult)) {
				Write-LogErr "Failed to retrieve a known test result: $($currentTestResult.TestResult)"
				$currentTestResult.TestResult = $global:ResultAborted
			}
		}
		return $currentTestResult
	}

	[object] RunOneTestCase($VmData, $CurrentTestData, $ExecutionCount, $SetupTypeData, $ApplyCheckpoint) {
		# Prepare test case log folder
		$currentTestName = $($CurrentTestData.testName)
		$oldLogDir = $global:LogDir
		$CurrentTestLogDir = "$global:LogDir\$currentTestName"
		$currentTestResult = Create-TestResultObject

		New-Item -Type Directory -Path $CurrentTestLogDir -ErrorAction SilentlyContinue | Out-Null
		Set-Variable -Name "LogDir" -Value $CurrentTestLogDir -Scope Global

		$this.JunitReport.StartLogTestCase("LISAv2Test-$($this.TestPlatform)","$currentTestName","$($this.TestPlatform)-$($CurrentTestData.Category)-$($CurrentTestData.Area)")

		try {
			# Get test case parameters
			$testParameters = @{}
			if ($CurrentTestData.TestParameters) {
				$testParameters = Parse-TestParameters -XMLParams $CurrentTestData.TestParameters `
					-GlobalConfig $this.GlobalConfig -AllVMData $VmData
			}

			# Run setup script if any
			Write-LogInfo "==> Run test setup script if defined."
			$this.TestProvider.RunSetup($VmData, $CurrentTestData, $testParameters, $ApplyCheckpoint)

			if (!$global:IsWindowsImage) {
				Write-LogInfo "==> Check the target machine kernel log."
				$this.GetAndCompareOsLogs($VmData, "Initial")
			}

			# Upload test files to VMs
			if ($CurrentTestData.files) {
				if(!$global:IsWindowsImage){
					foreach ($vm in $VmData) {
						Write-LogInfo "==> Upload test files to target machine $($vm.RoleName) if any."
						Copy-RemoteFiles -upload -uploadTo $vm.PublicIP -Port $vm.SSHPort `
							-files $CurrentTestData.files -Username $global:user -password $global:password
					}
				}
			}

			$timeout = 300
			if ($CurrentTestData.Timeout) {
				$timeout = $CurrentTestData.Timeout
			}

			Write-LogInfo "==> Run test script on the target machine."
			# Run test script
			if ($CurrentTestData.TestScript) {
				$currentTestResult = $this.RunTestScript(
					$CurrentTestData,
					$testParameters,
					$global:LogDir,
					$VmData,
					$global:user,
					$global:password,
					$CurrentTestData.SetupConfig.TestLocation,
					$timeout,
					$this.GlobalConfig,
					$this.TestProvider)
			} else {
				throw "Test case $currentTestName does not define any TestScript in the XML file."
			}
		} catch {
			$errorMessage = $_.Exception.Message
			$line = $_.InvocationInfo.ScriptLineNumber
			$scriptName = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
			Write-LogErr "EXCEPTION: $errorMessage"
			Write-LogErr "Source: Line $line in script $scriptName."
			$currentTestResult.TestResult = $global:ResultFail
			$currentTestResult.testSummary += Trim-ErrorLogMessage $errorMessage
		}

		# Sometimes test scripts may return an array, the last one is the result object
		if ($currentTestResult.count) {
			$currentTestResult = $currentTestResult[-1]
		}

		# Upload results to database
		Write-LogInfo "==> Upload test results to database."
		if ($currentTestResult.TestResultData) {
			Upload-TestResultDataToDatabase -TestResultData $currentTestResult.TestResultData -DatabaseConfig $this.GlobalConfig.Global.$($this.TestPlatform).ResultsDatabase
		}

		try {
			Write-LogInfo "==> Check if the test target machines are still running."
			$isVmAlive = Is-VmAlive -AllVMDataObject $VMData -MaxRetryCount 10
			if (!$global:IsWindowsImage -and $isVmAlive -eq "True" ) {
				if ($testParameters["SkipVerifyKernelLogs"] -ne "True") {
					$ret = $this.GetAndCompareOsLogs($VmData, "Final")
					if (($testParameters["FailForLogCheck"] -eq "True") -and ($ret -eq $false) -and ($currentTestResult.TestResult -eq $global:ResultPass)) {
						$currentTestResult.TestResult = $global:ResultFail
						Write-LogErr "Test $($CurrentTestData.TestName) fails for log check"
						$currentTestResult.testSummary += New-ResultSummary -testResult "Test fails for log check"
					}
				}
				$this.GetSystemBasicLogs($VmData, $global:user, $global:password, $CurrentTestData, $currentTestResult, $this.EnableTelemetry) | Out-Null
			}

			Write-LogInfo "==> Run test cleanup script if defined."
			$collectDetailLogs = !$this.TestCasePassStatus.contains($currentTestResult.TestResult) -and !$global:IsWindowsImage -and $testParameters["SkipVerifyKernelLogs"] -ne "True" -and $isVmAlive -eq "True"
			$doRemoveFiles = $this.TestCasePassStatus.contains($currentTestResult.TestResult) -and !($this.ResourceCleanup -imatch "Keep") -and !$global:IsWindowsImage -and $testParameters["SkipVerifyKernelLogs"] -ne "True"
			$this.TestProvider.RunTestCaseCleanup($vmData, $CurrentTestData, $currentTestResult, $collectDetailLogs, $doRemoveFiles, `
				$global:user, $global:password, $SetupTypeData, $testParameters)
		} catch {
			$errorMessage = $_.Exception.Message
			$line = $_.InvocationInfo.ScriptLineNumber
			$scriptName = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
			Write-LogErr "EXCEPTION: $errorMessage"
			Write-LogErr "Source: Line $line in script $scriptName."
		}

		# Update test summary
		$testRunDuration = $this.JunitReport.GetTestCaseElapsedTime("LISAv2Test-$($this.TestPlatform)","$currentTestName","mm")
		$this.TestSummary.UpdateTestSummaryForCase($CurrentTestData, $ExecutionCount, $currentTestResult.TestResult, $testRunDuration, $currentTestResult.testSummary, $VmData)

		# Update junit report for current test case
		$testCaseLog = ($currentTestResult.testSummary + (Get-Content -Raw "$CurrentTestLogDir\$global:LogFileName")).Trim()
		$this.JunitReport.CompleteLogTestCase("LISAv2Test-$($this.TestPlatform)","$currentTestName",$currentTestResult.TestResult,$testCaseLog)

		# Set back the LogDir to the parent folder
		Set-Variable -Name "LogDir" -Value $oldLogDir -Scope Global
		return $currentTestResult
	}

	[void] RunTestCasesInSequence([int]$TestIterations)
	{
		$executionCount = 0
		$CleanupResource = {
			param ([ref]$VmDataToBeDeleted)
			if ($VmDataToBeDeleted.Value) {
				Write-LogInfo "Delete deployed target machine ..."
				$null = $this.TestProvider.DeleteVMs($VmDataToBeDeleted.Value, $this.SetupTypeTable[$setupType], $this.UseExistingRG);
				$VmDataToBeDeleted.Value = $null
			}
		}
		foreach ($setupKey in $this.SetupTypeToTestCases.Keys) {
			$setupType = $setupKey.Split(',')[0]
			$vmData = $null
			$lastResult = $null
			$tests = 0
			foreach ($currentTestCase in $this.SetupTypeToTestCases[$setupKey]) {
				$executionCount += 1
				Write-LogInfo "($executionCount/$($this.TotalCaseNum)) testing started: $($currentTestCase.testName)"
				Write-LogInfo "SetupConfig: { $(ConvertFrom-SetupConfig -SetupConfig $currentTestCase.SetupConfig) }"
				if (!$vmData -or $this.DeployVMPerEachTest) {
					# Deploy the VM for the setup
					Write-LogInfo "Deploy target machine for test if required ..."
					$deployVMResults = $this.TestProvider.DeployVMs($this.GlobalConfig, $this.SetupTypeTable[$setupType], $currentTestCase, `
						$currentTestCase.SetupConfig.TestLocation, $currentTestCase.SetupConfig.RGIdentifier, $this.UseExistingRG, $this.ResourceCleanup)
					$vmData = $null
					$deployErrors = ""
					if ($deployVMResults) {
						# By default set $vmData with $deployVMResults, because providers may return array of vmData directly if no errors.
						$vmData = $deployVMResults
						# override the $vmData if $deployResults give VmData specifically with property 'VmData'
						if ($deployVMResults.Keys -and ($deployVMResults.Keys -contains "VmData")) {
							$vmData = $deployVMResults.VmData
						}
						# if there are deployment errors, skip RunTestCase and try to CleanupResource, as this is unrecoverable
						# and we do not care about the last test run result (Pass or Fail), always try to CleanupResource, unless 'ResourceCleanup = Keep' set
						if ($vmData -and $deployVMResults.Error) {
							if ($this.ResourceCleanup -imatch "Keep") {
								Write-LogWarn "ResourceCleanup = 'Keep' is respected, current test will abort, as deployment error(s) detected."
								$vmData = $null
							}
							else {
								&$CleanupResource -VmDataToBeDeleted ([ref]$vmData)
							}
						}
						$deployErrors = Trim-ErrorLogMessage $deployVMResults.Error
					}
					if (!$vmData) {
						# Failed to deploy the VMs, Set the case to abort
						Write-LogWarn("VMData is empty (null). Aborting the testing.")
						$this.JunitReport.StartLogTestCase("LISAv2Test-$($this.TestPlatform)","$($currentTestCase.testName)","$($this.TestPlatform)-$($currentTestCase.Category)-$($currentTestCase.Area)")
						$this.JunitReport.CompleteLogTestCase("LISAv2Test-$($this.TestPlatform)","$($currentTestCase.testName)","Aborted", $deployErrors)
						$this.TestSummary.UpdateTestSummaryForCase($currentTestCase, $executionCount, "Aborted", "0", $deployErrors, $null)
						continue
					}
					else {
						if(!$global:detectedDistro) {
							$detectedDistro = Detect-LinuxDistro -VIP $vmData[0].PublicIP -SSHport $vmData[0].SSHPort `
								-testVMUser $global:user -testVMPassword $global:password
						}
					}
				}
				# Run current test case
				Write-LogInfo "Run test case against the target machine ..."
				# If reuse $vmData of last test case, making sure the TestLocation also copied to '$currentTestCase.SetupConfig.TestLocation', as '-TestLocation' may be empty and only auto-selected by LISAv2 during DeployVMs()
				if ($vmData -and $vmData.Location -and !$currentTestCase.SetupConfig.TestLocation) {
					$location = $vmData.Location | Select-Object -First 1
					$currentTestCase.SetupConfig.InnerXml += "<TestLocation>$location</TestLocation>"
				}
				# After RunOneTestCase, we care about '$lastResult', to choose flow of 'reuse' or 'preserve' VMs
				$lastResult = $this.RunOneTestCase($vmData, $currentTestCase, $executionCount, $this.SetupTypeTable[$setupType], ($tests -ne 0))
				$tests++

				# Last Test is 'Pass', by default reuse VM deployment till the end of current SetupType (with the Combined Setup Key)
				if ($this.TestCasePassStatus.contains($lastResult.TestResult)) {
					# Unless '$this.DeployVMPerEachTest' is $true, then: (&$CleanupResource -VmDataToBeDeleted ([ref]$vmData))
					if ($this.DeployVMPerEachTest) {
						if ($this.ResourceCleanup -imatch "Keep") {
							Write-LogWarn "ResourceCleanup = 'Keep' is respected, but may be huge waste of resources when '-DeployVMPerEachTest' is Set."
							$vmData = $null
						}
						else {
							&$CleanupResource -VmDataToBeDeleted ([ref]$vmData)
						}
					}
				}
				else {
					#Last Test is Failed/Aborted, check '-ReuseVMOnFailure', and set $readyForReuseVM = $true if RestartAllDeployments successfully.
					$readyForReuseVM = $false
					if ($this.TestProvider.ReuseVmOnFailure) {
						Write-LogInfo "Try reuse VM instances from last deployment, as '-ReuseVmOnFailure' is True"
						# Here the VM is not an initial state after provision, should be responsible immediately, but maybe already kernel panic or no response at all, so if VM is Not Alive after 3 retries, giving up the restart.
						if($vmData -and ((Is-VmAlive -AllVMDataObject $vmData -MaxRetryCount 3) -eq "True")) {
							$readyForReuseVM = $this.TestProvider.RestartAllDeployments($vmData)
						}
					}
					# If -not $readyForReuseVM, LISA will preserve VM environment for analysis/debugging by default.
					# but eventually will set $vmData = $null, which means force another deployment happen for next test case
					if (!$readyForReuseVM) {
						# when '-ResourceCleanup = Delete', &$CleanupResource
						if ($vmData -and $this.ResourceCleanup -imatch "Delete") {
							&$CleanupResource -VmDataToBeDeleted ([ref]$vmData)
						}
						# when '-UseExistingRG', try to &$CleanupResource, unless '-ResourceCleanup = Keep'
						if ($vmData -and $this.UseExistingRG) {
							if ($this.ResourceCleanup -imatch "Keep") {
								# '-ResourceCleanup = Keep' may cause following test cases in the same Setup group Aborted (because resource names of deployment are duplicated in the ExistingRG)
								Write-LogWarn "ResourceCleanup = 'Keep' is respected, but may conflict with '-UseExistingRG', as 'Keep' will cause following tests Aborted."
							}
							else {
								&$CleanupResource -VmDataToBeDeleted ([ref]$vmData)
							}
						}
						# this is by default choice for last Failed/Aborted
						$vmData = $null
					}
				}
			}

			# Cleanup, if $vmData is not null (Not Preserved for failure/debugging) or 'ResourceCleanup = Delete'
			# at the end of each SetupType (Combined setup Key) after all tests belongs to this testSetup completed
			# unless $ResourceCleanup is Keep
			if ($vmData -or ($this.ResourceCleanup -imatch "Delete")) {
				if ($this.ResourceCleanup -imatch "Keep") {
					Write-LogWarn "ResourceCleanup = 'Keep' is respected, you may need to delete the testing resources * MANUALLY * sometime later."
					$vmData = $null
				}
				else {
					&$CleanupResource -VmDataToBeDeleted ([ref]$vmData)
				}
			}
		}

		Write-LogInfo "Cleanup test environment if required ..."
		$this.TestProvider.RunTestCleanup()
	}

	[void] RunLoadedTestCases([string]$TestReportXmlPath, [int]$TestIterations, [bool]$RunInParallel) {
		Write-LogInfo "Prepare test image if required ..."
		$this.PrepareTestImage()

		Write-LogInfo "Prepare test log structure and start testing now ..."
		# Start JUnit XML report logger.
		$this.JunitReport = [JUnitReportGenerator]::New($TestReportXmlPath)
		$this.JunitReport.StartLogTestSuite("LISAv2Test-$($this.TestPlatform)")
		$this.TestSummary = [TestSummary]::New($this.TestCategory, $this.TestArea, $this.TestNames, $this.TestTag, $this.TestPriority, $this.TotalCaseNum)

		if (!$RunInParallel) {
			$this.RunTestCasesInSequence($TestIterations)
		} else {
			throw "Running test in parallel is not supported yet."
		}

		$this.JunitReport.CompleteLogTestSuite("LISAv2Test-$($this.TestPlatform)")
		$this.JunitReport.SaveLogReport()
		$this.TestSummary.SaveHtmlTestSummary(".\Report\TestSummary-$global:TestID.html")
	}

	[void] GetSystemBasicLogs($AllVMData, $User, $Password, $CurrentTestData, $CurrentTestResult, $enableTelemetry) {
		try {
			if ($allVMData.Count -gt 1) {
				$vmData = $allVMData[0]
			} else {
				$vmData = $allVMData
			}
			$FilesToDownload = "$($vmData.RoleName)-*.txt"
			Copy-RemoteFiles -upload -uploadTo $vmData.PublicIP -port $vmData.SSHPort `
				-files .\Testscripts\Linux\CollectLogFile.sh `
				-username $user -password $password -maxRetry 5 | Out-Null
			$Null = Run-LinuxCmd -username $user -password $password -ip $vmData.PublicIP -port $vmData.SSHPort `
				-command "bash CollectLogFile.sh -hostname $($vmData.RoleName)" -ignoreLinuxExitCode -runAsSudo
			$Null = Copy-RemoteFiles -downloadFrom $vmData.PublicIP -port $vmData.SSHPort `
				-username $user -password $password -files "$FilesToDownload" -downloadTo $global:LogDir -download
			$global:FinalKernelVersion = Get-Content "$global:LogDir\$($vmData.RoleName)-kernelVersion.txt"
			$HardwarePlatform = Get-Content "$global:LogDir\$($vmData.RoleName)-hardwarePlatform.txt"
			$GuestDistro = Get-Content "$global:LogDir\$($vmData.RoleName)-distroVersion.txt"
			$LISMatch = (Select-String -Path "$global:LogDir\$($vmData.RoleName)-lis.txt" -Pattern "^version:").Line
			if ($LISMatch) {
				$LISVersion = $LISMatch.Split(":").Trim()[1]
			} else {
				$LISVersion = "NA"
			}

			$HostVersion = ""
			$FoundLineNumber = (Select-String -Path "$global:LogDir\$($vmData.RoleName)-dmesg.txt" -Pattern "Hyper-V Host Build").LineNumber
			if (![string]::IsNullOrEmpty($FoundLineNumber)) {
				$ActualLineNumber = $FoundLineNumber[-1] - 1
				$FinalLine = [string]((Get-Content -Path "$global:LogDir\$($vmData.RoleName)-dmesg.txt")[$ActualLineNumber])
				$FinalLine = $FinalLine.Replace('; Vmbus version:4.0', '')
				$FinalLine = $FinalLine.Replace('; Vmbus version:3.0', '')
				$HostVersion = ($FinalLine.Split(":")[$FinalLine.Split(":").Count - 1 ]).Trim().TrimEnd(";")
			}

			if ($currentTestData.SetupConfig.Networking -imatch "SRIOV") {
				$Networking = "SRIOV"
			} else {
				$Networking = "Synthetic"
			}
			$VMSize = ""
			if ($global:TestPlatform -eq "Azure") {
				$VMSize = $vmData.InstanceSize
			}
			if ($global:TestPlatform -eq "HyperV") {
				$VMSize = $global:HyperVInstanceSize
			}
			$VMGen = $CurrentTestData.SetupConfig.VMGeneration

			if ($enableTelemetry) {
				$dataTableName = ""
				if ($this.XmlSecrets.secrets.TableName) {
					$dataTableName = $this.XmlSecrets.secrets.TableName
					Write-LogInfo "Using table name from secrets: $dataTableName"
				} else {
					$dataTableName = "LISAv2Results"
				}

				$SQLQuery = Get-SQLQueryOfTelemetryData -TestPlatform $global:TestPlatform -TestLocation $CurrentTestData.SetupConfig.TestLocation -TestCategory $CurrentTestData.Category `
					-TestArea $CurrentTestData.Area -TestName $CurrentTestData.TestName -CurrentTestResult $CurrentTestResult `
					-ExecutionTag ($global:GlobalConfig).Global.($global:TestPlatform).ResultsDatabase.testTag -GuestDistro $GuestDistro -KernelVersion $global:FinalKernelVersion `
					-HardwarePlatform $HardwarePlatform -LISVersion $LISVersion -HostVersion $HostVersion -VMSize $VMSize -VMGeneration $VMGen -Networking $Networking `
					-ARMImageName $CurrentTestData.SetupConfig.ARMImageName -OsVHD $global:BaseOsVHD -BuildURL $env:BUILD_URL -TableName $dataTableName

				Upload-TestResultToDatabase -SQLQuery $SQLQuery
			}
		}
		catch {
			$line = $_.InvocationInfo.ScriptLineNumber
			$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
			$ErrorMessage =  $_.Exception.Message
			Write-LogErr "EXCEPTION: $ErrorMessage"
			Write-LogErr "Calling function - $($MyInvocation.MyCommand)."
			Write-LogErr "Source: Line $line in script $script_name."
		}
	}

	[bool] GetAndCompareOsLogs($AllVMData, $Status) {
		$retValue = $true
		try	{
			if (!($status -imatch "Initial" -or $status -imatch "Final")) {
				Write-LogErr "Status value should be either final or initial"
				return $false
			}
			foreach ($VM in $AllVMData) {
				Write-LogInfo "Collecting $($VM.RoleName) VM Kernel $status Logs ..."

				$bootLogDir = "$global:Logdir\$($VM.RoleName)"
				mkdir $bootLogDir -Force | Out-Null

				$currentBootLogFile = "${status}BootLogs.txt"
				$currentBootLog = Join-Path $BootLogDir $currentBootLogFile

				$initialBootLogFile = "InitialBootLogs.txt"
				$initialBootLog = Join-Path $BootLogDir $initialBootLogFile

				$kernelLogStatus = Join-Path $BootLogDir "KernelLogStatus.txt"

				if ($this.EnableCodeCoverage -and ($status -imatch "Final")) {
					Write-LogInfo "Collecting coverage debug files from VM $($VM.RoleName)"

					$gcovCollected = Collect-GcovData -ip $VM.PublicIP -port $VM.SSHPort `
						-username $global:user -password $global:password -logDir $global:LogDir

					if ($gcovCollected) {
						Write-LogInfo "GCOV data collected successfully"
					} else {
						Write-LogErr "Failed to collect GCOV data from VM: $($VM.RoleName)"
					}
				}

				Run-LinuxCmd -ip $VM.PublicIP -port $VM.SSHPort -runAsSudo `
					-username $global:user -password $global:password `
					-command "dmesg > ./${currentBootLogFile}" | Out-Null
				Copy-RemoteFiles -download -downloadFrom $VM.PublicIP -port $VM.SSHPort -files "./${currentBootLogFile}" `
					-downloadTo $BootLogDir -username $global:user -password $global:password | Out-Null
				Write-LogInfo "$($VM.RoleName): $status kernel log, ${currentBootLogFile}, collected successfully."

				Write-LogInfo "Checking for call traces in kernel logs.."
				$KernelLogs = Get-Content $currentBootLog
				$callTraceFound  = $false
				foreach ($line in $KernelLogs) {
					if (( $line -imatch "Call Trace" ) -and ($line -inotmatch "initcall ")) {
						Write-LogErr $line
						$callTraceFound = $true
					}
					if ($callTraceFound) {
						if ($line -imatch "\[<") {
							Write-LogErr $line
						}
					}
				}
				if (!$callTraceFound) {
					Write-LogInfo "No kernel call traces found in the kernel log"
				}

				if($status -imatch "Final") {
					$ret = Compare-OsLogs -InitialLogFilePath $InitialBootLog -FinalLogFilePath $currentBootLog -LogStatusFilePath $KernelLogStatus `
						-ErrorMatchPatten "fail|error|warning"

					if ($ret -eq $false) {
						$retValue = $false
					}

					# Removing final dmesg file from logs to reduce the size of logs.
					# We can always see complete Final Logs as: Initial Kernel Logs + Difference in Kernel Logs
					Remove-Item -Path $currentBootLog -Force | Out-Null

					Write-LogInfo "$($VM.RoleName): $status Kernel logs collected and compared successfully"

					if ($callTraceFound -and $global:TestPlatform -imatch "Azure") {
						Write-LogInfo "Preserving the Resource Group(s) $($VM.ResourceGroupName). Setting tags : calltrace = yes"
						Add-ResourceGroupTag -ResourceGroup $VM.ResourceGroupName -TagName "calltrace" -TagValue "yes"
					}
				}
			}
		} catch {
			$line = $_.InvocationInfo.ScriptLineNumber
			$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
			$ErrorMessage =  $_.Exception.Message
			Write-LogErr "EXCEPTION: $ErrorMessage"
			Write-LogErr "Calling function - $($MyInvocation.MyCommand)."
			Write-LogErr "Source: Line $line in script $script_name."
		}

		return $retValue
	}
}
