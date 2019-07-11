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
    cp "$1" /root/initr/boot.img
    cd /root/initr/

    img_type=$(file boot.img)
    LogMsg "The image type is: $img_type"
}

SearchModules()
{
    LogMsg "Searching for modules..."
    if [[ -d "/root/initr/usr/lib/modules" ]]; then
        abs_path="/root/initr/usr/lib/modules/"
    elif [[ -d "/root/initr/lib/modules" ]]; then
        abs_path="/root/initr/lib/modules/"
    elif [[ -d "/usr/lib64/modules" ]]; then
        abs_path="/usr/lib64/modules/"
    fi
    if [[ $DISTRO == "suse_12" ]]; then
        abs_path="/lib/modules/"
    fi
    for module in "${hv_modules[@]}"; do
        grep -i "$module" $abs_path*/modules.dep
        if [ $? -eq 0 ]; then
            LogMsg "Module $module was found in initrd."
            echo "Module $module was found in initrd." >> /root/summary.log
        else
            LogMsg "Module $module was NOT found."
            echo "Module $module was NOT found." >> /root/summary.log
            grep -i "$module" $abs_path*/modules.dep >> /root/summary.log
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
config_path="/boot/config-$(uname -r)"
if [[ $(detect_linux_distribution) == 'coreos' ]]; then
    config_path="/usr/lib/kernel/config-$(uname -r)"
fi
declare -A config_modulesDic
config_modulesDic=(
[CONFIG_HYPERV=y]="hv_vmbus.ko"
[CONFIG_HYPERV_STORAGE=y]="hv_storvsc.ko"
[CONFIG_HYPERV_NET=y]="hv_netvsc.ko"
)
for key in $(echo ${!config_modulesDic[*]})
do
    module_included=$(grep $key "$config_path")
    if [ "$module_included" ]; then
        skip_modules+=("${config_modulesDic[$key]}")
        LogMsg "Info: Skiping ${config_modulesDic[$key]} module as it is built-in."
    fi
done

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
    LogMsg "hv_vmbus.ko, hv_storvsc.ko and hv_netvsc.ko modules are built-in, skip test"
    SetTestStateSkipped
    exit 0
fi

GetDistro
case $DISTRO in
    centos_6 | redhat_6)
        update_repos
        install_package dracut-network
        dracut -f
        if [ "$?" = "0" ]; then
            LogMsg "Info: dracut -f ran successfully"
        else
            LogErr "Error: dracut -f fails to execute"
            SetTestStateAborted
            exit 1
        fi
    ;;
    ubuntu* | debian*)
        update_repos
        # Provides skipcpio binary
        install_package dracut-core
    ;;
esac

if [ -f /boot/initramfs-0-rescue* ]; then
    img=$(find /boot -name "initramfs-0-rescue*" | head -1)
else
  if [ -f "/boot/initrd-$(uname -r)" ]; then
    img="/boot/initrd-$(uname -r)"
  fi

  if [ -f "/boot/initramfs-$(uname -r).img" ]; then
    img="/boot/initramfs-$(uname -r).img"
  fi

  if [ -f "/boot/initrd.img-$(uname -r)" ]; then
    img="/boot/initrd.img-$(uname -r)"
  fi
fi

UpdateSummary "The initrd test image is: $img"

CopyImage "$img"

LogMsg "Unpacking the image..."

case $img_type in
    *ASCII*cpio*)
        cpio -id -F boot.img &> out.file
        skip_block_size=$(cat out.file | awk '{print $1}')
        dd if=boot.img of=finalInitrd.img bs=512 skip="$skip_block_size"
        /usr/lib/dracut/skipcpio finalInitrd.img |zcat| cpio -id --no-absolute-filenames
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