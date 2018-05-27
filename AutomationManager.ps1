##############################################################################################
# AzureAutomationManager.ps1
# Description : This script manages all the setup and test operations in Azure environemnt.
#               It is an entry script of Azure Automation
# Operations :
#              - Installing AzureSDK
#              - VHD preparation : Installing packages required by ICA, LIS drivers and waagent
#              - Uplaoding test VHD to cloud
#              - Invokes azure test suite
## Author : v-shisav@microsoft.com
## Author : v-ampaw@microsoft.com
###############################################################################################
param (
[CmdletBinding()]
[string] $xmlConfigFile,
[switch] $eMail,
[string] $logFilename="azure_ica.log",
[switch] $runtests, [switch]$onCloud,
[switch] $vhdprep,
[switch] $upload,
[switch] $help,
[string] $RGIdentifier,
[string] $cycleName,
[string] $RunSelectedTests,
[string] $TestPriority,
[string] $osImage,
[switch] $EconomyMode,
[switch] $KeepReproInact,
[string] $DebugDistro,
[switch] $UseAzureResourceManager,
[string] $OverrideVMSize,
[switch] $EnableAcceleratedNetworking,
[string] $CustomKernel,
[string] $CustomLIS,
[string] $customLISBranch,
[string] $resizeVMsAfterDeployment,
[string] $ExistingResourceGroup,
[switch] $CleanupExistingRG,
[string] $XMLSecretFile,

# Experimental Feature
[switch] $UseManagedDisks,

[int] $CoreCountExceededTimeout = 3600,
[int] $TestIterations = 1,
[string] $TiPSessionId="",
[string] $TiPCluster="",
[switch] $ForceDeleteResources
)
Get-ChildItem .\Libraries -Recurse | Where-Object { $_.FullName.EndsWith(".psm1") } | ForEach-Object { Import-Module $_.FullName -Force -Global}

$xmlConfig = [xml](Get-Content $xmlConfigFile)
$user = $xmlConfig.config.Azure.Deployment.Data.UserName
$password = $xmlConfig.config.Azure.Deployment.Data.Password
$sshKey = $xmlConfig.config.Azure.Deployment.Data.sshKey
$sshPublickey = $xmlConfig.config.Azure.Deployment.Data.sshPublicKey

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

Set-Variable -Name global4digitRandom -Value $(Get-Random -SetSeed $(Get-Random) -Maximum 9999 -Minimum 1111) -Scope Global
Set-Variable -Name CoreCountExceededTimeout -Value $CoreCountExceededTimeout -Scope Global

if($EnableAcceleratedNetworking)
{
    Set-Variable -Name EnableAcceleratedNetworking -Value $true -Scope Global
}

if($ForceDeleteResources)
{
    Set-Variable -Name ForceDeleteResources -Value $true -Scope Global
}
if($resizeVMsAfterDeployment)
{
    Set-Variable -Name resizeVMsAfterDeployment -Value $resizeVMsAfterDeployment -Scope Global
}

if ( $OverrideVMSize )
{
    Set-Variable -Name OverrideVMSize -Value $OverrideVMSize -Scope Global
}
if ( $CustomKernel )
{
    Set-Variable -Name CustomKernel -Value $CustomKernel -Scope Global
}
if ( $CustomLIS )
{
    Set-Variable -Name CustomLIS -Value $CustomLIS -Scope Global
}
if ( $customLISBranch )
{
    Set-Variable -Name customLISBranch -Value $customLISBranch -Scope Global
}
if ( $RunSelectedTests )
{
    Set-Variable -Name RunSelectedTests -Value $RunSelectedTests -Scope Global
}
if ($ExistingResourceGroup)
{
    Set-Variable -Name ExistingRG -Value $ExistingResourceGroup -Scope Global
}
if ($CleanupExistingRG)
{
    Set-Variable -Name CleanupExistingRG -Value $true -Scope Global
}
else
{
    Set-Variable -Name CleanupExistingRG -Value $false -Scope Global
}
if ($UseManagedDisks)
{
    Set-Variable -Name UseManagedDisks -Value $true -Scope Global
}
else 
{
    Set-Variable -Name UseManagedDisks -Value $false -Scope Global    
}

