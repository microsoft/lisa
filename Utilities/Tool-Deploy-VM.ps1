[CmdletBinding()]
Param(
    # [Required]
    $ARMVMImage = "",
    $RegionVMsize = "",
    $CustomVHD,
    $GuestOSType = "",
    $StorageAccountName = "",
    $UseManagedDisk = "",
    $VMName = "",
    $NumberOfVMs = 1,
    $NICsForEachVM = 1,
    $AcceleratedNetworking_SRIOV = "",
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
    Copy-Item -Path .\XML\TestCases\FunctionalTests.xml -Destination .\XML\TestCases\FunctionalTests.xml.backup -Force
    Copy-Item -Path .\XML\VMConfigurations\OneVM.xml -Destination .\XML\VMConfigurations\OneVM.xml.backup -Force
    Copy-Item -Path $customSecretsFilePath -Destination "$customSecretsFilePath.backup" -Force

    $Location = $RegionVMsize.Split(" ")[0]
    $VMSize = $RegionVMsize.Split(" ")[1]

    $SetupTypeName = "Deploy$NumberOfVMs`VM"

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

    $SingleResourceGroup = '
    <CUSTOM_RG>
        <isDeployed>NO</isDeployed>
        <ResourceGroup>
            CUSTOM_VMS
        </ResourceGroup>
    </CUSTOM_RG>'

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
    $VMSize = $RegionVMsize.Split(" ")[1]
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

    $CUSTOM_RGS = $SingleResourceGroup.Replace("CUSTOM_VMS", "$CUSTOM_VMS")
    $CUSTOM_RGS = $CUSTOM_RGS.Replace("CUSTOM_RG", $SetupTypeName)
    $VMConfigurations = (Get-Content .\XML\VMConfigurations\OneVM.xml)
    $VMConfigurations = $VMConfigurations.Replace('</OneVM>', "</OneVM>$CUSTOM_RGS")
    Set-Content -Value $VMConfigurations -Path .\XML\VMConfigurations\OneVM.xml -Force

    $FunctionalTests = (Get-Content .\XML\TestCases\FunctionalTests.xml)
    $FunctionalTests = $FunctionalTests.Replace('>OneVM<', ">$SetupTypeName<")
    $FunctionalTests = $FunctionalTests.Replace('VERIFY-DEPLOYMENT-PROVISION', "TOOL-DEPLOYMENT-PROVISION")
    $TestParameters = "<testScript>TOOL-DEPLOYMENT-PROVISION.ps1</testScript>
    <TestParameters>
        <param>AutoCleanup=$AutoCleanup</param>
    </TestParameters>"
    $FunctionalTests = $FunctionalTests.Replace('<testScript>TOOL-DEPLOYMENT-PROVISION.ps1</testScript>', $TestParameters)

    Set-Content -Value $FunctionalTests -Path .\XML\TestCases\FunctionalTests.xml -Force
    $XmlSecrets = [xml](Get-Content -Path $customSecretsFilePath)
    $XmlSecrets.secrets.linuxTestUsername = $Username
    $XmlSecrets.secrets.linuxTestPassword = $Password
    $XmlSecrets.Save($customSecretsFilePath)

    .\Run-LisaV2.ps1 `
        -TestPlatform Azure `
        -TestLocation $Location `
        -ARMImageName $ARMVMImage `
        -StorageAccount $StorageAccountName `
        -RGIdentifier $VMName `
        -TestNames "TOOL-DEPLOYMENT-PROVISION" `
        -XMLSecretFile $customSecretsFilePath `
        -ResourceCleanup Keep
}
catch {
    $ErrorMessage = $_.Exception.Message
    Write-Host "EXCEPTION : $ErrorMessage"
}
finally {
    Copy-Item -Path .\XML\TestCases\FunctionalTests.xml.backup -Destination .\XML\TestCases\FunctionalTests.xml -Force
    Copy-Item -Path .\XML\VMConfigurations\OneVM.xml.backup -Destination .\XML\VMConfigurations\OneVM.xml -Force
    Copy-Item -Path "$customSecretsFilePath.backup" -Destination "$customSecretsFilePath" -Force
}