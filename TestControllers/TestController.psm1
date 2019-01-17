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
	[string] $TestPriority
	[int] $TestIterations
	[bool] $EnableTelemetry
	[bool] $EnableAcceleratedNetworking
	[bool] $UseManagedDisks
	[string] $OverrideVMSize
	[bool] $ForceDeleteResources
	[bool] $DoNotDeleteVMs
	[bool] $DeployVMPerEachTest
	[string] $ResultDBTable
	[string] $ResultDBTestTag
	[bool] $UseExistingRG

	[string[]] ParseAndValidateParameters([Hashtable]$ParamTable) {
		$this.TestLocation = $ParamTable["TestLocation"]
		$this.RGIdentifier = $ParamTable["RGIdentifier"]
		$this.OsVHD = $ParamTable["OsVHD"]
		$this.TestCategory = $ParamTable["TestCategory"]
		$this.TestNames = $ParamTable["TestNames"]
		$this.TestArea = $ParamTable["TestArea"]
		$this.TestTag = $ParamTable["TestTag"]
		$this.TestPriority = $ParamTable["TestPriority"]
		$this.DoNotDeleteVMs = $ParamTable["DoNotDeleteVMs"]
		$this.ForceDeleteResources = $ParamTable["ForceDeleteResources"]
		$this.EnableTelemetry = $ParamTable["EnableTelemetry"]
		$this.TestIterations = $ParamTable["TestIterations"]
		$this.OverrideVMSize = $ParamTable["OverrideVMSize"]
		$this.EnableAcceleratedNetworking = $ParamTable["EnableAcceleratedNetworking"]
		$this.UseManagedDisks = $ParamTable["UseManagedDisks"]
		$this.DeployVMPerEachTest = $ParamTable["DeployVMPerEachTest"]
		$this.ResultDBTable = $ParamTable["ResultDBTable"]
		$this.ResultDBTestTag = $ParamTable["ResultDBTestTag"]
		$this.UseExistingRG = $ParamTable["UseExistingRG"]

		$this.TestProvider.CustomKernel = $ParamTable["CustomKernel"]
		$this.TestProvider.CustomLIS = $ParamTable["CustomLIS"]

		$parameterErrors = @()
		# Validate general parameters
		if (!$this.RGIdentifier) {
			$parameterErrors += "-RGIdentifier is not set"
		}
		if ($this.DoNotDeleteVMs -and $this.ForceDeleteResources) {
			$parameterErrors += "Conflict: both -DoNotDeleteVMs and -ForceDeleteResources are set."
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

	[void] PrepareTestEnvironment($XMLSecretFile) {
		if ($XMLSecretFile) {
			if (Test-Path -Path $XMLSecretFile) {
				$this.XmlSecrets = ([xml](Get-Content $XMLSecretFile))

				# Download the tools required for LISAv2 execution.
				Get-LISAv2Tools -XMLSecretFile $XMLSecretFile

				$this.UpdateXMLStringsFromSecretsFile()
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
		Set-Variable -Name resultPass -Value "PASS" -Scope Global
		Set-Variable -Name resultFail -Value "FAIL" -Scope Global
		Set-Variable -Name resultAborted -Value "ABORTED" -Scope Global
	}

	[void] LoadTestCases($WorkingDirectory, $CustomParameters) {
		$this.SetupTypeToTestCases = @{}
		$this.SetupTypeTable = @{}

		$TestXMLs = Get-ChildItem -Path "$WorkingDirectory\XML\TestCases\*.xml"
		$SetupTypeXMLs = Get-ChildItem -Path "$WorkingDirectory\XML\VMConfigurations\*.xml"
		$ReplaceableTestParameters = [xml](Get-Content -Path "$WorkingDirectory\XML\Other\ReplaceableTestParameters.xml")

		$allTests = Collect-TestCases -TestXMLs $TestXMLs -TestCategory $this.TestCategory -TestArea $this.TestArea `
			-TestNames $this.TestNames -TestTag $this.TestTag -TestPriority $this.TestPriority
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
					$this.SetupTypeTable.Add($SetupType, $CurrentSetupType.$SetupType)
				}
			}
		}
		# Inject custom parameters
		if ($CustomParameters) {
			Write-LogInfo "Checking custom parameters ..."
			$CustomParameters = $CustomParameters.Trim().Trim(";").Split(";")
			foreach ($CustomParameter in $CustomParameters)
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
				if ($test.InnerXml -imatch $ReplaceableParameter.ReplaceThis) {
					$test.InnerXml = $test.InnerXml.Replace($ReplaceableParameter.ReplaceThis,$ReplaceableParameter.ReplaceWith)
					Write-LogInfo "$($ReplaceableParameter.ReplaceThis)=$($ReplaceableParameter.ReplaceWith) injected to case $($test.testName)"
				}
			}

			# Inject EnableAcceleratedNetworking, UseManagedDisks, OverrideVMSize to test case data
			if ($this.EnableAcceleratedNetworking) {
				Set-AdditionalHWConfigInTestCaseData -CurrentTestData $test -ConfigName "Networking" -ConfigValue "SRIOV"
			}
			if ($this.UseManagedDisks) {
				Set-AdditionalHWConfigInTestCaseData -CurrentTestData $test -ConfigName "DiskType" -ConfigValue "Managed"
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
			if ($test.AdditionalHWConfig) {
				if ($test.AdditionalHWConfig.Networking) {
					$networking = $test.AdditionalHWConfig.Networking
				}
				if ($test.AdditionalHWConfig.DiskType) {
					$diskType = $test.AdditionalHWConfig.DiskType
				}
				if ($test.AdditionalHWConfig.OSDiskType) {
					$osDiskType = $test.AdditionalHWConfig.OSDiskType
				}
				if ($test.AdditionalHWConfig.SwitchName) {
					$switchName = $test.AdditionalHWConfig.SwitchName
				}
			}

			# Add case to hashtable
			if ($test.setupType) {
				$key = "$($test.setupType),$($test.OverrideVMSize),$networking,$diskType,$osDiskType,$switchName"
				if ($this.SetupTypeToTestCases.ContainsKey($key)) {
					$this.SetupTypeToTestCases[$key] += $test
				} else {
					$this.SetupTypeToTestCases.Add($key, @($test))
				}
			}

			# Check whether the case if for Windows images
			$isWindows = $false
			if($test.Tags -and $test.Tags.ToString().Contains("nested-hyperv")) {
				$isWindows = $true
			}
			Set-Variable -Name IsWindows -Value $isWindows -Scope Global
		}
	}

	[void] PrepareTestImage() {}

	[object] RunTestCase($VmData, $CurrentTestData, $ExecutionCount, $SetupTypeData) {
		# Prepare test case log folder
		$currentTestName = $($CurrentTestData.testName)
		$oldLogDir = $global:LogDir
		$CurrentTestLogDir = "$global:LogDir\$currentTestName"
		$currentTestResult = Create-TestResultObject

		New-Item -Type Directory -Path $CurrentTestLogDir -ErrorAction SilentlyContinue | Out-Null
		Set-Variable -Name "LogDir" -Value $CurrentTestLogDir -Scope Global

		$this.JunitReport.StartLogTestCase("LISAv2Test","$currentTestName","$global:TestID")

		try {
			# Get test case parameters
			$testParameters = @{}
			if ($CurrentTestData.TestParameters) {
				$testParameters = Parse-TestParameters -XMLParams $CurrentTestData.TestParameters `
					-GlobalConfig $this.GlobalConfig -AllVMData $VmData
			}

			if (!$this.IsWindows) {
				GetAndCheck-KernelLogs -allDeployedVMs $VmData -status "Initial" | Out-Null
			}

			# Run setup script if any
			$this.TestProvider.RunSetup($VmData, $CurrentTestData, $testParameters)

			# Upload test files to VMs
			if ($CurrentTestData.files) {
				if(!$this.IsWindows){
					foreach ($vm in $VmData) {
						Copy-RemoteFiles -upload -uploadTo $vm.PublicIP -Port $vm.SSHPort `
							-files $CurrentTestData.files -Username $this.VmUsername -password $this.VmPassword
						Write-LogInfo "Test files uploaded to VM $($vm.RoleName)"
					}
				}
			}

			$timeout = 300
			if ($CurrentTestData.Timeout) {
				$timeout = $CurrentTestData.Timeout
			}

			# Run test script
			if ($CurrentTestData.TestScript) {
				$testResult = Run-TestScript -CurrentTestData $CurrentTestData `
					-Parameters $testParameters -LogDir $global:LogDir -VMData $VmData `
					-Username $this.VmUsername -password $this.VmPassword `
					-TestLocation $this.TestLocation -TestProvider $this.TestProvider `
					-Timeout $timeout -GlobalConfig $this.GlobalConfig
				# Some cases returns a string, some returns a result object
				if ($testResult.TestResult) {
					$currentTestResult = $testResult
				} else {
					$currentTestResult.TestResult = Get-FinalResultHeader -resultArr $testResult
				}
			} else {
				throw "Missing TestScript in case $currentTestName."
			}
		}
		catch {
			$errorMessage = $_.Exception.Message
			$line = $_.InvocationInfo.ScriptLineNumber
			$scriptName = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
			Write-LogErr "EXCEPTION : $errorMessage"
			Write-LogErr "Source : Line $line in script $scriptName."
			$currentTestResult.TestResult = "Aborted"
		}

		# Do log collecting and VM clean up
		if (!$this.IsWindows -and $testParameters["SkipVerifyKernelLogs"] -ne "True") {
			GetAndCheck-KernelLogs -allDeployedVMs $VmData -status "Final" | Out-Null
			Get-SystemBasicLogs -AllVMData $VmData -User $this.VmUsername -Password $this.VmPassword -CurrentTestData $CurrentTestData `
				-CurrentTestResult $currentTestResult -enableTelemetry $this.EnableTelemetry
		}

		$collectDetailLogs = $currentTestResult.TestResult -ne "PASS" -and !$this.IsWindows -and $testParameters["SkipVerifyKernelLogs"] -ne "True"
		$doRemoveFiles = $currentTestResult.TestResult -eq "PASS" -and !$this.DoNotDeleteVMs -and !$this.IsWindows -and $testParameters["SkipVerifyKernelLogs"] -ne "True"
		$this.TestProvider.RunTestCaseCleanup($vmData, $CurrentTestData, $currentTestResult, $collectDetailLogs, $doRemoveFiles, `
				$this.VmUsername, $this.VmPassword, $SetupTypeData, $testParameters)

		# Update test summary
		$testRunDuration = $this.junitReport.GetTestCaseElapsedTime("LISAv2Test","$currentTestName","mm")
		$this.TestSummary.UpdateTestSummaryForCase($currentTestName, $ExecutionCount, $currentTestResult.TestResult, $testRunDuration, $currentTestResult.testSummary, $VmData)

		# Update junit report for current test case
		$caseLog = Get-Content -Raw "$CurrentTestLogDir\$global:LogFileName"
		$this.JunitReport.CompleteLogTestCase("LISAv2Test","$currentTestName",$currentTestResult.TestResult,$caseLog)

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
			foreach ($case in $this.SetupTypeToTestCases[$key]) {
				$originalTestName = $case.TestName
				for ( $testIterationCount = 1; $testIterationCount -le $this.TestIterations; $testIterationCount ++ ) {
					if ( $this.TestIterations -ne 1 ) {
						$case.testName = "$($originalTestName)-$testIterationCount"
					}
					$executionCount += 1
					if (!$vmData -or $this.DeployVMPerEachTest) {
						# Deploy the VM for the setup
						$vmData = $this.TestProvider.DeployVMs($this.GlobalConfig, $this.SetupTypeTable[$setupType], $this.SetupTypeToTestCases[$key][0], `
							$this.TestLocation, $this.RGIdentifier, $this.UseExistingRG)
						if (!$vmData) {
							# Failed to deploy the VMs, Set the case to abort
							$this.JunitReport.StartLogTestCase("LISAv2Test","$($case.testName)","$global:TestID")
							$this.JunitReport.CompleteLogTestCase("LISAv2Test","$($case.testName)","Aborted","")
							$this.TestSummary.UpdateTestSummaryForCase($case.testName, $executionCount, "Aborted", "0", "", $null)
							continue
						}
					}
					# Run test case
					$lastResult = $this.RunTestCase($vmData, $case, $executionCount, $this.SetupTypeTable[$setupType])
					# If the case doesn't pass, keep the VM for failed case except when ForceDeleteResources is set
					# and deploy a new VM for the next test
					if ($lastResult.TestResult -ne "PASS") {
						if ($this.ForceDeleteResources) {
							$this.TestProvider.DeleteTestVMS($vmData, $this.SetupTypeTable[$setupType], $this.UseExistingRG)
						}
						$vmData = $null
					} elseif ($this.DeployVMPerEachTest -and !$this.DoNotDeleteVMs) {
						# Delete the VM if DeployVMPerEachTest is set
						# Do not delete the VMs if testing against existing resource group, or DoNotDeleteVMs is set
						$this.TestProvider.DeleteTestVMS($vmData, $this.SetupTypeTable[$setupType], $this.UseExistingRG)
					}
				}
			}

			# Delete the VM after all the cases of same setup are run, if DeployVMPerEachTest is not set
			if ($lastResult.TestResult -eq "PASS" -and !$this.DoNotDeleteVMs -and !$this.DeployVMPerEachTest) {
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
		$this.JunitReport.StartLogTestSuite("LISAv2Test")
		$this.TestSummary = [TestSummary]::New($this.TestCategory, $this.TestArea, $this.TestName, $this.TestTag, $this.TestPriority, $this.TotalCaseNum)

		if (!$RunInParallel) {
			$this.RunTestInSequence($TestIterations)
		} else {
			throw "Running test in parallel is not supported yet."
		}

		$this.JunitReport.CompleteLogTestSuite("LISAv2Test")
		$this.JunitReport.SaveLogReport()
		$this.TestSummary.SaveHtmlTestSummary(".\Report\TestSummary-$global:TestID.html")
	}
}



