param (
    [string]$vendorId,
    [string]$deviceId
)

# Get PCI device information using PowerShell
#
# These variables are device properties.  For people who are very
# curious about this, you can download the Windows Driver Kit headers and
# look for pciprop.h.  All of these are contained in that file.
#
$devpkey_PciDevice_DeviceType = "{3AB22E31-8264-4b4e-9AF5-A8D2D8E33E62}  1"
$devpkey_PciDevice_BaseClass = "{3AB22E31-8264-4b4e-9AF5-A8D2D8E33E62}  3"
$devpkey_PciDevice_RequiresReservedMemoryRegion = "{3AB22E31-8264-4b4e-9AF5-A8D2D8E33E62}  34"
$devpkey_PciDevice_AcsCompatibleUpHierarchy = "{3AB22E31-8264-4b4e-9AF5-A8D2D8E33E62}  31"

$devprop_PciDevice_DeviceType_PciConventional                        =   0
$devprop_PciDevice_DeviceType_PciX                                   =   1
$devprop_PciDevice_DeviceType_PciExpressEndpoint                     =   2
$devprop_PciDevice_DeviceType_PciExpressLegacyEndpoint               =   3
$devprop_PciDevice_DeviceType_PciExpressRootComplexIntegratedEndpoint=   4
$devprop_PciDevice_DeviceType_PciExpressTreatedAsPci                 =   5
$devprop_PciDevice_BridgeType_PciConventional                        =   6
$devprop_PciDevice_BridgeType_PciX                                   =   7
$devprop_PciDevice_BridgeType_PciExpressRootPort                     =   8
$devprop_PciDevice_BridgeType_PciExpressUpstreamSwitchPort           =   9
$devprop_PciDevice_BridgeType_PciExpressDownstreamSwitchPort         =  10
$devprop_PciDevice_BridgeType_PciExpressToPciXBridge                 =  11
$devprop_PciDevice_BridgeType_PciXToExpressBridge                    =  12
$devprop_PciDevice_BridgeType_PciExpressTreatedAsPci                 =  13
$devprop_PciDevice_BridgeType_PciExpressEventCollector               =  14

$devprop_PciDevice_AcsCompatibleUpHierarchy_NotSupported             =   0
$devprop_PciDevice_AcsCompatibleUpHierarchy_SingleFunctionSupported  =   1
$devprop_PciDevice_AcsCompatibleUpHierarchy_NoP2PSupported           =   2
$devprop_PciDevice_AcsCompatibleUpHierarchy_Supported                =   3

#
# These values are defined in the PCI spec, and are also published in wdm.h
# of the Windows Driver Kit headers.
#
$devprop_PciDevice_BaseClass_DisplayCtlr                             =   3


function deviceListByVendorDeviceId {
    param(
        $vendorId,
        $deviceId
    )
    $deviceList = @()

    $PciDevices = Get-WmiObject Win32_PnPEntity | Where-Object {
        $_.DeviceID -match "VEN_$vendorId" -and $_.DeviceID -match "DEV_$deviceId"
    } | Select-Object -Property DeviceID, Description

    foreach ($Device in $PciDevices) { 
        $deviceList += $Device
    }
    return $deviceList
}

