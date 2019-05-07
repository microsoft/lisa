[CmdletBinding()]
Param(
    $ARMVMImage = "",
    $Region = "",
    $VMsize = "",
    $CustomVHD,
    $GuestOSType = "",
    $StorageAccountName = "",
    $DiskType = "",
    $VMName = "",
    $NumberOfVMs = 1,
    $NICsForEachVM = 1,
    $Networking = "",
    $DataDisks = 0,
    $DataDiskSizeGB = "",
    $DataDiskCaching = "",
    $Username = "",
    $Password = "",
    $AutoCleanup = "",
    $GuestVMOperations = "",
    $ExecuteShellScript = "",
    $TiPCluster = "",
    $TipSessionID = "",
    $customSecretsFilePath = ""
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

    $GuestOSType = "Linux"
    if ($GuestOSType -eq "Windows") {
        $ConnectionPort = 3389
        $ConnectionPortName = "RDP"
    }
    elseif ($GuestOSType -eq "Linux") {
        $ConnectionPort = 22
        $ConnectionPortName = "SSH"
    }

    if ($DataDisks -gt 0) {
        $CUSTOM_DISKS = $null
        for ( $i = 0; $i -lt $DataDisks; $i++ ) {
            $CUSTOM_DISKS += $SingleDataDisk.Replace("DISK_NUMBER", "$i").Replace("DISK_SIZE", "$($DataDiskSizeGB)").Replace("DISK_CACHING", "$DataDiskCaching") + "`n"
        }
    }
    else {
        $CUSTOM_DISKS = ""
    }

    if ($NumberOfVMs -eq 1) {
        $CUSTOM_ENDPOINTS = $SinglePort.Replace("PORT_NAME", "$ConnectionPortName").Replace("PORT_TYPE", "tcp").Replace("LOCAL_PORT", "$ConnectionPort").Replace("PUBLIC_PORT", "$ConnectionPort")
        $CUSTOM_VMS = $SingleVM.Replace("CUSTOM_ENDPOINTS", "$CUSTOM_ENDPOINTS")
        $CUSTOM_VMS = $CUSTOM_VMS.Replace("CUSTOM_DISKS", "$CUSTOM_DISKS")
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
            $CurrentVM = $CurrentVM.Replace("CUSTOM_DISKS", "$CUSTOM_DISKS")
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
    .\Run-LisaV2.ps1 `
        -TestPlatform Azure `
        -TestLocation $Region `
        -ARMImageName $ARMVMImage `
        -StorageAccount $StorageAccountName `
        -RGIdentifier $VMName `
        -TestNames "TOOL-DEPLOYMENT-PROVISION" `
        -XMLSecretFile $customSecretsFilePath `
        -ResourceCleanup Keep `
        -CustomParameters "Networking=$Networking;DiskType=$DiskType"
}
catch {
    $ErrorMessage = $_.Exception.Message
    Write-Host "EXCEPTION : $ErrorMessage"
}
finally {
    Copy-Item -Path "$customSecretsFilePath.backup" -Destination "$customSecretsFilePath" -Force
}