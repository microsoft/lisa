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

		$this.TestProvider.CustomKernel = $ParamTable["CustomKernel"]
		$this.TestProvider.CustomLIS = $ParamTable["CustomLIS"]
		$this.CustomParams = @{}
		if ( $ParamTable.ContainsKey("CustomParameters") ) {
			$ParamTable["CustomParameters"].ToLower().Split(';').Trim() | ForEach-Object {
				$key,$value = $_.ToLower().Split('=').Trim()
				$this.CustomParams[$key] = $value
			}
		}
		$parameterErrors = @()
		# Validate general parameters
		if (!$this.RGIdentifier) {
			$parameterErrors += "-RGIdentifier is not set"
		}
		return $parameterErrors
	}

	[void] UpdateXMLStringsFromSecretsFile()
	{
		if ($this.XMLSecrets) {
			$TestXMLs = Get-ChildItem -Path ".\XML\TestCases\*.xml"

			foreach ($file in $TestXMLs)
			{
				$CurrentXMLText = Get-Content -Path $file.FullName
				foreach ($Replace in $this.XMLSecrets.secrets.ReplaceTestXMLStrings.Replace)
				{
					$ReplaceString = $Replace.Split("=")[0]
					$ReplaceWith = $Replace.Split("=")[1]
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
			$FilePath = Resolve-Path ".\XML\RegionAndStorageAccounts.xml"
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
				Write-LogErr "The Secret file provided: $XMLSecretFile does not exist"
			}
		} else {
			Write-LogErr "Failed to update configuration files. '-XMLSecretFile [FilePath]' is not provided."
		}
		$GlobalConfigurationFile = Resolve-Path ".\XML\GlobalConfigurations.xml"
		if (Test-Path -Path $GlobalConfigurationFile) {
			$this.GlobalConfigurationFilePath = $GlobalConfigurationFile
			$this.GlobalConfig = [xml](Get-Content $GlobalConfigurationFile)
		} else {
			throw "Global configuration $GlobalConfigurationFile file does not exist"
		}
	}

	[void] SetGlobalVariables() {
		# Used in STRESS-WEB.ps1
		Set-Variable -Name RGIdentifier -Value $this.RGIdentifier -Scope Global -Force
		# Used in CAPTURE-VHD-BEFORE-TEST.ps1, and Create-HyperVGroupDeployment
		Set-Variable -Name BaseOsVHD -Value $this.OsVHD -Scope Global -Force
		# used in telemetry
		Set-Variable -Name TestLocation -Value $this.TestLocation -Scope Global -Force
		Set-Variable -Name TestPlatform -Value $this.TestPlatform -Scope Global -Force
		# Used in test cases
		Set-Variable -Name user -Value $this.VmUsername -Scope Global -Force
		Set-Variable -Name password -Value $this.VmPassword -Scope Global -Force
		# Global config
		Set-Variable -Name GlobalConfig -Value $this.GlobalConfig -Scope Global -Force
		# XML secrets, used in Upload-TestResultToDatabase
		Set-Variable -Name XmlSecrets -Value $this.XmlSecrets -Scope Global -Force
		# Test results
		$passResult = "PASS"
		$skippedResult = "SKIPPED"
		$failResult = "FAIL"
		$abortedResult = "ABORTED"
		Set-Variable -Name ResultPass -Value $passResult -Scope Global
		Set-Variable -Name ResultSkipped -Value $skippedResult -Scope Global
		Set-Variable -Name ResultFail -Value $failResult -Scope Global
		Set-Variable -Name ResultAborted -Value $abortedResult -Scope Global
		$this.TestCaseStatus = @($passResult, $skippedResult, $failResult, $abortedResult)
		$this.TestCasePassStatus = @($passResult, $skippedResult)
	}

	[void] LoadTestCases($WorkingDirectory, $CustomTestParameters) {
		$this.SetupTypeToTestCases = @{}
		$this.SetupTypeTable = @{}

		$TestXMLs = Get-ChildItem -Path "$WorkingDirectory\XML\TestCases\*.xml"
		$SetupTypeXMLs = Get-ChildItem -Path "$WorkingDirectory\XML\VMConfigurations\*.xml"
		$ReplaceableTestParameters = [xml](Get-Content -Path "$WorkingDirectory\XML\Other\ReplaceableTestParameters.xml")

		$allTests = Collect-TestCases -TestXMLs $TestXMLs -TestCategory $this.TestCategory -TestArea $this.TestArea `
			-TestNames $this.TestNames -TestTag $this.TestTag -TestPriority $this.TestPriority -ExcludeTests $this.ExcludeTests

		if( !$allTests ) {
			Throw "Not able to collect any test cases from XML files"
		}
		Write-LogInfo "$(@($allTests).Length) Test Cases have been collected"

		$SetupTypes = $allTests.setupType | Sort-Object | Get-Unique

		foreach ( $file in $SetupTypeXMLs.FullName) {
			foreach ( $SetupType in $SetupTypes ) {
				$CurrentSetupType = ([xml]( Get-Content -Path $file)).TestSetup
				if ($CurrentSetupType.$SetupType) {
					$this.SetupTypeTable[$SetupType] = $CurrentSetupType.$SetupType
				}
			}
		}
		# Inject custom parameters
		if ($CustomTestParameters) {
			Write-LogInfo "Checking custom parameters ..."
			$CustomTestParameters = $CustomTestParameters.Trim().Trim(";").Split(";")
			foreach ($CustomParameter in $CustomTestParameters)
			{
				$CustomParameter = $CustomParameter.Trim()
				$ReplaceThis = $CustomParameter.Split("=")[0]
				$ReplaceWith = $CustomParameter.Split("=")[1]

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
				$FindReplaceArray = @(
					("=$($ReplaceableParameter.ReplaceThis)<" ,"=$($ReplaceableParameter.ReplaceWith)<" ),
					("=`"$($ReplaceableParameter.ReplaceThis)`"" ,"=`"$($ReplaceableParameter.ReplaceWith)`""),
					(">$($ReplaceableParameter.ReplaceThis)<" ,">$($ReplaceableParameter.ReplaceWith)<")
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

			# Inject Networking=SRIOV/Synthetic, DiskType=Managed, OverrideVMSize to test case data
			if ( $this.CustomParams["Networking"] -eq "sriov" -or $this.CustomParams["Networking"] -eq "synthetic" ) {
				Set-AdditionalHWConfigInTestCaseData -CurrentTestData $test -ConfigName "Networking" -ConfigValue $this.CustomParams["Networking"]
			}
			if ( $this.CustomParams["DiskType"] -eq "managed" -or $this.CustomParams["DiskType"] -eq "unmanaged") {
				Set-AdditionalHWConfigInTestCaseData -CurrentTestData $test -ConfigName "DiskType" -ConfigValue $this.CustomParams["DiskType"]
			}
			if ( $this.CustomParams["ImageType"] -eq "Specialized" -or $this.CustomParams["ImageType"] -eq "Generalized") {
				Set-AdditionalHWConfigInTestCaseData -CurrentTestData $test -ConfigName "ImageType" -ConfigValue $this.CustomParams["ImageType"]
			}
			if ( $this.CustomParams["OSType"] -eq "Windows" -or $this.CustomParams["OSType"] -eq "Linux") {
				Set-AdditionalHWConfigInTestCaseData -CurrentTestData $test -ConfigName "OSType" -ConfigValue $this.CustomParams["OSType"]
			}
			if ($this.OverrideVMSize) {
				$this.OverrideVMSize = ($this.OverrideVMSize.Split(",") | select -Unique) -join ","
				Write-LogInfo "The OverrideVMSize of case $($test.testName) is set to $($this.OverrideVMSize)"
				if ($test.OverrideVMSize) {
					$test.OverrideVMSize = $this.OverrideVMSize
				} else {
					$test.InnerXml += "<OverrideVMSize>$($this.OverrideVMSize)</OverrideVMSize>"
				}
			}

			# Put test case to hashtable, per setupType,OverrideVMSize,networking,diskType,osDiskType,switchName
			if ($test.setupType) {
				$key = "$($test.setupType),$($test.OverrideVMSize),$($test.AdditionalHWConfig.Networking),$($test.AdditionalHWConfig.DiskType)," +
					"$($test.AdditionalHWConfig.OSDiskType),$($test.AdditionalHWConfig.SwitchName),$($test.AdditionalHWConfig.ImageType)," +
					"$($test.AdditionalHWConfig.OSType),$($test.AdditionalHWConfig.StorageAccountType)"
				if ($this.SetupTypeToTestCases.ContainsKey($key)) {
					$this.SetupTypeToTestCases[$key] += $test
				} else {
					$this.SetupTypeToTestCases.Add($key, @($test))
				}
			}

			# Check whether the case if for Windows images
			$IsWindowsImage = $false
			if(($test.AdditionalHWConfig.OSType -contains "Windows")) {
				$IsWindowsImage = $true
			}
			Set-Variable -Name IsWindowsImage -Value $IsWindowsImage -Scope Global
			if ($test.OverrideVMSize) {
				$this.TotalCaseNum += $test.OverrideVMSize.Split(",").Count
			} else {
				$this.TotalCaseNum++
			}
		}
		$this.TotalCaseNum *= $this.TestIterations
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
		# Note(v-advlad): PowerShell scripts can have a side effect of changing the
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

	[object] RunTestCase($VmData, $CurrentTestData, $ExecutionCount, $SetupTypeData, $ApplyCheckpoint) {
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
			$this.TestProvider.RunSetup($VmData, $CurrentTestData, $testParameters, $ApplyCheckpoint)

			if (!$global:IsWindowsImage) {
				GetAndCheck-KernelLogs -allDeployedVMs $VmData -status "Initial" | Out-Null
			}

			# Upload test files to VMs
			if ($CurrentTestData.files) {
				if(!$global:IsWindowsImage){
					foreach ($vm in $VmData) {
						Copy-RemoteFiles -upload -uploadTo $vm.PublicIP -Port $vm.SSHPort `
							-files $CurrentTestData.files -Username $global:user -password $global:password
						Write-LogInfo "Test files uploaded to VM $($vm.RoleName)"
					}
				}
			}

			$timeout = 300
			if ($CurrentTestData.Timeout) {
				$timeout = $CurrentTestData.Timeout
			}
			Write-LogInfo "Before run-test script with $($global:user)"
			# Run test script
			if ($CurrentTestData.TestScript) {
				$currentTestResult = $this.RunTestScript(
					$CurrentTestData,
					$testParameters,
					$global:LogDir,
					$VmData,
					$global:user,
					$global:password,
					$this.TestLocation,
					$timeout,
					$this.GlobalConfig,
					$this.TestProvider)
			} else {
				throw "Missing TestScript in case $currentTestName."
			}
		} catch {
			$errorMessage = $_.Exception.Message
			$line = $_.InvocationInfo.ScriptLineNumber
			$scriptName = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
			Write-LogErr "EXCEPTION: $errorMessage"
			Write-LogErr "Source: Line $line in script $scriptName."
			$currentTestResult.TestResult = $global:ResultFail
			$currentTestResult.testSummary += $errorMessage
		}

		# Upload results to database
		if ($currentTestResult.TestResultData) {
			Upload-TestResultDataToDatabase -TestResultData $currentTestResult.TestResultData -DatabaseConfig $this.GlobalConfig.Global.$($this.TestPlatform).ResultsDatabase
		}

		# Do log collecting and VM clean up
		$isVmAlive = Is-VmAlive -AllVMDataObject $VMData -MaxRetryCount 10
		# Check if VM is running before collecting logs
		if (!$global:IsWindowsImage -and $testParameters["SkipVerifyKernelLogs"] -ne "True" -and $isVmAlive -eq "True" ) {
			GetAndCheck-KernelLogs -allDeployedVMs $VmData -status "Final" -EnableCodeCoverage $this.EnableCodeCoverage | Out-Null
			$this.GetSystemBasicLogs($VmData, $global:user, $global:password, $CurrentTestData, $currentTestResult, $this.EnableTelemetry) | Out-Null
		}

		$collectDetailLogs = !$this.TestCasePassStatus.contains($currentTestResult.TestResult) -and !$global:IsWindowsImage -and $testParameters["SkipVerifyKernelLogs"] -ne "True" -and $isVmAlive -eq "True"
		$doRemoveFiles = $this.TestCasePassStatus.contains($currentTestResult.TestResult) -and !($this.ResourceCleanup -imatch "Keep") -and !$global:IsWindowsImage -and $testParameters["SkipVerifyKernelLogs"] -ne "True"
		$this.TestProvider.RunTestCaseCleanup($vmData, $CurrentTestData, $currentTestResult, $collectDetailLogs, $doRemoveFiles, `
			$global:user, $global:password, $SetupTypeData, $testParameters)

		# Update test summary
		$testRunDuration = $this.JunitReport.GetTestCaseElapsedTime("LISAv2Test-$($this.TestPlatform)","$currentTestName","mm")
		$this.TestSummary.UpdateTestSummaryForCase($CurrentTestData, $ExecutionCount, $currentTestResult.TestResult, $testRunDuration, $currentTestResult.testSummary, $VmData)

		# Update junit report for current test case
		$caseLog = ($currentTestResult.testSummary + (Get-Content -Raw "$CurrentTestLogDir\$global:LogFileName")).Trim()
		$this.JunitReport.CompleteLogTestCase("LISAv2Test-$($this.TestPlatform)","$currentTestName",$currentTestResult.TestResult,$caseLog)

		# Set back the LogDir to the parent folder
		Set-Variable -Name "LogDir" -Value $oldLogDir -Scope Global
		return $currentTestResult
	}

	[array] GetMultiplexedTestConfigs($testName, $testOverrideVmSize) {
		$multiplexedTestConfigs = @()
		$testVmSizes = @("unknown")

		if ($testOverrideVmSize) {
			$testVmSizes = $testOverrideVmSize.Split(",").Trim()
		}
		if ($this.OverrideVMSize) {
			$testVmSizes = $this.OverrideVMSize.Split(",").Trim()
		}

		if ($this.TestIterations -gt 1 -or $testVmSizes.Count -gt 1) {
			foreach($testVmSize in $testVmSizes) {
				for ($iteration = 1; $iteration -lt $this.TestIterations + 1; $iteration++) {
					$multiplexedTestConfig = @{
						"TestName" = $testName
					}
					if ($testVmSizes.Count -gt 1) {
						$multiplexedTestConfig["TestName"] += "-${testVmSize}"
						$multiplexedTestConfig["TestVmSize"] = $testVmSize
					}
					if ($this.TestIterations -gt 1) {
						$multiplexedTestConfig["TestName"] += "-${iteration}"
					}
					$multiplexedTestConfigs += $multiplexedTestConfig
				}
			}
		} else {
			$multiplexedTestConfigs = @(@{
				"TestName" = $testName
			})
		}

		return $multiplexedTestConfigs
	}

	[void] RunTestInSequence([int]$TestIterations)
	{
		$executionCount = 0

		foreach ($key in $this.SetupTypeToTestCases.Keys) {
			$setupType = $key.Split(',')[0]

			$vmData = $null
			$lastResult = $null
			$tests = 0

			foreach ($case in $this.SetupTypeToTestCases[$key]) {
				$multiplexedTestConfigs = $this.GetMultiplexedTestConfigs($case.testName, $case.OverrideVMSize)
				$tcDeployVM = $this.DeployVMPerEachTest
				$tcRemoveVM = $this.DeployVMPerEachTest
				for ($multiplexedTestIndex = 0; $multiplexedTestIndex -lt $multiplexedTestConfigs.Count; $multiplexedTestIndex++) {
					$multiplexedTestConfig = $multiplexedTestConfigs[$multiplexedTestIndex]
					$case.testName = $multiplexedTestConfig["TestName"]
					if ($multiplexedTestIndex -lt ($multiplexedTestConfigs.Count - 1)) {
						$tcRemoveVM = $this.DeployVMPerEachTest -or `
							($multiplexedTestConfigs[$multiplexedTestIndex + 1]["TestVmSize"] -ne $multiplexedTestConfig["TestVmSize"])
					}
					if ($multiplexedTestIndex -gt 0) {
						$tcDeployVM = $this.DeployVMPerEachTest -or `
							($multiplexedTestConfigs[$multiplexedTestIndex - 1]["TestVmSize"] -ne $multiplexedTestConfig["TestVmSize"])
					}
					if ($multiplexedTestConfig["TestVmSize"]) {
						$case.OverrideVMSize = $multiplexedTestConfig["TestVmSize"]
						$this.SetupTypeToTestCases[$key][0].OverrideVMSize = $multiplexedTestConfig["TestVmSize"]
					}

					Write-LogInfo "$($case.testName) started running."
					$executionCount += 1
					if (!$vmData -or $tcDeployVM) {
						# Deploy the VM for the setup
						$deployVMStatus = $this.TestProvider.DeployVMs($this.GlobalConfig, $this.SetupTypeTable[$setupType], $this.SetupTypeToTestCases[$key][0], `
							$this.TestLocation, $this.RGIdentifier, $this.UseExistingRG, $this.ResourceCleanup)
						$vmData = $null
						$deployErrors = ""
						if ($deployVMStatus) {
							$vmData = $deployVMStatus
							$deployErrors = $deployVMStatus.Error
							if ($deployVMStatus.Keys -and ($deployVMStatus.Keys -contains "VmData")) {
								$vmData = $deployVMStatus.VmData
							}
						}
						if (!$vmData) {
							# Failed to deploy the VMs, Set the case to abort
							$this.JunitReport.StartLogTestCase("LISAv2Test-$($this.TestPlatform)","$($case.testName)","$($this.TestPlatform)-$($case.Category)-$($case.Area)")
							$this.JunitReport.CompleteLogTestCase("LISAv2Test-$($this.TestPlatform)","$($case.testName)","Aborted", $deployErrors)
							$this.TestSummary.UpdateTestSummaryForCase($case, $executionCount, "Aborted", "0", $deployErrors, $null)
							continue
						}
					}
					# Run test case
					$lastResult = $this.RunTestCase($vmData, $case, $executionCount, $this.SetupTypeTable[$setupType], ($tests -ne 0))
					$tests++
					# If the case doesn't pass, keep the VM for failed case except when ResourceCleanup = "Delete" is set
					# and deploy a new VM for the next test
					if (!$this.TestCasePassStatus.contains($lastResult.TestResult)) {
						if ($this.ResourceCleanup -imatch "Delete") {
							$this.TestProvider.DeleteTestVMS($vmData, $this.SetupTypeTable[$setupType], $this.UseExistingRG)
							$vmData = $null
						} elseif (!$this.TestProvider.ReuseVmOnFailure) {
							$vmData = $null
						}
					} elseif ($tcRemoveVM -and !($this.ResourceCleanup -imatch "Keep")) {
						# Delete the VM if tcRemoveVM is set
						# Do not delete the VMs if testing against existing resource group, or -ResourceCleanup = Keep is set
						$this.TestProvider.DeleteTestVMS($vmData, $this.SetupTypeTable[$setupType], $this.UseExistingRG)
						$vmData = $null
					}

					Write-LogInfo "$($case.testName) ended running with status: $($lastResult.TestResult)."
				}
			}

			# Delete the VM after all the cases of same setup are run, if DeployVMPerEachTest is not set
			if ($this.TestCasePassStatus.contains($lastResult.TestResult) -and !($this.ResourceCleanup -imatch "Keep") -and !$this.DeployVMPerEachTest) {
				$this.TestProvider.DeleteTestVMS($vmData, $this.SetupTypeTable[$setupType], $this.UseExistingRG)
			}
		}

		$this.TestProvider.RunTestCleanup()
	}

	[void] RunTest([string]$TestReportXmlPath, [int]$TestIterations, [bool]$RunInParallel) {
		$this.PrepareTestImage()
		Write-LogInfo "Starting the test"

		# Start JUnit XML report logger.
		$this.JunitReport = [JUnitReportGenerator]::New($TestReportXmlPath)
		$this.JunitReport.StartLogTestSuite("LISAv2Test-$($this.TestPlatform)")
		$this.TestSummary = [TestSummary]::New($this.TestCategory, $this.TestArea, $this.TestName, $this.TestTag, $this.TestPriority, $this.TotalCaseNum)

		if (!$RunInParallel) {
			$this.RunTestInSequence($TestIterations)
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
			$KernelVersion = Get-Content "$global:LogDir\$($vmData.RoleName)-kernelVersion.txt"
			$HardwarePlatform = Get-Content "$global:LogDir\$($vmData.RoleName)-hardwarePlatform.txt"
			$GuestDistro = Get-Content "$global:LogDir\$($vmData.RoleName)-distroVersion.txt"
			$LISMatch = (Select-String -Path "$global:LogDir\$($vmData.RoleName)-lis.txt" -Pattern "^version:").Line
			if ($LISMatch) {
				$LISVersion = $LISMatch.Split(":").Trim()[1]
			} else {
				$LISVersion = "NA"
			}
			#region Host Version checking
			$HostVersion = ""
			$FoundLineNumber = (Select-String -Path "$global:LogDir\$($vmData.RoleName)-dmesg.txt" -Pattern "Hyper-V Host Build").LineNumber
			if (![string]::IsNullOrEmpty($FoundLineNumber)) {
				$ActualLineNumber = $FoundLineNumber[-1] - 1
				$FinalLine = [string]((Get-Content -Path "$global:LogDir\$($vmData.RoleName)-dmesg.txt")[$ActualLineNumber])
				$FinalLine = $FinalLine.Replace('; Vmbus version:4.0', '')
				$FinalLine = $FinalLine.Replace('; Vmbus version:3.0', '')
				$HostVersion = ($FinalLine.Split(":")[$FinalLine.Split(":").Count - 1 ]).Trim().TrimEnd(";")
			}
			#endregion

			if ($currentTestData.AdditionalHWConfig.Networking -imatch "SRIOV") {
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
			$VMGeneration = $vmData.VMGeneration
			#endregion
			if ($enableTelemetry) {
				$dataTableName = ""
				if ($this.XmlSecrets.secrets.TableName) {
					$dataTableName = $this.XmlSecrets.secrets.TableName
					Write-LogInfo "Using table name from secrets: $dataTableName"
				} else {
					$dataTableName = "LISAv2Results"
				}

				$SQLQuery = Get-SQLQueryOfTelemetryData -TestPlatform $global:TestPlatform -TestLocation $global:TestLocation -TestCategory $CurrentTestData.Category `
					-TestArea $CurrentTestData.Area -TestName $CurrentTestData.TestName -CurrentTestResult $CurrentTestResult `
					-ExecutionTag $global:GlobalConfig.Global.$global:TestPlatform.ResultsDatabase.testTag -GuestDistro $GuestDistro -KernelVersion $KernelVersion `
					-HardwarePlatform $HardwarePlatform -LISVersion $LISVersion -HostVersion $HostVersion -VMSize $VMSize -VMGeneration $VMGeneration -Networking $Networking `
					-ARMImageName $global:ARMImageName -OsVHD $global:BaseOsVHD -BuildURL $env:BUILD_URL -TableName $dataTableName

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
}