function isDDAEnabled {
    param(
        $pcidev
    )
    Write-Host "------------------------------------------------------------------"
    Write-Host -ForegroundColor White -BackgroundColor Black $pcidev.FriendlyName

    $rmrr =  ($pcidev | Get-PnpDeviceProperty $devpkey_PciDevice_RequiresReservedMemoryRegion).Data
    if ($rmrr -ne 0) {
        write-host -ForegroundColor Red -BackgroundColor Black "BIOS requires that this device remain attached to BIOS-owned memory.  Not assignable."
        return ""
    }

    $acsUp =  ($pcidev | Get-PnpDeviceProperty $devpkey_PciDevice_AcsCompatibleUpHierarchy).Data
    if ($acsUp -eq $devprop_PciDevice_AcsCompatibleUpHierarchy_NotSupported) {
        write-host -ForegroundColor Red -BackgroundColor Black "Traffic from this device may be redirected to other devices in the system.  Not assignable."
        return ""
    }

    $devtype = ($pcidev | Get-PnpDeviceProperty $devpkey_PciDevice_DeviceType).Data
    if ($devtype -eq $devprop_PciDevice_DeviceType_PciExpressEndpoint) {
        Write-Host "Express Endpoint -- more secure."
    } else {
        if ($devtype -eq $devprop_PciDevice_DeviceType_PciExpressRootComplexIntegratedEndpoint) {
            Write-Host "Embedded Endpoint -- less secure."
        } elseif ($devtype -eq $devprop_PciDevice_DeviceType_PciExpressLegacyEndpoint) {
            $devBaseClass = ($pcidev | Get-PnpDeviceProperty $devpkey_PciDevice_BaseClass).Data

            if ($devBaseClass -eq $devprop_PciDevice_BaseClass_DisplayCtlr) {
                Write-Host "Legacy Express Endpoint -- graphics controller."
            } else {
                Write-Host -ForegroundColor Red -BackgroundColor Black "Legacy, non-VGA PCI device.  Not assignable."
                return ""
            }
        } else {
            if ($devtype -eq $devprop_PciDevice_DeviceType_PciExpressTreatedAsPci) {
                Write-Host -ForegroundColor Red -BackgroundColor Black "BIOS kept control of PCI Express for this device.  Not assignable."
            } else {
                Write-Host -ForegroundColor Red -BackgroundColor Black "Old-style PCI device, switch port, etc.  Not assignable."
            }
            return ""
        }
    }

    $locationpath = ($pcidev | get-pnpdeviceproperty DEVPKEY_Device_LocationPaths).data[0]

    #
    # If the device is disabled, we can't check the resources, report a warning and continue on.
    #
    #
    if ($pcidev.ConfigManagerErrorCode -eq "CM_PROB_DISABLED")
    {
        Write-Host -ForegroundColor Yellow -BackgroundColor Black "Device is Disabled, unable to check resource requirements, it may be assignable."
        Write-Host -ForegroundColor Yellow -BackgroundColor Black "Enable the device and rerun this script to confirm."
        $locationpath
        return ""
    }

    #
    # Now do a check for the interrupts that the device uses.  Line-based interrupts
    # aren't assignable.
    #
    $doubleslashDevId = "*" + $pcidev.PNPDeviceID.Replace("\","\\") + "*"
    $irqAssignments = gwmi -query "select * from Win32_PnPAllocatedResource" | Where-Object {$_.__RELPATH -like "*Win32_IRQResource*"} | Where-Object {$_.Dependent -like $doubleslashDevId}

    #$irqAssignments | Format-Table -Property __RELPATH

    if ($irqAssignments.length -eq 0) {
        Write-Host -ForegroundColor Green -BackgroundColor Black "    And it has no interrupts at all -- assignment can work."
    } else {
        #
        # Find the message-signaled interrupts.  They are reported with a really big number in
        # decimal, one which always happens to start with "42949...".
        #
        $msiAssignments = $irqAssignments | Where-Object {$_.Antecedent -like "*IRQNumber=42949*"}
    
        #$msiAssignments | Format-Table -Property __RELPATH

        if ($msiAssignments.length -eq 0) {
            Write-Host -ForegroundColor Red -BackgroundColor Black "All of the interrupts are line-based, no assignment can work."
            return ""
        } else {
            Write-Host -ForegroundColor Green -BackgroundColor Black "    And its interrupts are message-based, assignment can work."
        }
    }

    #
    # Check how much MMIO space the device needs
    # not strictly an issue devices, but very useful when you want to set MMIO gap sizes
    #

    $mmioAssignments = gwmi -query "select * from Win32_PnPAllocatedResource" | Where-Object {$_.__RELPATH -like "*Win32_DeviceMemoryAddress*"} | Where-Object {$_.Dependent -like $doubleslashDevId}
    $mmioTotal = 0
    foreach ($mem in $mmioAssignments) 
    {
        $baseAdd =$mem.Antecedent.SubString($mem.Antecedent.IndexOf("""")+1)
        $baseAdd=$baseAdd.SubString(0,$baseAdd.IndexOf(""""))
        $mmioRange = gwmi -query "select * from Win32_DeviceMemoryAddress" | Where-Object{$_.StartingAddress -like $baseAdd}
        $mmioTotal = $mmioTotal + $mmioRange.EndingAddress - $mmioRange.StartingAddress
    }
    if ($mmioTotal -eq 0)
    {
        Write-Host -ForegroundColor Green -BackgroundColor Black "    And it has no MMIO space"
    } else {
  	     [int]$mmioMB = [math]::ceiling($mmioTotal / 1MB)
        Write-Host -ForegroundColor Green -BackgroundColor Black "    And it requires at least:" $mmioMB "MB of MMIO gap space"
    }
    


    #
    # Print out the location path, as that's the way to refer to this device that won't
    # change even if you add or remove devices from the machine or change the way that
    # the BIOS is configured.
    #
    return  [PSCustomObject]@{
        deviceName = $pcidev.FriendlyName;
        locationPath = $locationpath;
        instanceId = $pcidev.InstanceId;
    }
}

function main {
    param(
        $vendorId,
        $deviceId
    )
    $device_list_raw = deviceListByVendorDeviceId -vendorId $vendorId -deviceId $deviceId

    $pnpdevs = Get-PnpDevice -PresentOnly
    $pcidevs = $pnpdevs | Where-Object {$_.InstanceId -like "PCI*"}

    $devices = @()
    foreach ($dev in $device_list_raw) {
        foreach ($pcidev in $pcidevs) {
            if ($pcidev.InstanceId -eq $dev.DeviceID){
                $result = isDDAEnabled -pcidev $pcidev
                if (-not [string]::IsNullOrEmpty($result)) {
                    # Add the result to the array
                    $devices += $result
                }
            }
        }
    }
    if ($devices.Count -eq 0) {
        Write-Output "The list is empty."
        exit 0
    } else {
        $csvString = $devices | ConvertTo-Csv -NoTypeInformation
        $csvString = $csvString[1..$csvString.Length] -join "`n"
        Write-Output "Assignable Devices Found: `n$csvString"
    }
}

main -vendorId $vendorId -deviceId $deviceId