if ( $XMLSecretFile )
{
    $xmlSecrets = ([xml](Get-Content $XMLSecretFile))
    Set-Variable -Value $xmlSecrets -Name xmlSecrets -Scope Global -Force 
    LogMsg "XmlSecrets set as global variable."
}
elseif ($env:Azure_Secrets_File)
{
    $xmlSecrets = ([xml](Get-Content $env:Azure_Secrets_File))
    Set-Variable -Value $xmlSecrets -Name xmlSecrets -Scope Global -Force 
    LogMsg "XmlSecrets set as global variable."
}

if ( $xmlConfig.config.Azure.General.ARMStorageAccount -imatch "NewStorage_" )
{
    $NewARMStorageAccountType = ($xmlConfig.config.Azure.General.ARMStorageAccount).Replace("NewStorage_","")
    Set-Variable -Name NewARMStorageAccountType -Value $NewARMStorageAccountType -Scope Global
}
try
{
    $Platform = $xmlConfig.config.CurrentTestPlatform

    if ( $Platform -eq "Azure" )
    {
        $testResults = "TestResults"
        if (! (test-path $testResults))
        {
            mkdir $testResults | out-null
        }
        if (! (test-path ".\report"))
        {
            mkdir ".\report" | out-null
        }        
        $testStartTime = [DateTime]::Now.ToUniversalTime()
        Set-Variable -Name testStartTime -Value $testStartTime -Scope Global
        $testDir = $testResults + "\" + $cycleName + "-" + $testStartTime.ToString("yyyyMMddHHmmssff")
        mkdir $testDir -ErrorAction SilentlyContinue | out-null
        Set-Content -Value "" -Path .\report\testSummary.html -Force -ErrorAction SilentlyContinue | Out-Null
        Set-Content -Value "" -Path .\report\AdditionalInfo.html -Force -ErrorAction SilentlyContinue | Out-Null
        $logFile = $testDir + "\" + "AzureLogs.txt"
        Set-Variable -Name logfile -Value $logFile -Scope Global
        Set-Variable -Name Distro -Value $RGIdentifier -Scope Global
        Set-Variable -Name onCloud -Value $onCloud -Scope Global
        Set-Variable -Name xmlConfig -Value $xmlConfig -Scope Global
        LogMsg = "'$testDir' saved to .\report\lastLogDirectory.txt"
        Set-Content -Path .\report\lastLogDirectory.txt -Value $testDir -Force
        Set-Variable -Name vnetIsAllConfigured -Value $false -Scope Global
        if($EconomyMode)
        {
            Set-Variable -Name EconomyMode -Value $true -Scope Global
            if($KeepReproInact)
            {
                Set-Variable -Name KeepReproInact -Value $true -Scope Global
            }
        }
        else
        {
            Set-Variable -Name EconomyMode -Value $false -Scope Global
            if($KeepReproInact)
            {
                Set-Variable -Name KeepReproInact -Value $true -Scope Global
            }
            else
            {
                Set-Variable -Name KeepReproInact -Value $false -Scope Global
            }
        }
        $AzureSetup = $xmlConfig.config.Azure.General
        LogMsg  ("Info : AzureAutomationManager.ps1 - LIS on Azure Automation")
        LogMsg  ("Info : Created test results directory:", $testDir)
        LogMsg  ("Info : Logfile = $logfile")
        LogMsg  ("Info : Using config file $xmlConfigFile")
        if ( ( $xmlConfig.config.Azure.General.ARMStorageAccount -imatch "ExistingStorage" ) -or ($xmlConfig.config.Azure.General.StorageAccount -imatch "ExistingStorage" ) )
        {
            $regionName = $xmlConfig.config.Azure.General.Location.Replace(" ","").Replace('"',"").ToLower()
            $regionStorageMapping = [xml](Get-Content .\XML\RegionAndStorageAccounts.xml)
    
            if ( $xmlConfig.config.Azure.General.ARMStorageAccount -imatch "standard")
            {
               $xmlConfig.config.Azure.General.ARMStorageAccount = $regionStorageMapping.AllRegions.$regionName.StandardStorage
               LogMsg "Info : Selecting existing standard storage account in $regionName - $($regionStorageMapping.AllRegions.$regionName.StandardStorage)"
            }
            if ( $xmlConfig.config.Azure.General.ARMStorageAccount -imatch "premium")
            {
               $xmlConfig.config.Azure.General.ARMStorageAccount = $regionStorageMapping.AllRegions.$regionName.PremiumStorage
               LogMsg "Info : Selecting existing premium storage account in $regionName - $($regionStorageMapping.AllRegions.$regionName.PremiumStorage)"
            }
        }
        Set-Variable -Name UseAzureResourceManager -Value $true -Scope Global
        $SelectedSubscription = Select-AzureRmSubscription -SubscriptionId $AzureSetup.SubscriptionID
        $subIDSplitted = ($SelectedSubscription.Subscription.SubscriptionId).Split("-")
        $userIDSplitted = ($SelectedSubscription.Account.Id).Split("-")
        LogMsg "SubscriptionName       : $($SelectedSubscription.Subscription.Name)"
        LogMsg "SubscriptionId         : $($subIDSplitted[0])-xxxx-xxxx-xxxx-$($subIDSplitted[4])"
        LogMsg "User                   : $($userIDSplitted[0])-xxxx-xxxx-xxxx-$($userIDSplitted[4])"
        LogMsg "ServiceEndpoint        : $($SelectedSubscription.Environment.ActiveDirectoryServiceEndpointResourceId)"
        LogMsg "CurrentStorageAccount  : $($AzureSetup.ARMStorageAccount)"
        if($KeepReproInact)
        {
            LogMsg "PLEASE NOTE: KeepReproInact is set. VMs will not be deleted after test is finished even if, test gets PASS."
        }
        
        if ($DebugDistro)
        {
            $OsImage = $xmlConfig.config.Azure.Deployment.Data.Distro | ? { $_.name -eq $DebugDistro} | % { $_.OsImage }
            Set-Variable -Name DebugOsImage -Value $OsImage -Scope Global
        }
        $testCycle =  GetCurrentCycleData -xmlConfig $xmlConfig -cycleName $cycleName
        $testSuiteResultDetails=.\AzureTestSuite.ps1 $xmlConfig -Distro $Distro -cycleName $cycleName -TestIterations $TestIterations
        $logDirFilename = [System.IO.Path]::GetFilenameWithoutExtension($xmlConfigFile)
        $summaryAll = GetTestSummary -testCycle $testCycle -StartTime $testStartTime -xmlFileName $logDirFilename -distro $Distro -testSuiteResultDetails $testSuiteResultDetails
        $PlainTextSummary += $summaryAll[0]
        $HtmlTextSummary += $summaryAll[1]
        Set-Content -Value $HtmlTextSummary -Path .\report\testSummary.html -Force | Out-Null
        $PlainTextSummary = $PlainTextSummary.Replace("<br />", "`r`n")
        $PlainTextSummary = $PlainTextSummary.Replace("<pre>", "")
        $PlainTextSummary = $PlainTextSummary.Replace("</pre>", "")
        LogMsg  "$PlainTextSummary"
        if($eMail)
        {
            SendEmail $xmlConfig -body $HtmlTextSummary
        }
    }
    else 
    {
        LogError "$Platform not supported."    
    }
}
catch
{
    ThrowException($_)
}
Finally
{
	exit
}