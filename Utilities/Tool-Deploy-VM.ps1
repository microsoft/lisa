[CmdletBinding()]
Param(
    [Parameter(Mandatory=$true)]
    [String] $customSecretsFilePath,

    # Provide ARMVMImage / CustomVHD.
    [String] $ARMVMImage,
    [String] $CustomVHD,

    [Parameter(Mandatory=$true)]
    [String] $Region,
    [Parameter(Mandatory=$true)]
    [String] $VMsize = "",

    [Parameter(Mandatory=$true)]
    [ValidateSet("Linux","Windows")]
    [String] $GuestOSType = "",

    [String] $StorageAccountName = "",

    [Parameter(Mandatory=$true)]
    [ValidateSet("Managed","Unmanaged")]
    [String] $DiskType,

    [Parameter(Mandatory=$true)]
    [String] $VMName,

    [ValidateRange(1,1024)]
    [Int] $NumberOfVMs,

    [ValidateRange(1,8)]
    [Int] $NICsForEachVM,

    [Parameter(Mandatory=$true)]
    [ValidateSet("Synthetic","SRIOV")]
    [String] $Networking,

    [ValidateRange(1,64)]
    [Int] $DataDisks,

    [ValidateRange(1,4096)]
    [Int] $DataDiskSizeGB,

    [ValidateSet("None","ReadWrite","SRIOV")]
    [String] $DataDiskCaching,

    # Guest VM Username and Password
    [Parameter(Mandatory=$true)]
    [String] $Username,
    [Parameter(Mandatory=$true)]
    [String] $Password,

    [String] $AutoCleanup,
    [String] $TiPCluster,
    [String] $TipSessionID
)
try {
    #Make a backup of XML files.

    if ($Username -and $Password) {
        # Create a backup of secret file before injecting custom username and password.
        Copy-Item -Path $customSecretsFilePath -Destination "$customSecretsFilePath.backup" -Force

        $XmlSecrets = [xml](Get-Content -Path $customSecretsFilePath)
        $XmlSecrets.secrets.linuxTestUsername = $Username
        $XmlSecrets.secrets.linuxTestPassword = $Password
        $XmlSecrets.Save($customSecretsFilePath)
    } else {
        Throw "Please provide -Username and -Password"
    }

    $SetupTypeName = "Deploy$NumberOfVMs`VM"

    $TestDefinition = '
    <TestCases>
        <test>
            <TestName>TOOL-DEPLOYMENT-PROVISION</TestName>
            <testScript>TOOL-DEPLOYMENT-PROVISION.ps1</testScript>
            <files></files>
            <setupType>SETUP_TYPE_NAME</setupType>
            <Platform>Azure,HyperV</Platform>
            <Category>Tool</Category>
            <Area>DEPLOYVM</Area>
            <TestParameters>
                <param>AutoCleanup=AUTO_CLEANUP</param>
            </TestParameters>"
            <Tags>provision</Tags>
            <Priority>0</Priority>
        </test>
    </TestCases>
    '
    $SetupTypeDefinition = '
    <TestSetup>
        <SETUP_TYPE_NAME>
            <isDeployed>NO</isDeployed>
            <ResourceGroup>
                CUSTOM_VMS
            </ResourceGroup>
        </SETUP_TYPE_NAME>
    </TestSetup>'

    $SingleDataDisk = '
                <DataDisk>
                    <LUN>DISK_NUMBER</LUN>
                    <DiskSizeInGB>DISK_SIZE</DiskSizeInGB>
                    <HostCaching>DISK_CACHING</HostCaching>
                </DataDisk>'
    $SinglePort = '
                <EndPoints>
                    <Name>PORT_NAME</Name>
                    <Protocol>PORT_TYPE</Protocol>
                    <LocalPort>LOCAL_PORT</LocalPort>
                    <PublicPort>PUBLIC_PORT</PublicPort>
                </EndPoints>'
    $SingleVM = '
            <VirtualMachine>
                <state></state>
                <InstanceSize>VM_SIZE</InstanceSize>
                <ARMInstanceSize>VM_SIZE</ARMInstanceSize>
                <RoleName>VM_NAME</RoleName>
                CUSTOM_ENDPOINTS
                CUSTOM_DISKS
                <ExtraNICs>EXTRA_NICS</ExtraNICs>
            </VirtualMachine>'

    if ($GuestOSType -eq "Windows") {
        $ConnectionPort = 3389
        $ConnectionPortName = "RDP"
    }
    elseif ($GuestOSType -eq "Linux") {
        $ConnectionPort = 22
        $ConnectionPortName = "SSH"
    }

    if ($DataDisks -gt 0) {
        $CustomDisksXmlString = $null
        for ( $i = 0; $i -lt $DataDisks; $i++ ) {
            $CustomDisksXmlString += $SingleDataDisk.Replace("DISK_NUMBER", "$i").Replace("DISK_SIZE", "$($DataDiskSizeGB)").Replace("DISK_CACHING", "$DataDiskCaching") + "`n"
        }
    }
    else {
        $CustomDisksXmlString = ""
    }

    if ($NumberOfVMs -eq 1) {
        $CUSTOM_ENDPOINTS = $SinglePort.Replace("PORT_NAME", "$ConnectionPortName").Replace("PORT_TYPE", "tcp").Replace("LOCAL_PORT", "$ConnectionPort").Replace("PUBLIC_PORT", "$ConnectionPort")
        $CUSTOM_VMS = $SingleVM.Replace("CUSTOM_ENDPOINTS", "$CUSTOM_ENDPOINTS")
        $CUSTOM_VMS = $CUSTOM_VMS.Replace("CUSTOM_DISKS", "$CustomDisksXmlString")
        $CUSTOM_VMS = $CUSTOM_VMS.Replace("EXTRA_NICS", "$($NICsForEachVM -1)")
        $CUSTOM_VMS = $CUSTOM_VMS.Replace("VM_NAME", "$VMName")
        $CUSTOM_VMS = $CUSTOM_VMS.Replace("VM_SIZE", "$VMSize")
    }
    else {
        $CUSTOM_VMS = ""
        $StartPort = 1111
        for ($j = 1; $j -le $NumberOfVMs; $j++ ) {
            $CurrentVM = $SingleVM
            $CUSTOM_ENDPOINTS = $SinglePort.Replace("PORT_NAME", "$ConnectionPortName").Replace("PORT_TYPE", "tcp").Replace("LOCAL_PORT", "$ConnectionPort").Replace("PUBLIC_PORT", "$StartPort")
            $StartPort += 1
            $CurrentVM = $CurrentVM.Replace("CUSTOM_DISKS", "$CustomDisksXmlString")
            $CurrentVM = $CurrentVM.Replace("EXTRA_NICS", "$($NICsForEachVM - 1)")
            $CurrentVM = $CurrentVM.Replace("VM_SIZE", "$VMSize")
            $CurrentVM = $CurrentVM.Replace("CUSTOM_ENDPOINTS", "$CUSTOM_ENDPOINTS")
            $CurrentVM = $CurrentVM.Replace("VM_NAME", "$VMName-$j")
            $CUSTOM_VMS += $CurrentVM
        }
    }

    # Write the Tool-Deploy-VM TestDefition
    $TestDefinition = $TestDefinition.Replace('SETUP_TYPE_NAME',$SetupTypeName)
    $TestDefinition = $TestDefinition.Replace('AUTO_CLEANUP',$AutoCleanup)
    Set-Content -Value $TestDefinition -Path .\XML\TestCases\Tool-Deploy-VM.xml -Force

    # Write the Tool-Deploy-VM SetupTypeDefition
    $SetupTypeDefinition = $SetupTypeDefinition.Replace("CUSTOM_VMS", "$CUSTOM_VMS")
    $SetupTypeDefinition = $SetupTypeDefinition.Replace("SETUP_TYPE_NAME", $SetupTypeName)
    Set-Content -Value $SetupTypeDefinition -Path .\XML\VMConfigurations\Tool-Deploy-VM.xml -Force

    # Start the LISAv2 Test with ResourceCleanup = Keep
    $Command = ".\Run-LisaV2.ps1"
    $Command += " -TestPlatform Azure"
    $Command += " -TestLocation '$Region'"
    $Command += " -ARMImageName '$ARMVMImage'"
    $Command += " -StorageAccount '$StorageAccountName'"
    $Command += " -RGIdentifier '$VMName'"
    $Command += " -TestNames 'TOOL-DEPLOYMENT-PROVISION'"
    $Command += " -XMLSecretFile '$customSecretsFilePath'"
    $Command += " -ResourceCleanup Keep"
    if ($TiPCluster -and $TipSessionID) {
        $Command += " -CustomParameters 'Networking=$Networking;DiskType=$DiskType;OSType=$GuestOSType'"
    } else {
        $Command += " -CustomParameters 'Networking=$Networking;DiskType=$DiskType;OSType=$GuestOSType;TiPCluster=$TiPCluster;TipSessionId=$TipSessionID'"
    }
    Invoke-Expression -Command $Command
}
catch {
    $ErrorMessage = $_.Exception.Message
    Write-Host "EXCEPTION (Tool-Deploy-VM) : $ErrorMessage"
}
finally {
    Move-Item -Path "$customSecretsFilePath.backup" -Destination "$customSecretsFilePath" -Force
    Remove-Item -Path .\XML\TestCases\Tool-Deploy-VM.xml -Force -ErrorAction SilentlyContinue
    Remove-Item -Path .\XML\VMConfigurations\Tool-Deploy-VM.xml -Force -Force -ErrorAction SilentlyContinue
}