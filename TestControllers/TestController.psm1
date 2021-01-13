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

Class TestController {
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
	[string] $TestSetup
	[int] $TestIterations
	[bool] $EnableTelemetry
	[string] $OverrideVMSize
	[string] $ResourceCleanup
	[bool] $DeployVMPerEachTest
	[string] $ResultDBTable
	[string] $ResultDBTestTag
	[string] $TestPassID
	[bool] $UseExistingRG
	[array] $TestCaseStatus
	[array] $TestCasePassStatus
	[bool] $EnableCodeCoverage
	[Hashtable] $CustomParams
	[string] $VMGeneration
	[bool] $ForceCustom # For overwrite custom parameters or not
	[bool] $RunInParallel
	[int] $TotalCountInParallel
	[object] $ParamsInParallel
	[string] $TestIdInParallel

	[void] SyncEquivalentCustomParameters([string] $Key, [string] $Value) {
		if ($Value) {
			if ($this.CustomParams.$Key -and $this.CustomParams.$Key -cne $Value) {
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
		$this.TestSetup = $ParamTable["TestSetup"]
		$this.ResourceCleanup = $ParamTable["ResourceCleanup"]
		$this.EnableTelemetry = $ParamTable["EnableTelemetry"]
		$this.TestIterations = $ParamTable["TestIterations"]
		$this.OverrideVMSize = $ParamTable["OverrideVMSize"]
		$this.DeployVMPerEachTest = $ParamTable["DeployVMPerEachTest"]
		$this.ResultDBTable = $ParamTable["ResultDBTable"]
		$this.ResultDBTestTag = $ParamTable["ResultDBTestTag"]
		$this.TestPassID = $ParamTable["TestPassID"]
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
				$value = $_.Substring($_.IndexOf("=") + 1)
				$this.CustomParams[$key] = $value
			}
		}
		$this.ForceCustom = ($ParamTable.ContainsKey("ForceCustom"))
		$this.RunInParallel = ($ParamTable.ContainsKey("RunInParallel"))
		$this.TotalCountInParallel = $ParamTable["TotalCountInParallel"]
		if (!$this.TotalCountInParallel) {
			$processorCount = (Get-WmiObject -class Win32_ComputerSystem).numberoflogicalprocessors
			$this.TotalCountInParallel = [math]::Ceiling($processorCount / 2)
		}
		$this.ParamsInParallel = $ParamTable["ParamsInParallel"]
		$this.TestIdInParallel = $ParamTable["TestIdInParallel"]
		$GlobalConfigurationFile = "$PSScriptRoot\..\XML\GlobalConfigurations.xml"
		if (Test-Path -Path $GlobalConfigurationFile) {
			$this.GlobalConfigurationFilePath = $GlobalConfigurationFile
			$this.GlobalConfig = [xml](Get-Content $GlobalConfigurationFile)
		}
		else {
			throw "Global configuration '$GlobalConfigurationFile' file does not exist"
		}
		$this.SyncEquivalentCustomParameters("TestLocation", $this.TestLocation)
		$this.SyncEquivalentCustomParameters("OsVHD", $this.OsVHD)
		$this.SyncEquivalentCustomParameters("OverrideVMSize", $this.OverrideVMSize)
		$this.SyncEquivalentCustomParameters("VMGeneration", $this.VMGeneration)

		$parameterErrors = @()
		# Validate general parameters
		return $parameterErrors
	}

	[void] UpdateXMLStringsFromSecretsFile() {
		if ($this.XMLSecrets -and !$this.TestIdInParallel) {
			$TestXMLs = Get-ChildItem -Path "$PSScriptRoot\..\XML\TestCases\*.xml"

			foreach ($file in $TestXMLs) {
				$CurrentXMLText = Get-Content -Path $file.FullName
				foreach ($Replace in $this.XMLSecrets.secrets.ReplaceTestXMLStrings.Replace) {
					if ($Replace.InnerText) {
						$Replace.InnerText = [System.Security.SecurityElement]::Escape($Replace.InnerText)
						$ReplaceString, $ReplaceWith = $Replace.InnerText -split '=', 2
					}
					else {
						$ReplaceString, $ReplaceWith = $Replace -split '=', 2
					}
					if ($CurrentXMLText -imatch $ReplaceString) {
						$content = [System.IO.File]::ReadAllText($file.FullName).Replace($ReplaceString, $ReplaceWith)
						[System.IO.File]::WriteAllText($file.FullName, $content)
						Write-LogInfo "$ReplaceString replaced in $($file.FullName)"
					}
				}
			}
			Write-LogInfo "Updated Test Case xml files."
		}
	}

	[void] UpdateRegionAndStorageAccountsFromSecretsFile() {
		if ($this.XMLSecrets.secrets.RegionAndStorageAccounts -and !$this.TestIdInParallel) {
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
				$kustoDataDLLPath = $this.XmlSecrets.secrets.KustoDataDLLPath
				if ($kustoDataDllPath -and (Test-Path "$kustoDataDLLPath")) {
					[System.Reflection.Assembly]::LoadFrom("$kustoDataDllPath") | Out-Null
				}
			}
			else {
				Write-LogErr "The Secret file provided: '$XMLSecretFile' does not exist"
			}
		}
		else {
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

	[void] PrepareSetupTypeToTestCases([hashtable]$SetupTypeToTestCases, [System.Collections.ArrayList]$AllTests) {
		# The multiple TestLocation may be separated by ','
		# and in most cases, the multiple TestLocations should always stick together for certain one TestCase.
		# So, use a fake SplitBy ';' to avoid TestLocations being Splitted into multi single ConfigValues for $AllTests.
		Add-SetupConfig -AllTests $AllTests -ConfigName "TestLocation" -ConfigValue $this.CustomParams["TestLocation"] -SplitBy ';' -Force $this.ForceCustom
		Add-SetupConfig -AllTests $AllTests -ConfigName "OsVHD" -ConfigValue $this.CustomParams["OsVHD"] -Force $this.ForceCustom
		if ($this.TestIterations -gt 1) {
			$testIterationsParamValue = @(1..$this.TestIterations) -join ','
			Add-SetupConfig -AllTests $AllTests -ConfigName "TestIteration" -ConfigValue $testIterationsParamValue -Force $this.ForceCustom
		}

		foreach ($test in $AllTests) {
			# Put test case to hashtable, per setupType, TestLocation, OsVHD
			$key = "$($test.SetupConfig.SetupType),$($test.SetupConfig.TestLocation),$($test.SetupConfig.OsVHD)"
			if ($test.SetupConfig.SetupType) {
				if ($SetupTypeToTestCases.ContainsKey($key)) {
					$SetupTypeToTestCases[$key] += $test
				}
				else {
					$SetupTypeToTestCases.Add($key, @($test))
				}
			}
		}
		$this.TotalCaseNum = ([System.Collections.ArrayList]$AllTests).Count
	}

	[void] LoadTestCases($WorkingDirectory, $CustomTestParameters) {
		$this.SetupTypeToTestCases = @{}
		$this.SetupTypeTable = @{}
		$allTests = $null
		$SetupTypeXMLs = Get-ChildItem -Path "$WorkingDirectory\XML\VMConfigurations\*.xml"
		foreach ($file in $SetupTypeXMLs.FullName) {
			$setupXml = [xml]( Get-Content -Path $file)
			foreach ($setupTypeXml in $setupXml.SelectNodes("/TestSetup/*")) {
				if (!$this.SetupTypeTable[$setupTypeXml.LocalName]) {
					$this.SetupTypeTable[$setupTypeXml.LocalName] = $setupTypeXml
				}
				else {
					Throw "Duplicate setup type defined with the same name: $($setupTypeXml.LocalName) from $file"
				}
			}
		}
		if ($this.TestIdInParallel) {
			Write-LogWarn "Testing under parallel with TestId '$($this.TestIdInParallel)', all SetupConfig and Test Case Filtering parameters will be ignored."
			$parallelTestsFilePath = Join-Path -Path $env:TEMP -ChildPath "AllTests.xml"
			if (Test-Path -Path $parallelTestsFilePath) {
				$parallelTestsDoc = [xml](Get-Content $parallelTestsFilePath)
				$allTests = [System.Collections.ArrayList]@($parallelTestsDoc.TestCases.test)
			}
		}
		else {
			$TestXMLs = Get-ChildItem -Path "$WorkingDirectory\XML\TestCases\*.xml"
			$allTests = [System.Collections.ArrayList](Select-TestCases -TestXMLs $TestXMLs -TestCategory $this.TestCategory -TestArea $this.TestArea -TestSetup $this.TestSetup `
				-TestNames $this.TestNames -TestTag $this.TestTag -TestPriority $this.TestPriority -ExcludeTests $this.ExcludeTests)
			$ReplaceableTestParameters = [xml](Get-Content -Path "$WorkingDirectory\XML\Other\ReplaceableTestParameters.xml")
			# Inject custom parameters
			if ($CustomTestParameters) {
				Write-LogInfo "Checking custom parameters ..."
				$CustomTestParameters = @($CustomTestParameters.Trim("; ").Split(";").Trim())
				foreach ($CustomParameter in $CustomTestParameters) {
					$ReplaceThis = $CustomParameter.Split("=")[0]
					$ReplaceWith = $CustomParameter.Substring($CustomParameter.IndexOf("=") + 1)
					$OldValue = ($ReplaceableTestParameters.ReplaceableTestParameters.Parameter | Where-Object `
						{ $_.ReplaceThis -eq $ReplaceThis }).ReplaceWith
					($ReplaceableTestParameters.ReplaceableTestParameters.Parameter | Where-Object `
						{ $_.ReplaceThis -eq $ReplaceThis }).ReplaceWith = $ReplaceWith
					Write-LogInfo "Custom Parameter: $ReplaceThis=$OldValue --> $ReplaceWith"
				}
				Write-LogInfo "Custom parameter(s) are ready to be injected along with default parameters, if any."
			}
			# Inject replaceable parameters
			foreach ($ReplaceableParameter in $ReplaceableTestParameters.ReplaceableTestParameters.Parameter) {
				$replaceWith = [System.Security.SecurityElement]::Escape($ReplaceableParameter.ReplaceWith)
				foreach ($test in $allTests) {
					$originalInnerXml = $test.InnerXml
					$test.InnerXml = $test.InnerXml -replace "(?<=[>=])([`"]*)$($ReplaceableParameter.ReplaceThis)([`"]*)<", "`${1}$replaceWith`${2}<"
					if ($test.InnerXml -ne $originalInnerXml) {
						Write-LogInfo "$($ReplaceableParameter.ReplaceThis)=$($ReplaceableParameter.ReplaceWith) injected to case $($test.testName)"
					}
				}
			}
		}
		if (!$allTests) {
			Throw "Not able to collect any test cases from XML files"
		}
		else {
			$collectedTCCount = $allTests.Count
			Write-LogInfo "$collectedTCCount Test Cases have been collected"
		}
		$this.PrepareSetupTypeToTestCases($this.SetupTypeToTestCases, $allTests)
		if (($this.TotalCaseNum -eq 0) -or ($allTests.Count -eq 0)) {
			Write-LogWarn "All collected test cases are skipped, because the test case has native SetupConfig that conflicts with current Run-LISAv2 parameters, or LISAv2 needs more specific parameters to run against selected test cases, please check again"
		}
		elseif ($collectedTCCount -ne $allTests.Count) {
			Write-LogInfo "$($allTests.Count) Test Cases have been selected or expanded to be run in this LISAv2 execution, other test cases may have been skipped due to test case native SetupConfig conflicts with current Run-LISAv2 parameters"
		}

		if ($this.RunInParallel -and !$this.TestIdInParallel) {
			if ($this.TotalCountInParallel -ge $allTests.Count) {
				$this.TotalCountInParallel = $allTests.Count
			}
			for ($pIndex = 1; $pIndex -le $this.TotalCountInParallel; $pIndex++) {
				$index = 0..$($allTests.Count - 1) | Where-Object { [int]($_ + 1) % $this.TotalCountInParallel -eq $($pIndex % $this.TotalCountInParallel)}
				$parallelTest = $allTests | Select-Object -Index $index
				$targetTestsFolder = Join-Path -Path $env:TEMP -ChildPath "$global:TestId-$pIndex"
				if (!(Test-Path -Path $targetTestsFolder)) {
					New-Item -Force -Path $targetTestsFolder -ItemType Directory
				}
				$parallelTestsFilePath = Join-Path -Path $targetTestsFolder -ChildPath "AllTests.xml"
				if (Test-Path -Path $parallelTestsFilePath) {
					Remove-Item -Force -Path $parallelTestsFilePath
				}
				[xml]$parallelTestsDoc = New-Object System.Xml.XmlDocument
				$dec = $parallelTestsDoc.CreateXmlDeclaration("1.0", "UTF-8", $null)
				$null = $parallelTestsDoc.AppendChild($dec)
				#$parallelTests.AppendChild($parallelTests.CreateComment($text))
				$tcNode = $parallelTestsDoc.CreateElement("TestCases")
				$parallelTest | ForEach-Object {
					$null = $tcNode.AppendChild($parallelTestsDoc.ImportNode($_, $true))
				}
				$null = $parallelTestsDoc.AppendChild($tcNode)
				$parallelTestsDoc.Save("$parallelTestsFilePath")
			}
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
		if ($CurrentTestData.SetupConfig.OSType -notcontains "Windows") {
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
				$pythonPathSymlink = $pythonPath.Substring(0, $pythonPath.LastIndexOf("/") + 1)
				$pythonPathSymlink += "python"
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
		}
		elseif ($scriptExtension -eq "py") {
			Run-LinuxCmd -Username $Username -password $Password -ip $testVMData.PublicIP -Port $testVMData.SSHPort `
				-Command "python ${Script}" -runMaxAllowedTime $Timeout -runAsSudo
			Run-LinuxCmd -Username $Username -password $Password -ip $testVMData.PublicIP -Port $testVMData.SSHPort `
				-Command "mv Runtime.log ${TestName}_summary.log" -runAsSudo
		}
		elseif ($scriptExtension -eq "ps1") {
			$scriptDir = Join-Path $workDir "Testscripts\Windows"
			$scriptLoc = Join-Path $scriptDir $Script
			$scriptParameters = ""
			foreach ($param in $Parameters.Keys) {
				$scriptParameters += (";{0}={1}" -f ($param, $($Parameters[$param])))
			}
			Write-LogInfo "${scriptLoc} -TestParams $scriptParameters -AllVmData $VmData -TestProvider $TestProvider -CurrentTestData $CurrentTestData"
			$psScriptTestResult = & "${scriptLoc}" -TestParams $scriptParameters -AllVmData `
				$VmData -TestProvider $TestProvider -CurrentTestData $CurrentTestData
		}

		if ($scriptExtension -ne "ps1") {
			$currentTestResult = Collect-TestLogs -LogsDestination $LogDir -ScriptName $scriptName `
				-TestType $scriptExtension -PublicIP $testVMData.PublicIP -SSHPort $testVMData.SSHPort `
				-Username $Username -password $Password -TestName $TestName
		}
		else {
			if ($psScriptTestResult.TestResult) {
				$currentTestResult = $psScriptTestResult
			}
			else {
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
		$oldLogDir = $global:LogDir
		$currentTestResult = Create-TestResultObject
		try {
			# Prepare test case log folder
			$currentTestName = $($CurrentTestData.testName)
			$CurrentTestLogDir = "$global:LogDir\$currentTestName"

			New-Item -Type Directory -Path $CurrentTestLogDir -ErrorAction SilentlyContinue | Out-Null
			Set-Variable -Name "LogDir" -Value $CurrentTestLogDir -Scope Global

			$this.JunitReport.StartLogTestCase("LISAv2Test-$($this.TestPlatform)", "$currentTestName", "$($this.TestPlatform)-$($CurrentTestData.Category)-$($CurrentTestData.Area)")

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

				if ($CurrentTestData.SetupConfig.OSType -notcontains "Windows") {
					Write-LogInfo "==> Check the target machine kernel log."
					$this.GetAndCompareOsLogs($VmData, "Initial")
				}

				# Upload test files to VMs
				if ($CurrentTestData.files) {
					if ($CurrentTestData.SetupConfig.OSType -notcontains "Windows") {
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
				}
				else {
					throw "Test case $currentTestName does not define any TestScript in the XML file."
				}
			}
			catch {
				$errorMessage = $_.Exception.Message
				$line = $_.InvocationInfo.ScriptLineNumber
				$scriptName = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
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

			if ($CurrentTestData.SetupConfig.OSType -notcontains "Windows") {
				if ($testParameters["SkipVerifyKernelLogs"] -ne "True") {
					$ret = $this.GetAndCompareOsLogs($VmData, "Final")
					if (($testParameters["FailForLogCheck"] -eq "True") -and ($ret -eq $false) -and ($currentTestResult.TestResult -eq $global:ResultPass)) {
						$currentTestResult.TestResult = $global:ResultFail
						Write-LogErr "Test $($CurrentTestData.TestName) fails for log check"
						$currentTestResult.testSummary += New-ResultSummary -testResult "Test fails for log check"
					}
				}
			}
			$this.GetSystemBasicLogs($VmData, $global:user, $global:password, $CurrentTestData, $currentTestResult, $this.EnableTelemetry) | Out-Null
			$SystemLogsTelemetryDataCollected = $?

			Write-LogInfo "==> Run test cleanup script if defined."
			$collectDetailLogs = (!$this.TestCasePassStatus.contains($currentTestResult.TestResult) -or $this.CustomParams.VerifyKernelLogs -eq "True") -and ($CurrentTestData.SetupConfig.OSType -notcontains "Windows") -and ((Is-VmAlive -AllVMDataObject $VmData -MaxRetryCount 5) -eq "True")
			$doRemoveFiles = $this.TestCasePassStatus.contains($currentTestResult.TestResult) -and !($this.ResourceCleanup -imatch "Keep") -and ($CurrentTestData.SetupConfig.OSType -notcontains "Windows") -and $this.CustomParams.VerifyKernelLogs -ne "True"
			$this.TestProvider.RunTestCaseCleanup($vmData, $CurrentTestData, $currentTestResult, $collectDetailLogs, $doRemoveFiles, `
					$global:user, $global:password, $SetupTypeData, $testParameters)

			# Set back the LogDir to the parent folder, in order to record Test Summary
			Set-Variable -Name "LogDir" -Value $oldLogDir -Scope Global
			# Update test summary
			$testRunDuration = $this.JunitReport.GetTestCaseElapsedTime("LISAv2Test-$($this.TestPlatform)", "$currentTestName", "mm")
			$this.TestSummary.UpdateTestSummaryForCase($CurrentTestData, $ExecutionCount, $currentTestResult.TestResult, $testRunDuration, $currentTestResult.testSummary, $VmData)

			# Update junit report for current test case
			$testCaseLog = ($currentTestResult.testSummary + (Get-Content -Raw "$CurrentTestLogDir\$global:LogFileName")).Trim()
			$this.JunitReport.CompleteLogTestCase("LISAv2Test-$($this.TestPlatform)", "$currentTestName", $currentTestResult.TestResult, $testCaseLog)
		}
		catch {
			$errorMessage = $_.Exception.Message
			$line = $_.InvocationInfo.ScriptLineNumber
			$scriptName = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
			Write-LogErr "EXCEPTION: $errorMessage"
			Write-LogErr "Source: Line $line in script $scriptName."
		}
		finally {
			if (!$SystemLogsTelemetryDataCollected) {
				$this.GetSystemBasicLogs($VmData, $global:user, $global:password, $CurrentTestData, $currentTestResult, $this.EnableTelemetry) | Out-Null
			}
			# Set back the LogDir to the parent folder, in order to record Test Summary
			Set-Variable -Name "LogDir" -Value $oldLogDir -Scope Global
		}
		return $currentTestResult
	}

	[void] RunTestCasesInParallel([int] $CountInParallel) {
		$this.ParamsInParallel.Remove("RunInParallel")
		$this.ParamsInParallel.Remove("TotalCountInParallel")
		$parallelJobIds = [System.Collections.ArrayList]@()
		for ($pIndex = 1; $pIndex -le $CountInParallel; $pIndex++) {
			$parallelParams = ([System.Collections.Hashtable]$this.ParamsInParallel).Clone()
			$parallelTestId = "$global:TestId-$pIndex"
			if ($this.UseExistingRG) {
				$parallelParams["RGIdentifier"] = "$($this.RGIdentifier)-$parallelTestId"
			}
			$parallelParams["TestIdInParallel"] = $parallelTestId
			$parallelJob = Start-Job -Name "$parallelTestId" -ScriptBlock { Set-Location "$Using:PSScriptRoot\.."; $params = $Using:parallelParams; .\Run-LisaV2.ps1 @params }
			$null = $parallelJobIds.Add($parallelJob.Id)
		}
		$parallelTestSummary = [System.Collections.ArrayList]@()
		while ($parallelJobIds.Count -gt 0) {
			for ($i = 0; $i -lt $parallelJobIds.Count; ) {
				$jobId = $parallelJobIds[$i]
				$parallelJob = Get-Job -Id $jobId
				if ($parallelJob.State -eq "Running") {
					Write-LogInfo "$($parallelJob.Name) is still running"
				}
				else {
					Write-LogInfo "$($parallelJob.Name) finished with State: [$($parallelJob.State)]"
					Remove-Job $parallelJob -Force
					$parallelJobIds.RemoveAt($i)
					$LogFile = Get-Item "$PSScriptRoot\..\TestResults\*$($parallelJob.Name)\*$($parallelJob.Name).log" | Sort-Object CreationTime -Descending | Select-Object -First 1
					if ($logFile) {
						#[INFO ] LISAv2 exit code: 0
						$totalLineOfSummary = Select-String -Path $LogFile.FullName -Pattern "\[INFO \] LISAv2 exit code:"
						$jobTestSummary = Select-String -Path $LogFile.FullName -Pattern "Test $($parallelJob.Name) finished" -Context 0, $totalLineOfSummary.LineNumber
						# Get Total Test Cases from parallel job
						# example of: Total Test Cases      : 3 (2 Passed, 0 Failed, 0 Aborted, 1 Skipped)
						foreach ($summaryline in $jobTestSummary.Context.PostContext) {
							$tcMatches = $summaryline | Select-String -Pattern '\((?<Passed>[0-9]+)\sPassed,\s(?<Failed>[0-9]+)\sFailed,\s(?<Aborted>[0-9]+)\sAborted,\s(?<Skipped>[0-9]+)\sSkipped\)$'
							if ($tcMatches.Matches) {
								foreach ($matchGroup in $tcMatches.Matches.Groups) {
									switch ($matchGroup.Name) {
										"Passed" { $this.TestSummary.TotalPassTc += [int]$matchGroup.Value; break; }
										"Failed" { $this.TestSummary.TotalFailTc += [int]$matchGroup.Value; break; }
										"Aborted" { $this.TestSummary.TotalAbortedTc += [int]$matchGroup.Value; break; }
										"Skipped" { $this.TestSummary.TotalSkippedTc += [int]$matchGroup.Value; break; }
										Default {break;}
									}
								}
								break
							}
						}
						# Skip parallel job Headers and skip [INFO ] Analyzing test results ...
						$isAnalyzingTestResults = $false
						$isSkippedSummaryHeader = $false
						$jobTestSummary.Context.PostContext | Select-Object -Skip 2 | ForEach-Object {
							#Total Time (dd:hh:mm) : 0:0:15
							if ($_ -imatch 'Total Time \(dd:hh:mm\) : ') {
								$isSkippedSummaryHeader = $true
							}
							else {
								#[INFO ] Analyzing test results ...
								if ($_ -imatch '\[INFO \] Analyzing test results ...') {
									$isAnalyzingTestResults = $true
									$null = $parallelTestSummary.Add('')
								}
								if ($isSkippedSummaryHeader -and !$isAnalyzingTestResults) {
									$null = $parallelTestSummary.Add($_)
								}
							}
						}
						Get-Content $LogFile.FullName | foreach-Object { Write-Host "[$($parallelJob.Name)] |>" $_ }
					}
					break
				}
				$i++
				if ($i -eq $parallelJobIds.Count) {
					Write-LogInfo "There are $($parallelJobIds.Count) jobs are still running, will check again after 180 seconds..."
					Start-Sleep -Seconds 180
				}
			}
		}
		Write-Host "[[=====================================================                             =====================================================]]"
		Write-Host "[[===================================================== All Parallel Tests Finished =====================================================]]"
		Write-Host "[[=====================================================                             =====================================================]]"
		$sumTC = [int]($this.TestSummary.TotalPassTc + $this.TestSummary.TotalFailTc + $this.TestSummary.TotalAbortedTc + $this.TestSummary.TotalSkippedTc)
		if ($sumTC -lt [int]$this.TestSummary.TotalTc) {
			Write-LogErr "Some parallel jobs are not finished expectedly, please check and run LISAv2 with another try."
		}
		if ($parallelTestSummary) {
			$this.TestSummary.TextSummary = $parallelTestSummary -join "`r`n"
		}
	}

	[void] RunTestCasesInSequence([int]$TestIterations) {
		$TryCleanupOnSuccess = {
			param ([ref]$VmDataOnSuccess, [object]$SetupTypeData)
			if ($this.ResourceCleanup -imatch "Keep") {
				Write-LogWarn "ResourceCleanup = 'Keep' is respected, you may need to delete the testing resources * MANUALLY * sometime later."
			}
			elseif ($VmDataOnSuccess.Value) {
				Write-LogInfo "Delete deployed target machine ..."
				$null = $this.TestProvider.DeleteVMs($VmDataOnSuccess.Value, $SetupTypeData, $this.UseExistingRG);
			}
			$VmDataOnSuccess.Value = $null
		}
		$TryCleanupOnFailure = {
			param ([ref]$VmDataOnFailure, [object]$SetupTypeData)
			if ($VmDataOnFailure.Value) {
				# when '-ResourceCleanup = Delete', DeleteVMs
				if ($this.ResourceCleanup -imatch "Delete") {
					Write-LogInfo "Delete deployed target machine ..."
					$null = $this.TestProvider.DeleteVMs($VmDataOnFailure.Value, $SetupTypeData, $this.UseExistingRG);
				}
				# when '-UseExistingRG', try to DeleteVMs, unless '-ResourceCleanup = Keep'
				elseif ($this.UseExistingRG) {
					if ($this.ResourceCleanup -imatch "Keep") {
						# '-ResourceCleanup = Keep' may cause following test cases in the same Setup group Aborted (because resource names of deployment are duplicated in the ExistingRG)
						Write-LogWarn "ResourceCleanup = 'Keep' is respected, but may conflict with '-UseExistingRG', as 'Keep' will cause following tests Aborted."
					}
					else {
						Write-LogInfo "Delete deployed target machine ..."
						$null = $this.TestProvider.DeleteVMs($VmDataOnFailure.Value, $SetupTypeData, $this.UseExistingRG);
					}
				}
			}
			# this is by default choice for last Failed/Aborted, when $this.ResourceCleanup -eq 'Default'
			$VmDataOnFailure.Value = $null
		}

		$executionCount = 0
		$setupKeys = @($this.SetupTypeToTestCases.Keys | Sort-Object)
		foreach ($setupKey in $setupKeys) {
			$setupType = $setupKey.Split(',')[0]
			$vmData = $null
			$lastResult = $null
			$tests = 0
			$setOfTests = @($this.SetupTypeToTestCases[$setupKey] | Sort-Object -Property @{Expression = { if ($_.Priority) { $_.Priority } else { '9' } } ; ascending = $true }, TestName)
			foreach ($currentTestCase in $setOfTests) {
				# Reset FinalKernelVersion for each TestCase run
				Set-Variable -Name FinalKernelVersion -Value "" -Scope Global -Force
				$executionCount += 1
				Write-LogInfo "($executionCount/$($this.TotalCaseNum)) testing started: $($currentTestCase.testName)"
				Write-LogInfo "SetupConfig: { $(ConvertFrom-SetupConfig -SetupConfig $currentTestCase.SetupConfig) }"
				if (!$vmData -or $this.DeployVMPerEachTest) {
					# Deploy the VM for the setup
					Write-LogInfo "Deploy target machine for test if required ..."
					$deployVMResults = $this.TestProvider.DeployVMs($this.GlobalConfig, $this.SetupTypeTable[$setupType], $currentTestCase, `
							$currentTestCase.SetupConfig.TestLocation, $this.RGIdentifier, $this.UseExistingRG, $this.ResourceCleanup)
					$vmData = $null
					$deployErrors = ""
					$systemBasicLogsCollected = $false
					if ($deployVMResults) {
						# By default set $vmData with $deployVMResults, because providers may return array of vmData directly if no errors.
						$vmData = $deployVMResults
						$deployErrors = Trim-ErrorLogMessage $deployVMResults.Error
						# override the $vmData if $deployResults give VmData specifically with property 'VmData'
						if ($deployVMResults.Keys -and ($deployVMResults.Keys -contains "VmData")) {
							$vmData = $deployVMResults.VmData
						}
						# if there are deployment errors, skip RunTestCase and TryCleanupOnFailure, and we don't care about '-ReuseVmOnFailure', because this is unrecoverable
						if ($vmData -and $deployVMResults.Error) {
							# Before TryCleanupOnFailure, Set the case to abort, and Submit Telemetry Result
							if (!$systemBasicLogsCollected) {
								$currentTestResult = Create-TestResultObject
								$currentTestResult.TestResult = $global:ResultAborted
								$currentTestResult.TestSummary += $deployErrors
								$this.GetSystemBasicLogs($vmData, $global:user, $global:password, $currentTestCase, $currentTestResult, $this.EnableTelemetry) | Out-Null
								$systemBasicLogsCollected = $true
							}
							&$TryCleanupOnFailure -VmDataOnFailure ([ref]$vmData) -SetupTypeData $this.SetupTypeTable[$setupType]
						}
					}
					if (!$vmData) {
						# Failed to deploy the VMs, Set the case to abort
						$currentTestResult = Create-TestResultObject
						if (!$systemBasicLogsCollected) {
							$currentTestResult = Create-TestResultObject
							$currentTestResult.TestResult = $global:ResultAborted
							$currentTestResult.TestSummary += $deployErrors
							$this.GetSystemBasicLogs($vmData, $global:user, $global:password, $currentTestCase, $currentTestResult, $this.EnableTelemetry) | Out-Null
							$systemBasicLogsCollected = $true
						}
						Write-LogWarn("VMData is empty (null). Aborting the testing.")
						$this.JunitReport.StartLogTestCase("LISAv2Test-$($this.TestPlatform)", "$($currentTestCase.testName)", "$($this.TestPlatform)-$($currentTestCase.Category)-$($currentTestCase.Area)")
						$this.JunitReport.CompleteLogTestCase("LISAv2Test-$($this.TestPlatform)", "$($currentTestCase.testName)", $global:ResultAborted, $deployErrors)
						$this.TestSummary.UpdateTestSummaryForCase($currentTestCase, $executionCount, $global:ResultAborted, "0", $deployErrors, $null)
						continue
					}
					else {
						if ($currentTestCase.SetupConfig.OSType -notcontains "Windows" -and !$global:detectedDistro) {
							$detectedDistro = Detect-LinuxDistro -VIP $vmData[0].PublicIP -SSHport $vmData[0].SSHPort `
								-testVMUser $global:user -testVMPassword $global:password
						}
					}
				}
				elseif ($vmData) {
					# Get updated Initial Kernel for current Test Case, because last test case may have updated kernel version
					$firstVMData = $vmData | Select-Object -First 1
					if (!$vmData.IsWindows) {
						$global:InitialKernelVersion = Run-LinuxCmd -ip $firstVMData.PublicIP -port $firstVMData.SSHPort -username $global:user -password $global:password -command "uname -r"
						Write-LogInfo "Initial Kernel Version: $global:InitialKernelVersion"
					}

					if ($this.TestPlatform -imatch "Azure") {
						Add-ResourceGroupTag -ResourceGroup $firstVMData.ResourceGroupName -TagName TestName -TagValue $currentTestCase.TestName
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
					# Only when '$this.DeployVMPerEachTest', TryCleanupOnSuccess, otherwise, keep and reuse all VmData
					if ($this.DeployVMPerEachTest -or ($currentTestCase.DeleteVMsOnSuccess -eq 'True')) {
						&$TryCleanupOnSuccess -VmDataOnSuccess ([ref]$vmData) -SetupTypeData $this.SetupTypeTable[$setupType]
					}
				}
				else {
					#Last Test is Failed/Aborted, check '-ReuseVMOnFailure', and set $readyForReuseVM = $true if RestartAllDeployments successfully.
					$readyForReuseVM = $false
					if ($this.TestProvider.ReuseVmOnFailure) {
						Write-LogInfo "Try reuse VM instances from last deployment, as '-ReuseVmOnFailure' is True"
						# Here the VM is not an initial state after provision, should be responsible immediately, but maybe already kernel panic or no response at all, so if VM is Not Alive after 3 retries, giving up the restart.
						if ($vmData -and ((Is-VmAlive -AllVMDataObject $vmData -MaxRetryCount 3) -eq "True")) {
							$readyForReuseVM = $this.TestProvider.RestartAllDeployments($vmData)
						}
					}
					# If -not $readyForReuseVM, LISA will preserve VM environment for analysis/debugging by default.
					# but eventually will set $vmData = $null, which means force another deployment happen for next test case
					if (!$readyForReuseVM) {
						&$TryCleanupOnFailure -VmDataOnFailure ([ref]$vmData) -SetupTypeData $this.SetupTypeTable[$setupType]
					}
				}
			}

			# Cleanup, if $vmData is not $null (Not Preserved for failure/debugging) or 'ResourceCleanup = Delete'
			# at the end of each SetupType (Combined setup Key) after all tests belongs to this testSetup completed
			if ($vmData -or ($this.ResourceCleanup -imatch "Delete")) {
				&$TryCleanupOnSuccess -VmDataOnSuccess ([ref]$vmData) -SetupTypeData $this.SetupTypeTable[$setupType]
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
		}
		else {
			$this.RunTestCasesInParallel($this.TotalCountInParallel)
		}

		$this.JunitReport.CompleteLogTestSuite("LISAv2Test-$($this.TestPlatform)")
		$this.JunitReport.SaveLogReport()
		$this.TestSummary.SaveHtmlTestSummary(".\Report\TestSummary-$global:TestID.html")
	}

	[void] GetSystemBasicLogs($AllVMData, $User, $Password, $CurrentTestData, $CurrentTestResult, $enableTelemetry) {
		$GuestDistro = $null
		$HardwarePlatform = $null
		$LISVersion = "NA"
		$HostVersion = $null
		$VMSize = $null
		$VMGen = $null
		$Networking = $null
		try {
			$VMGen = $CurrentTestData.SetupConfig.VMGeneration
			if ($currentTestData.SetupConfig.Networking -imatch "SRIOV") {
				$Networking = "SRIOV"
			}
			else {
				$Networking = "Synthetic"
			}
			if ($global:TestPlatform -eq "HyperV") {
				$VMSize = $global:HyperVInstanceSize
			}
			if ($AllVMData.Count -gt 1) {
				$vmData = $AllVMData[0]
			}
			else {
				$vmData = $AllVMData
			}

			if ($vmData -and !$vmData.IsWindows -and ((Is-VmAlive -AllVMDataObject $vmData -MaxRetryCount 5) -eq "True")) {
				if ($global:TestPlatform -eq "Azure") {
					$VMSize = $vmData.InstanceSize
					# No Azure API, we use ARMImageName convention to get VMGeneration for Azure
					if (!$CurrentTestData.SetupConfig.OsVHD -and ($CurrentTestData.SetupConfig.VMGeneration -ne "2") -and $CurrentTestData.SetupConfig.ARMImageName -imatch "gen2") {
						$VMGen = 2
					}
				}
				if ($global:TestPlatform -eq "HyperV") {
					$VMGen = $vmData.VMGeneration
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
				}
				$HostBuildMatches = Select-string -Path "$global:LogDir\$($vmData.RoleName)-dmesg.txt" -Pattern "Hyper-V\s*Host.*Build:\s*([^a-zA-Z:;\s]+)"
				if ($HostBuildMatches) {
					$HostVersion = $HostBuildMatches.Matches.Groups[1].Value
				}
			}
		}
		catch {
			$line = $_.InvocationInfo.ScriptLineNumber
			$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
			$ErrorMessage = $_.Exception.Message
			Write-LogErr "EXCEPTION: $ErrorMessage"
			Write-LogErr "Calling function - $($MyInvocation.MyCommand)."
			Write-LogErr "Source: Line $line in script $script_name."
		}

		if ($enableTelemetry) {
			try {
				$dataTableName = ""
				if ($this.XmlSecrets.secrets.TableName) {
					$dataTableName = $this.XmlSecrets.secrets.TableName
					Write-LogInfo "Using table name from secrets: $dataTableName"
				}
				else {
					#$dataTableName = "LISAv2Results"
					$dataTableName = "LISATestTelemetry"
				}

				$failureReason = ""
				if ($CurrentTestResult.TestSummary) {
					switch ($CurrentTestResult.TestSummary) {
						{ $_ -imatch "The following list of images referenced from the deployment template are not found" } {
							$failureReason = "Image is not available when deploying the image"
							break
						}
						{ $_ -imatch 'Marketplace purchase eligibilty check returned errors. See inner errors for details' } {
							$failureReason = "Purchase Plan Error - Marketplace purchase eligibilty check returned errors"
							break
						}
						{ $_ -imatch 'Reboot : FAIL' -or `
							(
								$_ -imatch "Template output evaluation skipped: at least one resource deployment operation failed." `
									-and `
								(
									$_ -imatch "VM [^\s]+ did not start in the allotted time. The VM may still start successfully. Please check the power state later." `
										-or `
										$_ -imatch "VM [^\s]+ did not finish in the allotted time. The VM may still finish provisioning successfully. Please check provisioning state later." `
										-or `
										$_ -imatch "OS Provisioning failed for VM [^\s]+ due to an internal error."
								)
							) } {
							$failureReason = "VM did not boot up"
							break
						}
						{ $_ -imatch 'Username specified for the VM is invalid for this Linux distribution.' -or $_ -imatch 'Calling function - Upload-RemoteFile. Error in upload after 10 attempt, hence giving up' } {
							$failureReason = "Image configuration issue"
							break
						}
						Default { if ($this.TestCasePassStatus -notcontains $CurrentTestResult.TestResult) { $failureReason = "Pending Triage" }; break }
					}
				}
				$SQLQuery = Get-SQLQueryOfTelemetryData -TestPlatform $global:TestPlatform -TestLocation $CurrentTestData.SetupConfig.TestLocation -TestCategory $CurrentTestData.Category `
					-TestArea $CurrentTestData.Area -TestName $CurrentTestData.TestName -CurrentTestResult $CurrentTestResult `
					-ExecutionTag ($global:GlobalConfig).Global.($global:TestPlatform).ResultsDatabase.testTag -GuestDistro $GuestDistro -KernelVersion $global:FinalKernelVersion `
					-HardwarePlatform $HardwarePlatform -LISVersion $LISVersion -HostVersion $HostVersion -VMSize $VMSize -VMGeneration $VMGen -Networking $Networking `
					-ARMImageName $CurrentTestData.SetupConfig.ARMImageName -OsVHD $global:BaseOsVHD -BuildURL $env:BUILD_URL -TableName $dataTableName -TestPassID $this.TestPassID -FailureReason $failureReason

				Upload-TestResultToDatabase -SQLQuery $SQLQuery

				# IngestKusto may throw exceptions or log error messages, in that case, manual configuration is needed from kusto cluster service for its table schemas mapping to exising SQL database
				Invoke-IngestKustoFromTSQL -SQLString $SQLQuery
			}
			catch {
				$line = $_.InvocationInfo.ScriptLineNumber
				$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
				$ErrorMessage = $_.Exception.Message
				Write-LogErr "EXCEPTION: $ErrorMessage"
				Write-LogErr "Calling function - $($MyInvocation.MyCommand)."
				Write-LogErr "Source: Line $line in script $script_name."
			}
		}
	}

	[bool] GetAndCompareOsLogs($AllVMData, $Status) {
		$retValue = $true
		try	{
			if (!($status -imatch "Initial" -or $status -imatch "Final")) {
				Write-LogErr "Status value should be either final or initial"
				return $false
			}
			if ((Is-VmAlive -AllVMDataObject $AllVMData -MaxRetryCount 5) -eq "True") {
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
						}
						else {
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
					$callTraceFound = $false
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

					if ($status -imatch "Final") {
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
			}
		}
		catch {
			$line = $_.InvocationInfo.ScriptLineNumber
			$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
			$ErrorMessage = $_.Exception.Message
			Write-LogErr "EXCEPTION: $ErrorMessage"
			Write-LogErr "Calling function - $($MyInvocation.MyCommand)."
			Write-LogErr "Source: Line $line in script $script_name."
		}

		return $retValue
	}
}
