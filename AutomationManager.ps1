##############################################################################################
# AutomationManager.ps1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
<#
.SYNOPSIS
	This script manages all the setup and test operations in Azure & Hyper-V environment.
		It is an entry script of Automation
		Installing AzureSDK
		- VHD preparation : Installing packages required by ICA, LIS drivers and WALA
		- Uploading test VHD to cloud
		- Invokes Azure test suite or Hyper-v tests

.PARAMETER
#	See param lines

.INPUTS
	Load dependent modules
	Set all parameters as global variables
	Azure login
#>
###############################################################################################
using Module .\Libraries\LogProcessing.psm1

param (
[CmdletBinding()]
[string] $xmlConfigFile,
[string] $RGIdentifier,
[string] $cycleName,
[string] $TestPriority,
[switch] $DeployVMPerEachTest,
[switch] $DoNotDeleteVMs,
[string] $OverrideVMSize,
[switch] $EnableAcceleratedNetworking,
[string] $CustomKernel,
[string] $CustomLIS,
[string] $customLISBranch,
[string] $ExistingResourceGroup,
[switch] $CleanupExistingRG,
[string] $XMLSecretFile,
[string] $TestReportXmlPath,

# Experimental Feature
[switch] $UseManagedDisks,

[int] $TestIterations = 1,
[string] $TiPSessionId="",
[string] $TiPCluster="",
[switch] $ForceDeleteResources
)

