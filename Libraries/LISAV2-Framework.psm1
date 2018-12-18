##############################################################################################
# LISAV2-Framework.psm1
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
<#
.SYNOPSIS
    Pipeline framework modules for Azure environment.

.PARAMETER
    <Parameters>

.INPUTS


.NOTES
    Creation Date:
    Purpose/Change:

.EXAMPLE


#>
###############################################################################################

function Validate-AzureParameters {
    $parameterErrors = @()
    if ( !$ARMImageName -and !$OsVHD ) {
        $parameterErrors += "-ARMImageName '<Publisher> <Offer> <Sku> <Version>', or -OsVHD <'VHD_Name.vhd'> is required."
    }

    if (!$OsVHD) {
        if (($ARMImageName.Trim().Split(" ").Count -ne 4) -and ($ARMImageName -ne "")) {
            $parameterErrors += ("Invalid value for the provided ARMImageName parameter: <'${ARMImageName}'>." + `
                                 "The ARM image should be in the format: '<Publisher> <Offer> <Sku> <Version>'.")
        }
    }

    if (!$ARMImageName) {
        if ($OsVHD -and [System.IO.Path]::GetExtension($OsVHD) -ne ".vhd" -and !$OsVHD.Contains("vhd")) {
            $parameterErrors += "-OsVHD $OsVHD does not have .vhd extension required by Platform Azure."
        }
    }

    if (!$TestLocation) {
        $parameterErrors += "-TestLocation <AzureRegion> is required."
    }

    if ([string]$VMGeneration -eq "2") {
        $parameterErrors += "-VMGeneration 2 is not supported on Azure."
    }
    return $parameterErrors
}

function Validate-HyperVParameters {
    $parameterErrors = @()
    if (!$OsVHD ) {
        $parameterErrors += "-OsVHD <'VHD_Name.vhd'> is required."
    }
    return $parameterErrors
}

function Validate-Parameters {
    $parameterErrors = @()
    $supportedPlatforms = @("Azure", "HyperV")

    if ($supportedPlatforms.contains($TestPlatform)) {

        # Validate general parameters
        if ( !$RGIdentifier ) {
            $parameterErrors += "-RGIdentifier <ResourceGroupIdentifier> is required."
        }
        if (!$VMGeneration) {
			# Set VM Generation default value to 1, if not specified.
			Write-LogInfo "-VMGeneration not specified. Using default VMGeneration = 1"
			Set-Variable -Name VMGeneration -Value 1 -Scope Global
        } else {
            $supportedVMGenerations = @("1","2")
            if ($supportedVMGenerations.contains([string]$VMGeneration)) {
                if ([string]$VMGeneration -eq "2" -and $OsVHD `
                         -and [System.IO.Path]::GetExtension($OsVHD) -ne ".vhdx") {
                    $parameterErrors += "-VMGeneration 2 requires .vhdx files."
                }
            } else {
                $parameterErrors += "-VMGeneration $VMGeneration is not yet supported."
            }
        }

        # Validate platform dependent parameters
        $parameterErrors += & "Validate-${TestPlatform}Parameters"
    } else {
        if ($TestPlatform) {
            $parameterErrors += "$TestPlatform is not yet supported."
        } else {
            $parameterErrors += "'-TestPlatform' is not provided."
        }
    }
    if ($parameterErrors.Count -gt 0) {
        $parameterErrors | ForEach-Object { Write-LogErr $_ }
        throw "Failed to validate the test parameters provided. Please fix above issues and retry."
    } else {
        Write-LogInfo "Test parameters have been validated successfully. Continue running the test."
    }
}

