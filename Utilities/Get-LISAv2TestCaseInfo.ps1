# Linux on Hyper-V and Azure Test Code, ver. 1.0.0
# Copyright (c) Microsoft Corporation

# Description: This script displays the LISav2 test case statistics and list of available tags.

# Read all test case xml files
param (
    [string] $AzureSecretsFile,
    [string] $TableName = "LISAv2TestCases",
    [string] $LogFileName = "GetAzureVMs.log"
)

function Delete-DeprecatedRecord($CaseNameList) {
    $server = $XmlSecrets.secrets.DatabaseServer
    $dbuser = $XmlSecrets.secrets.DatabaseUser
    $dbpassword = $XmlSecrets.secrets.DatabasePassword
    $database = $XmlSecrets.secrets.DatabaseName

    $connectionString = "Server=$server;uid=$dbuser; pwd=$dbpassword;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    $connection = New-Object System.Data.SqlClient.SqlConnection
    $connection.ConnectionString = $connectionString
    $connection.Open()
    
    try {
        $sqlQuery = "SELECT ID,TestCaseName from $TableName"
        $command = $connection.CreateCommand()
        $command.CommandText = $SQLQuery
        $reader = $command.ExecuteReader()
        $deprecatedIDList = @()
        while ($reader.Read()) {
            $id = $reader.GetValue($reader.GetOrdinal("ID"))
            $caseName = $reader.GetValue($reader.GetOrdinal("TestCaseName"))
            if (-not $CaseNameList.contains($caseName)) {
                $deprecatedIDList += $id
            }
        }
        $reader.Close()
        if ($deprecatedIDList.Count -gt 0) {
            $sqlQuery = "delete from $TableName where"
            $isFirst = $true
            foreach ($id in $deprecatedIDList) {
                if (-not $isFirst) {
                    $sqlQuery += " or"
                }
                $sqlQuery += " ID=$id"
                $isFirst = $false
            }
            
            Write-LogInfo "Executing command: $sqlQuery"
            $command.CommandText = $SQLQuery
            $null = $command.executenonquery()
        }
    } catch {
        $line = $_.InvocationInfo.ScriptLineNumber
        $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
        $ErrorMessage =  $_.Exception.Message

        Write-LogErr "EXCEPTION: $ErrorMessage"
        Write-LogErr "Source: Line $line in script $script_name."
    } finally {
        $reader.close()
        $connection.close()
    }
}

function Update-DatabaseRecord($TestCaseList) {
    $server = $XmlSecrets.secrets.DatabaseServer
    $dbuser = $XmlSecrets.secrets.DatabaseUser
    $dbpassword = $XmlSecrets.secrets.DatabasePassword
    $database = $XmlSecrets.secrets.DatabaseName

    $connectionString = "Server=$server;uid=$dbuser; pwd=$dbpassword;Database=$database;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    $connection = New-Object System.Data.SqlClient.SqlConnection
    $connection.ConnectionString = $connectionString
    $connection.Open()
    

    try {
        foreach ($TestCaseData in $TestCaseList) {
            # Query if the image exists in the database
            $sqlQuery = "SELECT * from $TableName where TestCaseName='$($TestCaseData.testName)'"
            $command = $connection.CreateCommand()
            $command.CommandText = $SQLQuery
            $reader = $command.ExecuteReader()
            # If the record exists, update the LastCheckedDate
            if ($reader.Read()) {
                $sqlQuery = ""
                $testCategory = $reader.GetValue($reader.GetOrdinal("TestCategory"))
                $testArea = $reader.GetValue($reader.GetOrdinal("TestArea"))
                $testPriority = $reader.GetValue($reader.GetOrdinal("TestPriority"))
                $testTags = $reader.GetValue($reader.GetOrdinal("TestTags"))
                $testPlatform = $reader.GetValue($reader.GetOrdinal("TestPlatform"))

                $priority = $TestCaseData.Priority
                if (-not $priority) {
                    $priority = -1
                }

                if ($testCategory -ne $TestCaseData.Category -or $testArea -ne $TestCaseData.Area -or $testPriority -ne $priority -or
                    $testTags -ne $TestCaseData.Tags -or $testPlatform -ne $TestCaseData.Platform) {
                    $sqlQuery = "Update $tableName Set TestCategory='$($TestCaseData.Category)', TestArea='$($TestCaseData.Area)', TestPriority=$priority,
                        TestTags='$($TestCaseData.Tags)',TestPlatform='$($TestCaseData.Platform)' where TestCaseName='$($TestCaseData.testName)'"
                }
            # If the record doesn't exist, insert a new record
            } else {
                $sqlQuery = "INSERT INTO $tableName (TestCaseName, TestCategory, TestArea, TestPriority, TestTags, TestPlatform) VALUES
                    ('$($TestCaseData.testName)','$($TestCaseData.Category)', '$($TestCaseData.Area)', '$($TestCaseData.Priority)', '$($TestCaseData.Tags)', '$($TestCaseData.Platform)')"
            }
            $reader.Close()
            if ($sqlQuery) {
                Write-LogInfo "Executing command: $sqlQuery"
                $command.CommandText = $SQLQuery
                $null = $command.executenonquery()
            }            
        }
    } catch {
        $line = $_.InvocationInfo.ScriptLineNumber
        $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD,".")
        $ErrorMessage =  $_.Exception.Message

        Write-LogErr "EXCEPTION: $ErrorMessage"
        Write-LogErr "Source: Line $line in script $script_name."
    } finally {
        $reader.close()
        $connection.close()
    }
}

#Load libraries
if (!$global:LogFileName) {
    Set-Variable -Name LogFileName -Value $LogFileName -Scope Global -Force
}
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global -DisableNameChecking }

#Read secrets file and terminate if not present.
if ($AzureSecretsFile) {
    $secretsFile = $AzureSecretsFile
}
elseif ($env:Azure_Secrets_File) {
    $secretsFile = $env:Azure_Secrets_File
}
else {
     Write-Host "-AzureSecretsFile and env:Azure_Secrets_File are empty. Exiting."
     exit 1
}

if (Test-Path $secretsFile) {
    Write-Host "Secrets file found."
    $secrets = [xml](Get-Content -Path $secretsFile)
    Set-Variable -Name XmlSecrets -Value $secrets -Scope Global -Force
}
 else {
     Write-Host "Secrets file not found. Exiting."
     exit 1
}

# Load test case xmls
$files = Get-ChildItem ".\XML\TestCases\*.xml" -Exclude Other.xml
$caseNameList = @()
foreach ($fname in $files) {
    $testCaseList = @()
    $xml = [xml](Get-Content $fname)
    foreach ($item in $xml.TestCases.test) {
        $testCaseList += $item
        $caseNameList += $item.testName
    }
    Update-DatabaseRecord -TestCaseList $testCaseList
}
Delete-DeprecatedRecord -CaseNameList $caseNameList