Function Run-TestsOnCycle ([string] $cycleName, [xml] $xmlConfig, [string] $Distro, [int] $TestIterations, [bool] $deployVMPerEachTest, [string] $TestReportXmlPath) {
	Write-LogInfo "Starting the Cycle - $($CycleName.ToUpper())"
	$executionCount = 0

	foreach ( $tempDistro in $xmlConfig.config.$TestPlatform.Deployment.Data.Distro ) {
		if ( ($tempDistro.Name).ToUpper() -eq ($Distro).ToUpper() ) {
			if ( ($null -ne $tempDistro.ARMImage.Publisher) -and ($null -ne $tempDistro.ARMImage.Offer) -and ($null -ne $tempDistro.ARMImage.Sku) -and ($null -ne $tempDistro.ARMImage.Version)) {
				$ARMImage = $tempDistro.ARMImage
				Set-Variable -Name ARMImage -Value $ARMImage -Scope Global
				Write-LogInfo "ARMImage name - $($ARMImage.Publisher) : $($ARMImage.Offer) : $($ARMImage.Sku) : $($ARMImage.Version)"
			}
			if ( $tempDistro.OsVHD ) {
				$BaseOsVHD = $tempDistro.OsVHD.InnerText.Trim()
				Set-Variable -Name BaseOsVHD -Value $BaseOsVHD -Scope Global
				Write-LogInfo "Base VHD name - $BaseOsVHD"
			}
		}
	}
	if (!$($ARMImage.Publisher) -and !$BaseOSVHD) {
		Throw "Please give ARM Image / VHD for ARM deployment."
	}

	#If Base OS VHD is present in another storage account, then copy to test storage account first.
	if ($BaseOsVHD -imatch "/") {
		#Check if the test storage account is same as VHD's original storage account.
		$givenVHDStorageAccount = $BaseOsVHD.Replace("https://","").Replace("http://","").Split(".")[0]
		$ARMStorageAccount = $xmlConfig.config.$TestPlatform.General.ARMStorageAccount

		if ($givenVHDStorageAccount -ne $ARMStorageAccount ) {
			Write-LogInfo "Your test VHD is not in target storage account ($ARMStorageAccount)."
			Write-LogInfo "Your VHD will be copied to $ARMStorageAccount now."
			$sourceContainer =  $BaseOsVHD.Split("/")[$BaseOsVHD.Split("/").Count - 2]
			$vhdName = $BaseOsVHD.Split("?")[0].split('/')[-1]
			if ($ARMStorageAccount -inotmatch "NewStorage_") {
				#Copy the VHD to current storage account.
				#Check if the BaseOsVHD is a SasUrl
				if ( ($BaseOsVHD -imatch 'sp=') -and ($BaseOsVHD -imatch 'sig=') ) {
					$copyStatus = Copy-VHDToAnotherStorageAccount -SasUrl $BaseOsVHD -destinationStorageAccount $ARMStorageAccount -destinationStorageContainer "vhds" -vhdName $vhdName
				} else {
					$copyStatus = Copy-VHDToAnotherStorageAccount -sourceStorageAccount $givenVHDStorageAccount -sourceStorageContainer $sourceContainer -destinationStorageAccount $ARMStorageAccount -destinationStorageContainer "vhds" -vhdName $vhdName
				}
				if (!$copyStatus) {
					Throw "Failed to copy the VHD to $ARMStorageAccount"
				} else {
					Set-Variable -Name BaseOsVHD -Value $vhdName -Scope Global
					Write-LogInfo "New Base VHD name - $vhdName"
				}
			} else {
				Throw "Automation only supports copying VHDs to existing storage account."
			}
		}
	}

	Write-LogInfo "Loading the test cycle data ..."

	$currentCycleData = Get-CurrentCycleData -xmlConfig $xmlConfig -cycleName $cycleName

	$xmlElementsToAdd = @("currentTest", "stateTimeStamp", "state", "textSummary", "htmlSummary", "jobID", "testCaseResults")
	foreach($element in $xmlElementsToAdd) {
		if (! $testCycle.${element}) {
			$newElement = $xmlConfig.CreateElement($element)
			$newElement.set_InnerText("")
			$testCycle.AppendChild($newElement)
		}
	}
	$testSuiteLogFile = $LogFile
	$testSuiteResultDetails = @{"totalTc"=0;"totalPassTc"=0;"totalFailTc"=0;"totalAbortedTc"=0}

	# Start JUnit XML report logger.
	$junitReport = [JUnitReportGenerator]::New($TestReportXmlPath)
	$junitReport.StartLogTestSuite("LISAv2Test")

	$VmSetup = @()
	$overrideVmSizeList = @()
	foreach ($test in $currentCycleData.test) {
		$currentTestData = Get-CurrentTestData -xmlConfig $xmlConfig -testName $test.Name
		$VmSetup += $currentTestData.setupType
		if ($currentTestData.OverrideVMSize) {
			$overrideVmSizeList += $currentTestData.OverrideVMSize
		} else {
			$overrideVmSizeList += "Null"
		}
	}

	$testCount = $currentCycleData.test.Length
	$testIndex = 0
	$SummaryHeaderAdded = $false
	if (-not $testCount) {
		$testCount = 1
	}

	foreach ($test in $currentCycleData.test) {
		$testIndex ++
		$currentTestData = Get-CurrentTestData -xmlConfig $xmlConfig -testName $test.Name
		$originalTestName = $currentTestData.testName
		if ( $currentTestData.AdditionalCustomization.Networking -eq "SRIOV" ) {
			Set-Variable -Name EnableAcceleratedNetworking -Value $true -Scope Global
		}

		$currentVmSetup = $VmSetup[$testIndex-1]
		$nextVmSetup = $VmSetup[$testIndex]
		$previousVmSetup = $VmSetup[$testIndex-2]

		$currentOverrideVmSize = $overrideVmSizeList[$testIndex-1]
		$nextOverrideVmSize = $overrideVmSizeList[$testIndex]
		$previousOverrideVmSize = $overrideVmSizeList[$testIndex-2]

		$shouldRunSetup = ($previousVmSetup -ne $currentVmSetup) -or ($previousOverrideVmSize -ne $currentOverrideVmSize)
		$shouldRunTeardown = ($currentVmSetup -ne $nextVmSetup) -or ($currentOverrideVmSize -ne $nextOverrideVmSize)

		if ($testIndex -eq 1) {
			$shouldRunSetup = $true
		}
		if ($testIndex -eq $testCount) {
			$shouldRunTeardown = $true
		}

		# Generate Unique Test
		for ( $testIterationCount = 1; $testIterationCount -le $TestIterations; $testIterationCount ++ ) {
			if ( $TestIterations -ne 1 ) {
				$currentTestData.testName = "$($originalTestName)-$testIterationCount"
			}

			if ($deployVMPerEachTest) {
				$shouldRunSetupForIteration = $true
				$shouldRunTeardownForIteration = $true
			} else {
				$shouldRunSetupForIteration = $shouldRunSetup
				$shouldRunTeardownForIteration = $shouldRunTeardown
				if ($testIterationCount -eq 1 -and $TestIterations -gt 1) {
					$shouldRunTeardownForIteration = $false
				}
				if ($testIterationCount -gt 1) {
					$shouldRunSetupForIteration = $false
				}
			}

			if ($currentTestData) {
				$currentTestName = $currentTestData.testName
				if (!( $currentTestData.Platform.Contains($xmlConfig.config.CurrentTestPlatform))) {
					Write-LogInfo "$currentTestName does not support $($xmlConfig.config.CurrentTestPlatform) platform."
					continue;
				}

				if(($testPriority -imatch $currentTestData.Priority ) -or (!$testPriority))	{
					$CurrentTestLogDir = "$LogDir\$currentTestName"
					New-Item -Type Directory -Path $CurrentTestLogDir -ErrorAction SilentlyContinue | Out-Null
					Set-Variable -Name "CurrentTestLogDir" -Value $CurrentTestLogDir -Scope Global
					Set-Variable -Name "LogDir" -Value $CurrentTestLogDir -Scope Global
					$junitReport.StartLogTestCase("LISAv2Test","$currentTestName","$($testCycle.cycleName)")

					Set-Variable -Name currentTestData -Value $currentTestData -Scope Global
					$testResult = ""
					$testSummary = ""
					Write-LogInfo "~~~~~~~~~~~~~~~TEST STARTED : $currentTestName~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"
					try	{
						$CurrentTestResult = Run-Test -CurrentTestData $currentTestData -XmlConfig $xmlConfig `
							-Distro $Distro -LogDir $CurrentTestLogDir -VMUser $user -VMPassword $password `
							-ExecuteSetup $shouldRunSetupForIteration -ExecuteTeardown $shouldRunTeardownForIteration
						$testResult = $CurrentTestResult.TestResult
						$testSummary = $CurrentTestResult.TestSummary
					}
					catch {
						$testResult = "ABORTED"
						$ErrorMessage =  $_.Exception.Message
						$line = $_.InvocationInfo.ScriptLineNumber
						$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
						Write-LogErr "EXCEPTION : $ErrorMessage"
						Write-LogErr "Source : Line $line in script $script_name."
					}
					finally	{
						Write-LogInfo "~~~~~~~~~~~~~~~TEST END : $currentTestName~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"
					}
					$executionCount += 1
					$testRunDuration = $junitReport.GetTestCaseElapsedTime("LISAv2Test","$currentTestName","mm")
					Update-TestSummaryForCase -TestName $currentTestName -ExecutionCount $executionCount -TestResult $testResult -TestCycle $testCycle -TestCase $testcase `
						-ResultDetails $testSuiteResultDetails -Duration $testRunDuration.ToString() -TestSummary $testSummary -AddHeader (-not $SummaryHeaderAdded)
					$SummaryHeaderAdded = $true

					$TestCaseLogFile = "$CurrentTestLogDir\$LogFileName"
					$caseLog = Get-Content -Raw $TestCaseLogFile
					$junitReport.CompleteLogTestCase("LISAv2Test","$currentTestName",$testResult,$caseLog)

					#Back to Test Suite Main Logging
					$global:LogFile = $testSuiteLogFile
					$currentJobs = Get-Job
					foreach ( $job in $currentJobs ) {
						$jobStatus = Get-Job -Id $job.ID
						if ( $jobStatus.State -ne "Running" ) {
							Remove-Job -Id $job.ID -Force
							if ( $? ) {
								Write-LogInfo "Removed $($job.State) background job ID $($job.Id)."
							}
						} else {
							Write-LogInfo "$($job.Name) is running."
						}
					}
				} else {
					Write-LogInfo "Skipping $($currentTestData.Priority) test : $currentTestName"
				}
			} else {
				Write-LogInfo "No Test Data found for $currentTestName.."
			}
		}
	}

	Write-LogInfo "Checking background cleanup jobs.."
	$cleanupJobList = Get-Job | Where-Object { $_.Name -imatch "Delete-ResourceGroup"}
	$isAllCleaned = $false
	while(!$isAllCleaned) {
		$runningJobsCount = 0
		$isAllCleaned = $true
		$cleanupJobList = Get-Job | Where-Object { $_.Name -imatch "Delete-ResourceGroup"}
		foreach ( $cleanupJob in $cleanupJobList ) {

			$jobStatus = Get-Job -Id $cleanupJob.ID
			if ( $jobStatus.State -ne "Running" ) {

				$tempRG = $($cleanupJob.Name).Replace("Delete-ResourceGroup-","")
				Write-LogInfo "$tempRG : Delete : $($jobStatus.State)"
				Remove-Job -Id $cleanupJob.ID -Force
			} else  {
				Write-LogInfo "$($cleanupJob.Name) is running."
				$isAllCleaned = $false
				$runningJobsCount += 1
			}
		}
		if ($runningJobsCount -gt 0) {
			Write-LogInfo "$runningJobsCount background cleanup jobs still running. Waiting 30 seconds..."
			Start-Sleep -Seconds 30
		}
	}
	Write-LogInfo "All background cleanup jobs finished."
	$azureContextFiles = Get-Item "$env:TEMP\*.azurecontext"
	$azureContextFiles | Remove-Item -Force | Out-Null
	Write-LogInfo "Removed $($azureContextFiles.Count) context files."
	Write-LogInfo "Cycle Finished.. $($CycleName.ToUpper())"

	$junitReport.CompleteLogTestSuite("LISAv2Test")
	$junitReport.SaveLogReport()

	$testSuiteResultDetails
}

Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | `
	ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking}

$xmlConfig = [xml](Get-Content $xmlConfigFile)
$user = $xmlConfig.config.$TestPlatform.Deployment.Data.UserName
$password = $xmlConfig.config.$TestPlatform.Deployment.Data.Password
$sshKey = $xmlConfig.config.$TestPlatform.Deployment.Data.sshKey
$sshPublickey = $xmlConfig.config.$TestPlatform.Deployment.Data.sshPublicKey

Set-Variable -Name user -Value $user -Scope Global
Set-Variable -Name password -Value $password -Scope Global
Set-Variable -Name sshKey -Value $sshKey -Scope Global
Set-Variable -Name sshPublicKey -Value $sshPublicKey -Scope Global
Set-Variable -Name sshPublicKeyThumbprint -Value $sshPublicKeyThumbprint -Scope Global
Set-Variable -Name PublicConfiguration -Value @() -Scope Global
Set-Variable -Name PrivateConfiguration -Value @() -Scope Global
Set-Variable -Name CurrentTestData -Value $CurrentTestData -Scope Global
Set-Variable -Name preserveKeyword -Value "preserving" -Scope Global
Set-Variable -Name TiPSessionId -Value $TiPSessionId -Scope Global
Set-Variable -Name TiPCluster -Value $TiPCluster -Scope Global

Set-Variable -Name resultPass -Value "PASS" -Scope Global
Set-Variable -Name resultFail -Value "FAIL" -Scope Global
Set-Variable -Name resultAborted -Value "ABORTED" -Scope Global

Set-Variable -Name AllVMData -Value @() -Scope Global
Set-Variable -Name isDeployed -Value @() -Scope Global

if ( $EnableAcceleratedNetworking ) {
	Set-Variable -Name EnableAcceleratedNetworking -Value $true -Scope Global
}

if ( $ForceDeleteResources ) {
	Set-Variable -Name ForceDeleteResources -Value $true -Scope Global
}

if ( $OverrideVMSize ) {
	Set-Variable -Name OverrideVMSize -Value $OverrideVMSize -Scope Global
}

if ( $CustomKernel ) {
	Set-Variable -Name CustomKernel -Value $CustomKernel -Scope Global
}

if ( $CustomLIS ) {
	Set-Variable -Name CustomLIS -Value $CustomLIS -Scope Global
}

if ( $customLISBranch ) {
	Set-Variable -Name customLISBranch -Value $customLISBranch -Scope Global
}

if ($ExistingResourceGroup) {
	Set-Variable -Name ExistingRG -Value $ExistingResourceGroup -Scope Global
}

if ($CleanupExistingRG) {
	Set-Variable -Name CleanupExistingRG -Value $true -Scope Global
} else {
	Set-Variable -Name CleanupExistingRG -Value $false -Scope Global
}

if ($UseManagedDisks) {
	Set-Variable -Name UseManagedDisks -Value $true -Scope Global
} else {
	Set-Variable -Name UseManagedDisks -Value $false -Scope Global
}

try {
	$TestResultsDir = "TestResults"
	if (! (Test-Path $TestResultsDir)) {
		mkdir $TestResultsDir | Out-Null
	}

	if (! (Test-Path ".\Report")) {
		mkdir ".\Report" | Out-Null
	}

	$testStartTime = [DateTime]::Now.ToUniversalTime()
	Set-Variable -Name testStartTime -Value $testStartTime -Scope Global
	Set-Content -Value "" -Path .\Report\testSummary.html -Force -ErrorAction SilentlyContinue | Out-Null
	Set-Content -Value "" -Path .\Report\AdditionalInfo.html -Force -ErrorAction SilentlyContinue | Out-Null
	Set-Variable -Name LogFile -Value $LogFile -Scope Global
	Set-Variable -Name Distro -Value $RGIdentifier -Scope Global
	Set-Variable -Name xmlConfig -Value $xmlConfig -Scope Global
	Write-LogInfo "'$LogDir' saved to .\Report\lastLogDirectory.txt"
	Set-Content -Path .\Report\lastLogDirectory.txt -Value $LogDir -Force
	Set-Variable -Name vnetIsAllConfigured -Value $false -Scope Global

	if($DoNotDeleteVMs) {
		Set-Variable -Name DoNotDeleteVMs -Value $true -Scope Global
	} else {
		Set-Variable -Name DoNotDeleteVMs -Value $false -Scope Global
	}

	Set-Variable -Name IsWindows -Value $false -Scope Global
	if($xmlconfig.config.testsDefinition.test.Tags `
            -and $xmlconfig.config.testsDefinition.test.Tags.ToString().Contains("nested-hyperv")) {
		Set-Variable -Name IsWindows -Value $true -Scope Global
	}

	$AzureSetup = $xmlConfig.config.$TestPlatform.General
	Write-LogInfo  ("Info : Using config file $xmlConfigFile")
	if ( ( $xmlConfig.config.$TestPlatform.General.ARMStorageAccount -imatch "ExistingStorage" ) -or ($xmlConfig.config.$TestPlatform.General.StorageAccount -imatch "ExistingStorage" )) {
		$regionName = $xmlConfig.config.$TestPlatform.General.Location.Replace(" ","").Replace('"',"").ToLower()
		$regionStorageMapping = [xml](Get-Content .\XML\RegionAndStorageAccounts.xml)

		if ( $xmlConfig.config.$TestPlatform.General.ARMStorageAccount -imatch "standard") {
			$xmlConfig.config.$TestPlatform.General.ARMStorageAccount = $regionStorageMapping.AllRegions.$regionName.StandardStorage
			Write-LogInfo "Info : Selecting existing standard storage account in $regionName - $($regionStorageMapping.AllRegions.$regionName.StandardStorage)"
		}

		if ( $xmlConfig.config.$TestPlatform.General.ARMStorageAccount -imatch "premium") {
			$xmlConfig.config.$TestPlatform.General.ARMStorageAccount = $regionStorageMapping.AllRegions.$regionName.PremiumStorage
			Write-LogInfo "Info : Selecting existing premium storage account in $regionName - $($regionStorageMapping.AllRegions.$regionName.PremiumStorage)"
		}
	}

	Write-LogInfo "------------------------------------------------------------------"
	if ( $TestPlatform -eq "Azure") {
		$SelectedSubscription = Select-AzureRmSubscription -SubscriptionId $AzureSetup.SubscriptionID
		$subIDSplitted = ($SelectedSubscription.Subscription.SubscriptionId).Split("-")
		$userIDSplitted = ($SelectedSubscription.Account.Id).Split("-")
		Write-LogInfo "SubscriptionName       : $($SelectedSubscription.Subscription.Name)"
		Write-LogInfo "SubscriptionId         : $($subIDSplitted[0])-xxxx-xxxx-xxxx-$($subIDSplitted[4])"
		Write-LogInfo "User                   : $($userIDSplitted[0])-xxxx-xxxx-xxxx-$($userIDSplitted[4])"
		Write-LogInfo "ServiceEndpoint        : $($SelectedSubscription.Environment.ActiveDirectoryServiceEndpointResourceId)"
		Write-LogInfo "CurrentStorageAccount  : $($AzureSetup.ARMStorageAccount)"
	} elseif ( $TestPlatform -eq "HyperV") {
		for( $index=0 ; $index -lt $xmlConfig.config.Hyperv.Hosts.ChildNodes.Count ; $index++ ) {
			Write-LogInfo "HyperV Host            : $($xmlConfig.config.Hyperv.Hosts.ChildNodes[$($index)].ServerName)"
			Write-LogInfo "Source VHD Path        : $($xmlConfig.config.Hyperv.Hosts.ChildNodes[$($index)].SourceOsVHDPath)"
			Write-LogInfo "Destination VHD Path   : $($xmlConfig.config.Hyperv.Hosts.ChildNodes[$($index)].DestinationOsVHDPath)"
		}
	}
	Write-LogInfo "------------------------------------------------------------------"

	if($DoNotDeleteVMs) {
		Write-LogInfo "PLEASE NOTE: DoNotDeleteVMs is set. VMs will not be deleted after test is finished even if, test gets PASS."
	}

	$testCycle = Get-CurrentCycleData -xmlConfig $xmlConfig -cycleName $cycleName
	$testSuiteResultDetails = Run-TestsOnCycle -xmlConfig $xmlConfig -Distro $Distro -cycleName $cycleName -TestIterations $TestIterations `
		-DeployVMPerEachTest $DeployVMPerEachTest -TestReportXmlPath $TestReportXmlPath
	$testSuiteResultDetails = $testSuiteResultDetails | Select-Object -Last 1
	$logDirFilename = [System.IO.Path]::GetFilenameWithoutExtension($xmlConfigFile)

	$testDuration= [Datetime]::Now.ToUniversalTime() - $testStartTime
	$htmlTextSummary = Get-HtmlTestSummary -testCycle $testCycle -startTime $testStartTime -testDuration $testDuration -xmlFileName $logDirFilename -testSuiteResultDetails $testSuiteResultDetails
	Set-Content -Value $htmlTextSummary -Path .\Report\testSummary.html -Force | Out-Null

	$plainTextSummary = Get-PlainTextSummary -testCycle $testCycle -startTime $testStartTime -testDuration $testDuration -xmlFileName $logDirFilename -testSuiteResultDetails $testSuiteResultDetails
	Write-LogInfo  "$PlainTextSummary"
} catch {
	Raise-Exception($_)
} Finally {
	exit
}