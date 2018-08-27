#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

CopyImage()
{
    if [ -d /root/initr ]; then
        LogMsg "Deleting old temporary rescue directory."
        rm -rf /root/initr/
    fi

    mkdir /root/initr
    cp $1 /root/initr/boot.img
    cd /root/initr/

    img_type=`file boot.img`
    LogMsg "The image type is: $img_type"
}

SearchModules()
{
    LogMsg "Searching for modules..."
    [[ -d "/root/initr/usr/lib/modules" ]] && abs_path="/root/initr/usr/lib/modules/" || abs_path="/root/initr/lib/modules/"
    for module in "${hv_modules[@]}"; do
        grep -i $module $abs_path*/modules.dep
        if [ $? -eq 0 ]; then
            LogMsg "Module $module was found in initrd."
            echo "Module $module was found in initrd." >> /root/summary.log
        else
            LogMsg "Module $module was NOT found."
            echo "Module $module was NOT found." >> /root/summary.log
            grep -i $module $abs_path*/modules.dep >> /root/summary.log
            SetTestStateFailed
            exit 1
        fi
    done
}

. utils.sh || {
    echo "Error: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 1
}

UtilsInit

hv_modules=()
if [ ! -d /sys/firmware/efi ]; then
    index=${!gen1_hv_modules[@]}
    n=0
    for n in $index
    do
        hv_modules[$n]=${gen1_hv_modules[$n]}
    done

else
    index=${!gen2_hv_modules[@]}
    n=0
    for n in $index
    do
        hv_modules[$n]=${gen2_hv_modules[$n]}
    done
fi

# Rebuild array to exclude built-in modules
skip_modules=()

vmbusIncluded=`grep CONFIG_HYPERV=y /boot/config-$(uname -r)`
if [ $vmbusIncluded ]; then
    skip_modules+=("hv_vmbus.ko")
    LogMsg "hv_vmbus module is built-in. Skipping module. "
fi
storvscIncluded=`grep CONFIG_HYPERV_STORAGE=y /boot/config-$(uname -r)`
if [ $storvscIncluded ]; then
    skip_modules+=("hv_storvsc.ko")
    LogMsg "hv_storvsc module is built-in. Skipping module. "
fi
netvscIncluded=`grep CONFIG_HYPERV_NET=y /boot/config-$(uname -r)`
if [ $netvscIncluded ]; then
    skip_modules+=("hv_netvsc.ko")
    LogMsg "hv_netvsc module is built-in. Skipping module. "
fi

# declare temporary array
tempList=()

# remove each module in skip_modules from hv_modules
for module in "${hv_modules[@]}"; do
    skip=""
    for modSkip in "${skip_modules[@]}"; do
        [[ $module == $modSkip ]] && { skip=1; break; }
    done
    [[ -n $skip ]] || tempList+=("$module")
done
hv_modules=("${tempList[@]}")

if [ "${hv_modules:-UNDEFINED}" = "UNDEFINED" ]; then
    LogErr "The test parameter hv_modules is not defined in constants file."
    SetTestStateAborted
    exit 0
fi

if [[ $DISTRO == "redhat_6" ]]; then
    yum_install -y dracut-network
    dracut -f
    if [ "$?" = "0" ]; then
        LogMsg "dracut -f ran successfully"
    else
        LogErr "dracut -f fails to execute"
        SetTestStateAborted
        exit 0
    fi
fi

if [ -f /boot/initramfs-0-rescue* ]; then
    img=/boot/initramfs-0-rescue*
else
  if [ -f "/boot/initrd-`uname -r`" ]; then
    img="/boot/initrd-`uname -r`"
  fi

  if [ -f "/boot/initramfs-`uname -r`.img" ]; then
    img="/boot/initramfs-`uname -r`.img"
  fi

  if [ -f "/boot/initrd.img-`uname -r`" ]; then
    img="/boot/initrd.img-`uname -r`"
  fi
fi

UpdateSummary "The initrd test image is: $img"

CopyImage $img

LogMsg "Unpacking the image..."

case $img_type in
    *ASCII*cpio*)
        /usr/lib/dracut/skipcpio boot.img |zcat| cpio -id --no-absolute-filenames
        if [ $? -eq 0 ]; then
            LogMsg "Successfully unpacked the image."
        else
            LogErr "Failed to unpack the initramfs image."
            SetTestStateFailed
            exit 0
        fi
    ;;
    *gzip*)
        gunzip -c boot.img | cpio -i -d -H newc --no-absolute-filenames
        if [ $? -eq 0 ]; then
            LogMsg "Successfully unpacked the image."
        else
            LogErr "Failed to unpack the initramfs image with gunzip."
            SetTestStateFailed
            exit 0
        fi
    ;;
    *XZ*)
        xzcat boot.img | cpio -i -d -H newc --no-absolute-filenames
        if [ $? -eq 0 ]; then
            LogMsg "Successfully unpacked the image."
        else
            LogErr "Failed to unpack the initramfs image with xzcat."
            SetTestStateFailed
            exit 0
        fi
    ;;
esac

SearchModules

SetTestStateCompleted
exit 0