Function Inject-CustomTestParameters($CustomParameters, $ReplaceableTestParameters, $TestConfigurationXmlFile)
{
	if ($CustomParameters)
	{
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

	$XmlConfigContents = (Get-Content -Path $TestConfigurationXmlFile)
	foreach ($ReplaceableParameter in $ReplaceableTestParameters.ReplaceableTestParameters.Parameter)
	{
		if ($XmlConfigContents -match $ReplaceableParameter.ReplaceThis)
		{
			$XmlConfigContents = $XmlConfigContents.Replace($ReplaceableParameter.ReplaceThis,$ReplaceableParameter.ReplaceWith)
			Write-LogInfo "$($ReplaceableParameter.ReplaceThis)=$($ReplaceableParameter.ReplaceWith) injected into $TestConfigurationXmlFile"
		}
	}
	Set-Content -Value $XmlConfigContents -Path $TestConfigurationXmlFile -Force
}

Function Update-GlobalConfigurationXML($XmlSecretsFilePath)
{
	# The file $XmlSecretsFilePath has been validated before calling this function
	Get-ChildItem (Join-Path "." "Libraries") -Recurse | `
		Where-Object { $_.FullName.EndsWith(".psm1") } | `
		ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

	$XmlSecrets = [xml](Get-Content $XmlSecretsFilePath)
	$GlobalConfigurationXMLFilePath = Resolve-Path ".\XML\GlobalConfigurations.xml"
	$GlobalXML = [xml](Get-Content $GlobalConfigurationXMLFilePath)
	$RegionAndStorageAccountsXMLFilePath = Resolve-Path ".\XML\RegionAndStorageAccounts.xml"
	$RegionStorageMapping = [xml](Get-Content $RegionAndStorageAccountsXMLFilePath)

	$GlobalXML.Global.Azure.Subscription.SubscriptionID = $XmlSecrets.secrets.SubscriptionID
	$GlobalXML.Global.Azure.TestCredentials.LinuxUsername = $XmlSecrets.secrets.linuxTestUsername
	$GlobalXML.Global.Azure.TestCredentials.LinuxPassword = $XmlSecrets.secrets.linuxTestPassword
	$GlobalXML.Global.Azure.ResultsDatabase.server = $XmlSecrets.secrets.DatabaseServer
	$GlobalXML.Global.Azure.ResultsDatabase.user = $XmlSecrets.secrets.DatabaseUser
	$GlobalXML.Global.Azure.ResultsDatabase.password = $XmlSecrets.secrets.DatabasePassword
	$GlobalXML.Global.Azure.ResultsDatabase.dbname = $XmlSecrets.secrets.DatabaseName
	$GlobalXML.Global.HyperV.TestCredentials.LinuxUsername = $XmlSecrets.secrets.linuxTestUsername
	$GlobalXML.Global.HyperV.TestCredentials.LinuxPassword = $XmlSecrets.secrets.linuxTestPassword
	$GlobalXML.Global.HyperV.ResultsDatabase.server = $XmlSecrets.secrets.DatabaseServer
	$GlobalXML.Global.HyperV.ResultsDatabase.user = $XmlSecrets.secrets.DatabaseUser
	$GlobalXML.Global.HyperV.ResultsDatabase.password = $XmlSecrets.secrets.DatabasePassword
	$GlobalXML.Global.HyperV.ResultsDatabase.dbname = $XmlSecrets.secrets.DatabaseName

	if ($TestPlatform -eq "Azure")
	{
		if ( $StorageAccount -imatch "ExistingStorage_Standard" )
		{
			$GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount = $RegionStorageMapping.AllRegions.$TestLocation.StandardStorage
		}
		elseif ( $StorageAccount -imatch "ExistingStorage_Premium" )
		{
			$GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount = $RegionStorageMapping.AllRegions.$TestLocation.PremiumStorage
		}
		elseif ( $StorageAccount -imatch "NewStorage_Standard" )
		{
			$GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount = "NewStorage_Standard_LRS"
		}
		elseif ( $StorageAccount -imatch "NewStorage_Premium" )
		{
			$GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount = "NewStorage_Premium_LRS"
		}
		elseif ($StorageAccount -eq "")
		{
			$GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount = $RegionStorageMapping.AllRegions.$TestLocation.StandardStorage
			Write-LogInfo "Auto selecting storage account : $($GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount) as per your test region."
		}
		elseif ($StorageAccount)
		{
			$GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount = $StorageAccount.Trim()
			Write-LogInfo "Selecting custom storage account : $($GlobalXML.Global.$TestPlatform.Subscription.ARMStorageAccount) as per your test region."
		}
	}
	if ($TestPlatform -eq "HyperV")
	{
		if ( $SourceOsVHDPath )
		{
			for( $index=0 ; $index -lt $GlobalXML.Global.$TestPlatform.Hosts.ChildNodes.Count ; $index++ ) {
				$GlobalXML.Global.$TestPlatform.Hosts.ChildNodes[$index].SourceOsVHDPath = $SourceOsVHDPath
			}
		}
		if ( $DestinationOsVHDPath )
		{
			for( $index=0 ; $index -lt $GlobalXML.Global.$TestPlatform.Hosts.ChildNodes.Count ; $index++ ) {
				$GlobalXML.Global.$TestPlatform.Hosts.ChildNodes[$index].DestinationOsVHDPath = $DestinationOsVHDPath
			}
		}
		if ($TestLocation)
		{
			$Locations = $TestLocation.split(',')
			$index = 0
			foreach($Location in $Locations)
			{
				$GlobalXML.Global.$TestPlatform.Hosts.ChildNodes[$index].ServerName = $Location
				Get-VM -ComputerName $GlobalXML.Global.$TestPlatform.Hosts.ChildNodes[$index].ServerName | Out-Null
				if ($?)
				{
					Write-LogInfo "Set '$($Location)' to As GlobalConfiguration.Global.HyperV.Hosts.ChildNodes[$($index)].ServerName"
				}
				else
				{
					Write-LogErr "Did you used -TestLocation XXXXXXX. In HyperV mode, -TestLocation can be used to Override HyperV server mentioned in GlobalConfiguration XML file."
					Write-LogErr "In HyperV mode, -TestLocation can be used to Override HyperV server mentioned in GlobalConfiguration XML file."
					Throw "Unable to access HyperV server - '$($Location)'"
				}
				$index++
			}
		}
		else
		{
			$TestLocation = $GlobalXML.Global.$TestPlatform.Hosts.ChildNodes[0].ServerName
			Write-LogInfo "Read Test Location from GlobalConfiguration.Global.HyperV.Hosts.ChildNodes[0].ServerName"
			Get-VM -ComputerName $TestLocation | Out-Null
		}
	}
	#If user provides Result database / result table, then add it to the GlobalConfiguration.
	if( $ResultDBTable -or $ResultDBTestTag)
	{
		if( $ResultDBTable )
		{
			$GlobalXML.Global.$TestPlatform.ResultsDatabase.dbtable = ($ResultDBTable).Trim()
			Write-LogInfo "ResultDBTable : $ResultDBTable added to .\XML\GlobalConfigurations.xml"
		}
		if( $ResultDBTestTag )
		{
			$GlobalXML.Global.$TestPlatform.ResultsDatabase.testTag = ($ResultDBTestTag).Trim()
			Write-LogInfo "ResultDBTestTag: $ResultDBTestTag added to .\XML\GlobalConfigurations.xml"
		}
	}
	#$GlobalConfiguration.Save("$WorkingDirectory\XML\GlobalConfigurations.xml")
	$GlobalXML.Save($GlobalConfigurationXMLFilePath )
	Write-LogInfo "Updated GlobalConfigurations.xml file."
}

Function Update-XMLStringsFromSecretsFile($XmlSecretsFilePath)
{
	# The file $XmlSecretsFilePath has been validated before calling this function
	$TestXMLs = Get-ChildItem -Path ".\XML\TestCases\*.xml"
	$XmlSecrets = [xml](Get-Content $XmlSecretsFilePath)
	foreach ($file in $TestXMLs)
	{
		$CurrentXMLText = Get-Content -Path $file.FullName
		foreach ($Replace in $XmlSecrets.secrets.ReplaceTestXMLStrings.Replace)
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

Function Match-TestPriority($currentTest, $TestPriority)
{
    if( -not $TestPriority ) {
        return $True
    }

    if( $TestPriority -eq "*") {
        return $True
    }

    $priorityInXml = $currentTest.Priority
    if (-not $priorityInXml) {
        Write-LogWarn "Priority of $($currentTest.TestName) is not defined, set it to 1 (default)."
        $priorityInXml = 1
    }
    foreach( $priority in $TestPriority.Split(",") ) {
        if ($priorityInXml -eq $priority) {
            return $True
        }
    }
    return $False
}

Function Match-TestTag($currentTest, $TestTag)
{
    if( -not $TestTag ) {
        return $True
    }

    if( $TestTag -eq "*") {
        return $True
    }

    $tagsInXml = $currentTest.Tags
    if (-not $tagsInXml) {
        Write-LogWarn "Test Tags of $($currentTest.TestName) is not defined; include this test case by default."
        return $True
    }
    foreach( $tagInTestRun in $TestTag.Split(",") ) {
        foreach( $tagInTestXml in $tagsInXml.Split(",") ) {
            if ($tagInTestRun -eq $tagInTestXml) {
                return $True
            }
        }
    }
    return $False
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
Function Collect-TestCases($TestXMLs)
{
    $AllLisaTests = @()

    # Check and cleanup the parameters
    if ( $TestCategory -eq "All")   { $TestCategory = "*" }
    if ( $TestArea -eq "All")       { $TestArea = "*" }
    if ( $TestNames -eq "All")      { $TestNames = "*" }
    if ( $TestTag -eq "All")        { $TestTag = "*" }
    if ( $TestPriority -eq "All")   { $TestPriority = "*" }

    if (!$TestCategory) { $TestCategory = "*" }
    if (!$TestArea)     { $TestArea = "*" }
    if (!$TestNames)    { $TestNames = "*" }
    if (!$TestTag)      { $TestTag = "*" }
    if (!$TestPriority) { $TestPriority = "*" }

    # Filter test cases based on the criteria
    foreach ($file in $TestXMLs.FullName) {
        $currentTests = ([xml]( Get-Content -Path $file)).TestCases
        foreach ($test in $currentTests.test){
            if (!($test.Platform.Split(",").Contains($TestPlatform))) {
                continue
            }

            if (($test.Category -ne $TestCategory) -and ($TestCategory -ne "*")) {
                continue
            }

            if (!($TestArea.Split(",").Contains($test.Area)) -and ($TestArea -ne "*")) {
                continue
            }

            if (!($TestNames.Split(",").Contains($test.testName)) -and ($TestNames -ne "*")) {
                continue
            }

            $testTagMatched = Match-TestTag -currentTest $test -TestTag $TestTag
            if ($testTagMatched -eq $false) {
                continue
            }

            $testPriorityMatched = Match-TestPriority -currentTest $test -TestPriority $TestPriority
            if ($testPriorityMatched -eq $false) {
                continue
            }

            Write-LogInfo "Collected: $($test.TestName)"
            $AllLisaTests += $test
        }
    }
    return $AllLisaTests
}

function Send-Email([XML] $xmlConfig, $body)
{
    <#
	.Synopsis
    	Send an e-mail message with test summary information.

    .Description
        Collect the test summary information from each testcycle.  Send an
        eMail message with this summary information to emailList defined
        in the xml config file.

	.Parameter xmlConfig
    	The parsed XML from the test xml file
        Type : [System.Xml]

    .ReturnValue
        none

    .Example
        Send-Email $myConfig
	#>

    $to = $xmlConfig.config.global.emailList.split(",")
    $from = $xmlConfig.config.global.emailSender
    $subject = $xmlConfig.config.global.emailSubject + " " + $testStartTime
    $smtpServer = $xmlConfig.config.global.smtpServer
    # Highlight the failed tests
    $body = $body.Replace("Aborted", '<em style="background:Yellow; color:Red">Aborted</em>')
    $body = $body.Replace("FAIL", '<em style="background:Yellow; color:Red">Failed</em>')

	Send-mailMessage -to $to -from $from -subject $subject -body $body -smtpserver $smtpServer -BodyAsHtml
}

Function Get-CurrentCycleData($xmlConfig, $cycleName)
{
    foreach ($Cycle in $xmlConfig.config.testCycles.Cycle )
    {
        if($cycle.cycleName -eq $cycleName)
        {
        return $cycle
        break
        }
    }

}

Function Get-CurrentCycleData($xmlConfig, $cycleName)
{
	foreach ($Cycle in $xmlConfig.config.testCycles.Cycle )
	{
		if($cycle.cycleName -eq $cycleName)
		{
		return $cycle
		break
		}
	}

}

Function Get-CurrentTestData($xmlConfig, $testName)
{
	foreach ($test in $xmlConfig.config.testsDefinition.test)
	{
		if ($test.testName -eq $testName)
		{
		Write-LogInfo "Loading the test data for $($test.testName)"
		Set-Variable -Name CurrentTestData -Value $test -Scope Global -Force
		return $test
		break
		}
	}
}

Function Refine-TestResult2 ($testResult)
{
	$i=0
	$tempResult = @()
	foreach ($cmp in $testResult)
	{
		if(($cmp -eq "PASS") -or ($cmp -eq "FAIL") -or ($cmp -eq "ABORTED") -or ($cmp -eq "Aborted"))
		{
			$tempResult += $testResult[$i]
			$tempResult += $testResult[$i+1]
			$testResult = $tempResult
			break
		}
		$i++;
	}
	return $testResult
}

Function Refine-TestResult1 ($tempResult)
{
	foreach ($new in $tempResult)
	{
		$lastObject = $new
	}
	$tempResultSplitted = $lastObject.Split(" ")
	if($tempResultSplitted.Length > 1 )
	{
		Write-Host "Test Result =  $lastObject" -ForegroundColor Gray
	}
	$lastWord = ($tempResultSplitted.Length - 1)

	return $tempResultSplitted[$lastWord]
}

Function Validate-VHD($vhdPath)
{
    try
    {
        $tempVHDName = Split-Path $vhdPath -leaf
        Write-LogInfo "Inspecting '$tempVHDName'. Please wait..."
        $VHDInfo = Get-VHD -Path $vhdPath -ErrorAction Stop
        Write-LogInfo "  VhdFormat            :$($VHDInfo.VhdFormat)"
        Write-LogInfo "  VhdType              :$($VHDInfo.VhdType)"
        Write-LogInfo "  FileSize             :$($VHDInfo.FileSize)"
        Write-LogInfo "  Size                 :$($VHDInfo.Size)"
        Write-LogInfo "  LogicalSectorSize    :$($VHDInfo.LogicalSectorSize)"
        Write-LogInfo "  PhysicalSectorSize   :$($VHDInfo.PhysicalSectorSize)"
        Write-LogInfo "  BlockSize            :$($VHDInfo.BlockSize)"
        Write-LogInfo "Validation successful."
    }
    catch
    {
        Write-LogInfo "Failed: Get-VHD -Path $vhdPath"
        Throw "INVALID_VHD_EXCEPTION"
    }
}

Function Validate-MD5($filePath, $expectedMD5hash)
{
    Write-LogInfo "Expected MD5 hash for $filePath : $($expectedMD5hash.ToUpper())"
    $hash = Get-FileHash -Path $filePath -Algorithm MD5
    Write-LogInfo "Calculated MD5 hash for $filePath : $($hash.Hash.ToUpper())"
    if ($hash.Hash.ToUpper() -eq  $expectedMD5hash.ToUpper())
    {
        Write-LogInfo "MD5 checksum verified successfully."
    }
    else
    {
        Throw "MD5 checksum verification failed."
    }
}

Function Test-FileLock
{
	param
	(
	  [parameter(Mandatory=$true)][string]$Path
	)
	$File = New-Object System.IO.FileInfo $Path
	if ((Test-Path -Path $Path) -eq $false)
	{
		return $false
	}
	try
	{
		$oStream = $File.Open([System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
		if ($oStream)
		{
			$oStream.Close()
		}
		return $false
	}
	catch
	{
		# file is locked by a process.
		return $true
	}
}

Function Create-ArrayOfTabs()
{
	$tab = @()
    for ( $i = 0; $i -lt 30; $i++)
    {
        $currentTab = ""
        for ( $j = 0; $j -lt $i; $j++)
        {
            $currentTab +=  "`t"
        }
        $tab += $currentTab
	}
	return $tab
}

Function Get-SQLQueryOfTelemetryData ($TestPlatform,$TestLocation,$TestCategory,$TestArea,$TestName,$CurrentTestResult, `
									$ExecutionTag,$GuestDistro,$KernelVersion,$LISVersion,$HostVersion,$VMSize, `
									$Networking,$ARMImage,$OsVHD,$LogFile,$BuildURL)
{
	if ($EnableTelemetry) {
		try
		{
			$TestResult = $CurrentTestResult.TestResult
			$TestSummary = $CurrentTestResult.TestSummary
			$UTCTime = (Get-Date).ToUniversalTime()
			$DateTimeUTC = "$($UTCTime.Year)-$($UTCTime.Month)-$($UTCTime.Day) $($UTCTime.Hour):$($UTCTime.Minute):$($UTCTime.Second)"
			$GlobalConfiguration = [xml](Get-Content .\XML\GlobalConfigurations.xml)
			$testLogStorageAccount = $XmlSecrets.secrets.testLogsStorageAccount
			$testLogStorageAccountKey = $XmlSecrets.secrets.testLogsStorageAccountKey
			$testLogFolder = "$($UTCTime.Year)-$($UTCTime.Month)-$($UTCTime.Day)"
			$ticks= (Get-Date).Ticks
			$uploadFileName = Join-Path $env:TEMP "$TestName-$ticks.zip"
			$null = New-ZipFile -zipFileName $uploadFileName -sourceDir $LogDir
			$UploadedURL = .\Utilities\UploadFilesToStorageAccount.ps1 -filePaths $uploadFileName `
			-destinationStorageAccount $testLogStorageAccount -destinationContainer "lisav2logs" `
			-destinationFolder "$testLogFolder" -destinationStorageKey $testLogStorageAccountKey
			if ($BuildURL) {
				$BuildURL = "$BuildURL`consoleFull"
			} else {
				$BuildURL = ""
			}
			if ($TestPlatform -eq "HyperV") {
				$TestLocation = ($GlobalConfiguration.Global.$TestPlatform.Hosts.ChildNodes[0].ServerName).ToLower()
			} elseif ($TestPlatform -eq "Azure") {
				$TestLocation = $TestLocation.ToLower()
			}
			$dataTableName = "LISAv2Results"
			$SQLQuery = "INSERT INTO $dataTableName (DateTimeUTC,TestPlatform,TestLocation,TestCategory,TestArea,TestName,TestResult,SubTestName,SubTestResult,ExecutionTag,GuestDistro,KernelVersion,LISVersion,HostVersion,VMSize,Networking,ARMImage,OsVHD,LogFile,BuildURL) VALUES "
			$SQLQuery += "('$DateTimeUTC','$TestPlatform','$TestLocation','$TestCategory','$TestArea','$TestName','$testResult','','','$ExecutionTag','$GuestDistro','$KernelVersion','$LISVersion','$HostVersion','$VMSize','$Networking','$ARMImageName','$OsVHD','$UploadedURL', '$BuildURL'),"
			if ($TestSummary) {
				foreach ($tempResult in $TestSummary.Split('>')) {
					if ($tempResult) {
						$tempResult = $tempResult.Trim().Replace("<br /","").Trim()
						$subTestResult = $tempResult.Split(":")[$tempResult.Split(":").Count -1 ].Trim()
						$subTestName = $tempResult.Replace("$subTestResult","").Trim().TrimEnd(":").Trim()
						$SQLQuery += "('$DateTimeUTC','$TestPlatform','$TestLocation','$TestCategory','$TestArea','$TestName','$testResult','$subTestName','$subTestResult','$ExecutionTag','$GuestDistro','$KernelVersion','$LISVersion','$HostVersion','$VMSize','$Networking','$ARMImageName','$OsVHD','$UploadedURL', '$BuildURL'),"
					}
				}
			}
			$SQLQuery = $SQLQuery.TrimEnd(',')
			Write-LogInfo "Get the SQL query of test results:  done"
			return $SQLQuery
		}
		catch
		{
			Write-LogErr "Get the SQL query of test results:  ERROR"
			$line = $_.InvocationInfo.ScriptLineNumber
			$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
			$ErrorMessage =  $_.Exception.Message
			Write-LogInfo "EXCEPTION : $ErrorMessage"
			Write-LogInfo "Source : Line $line in script $script_name."
		}
	} else {
		return $null
	}
}

Function Upload-TestResultToDatabase ($SQLQuery)
{
	if ($XmlSecrets) {
		$dataSource = $XmlSecrets.secrets.DatabaseServer
		$dbuser = $XmlSecrets.secrets.DatabaseUser
		$dbpassword = $XmlSecrets.secrets.DatabasePassword
		$database = $XmlSecrets.secrets.DatabaseName

		if ($dataSource -and $dbuser -and $dbpassword -and $database) {
			try
			{
				Write-LogInfo "SQLQuery:  $SQLQuery"
				$connectionString = "Server=$dataSource;uid=$dbuser; pwd=$dbpassword;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
				$connection = New-Object System.Data.SqlClient.SqlConnection
				$connection.ConnectionString = $connectionString
				$connection.Open()
				$command = $connection.CreateCommand()
				$command.CommandText = $SQLQuery
				$null = $command.executenonquery()
				$connection.Close()
				Write-LogInfo "Uploading test results to database :  done!!"
			}
			catch
			{
				Write-LogErr "Uploading test results to database :  ERROR"
				$line = $_.InvocationInfo.ScriptLineNumber
				$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
				$ErrorMessage =  $_.Exception.Message
				Write-LogInfo "EXCEPTION : $ErrorMessage"
				Write-LogInfo "Source : Line $line in script $script_name."
			}
		} else {
			Write-LogErr "Database details are not provided. Results will not be uploaded to database!!"
		}
	} else {
		Write-LogErr "Unable to send telemetry data to Azure. XML Secrets file not provided."
	}
}

Function Get-LISAv2Tools($XMLSecretFile)
{
	# Copy required binary files to working folder
	$CurrentDirectory = Get-Location
	$CmdArray = @('7za.exe','dos2unix.exe','gawk','jq','plink.exe','pscp.exe', `
					'kvp_client32','kvp_client64','nc.exe')

	if ($XMLSecretFile) {
		$WebClient = New-Object System.Net.WebClient
		$xmlSecret = [xml](Get-Content $XMLSecretFile)
		$toolFileAccessLocation = $xmlSecret.secrets.blobStorageLocation
	}

	$CmdArray | ForEach-Object {
		# Verify the binary file in Tools location
		if (! (Test-Path $CurrentDirectory/Tools/$_) ) {
			Write-LogErr "$_ file is not found in Tools folder."
		    if ($toolFileAccessLocation) {
		        $WebClient.DownloadFile("$toolFileAccessLocation/$_","$CurrentDirectory\Tools\$_")
		        Write-LogInfo "File $_ successfully downloaded in Tools folder: $CurrentDirectory\Tools."
		    } else {
		        Throw "$_ file is not found, please either download the file to Tools folder, or specify the blobStorageLocation in XMLSecretFile"
            }
        }
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
        [array]$ParamsArray,
        [xml]$XMLConfig
    )

    $platform = $XMLConfig.config.CurrentTestPlatform
    $testParams = @{}

    foreach ($param in $ParamsArray.Split(',')) {
        switch ($param) {
            "Password" {
                $value = $($XMLConfig.config.$platform.Deployment.Data.Password)
                $testParams["PASSWORD"] = $value
            }
            "RoleName" {
                $value = $AllVMData.RoleName | ?{$_ -notMatch "dependency"}
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
        $XMLConfig
    )

    $testParams = @{}
    foreach ($param in $XMLParams.param) {
        $name = $param.split("=")[0]
        if ($name -eq "SECRET_PARAMS") {
            $paramsArray = $param.split("=")[1].trim("(",")"," ").split(" ")
            $testParams += Get-SecretParams -ParamsArray $paramsArray `
                 -XMLConfig $XMLConfig
        } else {
            $value = $param.split("=")[1]
            $testParams[$name] = $value
        }
    }

    return $testParams
}

function Run-SetupScript {
    <#
    .DESCRIPTION
    Executes a powershell script specified in the <setupscript> tag
    Used to further prepare environment/VM
    #>

    param(
        [string]$Script,
        [hashtable]$Parameters
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
    $result = & "${scriptLocation}" -TestParams $scriptParameters
    return $result
}

function Create-ConstantsFile {
    <#
    .DESCRIPTION
    Generic function that creates the constants.sh file using a hashtable
    #>

    param(
        [string]$FilePath,
        [hashtable]$Parameters
    )

    Set-Content -Value "#Generated by LISAv2" -Path $FilePath -Force
    foreach ($param in $Parameters.Keys) {
        Add-Content -Value ("{0}={1}" `
                 -f @($param,$($Parameters[$param]))) -Path $FilePath -Force
        $msg = ("{0}={1} added to constants.sh file" `
                 -f @($param,$($Parameters[$param])))
        Write-LogInfo $msg
    }
}

function Run-TestScript {
    <#
    .DESCRIPTION
    Executes test scripts specified in the <testScript> tag.
    Supports python, shell and powershell scripts.
    Python and shell scripts will be executed remotely.
    Powershell scripts will be executed host side.
    After the test completion, the method will collect logs
    (for shell and python) and return the relevant test result.
    #>

    param(
        [string]$Script,
        [hashtable]$Parameters,
        [string]$LogDir,
        $VMData,
        $XMLConfig,
        [string]$Username,
        [string]$Password,
        [string]$TestName,
        [string]$TestLocation,
        [int]$Timeout
    )

    $workDir = Get-Location
    $scriptName = $Script.split(".")[0]
    $scriptExtension = $Script.split(".")[1]
    $constantsPath = Join-Path $workDir "constants.sh"
    $testResult = ""

    Create-ConstantsFile -FilePath $constantsPath -Parameters $Parameters
    if(!$IsWindows){
        foreach ($VM in $VMData) {
            Copy-RemoteFiles -upload -uploadTo $VM.PublicIP -Port $VM.SSHPort `
                -files $constantsPath -Username $Username -password $Password
            Write-LogInfo "Constants file uploaded to: $($VM.RoleName)"
        }
    }
    Write-LogInfo "Test script: ${Script} started."
    if ($scriptExtension -eq "sh") {
        Run-LinuxCmd -Command "echo '${Password}' | sudo -S -s eval `"export HOME=``pwd``;bash ${Script} > ${TestName}_summary.log 2>&1`"" `
             -Username $Username -password $Password -ip $VMData.PublicIP -Port $VMData.SSHPort `
             -runMaxAllowedTime $Timeout
    } elseif ($scriptExtension -eq "ps1") {
        $scriptDir = Join-Path $workDir "Testscripts\Windows"
        $scriptLoc = Join-Path $scriptDir $Script
        foreach ($param in $Parameters.Keys) {
            $scriptParameters += (";{0}={1}" -f ($param,$($Parameters[$param])))
        }
        Write-LogInfo "${scriptLoc} -TestParams $scriptParameters"
        $testResult = & "${scriptLoc}" -TestParams $scriptParameters
    } elseif ($scriptExtension -eq "py") {
        Run-LinuxCmd -Username $Username -password $Password -ip $VMData.PublicIP -Port $VMData.SSHPort `
             -Command "python ${Script}" -runMaxAllowedTime $Timeout -runAsSudo
        Run-LinuxCmd -Username $Username -password $Password -ip $VMData.PublicIP -Port $VMData.SSHPort `
             -Command "mv Runtime.log ${TestName}_summary.log" -runAsSudo
    }

    if (-not $testResult) {
        $testResult = Collect-TestLogs -LogsDestination $LogDir -ScriptName $scriptName -TestType $scriptExtension `
             -PublicIP $VMData.PublicIP -SSHPort $VMData.SSHPort -Username $Username -password $Password `
             -TestName $TestName
    }
    return $testResult
}

function Collect-TestLogs {
    <#
    .DESCRIPTION
    Collects logs created by the test script.
    The function collects logs only if a shell/python test script is executed.
    #>

    param(
        [string]$LogsDestination,
        [string]$ScriptName,
        [string]$PublicIP,
        [string]$SSHPort,
        [string]$Username,
        [string]$Password,
        [string]$TestType,
        [string]$TestName
    )
    # Note: This is a temporary solution until a standard is decided
    # for what string py/sh scripts return
    $resultTranslation = @{ "TestAborted" = "Aborted";
                            "TestFailed" = "FAIL";
                            "TestCompleted" = "PASS"
                          }

    if ($TestType -eq "sh") {
        $filesTocopy = "{0}/state.txt, {0}/summary.log, {0}/TestExecution.log, {0}/TestExecutionError.log" `
            -f @("/home/${Username}")
        Copy-RemoteFiles -download -downloadFrom $PublicIP -downloadTo $LogsDestination `
             -Port $SSHPort -Username "root" -password $Password `
             -files $filesTocopy
        $summary = Get-Content (Join-Path $LogDir "summary.log")
        $testState = Get-Content (Join-Path $LogDir "state.txt")
        $testResult = $resultTranslation[$testState]
    } elseif ($TestType -eq "py") {
        $filesTocopy = "{0}/state.txt, {0}/Summary.log, {0}/${TestName}_summary.log" `
            -f @("/home/${Username}")
        Copy-RemoteFiles -download -downloadFrom $PublicIP -downloadTo $LogsDestination `
             -Port $SSHPort -Username "root" -password $Password `
             -files $filesTocopy
        $summary = Get-Content (Join-Path $LogDir "Summary.log")
        $testResult = $summary
    }

    Write-LogInfo "TEST SCRIPT SUMMARY ~~~~~~~~~~~~~~~"
    $summary | ForEach-Object {
        Write-Host $_ -ForegroundColor Gray -BackgroundColor White
    }
    Write-LogInfo "END OF TEST SCRIPT SUMMARY ~~~~~~~~~~~~~~~"

    return $testResult
}

function Run-Test {
<#
    .SYNOPSIS
    Common framework used for test execution. Supports Azure and Hyper-V platforms.

    .DESCRIPTION
    The Run-Test function implements the existing LISAv2 methods into a common
    framework used to run tests.
    The function is comprised of the next steps:

    - Test resource deployment step:
        Deploys VMs and other necessary resources (network interfaces, virtual networks).
        Enables root user for all VMs in deployment.
        For Hyper-V it creates one snapshot for each VM in deployment.
    - Setup script execution step (Hyper-V only):
        Executes a setup script to further prepare environment/VMs.
        The script is specified in the test definition using the <SetupScript> tag.
    - Test dependency upload step:
        Uploads all files specified inside the test definition <files> tag.
    - Test execution step:
        Creates and uploads the constants.sh used to pass parameters to remote scripts
        (constants.sh file contains parameters specified in the <testParams> tag).
        Executes the test script specified in the <testScript> tag
        (the shell/python scripts will be executed remotely).
        Downloads logs for created by shell/python test scripts.
    - Test resource cleanup step:
        Removes deployed resources depending on the test result and parameters.

    .PARAMETER CurrentTestData
        Test definition xml structure.

    .PARAMETER XmlConfig
        Xml structure that contains all the relevant information about test/deployment.

    .PARAMETER Distro
        Distro under test.

    .PARAMETER VMUser
        Username used in all VMs in deployment.

    .PARAMETER VMPassword
        Password used in all VMs in deployment.

    .PARAMETER ExecuteSetup
        Switch variable that specifies if the framework should create a new deployment

    .PARAMETER ExecuteTeardown
        Switch variable that specifies if the framework should clean the deployment
    #>

    param(
        $CurrentTestData,
        $XmlConfig,
        [string]$Distro,
        [string]$LogDir,
        [string]$VMUser,
        [string]$VMPassword,
        [bool]$ExecuteSetup,
        [bool]$ExecuteTeardown
    )

    $currentTestResult = Create-TestResultObject
    $resultArr = @()
    $testParameters = @{}
    $testPlatform = $XmlConfig.config.CurrentTestPlatform
    $testResult = $false
    $timeout = 300

    if ($testPlatform -eq "Azure") {
        $testLocation = $($xmlConfig.config.$TestPlatform.General.Location).Replace('"',"").Replace(' ',"").ToLower()
    } elseif ($testPlatform -eq "HyperV") {
        if($TestLocation){
            $testLocation = $TestLocation
        }else{
            $testLocation = $xmlConfig.config.HyperV.Hosts.ChildNodes[0].ServerName
        }
    }

    if ($ExecuteSetup -or -not $isDeployed) {
        $global:isDeployed = Deploy-VMS -setupType $CurrentTestData.setupType `
            -Distro $Distro -XMLConfig $XmlConfig -VMGeneration $VMGeneration
        if (!$isDeployed) {
            throw "Could not deploy VMs."
        }
        if(!$IsWindows){
            Enable-RootUser -RootPassword $VMPassword -VMData $AllVMData `
                -Username $VMUser -password $VMPassword
        }
        if ($testPlatform.ToUpper() -eq "HYPERV") {
            Create-HyperVCheckpoint -VMData $AllVMData -CheckpointName "ICAbase"
            $global:AllVMData = Check-IP -VMData $AllVMData
        }
    } else {
        if ($testPlatform.ToUpper() -eq "HYPERV") {
            if ($CurrentTestData.AdditionalHWConfig.HyperVApplyCheckpoint -eq "False") {
                Remove-AllFilesFromHomeDirectory -allDeployedVMs $AllVMData
                Write-LogInfo "Removed all files from home directory."
            } else  {
                Apply-HyperVCheckpoint -VMData $AllVMData -CheckpointName "ICAbase"
                $global:AllVMData = Check-IP -VMData $AllVMData
                Write-LogInfo "Public IP found for all VMs in deployment after checkpoint restore"
            }
        }
    }

    if (!$IsWindows) {
        $null = GetAndCheck-KernelLogs -allDeployedVMs $allVMData -status "Initial"
    }

    if ($CurrentTestData.TestParameters) {
        $testParameters = Parse-TestParameters -XMLParams $CurrentTestData.TestParameters `
             -XMLConfig $xmlConfig
    }

    if ($testPlatform -eq "Hyperv" -and $CurrentTestData.SetupScript) {
        if ($null -eq $CurrentTestData.runSetupScriptOnlyOnce) {
            foreach ($VM in $AllVMData) {
                if (Get-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -EA SilentlyContinue) {
                    Stop-VM -Name $VM.RoleName -TurnOff -Force -ComputerName $VM.HyperVHost
                }
                foreach ($script in $($CurrentTestData.SetupScript).Split(",")) {
                    $null = Run-SetupScript -Script $script -Parameters $testParameters
                }
                if (Get-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost -EA SilentlyContinue) {
                    Start-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost
                }
            }
        }
        else {
            foreach ($script in $($CurrentTestData.SetupScript).Split(",")) {
                $null = Run-SetupScript -Script $script -Parameters $testParameters
            }
        }
    }

    if ($CurrentTestData.files) {
        # This command uploads test dependencies in the home directory for the $vmUsername user
        if(!$IsWindows){
            foreach ($VMData in $AllVMData) {
                Copy-RemoteFiles -upload -uploadTo $VMData.PublicIP -Port $VMData.SSHPort `
                    -files $CurrentTestData.files -Username $VMUser -password $VMPassword
                Write-LogInfo "Test files uploaded to VM $($VMData.RoleName)"
            }
        }
    }

    if ($CurrentTestData.Timeout) {
        $timeout = $CurrentTestData.Timeout
    }

    if ($CurrentTestData.TestScript) {
        $testResult = Run-TestScript -Script $CurrentTestData.TestScript `
             -Parameters $testParameters -LogDir $LogDir -VMData $AllVMData `
             -Username $VMUser -password $VMPassword -XMLConfig $XmlConfig `
             -TestName $currentTestData.testName -TestLocation $testLocation `
             -Timeout $timeout
        $resultArr += $testResult
    }

    if ($testPlatform -eq "Hyperv" -and $CurrentTestData.CleanupScript) {
        foreach ($VM in $AllVMData) {
            if (Get-VM -Name $VM.RoleName -ComputerName `
                $VM.HyperVHost -EA SilentlyContinue) {
                Stop-VM -Name $VM.RoleName -TurnOff -Force -ComputerName `
                    $VM.HyperVHost
            }
            foreach ($script in $($CurrentTestData.CleanupScript).Split(",")) {
                $null = Run-SetupScript -Script $script `
                    -Parameters $testParameters
            }
            if (Get-VM -Name $VM.RoleName -ComputerName $VM.HyperVHost `
                -EA SilentlyContinue) {
                Start-VM -Name $VM.RoleName -ComputerName `
                    $VM.HyperVHost
            }
        }
    }

    $currentTestResult.TestResult = Get-FinalResultHeader -resultarr $resultArr
    Write-LogInfo "VM CLEANUP ~~~~~~~~~~~~~~~~~~~~~~~"
    if ($xmlConfig.config.HyperV.Deployment.($CurrentTestData.setupType).ClusteredVM) {
        foreach ($VM in $AllVMData) {
            Add-VMGroupMember -Name $VM.HyperVGroupName -VM (Get-VM -name $VM.RoleName -ComputerName $VM.HyperVHost) `
                -ComputerName $VM.HyperVHost
        }
    }
    $optionalParams = @{}
    if ($testParameters["SkipVerifyKernelLogs"] -eq "True") {
        $optionalParams["SkipVerifyKernelLogs"] = $True
    }
    Do-TestCleanUp -CurrentTestResult $CurrentTestResult -TestName $currentTestData.testName `
    -ResourceGroups $isDeployed @optionalParams -DeleteRG $ExecuteTeardown

    return $currentTestResult
}

Function Do-TestCleanUp($CurrentTestResult, $testName, $DeployedServices, $ResourceGroups, [switch]$keepUserDirectory, [switch]$SkipVerifyKernelLogs, $DeleteRG=$true)
{
	try
	{
		$result = $CurrentTestResult.TestResult

		if($ResourceGroups)
		{
			if(!$IsWindows -and !$SkipVerifyKernelLogs) {
				try
				{
					if ($allVMData.Count -gt 1)
					{
						$vmData = $allVMData[0]
					}
					else
					{
						$vmData = $allVMData
					}
					$FilesToDownload = "$($vmData.RoleName)-*.txt"
					Copy-RemoteFiles -upload -uploadTo $vmData.PublicIP -port $vmData.SSHPort `
						-files .\Testscripts\Linux\CollectLogFile.sh `
						-username $user -password $password -maxRetry 5 | Out-Null
					$Null = Run-LinuxCmd -username $user -password $password -ip $vmData.PublicIP -port $vmData.SSHPort -command "bash CollectLogFile.sh" -ignoreLinuxExitCode -runAsSudo
					$Null = Copy-RemoteFiles -downloadFrom $vmData.PublicIP -port $vmData.SSHPort -username $user -password $password -files "$FilesToDownload" -downloadTo "$LogDir" -download
					$KernelVersion = Get-Content "$LogDir\$($vmData.RoleName)-kernelVersion.txt"
					$GuestDistro = Get-Content "$LogDir\$($vmData.RoleName)-distroVersion.txt"
					$LISMatch = (Select-String -Path "$LogDir\$($vmData.RoleName)-lis.txt" -Pattern "^version:").Line
					if ($LISMatch)
					{
						$LISVersion = $LISMatch.Split(":").Trim()[1]
					}
					else
					{
						$LISVersion = "NA"
					}
					#region Host Version checking
					$FoundLineNumber = (Select-String -Path "$LogDir\$($vmData.RoleName)-dmesg.txt" -Pattern "Hyper-V Host Build").LineNumber
					$ActualLineNumber = $FoundLineNumber - 1
					$FinalLine = (Get-Content -Path "$LogDir\$($vmData.RoleName)-dmesg.txt")[$ActualLineNumber]
					$FinalLine = $FinalLine.Replace('; Vmbus version:4.0','')
					$FinalLine = $FinalLine.Replace('; Vmbus version:3.0','')
					$HostVersion = ($FinalLine.Split(":")[$FinalLine.Split(":").Count -1 ]).Trim().TrimEnd(";")
					#endregion

					if($EnableAcceleratedNetworking -or ($currentTestData.AdditionalHWConfig.Networking -imatch "SRIOV"))
					{
						$Networking = "SRIOV"
					}
					else
					{
						$Networking = "Synthetic"
					}
					if ($TestPlatform -eq "Azure")
					{
						$VMSize = $vmData.InstanceSize
					}
					if ( $TestPlatform -eq "HyperV")
					{
						$VMSize = $HyperVInstanceSize
					}
					#endregion
					$SQLQuery = Get-SQLQueryOfTelemetryData -TestPlatform $TestPlatform -TestLocation $TestLocation -TestCategory $TestCategory `
					-TestArea $TestArea -TestName $CurrentTestData.TestName -CurrentTestResult $CurrentTestResult `
					-ExecutionTag $ResultDBTestTag -GuestDistro $GuestDistro -KernelVersion $KernelVersion `
					-LISVersion $LISVersion -HostVersion $HostVersion -VMSize $VMSize -Networking $Networking `
					-ARMImage $ARMImage -OsVHD $OsVHD -BuildURL $env:BUILD_URL
					if($SQLQuery)
					{
						Upload-TestResultToDatabase -SQLQuery $SQLQuery
					}
				}
				catch
				{
					$line = $_.InvocationInfo.ScriptLineNumber
					$script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
					$ErrorMessage =  $_.Exception.Message
					Write-LogErr "EXCEPTION : $ErrorMessage"
					Write-LogErr "Source : Line $line in script $script_name."
					Write-LogErr "Ignorable error in collecting final data from VMs."
				}
			}

			# Remove running background jobs
			$currentTestBackgroundJobs = Get-Content $LogDir\CurrentTestBackgroundJobs.txt -ErrorAction SilentlyContinue
			if ($currentTestBackgroundJobs) {
				$currentTestBackgroundJobs = $currentTestBackgroundJobs.Split()
			}
			foreach ($taskID in $currentTestBackgroundJobs) {
				Write-LogInfo "Removing Background Job $taskID..."
				Remove-Job -Id $taskID -Force
				Remove-Item $LogDir\CurrentTestBackgroundJobs.txt -ErrorAction SilentlyContinue
			}

			$user=$xmlConfig.config.$TestPlatform.Deployment.Data.UserName
			if (!$SkipVerifyKernelLogs) {
				try {
					GetAndCheck-KernelLogs -allDeployedVMs $allVMData -status "Final" | Out-Null
				} catch {
					$ErrorMessage =  $_.Exception.Message
					Write-LogInfo "EXCEPTION in GetAndCheck-KernelLogs(): $ErrorMessage"
				}
			}
			$isCleaned = @()
			$ResourceGroups = $ResourceGroups.Split("^")
			if(!$IsWindows){
				$isVMLogsCollected = $false
			} else {
				$isVMLogsCollected = $true
			}
			foreach ($group in $ResourceGroups)
			{
				if ($ForceDeleteResources)
				{
					$global:isDeployed = $null
					Write-LogInfo "-ForceDeleteResources is Set. Deleting $group. Set global variable isDeployed to $global:isDeployed"
					if ($TestPlatform -eq "Azure")
					{
						$isCleaned = Delete-ResourceGroup -RGName $group

					}
					elseif ($TestPlatform -eq "HyperV")
					{
						foreach($vmData in $allVMData)
						{
							if($group -eq $vmData.HyperVGroupName)
							{
								$isCleaned = Delete-HyperVGroup -HyperVGroupName $group -HyperVHost $vmData.HyperVHost
								if (Get-Variable 'DependencyVmHost' -Scope 'Global' -EA 'Ig') {
									if ($DependencyVmHost -ne $vmData.HyperVHost) {
										Delete-HyperVGroup -HyperVGroupName $group -HyperVHost $DependencyVmHost
									}
								}
							}
						}
					}
					if (!$isCleaned)
					{
						Write-LogInfo "CleanUP unsuccessful for $group.. Please delete the services manually."
					}
					else
					{
						Write-LogInfo "CleanUP Successful for $group.."
					}
				}
				else
				{
					if($result -eq "PASS")
					{
						if(-not $DeleteRG)
						{
							Write-LogInfo "Skipping cleanup of Resource Group : $group."
							if(!$keepUserDirectory)
							{
								Remove-AllFilesFromHomeDirectory -allDeployedVMs $allVMData
							}
						}
						else
						{
							$global:isDeployed = $null
							try
							{
								$RGdetails = Get-AzureRmResourceGroup -Name $group -ErrorAction SilentlyContinue
							}
							catch
							{
								Write-LogInfo "Resource group '$group' not found."
							}
							if ( $RGdetails.Tags -and (  $RGdetails.Tags[0].Name -eq $preserveKeyword ) -and (  $RGdetails.Tags[0].Value -eq "yes" ))
							{
								Write-LogInfo "Skipping Cleanup of preserved resource group."
								Write-LogInfo "Collecting VM logs.."
								if ( !$isVMLogsCollected)
								{
									Get-VMLogs -allVMData $allVMData
								}
								$isVMLogsCollected = $true
							}
							else
							{
								if ( $DoNotDeleteVMs )
								{
									Write-LogInfo "Skipping cleanup due to 'DoNotDeleteVMs' flag is set."
								}
								else
								{
									Write-LogInfo "Cleaning up deployed test virtual machines."
									if ($TestPlatform -eq "Azure")
									{
										$isCleaned = Delete-ResourceGroup -RGName $group
									}
									elseif ($TestPlatform -eq "HyperV")
									{
										foreach($vmData in $allVMData)
										{
											if($group -eq $vmData.HyperVGroupName)
											{
												$isCleaned = Delete-HyperVGroup -HyperVGroupName $group -HyperVHost $vmData.HyperVHost
												if (Get-Variable 'DependencyVmHost' -Scope 'Global' -EA 'Ig') {
													if ($DependencyVmHost -ne $vmData.HyperVHost) {
														Delete-HyperVGroup -HyperVGroupName $group -HyperVHost $DependencyVmHost
													}
												}
											}
										}
									}
									if (!$isCleaned)
									{
										Write-LogInfo "CleanUP unsuccessful for $group.. Please delete the services manually."
									}
									else
									{
										Write-LogInfo "CleanUP Successful for $group.."
									}
								}
							}
						}
					}
					else
					{
						Write-LogInfo "Preserving the Resource Group(s) $group"
						if ($TestPlatform -eq "Azure")
						{
							Add-ResourceGroupTag -ResourceGroup $group -TagName $preserveKeyword -TagValue "yes"
							$global:isDeployed = $null
						}
						Write-LogInfo "Collecting VM logs.."
						if ( !$isVMLogsCollected)
						{
							Get-VMLogs -allVMData $allVMData
						}
						$isVMLogsCollected = $true
						if ($TestPlatform -eq "HyperV") {
							Create-HyperVCheckpoint -VMData $AllVMData -CheckpointName "${testName}-$($CurrentTestResult.TestResult)" `
								-ShouldTurnOffVMBeforeCheckpoint $false -ShouldTurnOnVMAfterCheckpoint $false
						}
					}
				}
			}
		}
		else
		{
			$SQLQuery = Get-SQLQueryOfTelemetryData -TestPlatform $TestPlatform -TestLocation $TestLocation -TestCategory $TestCategory `
			-TestArea $TestArea -TestName $CurrentTestData.TestName -CurrentTestResult $CurrentTestResult `
			-ExecutionTag $ResultDBTestTag -GuestDistro $GuestDistro -KernelVersion $KernelVersion `
			-LISVersion $LISVersion -HostVersion $HostVersion -VMSize $VMSize -Networking $Networking `
			-ARMImage $ARMImage -OsVHD $OsVHD -BuildURL $env:BUILD_URL
			if($SQLQuery)
			{
				Upload-TestResultToDatabase -SQLQuery $SQLQuery
			}
			Write-LogInfo "Skipping cleanup, as No services / resource groups / HyperV Groups deployed for cleanup!"
		}
	}
	catch
	{
		$ErrorMessage =  $_.Exception.Message
		Write-Output "EXCEPTION in Do-TestCleanUp : $ErrorMessage"
	}
}

Function Is-VmAlive($AllVMDataObject) {
    Write-LogInfo "Trying to Connect to deployed VM(s)"
    $timeout = 0
    $retryCount = 20
    do {
        $WaitingForConnect = 0
        foreach ( $vm in $AllVMDataObject) {
            if ($IsWindows) {
                $port = $($vm.RDPPort)
            }
            else {
                $port = $($vm.SSHPort)
            }

            $out = Test-TCP  -testIP $($vm.PublicIP) -testport $port
            if ($out -ne "True") {
                Write-LogInfo "Connecting to  $($vm.PublicIP) : $port : Failed"
                $WaitingForConnect = $WaitingForConnect + 1
            }
            else {
                Write-LogInfo "Connecting to  $($vm.PublicIP) : $port : Connected"
            }
        }

        if ($WaitingForConnect -gt 0) {
            $timeout = $timeout + 1
            Write-LogInfo "$WaitingForConnect VM(s) still awaiting to open port $port .."
            Write-LogInfo "Retry $timeout/$retryCount"
            sleep 3
            $retValue = "False"
        } else {
            Write-LogInfo "ALL VM's port $port is/are open now.."
            $retValue = "True"
        }

    } While (($timeout -lt $retryCount) -and ($WaitingForConnect -gt 0))

    if ($retValue -eq "False") {
        foreach ($vm in $AllVMDataObject) {
            $out = Test-TCP -testIP $($vm.PublicIP) -testport $port
            if ($out -ne "True" -and $TestPlatform -eq "Azure") {
                Write-LogInfo "Getting Azure boot diagnostic data of VM $($vm.RoleName)"
                $vmStatus = Get-AzureRmVm -ResourceGroupName $vm.ResourceGroupName -VMName $vm.RoleName -Status
                if ($vmStatus -and $vmStatus.BootDiagnostics) {
                    if ($vmStatus.BootDiagnostics.SerialConsoleLogBlobUri) {
                        Write-LogInfo "Getting serial boot logs of VM $($vm.RoleName)"
                        $uri = [System.Uri]$vmStatus.BootDiagnostics.SerialConsoleLogBlobUri
                        $storageAccountName = $uri.Host.Split(".")[0]
                        $diagnosticRG = ((Get-AzureRmStorageAccount) | where {$_.StorageAccountName -eq $storageAccountName}).ResourceGroupName.ToString()
                        $key = (Get-AzureRmStorageAccountKey -ResourceGroupName $diagnosticRG -Name $storageAccountName)[0].value
                        $diagContext = New-AzureStorageContext -StorageAccountName $storageAccountName -StorageAccountKey $key
                        Get-AzureStorageBlobContent -Blob $uri.LocalPath.Split("/")[2] `
                            -Context $diagContext -Container $uri.LocalPath.Split("/")[1] `
                            -Destination "$LogDir\$($vm.RoleName)-SSH-Fail-Boot-Logs.txt"
                    }
                }
            }
        }
    }

    return $retValue
}