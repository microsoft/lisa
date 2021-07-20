# Description: This script is used for checking enabled VM sizes and VM core quota in the given azure subscription.
# It will upload subscription id and unavailable VM/insufficient VM core to db
# This script will be executed by 'Penguinator-Validate-Azure-Subscription-Info' pipeline
# This script should be under .\lisav2\Utilities directory

Param
(
    [String] $clientSecret,
    [String] $clientID,
    [String] $tenantID,
    [String] $subID,
    [String] $lisaTestCasesXMLPath = '.\lisav2\XML\TestCases',
    [String] $lisaVMConfigsPath = '.\lisav2\XML\VMConfigurations',
    [String] $penguinatorSecureFilePath
)


$AllLisaTests = [System.Collections.ArrayList]::new()
$script:AllTestVMSizes = @{}
$script:InsufficientVMSizes = [System.Collections.ArrayList]::new()
$script:InsufficientVMFamilyAndQuota = @{}

Import-Module .\lisav2\Libraries\TestLogs.psm1

# Merge VM config files for simpler checking
function Join-VMConfigFiles ($filePath) {
    $files = Get-ChildItem $filePath
    $finalXml = "<TestSetup>"
    foreach ($file in $files) {
        $xml = [xml](Get-Content $file.FullName)
        $finalXml += $xml.TestSetup.InnerXml
    }
    $finalXml += "</TestSetup>"
    ([xml]$finalXml).Save(".\lisav2\mergedVMConfig.xml")
    return [xml]$finalXml
}

