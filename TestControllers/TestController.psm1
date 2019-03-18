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
		} else {
			$this.TotalCaseNum = @($allTests).Count
		}
		Write-LogInfo "$(@($allTests).Length) Test Cases have been collected"

		$SetupTypes = $allTests.setupType | Sort-Object | Get-Unique

		foreach ( $file in $SetupTypeXMLs.FullName)	{
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
			if ($this.OverrideVMSize) {
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
					"$($test.AdditionalHWConfig.OSDiskType),$($test.AdditionalHWConfig.SwitchName),$($test.AdditionalHWConfig.ImageType)"
				if ($this.SetupTypeToTestCases.ContainsKey($key)) {
					$this.SetupTypeToTestCases[$key] += $test
				} else {
					$this.SetupTypeToTestCases.Add($key, @($test))
				}
			}

			# Check whether the case if for Windows images
			$IsWindowsImage = $false
			if($test.Tags -and $test.Tags.ToString().Contains("nested-hyperv")) {
				$IsWindowsImage = $true
			}
			Set-Variable -Name IsWindowsImage -Value $IsWindowsImage -Scope Global
		}
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
				-Command "which python || which python2 || which python3" -runAsSudo
			if (($pythonPath -imatch "python2") -or ($pythonPath -imatch "python3")) {
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

		$this.JunitReport.StartLogTestCase("LISAv2Test-$($this.TestPlatform)","$currentTestName","$($CurrentTestData.Category)-$($CurrentTestData.Area)")

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
			Get-SystemBasicLogs -AllVMData $VmData -User $global:user -Password $global:password -CurrentTestData $CurrentTestData `
				-CurrentTestResult $currentTestResult -enableTelemetry $this.EnableTelemetry
		}

		$collectDetailLogs = !$this.TestCasePassStatus.contains($currentTestResult.TestResult) -and !$global:IsWindowsImage -and $testParameters["SkipVerifyKernelLogs"] -ne "True" -and $isVmAlive -eq "True"
		$doRemoveFiles = $this.TestCasePassStatus.contains($currentTestResult.TestResult) -and !($this.ResourceCleanup -imatch "Keep") -and !$global:IsWindowsImage -and $testParameters["SkipVerifyKernelLogs"] -ne "True"
		$this.TestProvider.RunTestCaseCleanup($vmData, $CurrentTestData, $currentTestResult, $collectDetailLogs, $doRemoveFiles, `
			$global:user, $global:password, $SetupTypeData, $testParameters)

		# Update test summary
		$testRunDuration = $this.JunitReport.GetTestCaseElapsedTime("LISAv2Test-$($this.TestPlatform)","$currentTestName","mm")
		$this.TestSummary.UpdateTestSummaryForCase($CurrentTestData, $ExecutionCount, $currentTestResult.TestResult, $testRunDuration, $currentTestResult.testSummary, $VmData)

		# Update junit report for current test case
		$caseLog = Get-Content -Raw "$CurrentTestLogDir\$global:LogFileName"
		$this.JunitReport.CompleteLogTestCase("LISAv2Test-$($this.TestPlatform)","$currentTestName",$currentTestResult.TestResult,$caseLog)

		# Set back the LogDir to the parent folder
		Set-Variable -Name "LogDir" -Value $oldLogDir -Scope Global
		return $currentTestResult
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
				$originalTestName = $case.TestName
				for ( $testIterationCount = 1; $testIterationCount -le $this.TestIterations; $testIterationCount ++ ) {
					if ( $this.TestIterations -ne 1 ) {
						$case.testName = "$($originalTestName)-$testIterationCount"
					}
					Write-LogInfo "$($case.testName) started running."
					$executionCount += 1
					if (!$vmData -or $this.DeployVMPerEachTest) {
						# Deploy the VM for the setup
						$vmData = $this.TestProvider.DeployVMs($this.GlobalConfig, $this.SetupTypeTable[$setupType], $this.SetupTypeToTestCases[$key][0], `
							$this.TestLocation, $this.RGIdentifier, $this.UseExistingRG, $this.ResourceCleanup)
						if (!$vmData) {
							# Failed to deploy the VMs, Set the case to abort
							$this.JunitReport.StartLogTestCase("LISAv2Test-$($this.TestPlatform)","$($case.testName)","$($case.Category)-$($case.Area)")
							$this.JunitReport.CompleteLogTestCase("LISAv2Test-$($this.TestPlatform)","$($case.testName)","Aborted","")
							$this.TestSummary.UpdateTestSummaryForCase($case, $executionCount, "Aborted", "0", "", $null)
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
					} elseif ($this.DeployVMPerEachTest -and !($this.ResourceCleanup -imatch "Keep")) {
						# Delete the VM if DeployVMPerEachTest is set
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
}