function Measure-SubscriptionCapabilities() {
    Write-LogInfo "Measure VM capabilities of current subscription..."
    if (!$script:SubscriptionVMResourceSkus -or !$script:TestableLocations) {
        $regionScopeFromUser = @()
        $RegionAndStorageMapFile = ".\lisav2\XML\RegionAndStorageAccounts.xml"
        if (Test-Path $RegionAndStorageMapFile) {
            $RegionAndStorageMap = [xml](Get-Content $RegionAndStorageMapFile)
            $RegionAndStorageMap.AllRegions.ChildNodes | ForEach-Object { $regionScopeFromUser += $_.LocalName }
        }

        Set-Variable -Name SubscriptionVMResourceSkus -Option ReadOnly -Scope script `
            -Value (Get-AzComputeResourceSku | Where-Object { $_.ResourceType.Contains("virtualMachines") -and ($_.Restrictions.Type -notcontains 'Location') } | Select-Object Name, @{l = "Location"; e = { $_.Locations[0] } }, Family, Restrictions, Capabilities | Where-Object { $regionScopeFromUser -contains "$($_.Location)" })
        Set-Variable -Name TestableLocations -Option ReadOnly -Scope script -Value ($SubscriptionVMResourceSkus | Group-Object Location | Select-Object -ExpandProperty Name)
    }

    Write-LogInfo "Measure vCPUs, Family, and AvailableLocations for each test VM Size..."
    if ($script:AllTestVMSizes -and $script:TestableLocations) {
        $svmusage = @{}
        # loop through testable locations
        # use Get-AzVMUsage to get the virtual machine core count usage for a location
        # for each location, map location - value
        $script:TestableLocations | Foreach-Object {
            $loc = $_
            $svmusage["$_"] = (Get-AzVMUsage -Location $_ | Select-Object @{l = "Location"; e = { $loc } }, @{l = "VMFamily"; e = { $_.Name.Value } }, @{l = "AvailableUsage"; e = { $_.Limit - $_.CurrentValue } }, Limit)
        }
        # loop through AllTestVMSizes
        $script:AllTestVMSizes.Keys | Foreach-Object {
            $vmSize = $_
            $vmSizeSkus = $SubscriptionVMResourceSkus | Where-Object Name -eq "$vmSize"
            if ($vmSizeSkus) {
                $vmSizeSkusFirst = $vmSizeSkus | Select-Object -First 1
                $vmSizeCapabilities = $vmSizeSkusFirst | Select-Object -ExpandProperty Capabilities # {MaxResourceVolumeMB, OSVhdSizeMB, vCPUs, MemoryPreservingMaintenanceSupported...}

                $vmTestableLocation = $vmSizeSkus | Group-Object Location | Select-Object -ExpandProperty Name | Where-Object { $TestableLocations -contains $_ }
                $vmFamily = $vmSizeSkusFirst | Select-Object -ExpandProperty Family
                $vmCPUs = $vmSizeCapabilities | Where-Object { $_.Name -eq 'vCPUs' } | Select-Object -ExpandProperty Value
                $vmGenerations = $vmSizeCapabilities | Where-Object { $_.Name -eq 'HyperVGenerations' } | Select-Object -ExpandProperty Value

                $locationFamilyUsage = [System.Collections.ArrayList]@()
                $vmTestableLocation | Where-Object {
                    $locationFamilyUsage += $svmusage.$_ | Where-Object { $_.VMFamily -eq $vmFamily } | Select-Object Location, AvailableUsage
                }
                # update AllTestVMSizes for this vmSize
                $script:AllTestVMSizes.$vmSize["AvailableLocations"] = @($locationFamilyUsage | Sort-Object AvailableUsage -Descending | Select-Object -ExpandProperty Location)
                $script:AllTestVMSizes.$vmSize["Family"] = $vmFamily
                $script:AllTestVMSizes.$vmSize["vCPUs"] = [int]$vmCPUs
                $script:AllTestVMSizes.$vmSize["Generations"] = $vmGenerations
            }
        }
    }
}

# Check required VM size and core quota from LISAv2 XML
# Walk through all test cases, summarize requirements
function Assert-VMSizeAndCoreQuota () {
    $TestXMLs = Get-ChildItem -Path $lisaTestCasesXMLPath

    # Get AllTests
    foreach ($file in $TestXMLs.FullName) {
        $currentTests = ([xml](Get-Content -Path $file)).TestCases
        foreach ($test in $currentTests.test) {
            if (!($AllLisaTests | Where-Object {($_.TestName -eq $test.TestName) -or ($test.Priority -ge 3) })) {
                Write-LogInfo "Collected test: $($test.TestName) from $file"
                [void]$AllLisaTests.Add($test)
            }
            else {
                Write-LogWarn "Ignore duplicated or low priority ($($test.Priority)) test: $($test.TestName) from $file"
            }
        }
    }
    # filter out test cases not support Azure then sort result by priority&name
    $AllLisaTests = $AllLisaTests | Where-Object {$_.Platform.Contains("Azure")}
    $AllLisaTests = [System.Collections.ArrayList]@($AllLisaTests | Sort-Object -Property @{Expression = {if ($_.Priority) {$_.Priority} else {'9'}}}, TestName)

    # initialize AllTestVMSizes
    $AllLisaTests.SetupConfig.OverrideVMSize | Sort-Object -Unique | Foreach-Object {
        $_ = $_.Split(",")[0]
        if (!($script:AllTestVMSizes.$_)) {
            $script:AllTestVMSizes["$_"] = @{}
        }
    }
    $allTestSetupTypes = $AllLisaTests.SetupConfig.SetupType | Sort-Object -Unique
    $SetupTypeXMLs = Get-ChildItem -Path $lisaVMConfigsPath
    foreach ($file in $SetupTypeXMLs.FullName) {
        $setupXml = [xml]( Get-Content -Path $file)
        foreach ($SetupType in $setupXml.TestSetup.ChildNodes) {
            if ($allTestSetupTypes -contains $SetupType.LocalName) {
                $vmSizes = $SetupType.ResourceGroup.VirtualMachine.InstanceSize | Sort-Object -Unique
                $vmSizes | ForEach-Object {
                    if (!$script:AllTestVMSizes."$_") {
                        $script:AllTestVMSizes["$_"] = @{}
                    }
                }
            }
        }
    }

    # Update $AllTestVMSizes
    Measure-SubscriptionCapabilities

    # Join all VM configs
    $mergedVMConfigs = Join-VMConfigFiles($lisaVMConfigsPath)
    # Loop through tests
    foreach ($test in $AllLisaTests) {
        Write-LogInfo "Checking test: $($test.TestName)"
        $RGXMLData = $mergedVMConfigs.'TestSetup'.$($test.SetupConfig.SetupType).'ResourceGroup'
        Assert-ResourceLimitation $RGXMLData $test
    }
}

function Assert-ResourceLimitation($RGXMLData, $CurrentTestData) {
    # TODO: ADDING CHECK FOR NETWORK AND RESOURCE GROUP

    Function Test-OverflowErrors {
        Param (
            [string] $ResourceType,
            [int] $CurrentValue,
            [int] $RequiredValue,
            [int] $MaximumLimit,
            [string] $Location
        )
        $AllowedUsagePercentage = 1
        $ActualLimit = [int]($MaximumLimit * $AllowedUsagePercentage)
        $Message = "Current '$ResourceType' in region '$Location': Requested: $RequiredValue, Estimated usage after deploy: $($CurrentValue + $RequiredValue), Maximum allowed: $ActualLimit"
        if (($CurrentValue + $RequiredValue) -le $ActualLimit) {
            Write-LogDbg $Message
            return 0
        }
        else {
            Write-LogErr $Message
            return 1
        }
    }

    $VMGeneration = $CurrentTestData.SetupConfig.VMGeneration
    # Verify usage and select Test Location
    $vmCounter = 0
    $vmFamilyRequiredCPUs = @{}
    foreach ($VM in $RGXMLData.VirtualMachine) {
        $vmCounter += 1
        Write-LogInfo "Estimating VM #$vmCounter usage for $($CurrentTestData.TestName)."
        # this 'OverrideVMSize' is already expanded from CurrentTestData with single value
        if ($CurrentTestData.SetupConfig.OverrideVMSize) {
            $testVMSize = $CurrentTestData.SetupConfig.OverrideVMSize.Split(",")[0]
        }
        else {
            $testVMSize = $VM.InstanceSize
        }

        # For Gallery Image, leave HyperVGeneration checking before deployment 'Test-AzResourceGroupDeployment',
        # because getting 'HyperVGeneration' is not sufficient here to check from Region to Region.
        if ($CurrentTestData.SetupConfig.OsVHD -and $VMGeneration -and !$script:AllTestVMSizes.$testVMSize.Generations.Contains($VMGeneration)) {
            Write-LogErr "Requested VM size: '$testVMSize' with VM generation: '$VMGeneration' is NOT supported, this should be an Azure limitation temporarily, please try other VM Sizes that support HyperVGeneration '$VMGeneration'."
            [void]$script:InsufficientVMSizes.Add($testVMSize)
        }
        elseif (!$script:AllTestVMSizes.$testVMSize.AvailableLocations) {
            Write-LogErr "Requested VM size: '$testVMSize' is NOT enabled from any region of current subscription, please open Azure Support Tickets for it."
            [void]$script:InsufficientVMSizes.Add($testVMSize)
        }
        # remaining cases should be, not HyperV, and there is at least 1 available location/this vm size is enabled somewhere
        # then we should check if quota is enough
        else {
            $vmCPUs = $script:AllTestVMSizes.$testVMSize.vCPUs
            $vmFamily = $script:AllTestVMSizes.$testVMSize.Family
            if ($vmFamilyRequiredCPUs.$vmFamily) {
                $vmFamilyRequiredCPUs.$vmFamily["requiredCPUs"] += [int]$vmCPUs
            }
            else {
                $vmFamilyRequiredCPUs["$vmFamily"] = @{}
                $vmFamilyRequiredCPUs.$vmFamily["requiredCPUs"] = [int]$vmCPUs
            }

            $vmAvailableLocations = $script:AllTestVMSizes.$testVMSize.AvailableLocations

            $index = 0
            for ($index = 0; $index -lt $vmAvailableLocations.Count; ) {
                $regionVmUsage = Get-AzVMUsage -Location $vmAvailableLocations[$index]
                $vmFamilyUsage = $regionVmUsage | Where-Object { $_.Name.Value -imatch "$vmFamily" } | Select-Object CurrentValue, Limit
                $regionCoresUsage = $regionVmUsage | Where-Object { $_.Name.Value -imatch "$vmFamily" } | Select-Object CurrentValue, Limit
                $locationErrors = Test-OverflowErrors -ResourceType "$vmFamily" -CurrentValue $vmFamilyUsage.CurrentValue `
                    -RequiredValue $vmFamilyRequiredCPUs.$vmFamily["requiredCPUs"] -MaximumLimit $vmFamilyUsage.Limit -Location $vmAvailableLocations[$index]
                $locationErrors += Test-OverflowErrors -ResourceType "Region Total Cores" -CurrentValue $regionCoresUsage.CurrentValue `
                    -RequiredValue $vmFamilyRequiredCPUs.$vmFamily["requiredCPUs"] -MaximumLimit $regionCoresUsage.Limit -Location $vmAvailableLocations[$index]
                if ($locationErrors -gt 0) {
                    $index++
                }
                else {
                    Write-LogInfo "Test Location '$($vmAvailableLocations[$index])' has VM Size '$testVMSize' enabled and has enough quota for '$($CurrentTestData.TestName)' deployment"
                    break
                }
            }
            if ($index -gt 0) {
                # Index is larger than 0 but less than vmAvailableLocation size, $vmAvailableLocations[$index] should be the available location
                if ($index -lt $vmAvailableLocations.Count) {
                    $locationFamilyUsage = [System.Collections.ArrayList]@()
                    $vmAvailableLocations | Where-Object {
                        $loc = $_
                        $svmusage = (Get-AzVMUsage -Location $_ | Select-Object @{l = "Location"; e = { $loc } }, @{l = "VMFamily"; e = { $_.Name.Value } }, @{l = "AvailableUsage"; e = { $_.Limit - $_.CurrentValue } }, Limit)
                        $locationFamilyUsage += $svmusage | Where-Object { $_.VMFamily -eq $vmFamily } | Select-Object Location, AvailableUsage
                    }
                    $script:AllTestVMSizes.$testVMSize.AvailableLocations = ($locationFamilyUsage | Sort-Object AvailableUsage -Descending | Select-Object -ExpandProperty Location)
                }
                # Loop over the whole vmAvailableLocation list but found no available location
                else {
                    Write-LogErr "Estimated resource usage for VM Size: '$testVMSize' exceeded allowed limits."
                    $vmFamilyRequiredCPUs.$vmFamily["isEnough"] = 'false'
                    [void]$script:InsufficientVMSizes.Add($testVMSize)
                }
            }
        }
    }

    # loop through $vmFamilyRequiredCPUs, check if we need to update $InsufficientVMFamilyAndQuota
    foreach ($key in $vmFamilyRequiredCPUs.Keys) {
        if (!$vmFamilyRequiredCPUs.$key["isEnough"]) {
            # No 'isEnough' means this vmFamily is enabled and has enough quota
            continue
        }
        if ($script:InsufficientVMFamilyAndQuota.$key -and ($script:InsufficientVMFamilyAndQuota.$key -gt $vmFamilyRequiredCPUs.$key["RequiredCPUs"])) {
            continue
        } else {
            $script:InsufficientVMFamilyAndQuota[$key] = $vmFamilyRequiredCPUs.$key["RequiredCPUs"]
        }
    }

    Write-LogInfo "================================================================================"
}

function ExecuteSql($connection, $sql, $parameters, $timeout=30) {
    try {
        $command = $connection.CreateCommand()
        $command.CommandText = $sql
        $command.CommandTimeout = $timeout
        if ($parameters) {
            $parameters.Keys | ForEach-Object { $command.Parameters.AddWithValue($_, $parameters[$_]) | Out-Null }
        }

        $count = $command.ExecuteNonQuery()
        if ($count) {
            Write-LogDbg "ExecuteSql: $count records are effected"
        }
    }
    finally {
        $command.Dispose()
    }
}

function QuerySql($connection, $sql, $Parameters, $timeout=30) {
    try {
        $dataset = new-object "System.Data.Dataset"
        $command = $connection.CreateCommand()
        $command.CommandText = $sql
        $command.CommandTimeout  = $timeout
        if ($parameters) {
            $parameters.Keys | ForEach-Object { $command.Parameters.AddWithValue($_, $parameters[$_]) | Out-Null }
        }

        $dataAdapter = new-object System.Data.SqlClient.SqlDataAdapter
        $dataAdapter.SelectCommand = $command
        $null = $dataAdapter.Fill($dataset)

        $rows = @()
        if ($dataset.Tables.Rows -isnot [array]) {
            $rows = @($dataset.Tables.Rows)
        }
        else {
            $rows = $dataset.Tables.Rows
        }
    }
    finally {
        $dataAdapter.Dispose()
        $dataset.Dispose()
        $command.Dispose()
    }
    return $rows
}

###################################################################################################
# The main process
###################################################################################################

# Authenticate
$pass = ConvertTo-SecureString $clientSecret -AsPlainText -Force
$mycred = New-Object System.Management.Automation.PSCredential ($clientID, $pass)
Connect-AzAccount -ServicePrincipal -Tenant $tenantID -Credential $mycred

Set-AzContext -Subscription $subID

# Check enabled vm sizes and cpu quota in given subscription
Assert-VMSizeAndCoreQuota

# Write result to DB
Write-LogInfo "Get connection string from secrets file and db server..."
$DbSecrets = ([xml](Get-Content -Path $penguinatorSecureFilePath)).secrets
$DbServer = $DBSecrets.DatabaseServer
$DbDatabase = $DBSecrets.DatabaseName
$DbUserName = $DbSecrets.DatabaseUser
$DbPassword = $DbSecrets.DatabasePassword
$connectionString = "Server=$DbServer;uid=$DbUserName;pwd=$DbPassword;Database=$DbDatabase;" + `
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;MultipleActiveResultSets=True;"

try {
    Write-LogInfo "Connecting to Penguinator DB server..."
    $connection = New-Object System.Data.SqlClient.SqlConnection
    $connection.ConnectionString = $connectionString
    $connection.Open()

    $script:InsufficientVMSizes = $script:InsufficientVMSizes | Select-Object -Unique
    $InsufficientVMSizeString = $script:InsufficientVMSizes -join ";"
    $VMFamilyAndQuotaString = ""
    foreach ($key in $script:InsufficientVMFamilyAndQuota.Keys) {
        $VMFamilyAndQuotaString = $VMFamilyAndQuotaString + $key + ':' + [math]::Ceiling($script:InsufficientVMFamilyAndQuota.$key / 100) * 100 + ';'
    }

    $sql = "
    SELECT * FROM SubscriptionScanResults
    WHERE SubscriptionId = @subscriptionId"

    $parameters = @{"@subscriptionId" = $subID }
    $result = QuerySql $connection $sql $parameters
    if ($result) {
        Write-LogInfo "$subID exists in db. Updating the record with latest scan result VMs: $InsufficientVMSizeString"
        $sql = "
        UPDATE SubscriptionScanResults
        SET InsufficientVMs=@InsufficientVMs, VMFamilyAndQuota=@VMFamilyAndQuota
        WHERE SubscriptionId=@subscriptionId"
    }
    else {
        Write-LogInfo "$subID doesn't exist. Inserting new record with latest scan result VMs: $InsufficientVMSizeString"
        $sql = "
        INSERT INTO SubscriptionScanResults(SubscriptionId, InsufficientVMs, VMFamilyAndQuota)
        VALUES (@subscriptionId, @InsufficientVMs, @VMFamilyAndQuota)"
    }
    $parameters = @{"@subscriptionId" = $subID; "@InsufficientVMs" = $InsufficientVMSizeString; "@VMFamilyAndQuota" = $VMFamilyAndQuotaString }
    ExecuteSql $connection $sql $parameters
}
catch {
    $line = $_.InvocationInfo.ScriptLineNumber
    $script_name = ($_.InvocationInfo.ScriptName).Replace($PWD, ".")
    $ErrorMessage = $_.Exception.Message
    Write-LogErr "$ErrorMessage [SOURCE] Line $line in script $script_name."
    $exitCode = 1
}
finally {
    if ($null -ne $connection) {
        Write-LogInfo "Closing DB server connection..."
        $connection.Close()
        $connection.Dispose()
    }

    Get-Job | Remove-Job -Force
    exit $exitCode
}