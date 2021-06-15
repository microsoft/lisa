#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

kdump_conf=/etc/kdump.conf
dump_path=/var/crash
kdump_sysconfig=/etc/sysconfig/kdump
boot_filepath=""
target_version=2.0.15
dnf_preview_repo="/etc/yum.repos.d/mariner-preview-update.repo"

#
# Source utils.sh to get more utils
# Get $DISTRO, LogMsg directly from utils.sh
#
. utils.sh || {
    echo "unable to source utils.sh!"
    exit 0
}

#
# Source constants file and initialize most common variables
#
UtilsInit

UpdateMarinerPreviewRepo() {
    echo "UpdateRepo:: Updating repository..."
cat > ${dnf_preview_repo} << 'EOF'
[mariner-preview-update]
name=CBL-Mariner Preview Update $releasever $basearch
baseurl=https://packages.microsoft.com/cbl-mariner/$releasever/preview/update/$basearch/rpms
gpgkey=file:///etc/pki/rpm-gpg/MICROSOFT-RPM-GPG-KEY file:///etc/pki/rpm-gpg/MICROSOFT-METADATA-GPG-KEY
gpgcheck=1
repo_gpgcheck=1
enabled=1
skip_if_unavailable=True
sslverify=1
EOF
    dnf clean all && dnf repolist --refresh
    return 0
}


Install_Kexec() {
    case $DISTRO in
        centos* | redhat* | fedora* | almalinux*)
            if [[ $DISTRO != "redhat_8" ]] && [[ $DISTRO != "centos_8" ]] && [[ $DISTRO != "almalinux_8" ]]; then
                yum_install "kexec-tools kdump-tools makedumpfile"
                if [ $? -ne 0 ]; then
                    UpdateSummary "Warning: Kexec-tools failed to install."
                fi
            fi
        ;;
        mariner*)
            [[ ! -f ${dnf_preview_repo} ]] && UpdateMarinerPreviewRepo
            install_package kexec-tools
        ;;
        ubuntu* | debian*)
            export DEBIAN_FRONTEND=noninteractive
            dpkg_configure
            apt-get update --fix-missing; apt --fix-broken install -y; apt_get_install "kexec-tools kdump-tools makedumpfile"
            if [ $? -ne 0 ]; then
                UpdateSummary "Warning: Kexec-tools failed to install."
            fi
            #Existed bug for kexec-tools https://bugs.launchpad.net/ubuntu/+source/kexec-tools/+bug/1713940
            if [[ "$DISTRO" == "ubuntu_14.04" || "$DISTRO_NAME" == "debian" ]]; then
                kexec_version=$(kexec --v | awk -F' ' '{print $2}')
                if version_gt "${target_version}" "${kexec_version}"; then
                    apt_get_install "make gcc"
                    wget "https://mirrors.edge.kernel.org/pub/linux/utils/kernel/kexec/kexec-tools-${kexecVersion}.tar.gz"
                    kexec_tar=$(find -name "kexec-tools*" -type f)
                    tar xf "${kexec_tar}"
                    kexec_folder=$(find -name "kexec-tools*" -type d)
                    pushd "${kexec_folder}" && ./configure && make && make install > /dev/null 2>&1
                    popd
                    yes | cp -f /usr/local/sbin/kexec /sbin/
                fi
            fi
        ;;
        suse*)
            zypper refresh; zypper_install "kexec-tools kdump makedumpfile"
            if [ $? -ne 0 ]; then
                UpdateSummary "Warning: Kexec-tools failed to install."
            fi
        ;;
        coreos*)
            LogMsg "Distro not supported. Skip the test."
            SetTestStateSkipped
            exit 0
        ;;
        *)
            LogErr "Warning: Distro '${distro}' not supported. Kexec-tools failed to install."
        ;;
    esac
}

Rhel_Extra_Settings() {
    LogMsg "Adding extra kdump parameters(Rhel)..."

    to_be_updated=(
            'core_collector makedumpfile'
            'disk_timeout'
            'blacklist'
            'extra_modules'
        )
    value=(
        '-c --message-level 1 -d 31'
        '100'
        'hv_vmbus hv_storvsc hv_utils hv_netvsc hid-hyperv hyperv_fb hyperv-keyboard'
        'ata_piix sr_mod sd_mod'
        )

    for (( item=0; item<${#to_be_updated[@]-1}; item++))
    do
        sed -i "s/${to_be_updated[item]}.*/#${to_be_updated[item]} ${value[item]}/g" $kdump_conf
        echo "${to_be_updated[item]} ${value[item]}" >> $kdump_conf
    done

    kdump_commandline=(
        'irqpoll'
        'maxcpus='
        'reset_devices'
        'ide_core.prefer_ms_hyperv='
    )
    value_kdump=(
        ''
        '1'
        ''
        '0'
    )

    kdump_commandline_arguments=$(grep KDUMP_COMMANDLINE_APPEND $kdump_sysconfig |  sed 's/KDUMP_COMMANDLINE_APPEND="//g' | sed 's/"//g')
    for (( item=0; item<${#kdump_commandline[@]-1}; item++))
    do
        if [ $? -eq 0 ]; then
            kdump_commandline_arguments=$(echo "${kdump_commandline_arguments}" | sed "s/${kdump_commandline[item]}\S*//g")
        fi
        kdump_commandline_arguments="$kdump_commandline_arguments ${kdump_commandline[item]}${value_kdump[item]}"
    done

    sed -i "s/KDUMP_COMMANDLINE_APPEND.*/KDUMP_COMMANDLINE_APPEND=\"$kdump_commandline_arguments\"/g" $kdump_sysconfig
}

Config_Rhel() {
    # Modifying kdump.conf settings
    LogMsg "Configuring kdump (Rhel)..."

    sed -i '/^path/ s/path/#path/g' $kdump_conf
    if [ $? -ne 0 ]; then
        LogErr "Failed to comment path in /etc/kdump.conf. Probably kdump is not installed."
        SetTestStateAborted
        exit 0
    else
        echo path $dump_path >> $kdump_conf
        LogMsg "Success: Updated the path to /var/crash."
    fi

    sed -i '/^default/ s/default/#default/g' $kdump_conf
    if [ $? -ne 0 ]; then
        LogErr "Failed to comment default behaviour in /etc/kdump_conf. Probably kdump is not installed."
        SetTestStateAborted
        exit 0
    else
        echo 'default reboot' >>  $kdump_conf
        UpdateSummary "Success: Updated the default behaviour to reboot."
    fi

    if [[ -z "$os_RELEASE" ]]; then
        GetOSVersion
    fi

    # Extra config for RHEL5 RHEL6.1 RHEL6.2
    if [[ $os_RELEASE.$os_UPDATE =~ ^5.* ]] || [[ $os_RELEASE.$os_UPDATE =~ ^6.[0-2][^0-9] ]] ; then
        Rhel_Extra_Settings
    # Extra config for WS2012 - RHEL6.3+
    elif [[ $os_RELEASE.$os_UPDATE =~ ^6.* ]] && [[ $BuildNumber == "9200" ]] ; then
        echo "extra_modules ata_piix sr_mod sd_mod" >> /etc/kdump.conf
        echo "options ata_piix prefer_ms_hyperv=0" >> /etc/kdump.conf
        echo "blacklist hv_vmbus hv_storvsc hv_utils hv_netvsc hid-hyperv" >> /etc/kdump.conf
        echo "disk_timeout 100" >> /etc/kdump.conf
    fi

    # Extra config for WS2012 - RHEL7
    if [[ $os_RELEASE.$os_UPDATE =~ ^7.* ]] && [[ $BuildNumber == "9200" ]] ; then
        echo "extra_modules ata_piix sr_mod sd_mod" >> /etc/kdump.conf
        echo "KDUMP_COMMANDLINE_APPEND=\"ata_piix.prefer_ms_hyperv=0 disk_timeout=100 rd.driver.blacklist=hv_vmbus,hv_storvsc,hv_utils,hv_netvsc,hid-hyperv,hyperv_fb\"" >> /etc/sysconfig/kdump
    fi

    GetGuestGeneration
    # centos 7 gen2 - /boot/efi/EFI/centos/grub.cfg
    distro=$(detect_linux_distribution)
    if [ "$os_GENERATION" -eq 2 ] && [[ $os_RELEASE =~ 6.* ]]; then
        boot_filepath=/boot/efi/EFI/BOOT/bootx64.conf
    elif [ "$os_GENERATION" -eq 1 ] && [[ $os_RELEASE =~ ^6.* ]]; then
        boot_filepath=/boot/grub/grub.conf
    elif [ "$os_GENERATION" -eq 1 ] && [[ $os_RELEASE =~ ^7.* ]]; then
        boot_filepath=/boot/grub2/grub.cfg
    elif [ "$os_GENERATION" -eq 1 ] && [[ $os_RELEASE =~ 8.* ]]; then
        boot_filepath=/boot/grub2/grubenv
    elif [ "$os_GENERATION" -eq 2 ] && [[ $os_RELEASE =~ 7.* || $os_RELEASE =~ 8.* ]]; then
        boot_filepath=/boot/efi/EFI/$distro/grub.cfg
    else
        boot_filepath=$(find /boot -name grub.cfg)
    fi

    # Enable kdump service
    LogMsg "Enabling kdump"

    chkconfig kdump on --level 35
    if [ $? -ne 0 ]; then
        LogErr "Failed to enable kdump."
        SetTestStateAborted
        exit 0
    else
        UpdateSummary "Success: kdump enabled."
    fi

    # Configure to dump file on nfs server if it is the case
    if [ "$vm2ipv4" ] && [ "$vm2ipv4" != "" ]; then
        yum_install nfs-utils
        if [ $? -ne 0 ]; then
            LogErr "Failed to install nfs."
            SetTestStateAborted
            exit 0
        fi
        # Kdump configuration differs from RHEL 6 to RHEL 7
        if [ "$os_RELEASE" -le 6 ]; then
            echo "nfs $vm2ipv4:/mnt" >> /etc/kdump.conf
            if [ $? -ne 0 ]; then
                LogErr "Failed to configure kdump to use nfs."
                SetTestStateAborted
                exit 0
            fi
        else
            echo "dracut_args --mount \"$vm2ipv4:/mnt /var/crash nfs defaults\"" >> /etc/kdump.conf
            if [ $? -ne 0 ]; then
                LogErr "Failed to configure kdump to use nfs."
                SetTestStateAborted
                exit 0
            fi
        fi

        service kdump restart
        if [ $? -ne 0 ]; then
            LogErr "Failed to restart Kdump."
            SetTestStateAborted
            exit 0
        fi
    fi
}

Config_Sles() {
    LogMsg "Configuring kdump (Sles)..."

    if [[ -d /boot/grub2 ]]; then
        boot_filepath='/boot/grub2/grub.cfg'
    elif [[ -d /boot/grub ]]; then
        boot_filepath='/boot/grub/menu.lst'
    fi

    LogMsg "Enabling kdump"

    chkconfig boot.kdump on
    if [ $? -ne 0 ]; then
        systemctl enable kdump.service
        if [ $? -ne 0 ]; then
            LogErr "FAILED to enable kdump."
            SetTestStateAborted
            exit 0
        else
            UpdateSummary "Success: kdump enabled."
        fi
    else
        UpdateSummary "Success: kdump enabled."
    fi

    if [ "$vm2ipv4" ] && [ "$vm2ipv4" != "" ]; then
        zypper_install nfs-client
        if [ $? -ne 0 ]; then
            LogErr "Failed to install nfs."
            SetTestStateAborted
            exit 0
        fi
        sed -i 's\KDUMP_SAVEDIR="/var/crash"\KDUMP_SAVEDIR="nfs://'"$vm2ipv4"':/mnt"\g' /etc/sysconfig/kdump
        service kdump restart
    fi
}

Config_Debian() {
    boot_filepath="/boot/grub/grub.cfg"
    LogMsg "Configuring kdump (Ubuntu)..."
    UpdateSummary "Configuring kdump (Ubuntu)..."
    sed -i 's/USE_KDUMP=0/USE_KDUMP=1/g' /etc/default/kdump-tools
    grep -q "USE_KDUMP=1" /etc/default/kdump-tools
    if [ $? -ne 0 ]; then
        LogErr "kdump-tools are not existent or cannot be modified."
        SetTestStateAborted
        exit 0
    fi

    # Additional params needed
    sed -i 's/LOAD_KEXEC=true/LOAD_KEXEC=false/g' /etc/default/kexec

    # Configure to dump file on nfs server if it is the case
    update_repos
    sleep 10

    if [ "$vm2ipv4" ] && [ "$vm2ipv4" != "" ]; then
        apt_get_install nfs-kernel-server
        if [ $? -ne 0 ]; then
            LogErr "Failed to install nfs."
            SetTestStateAborted
            exit 0
        fi

        apt_get_install nfs-common
        if [ $? -ne 0 ]; then
            LogErr "Failed to install nfs-common."
            SetTestStateAborted
            exit 0
        fi
        echo "NFS=\"$vm2ipv4:/mnt\"" >> /etc/default/kdump-tools
        service kexec restart
    fi
}

Config_mariner() {
    LogMsg "Configuring kdump (Mariner)..."

    sed -i '/^path/ s/path/#path/g' $kdump_conf
    if [ $? -ne 0 ]; then
        LogErr "Failed to comment path in /etc/kdump.conf. Probably kdump is not installed."
        SetTestStateAborted
        exit 0
    else
        echo path $dump_path >> $kdump_conf
        LogMsg "Success: Updated the path to /var/crash."
    fi

    sed -i '/^default/ s/default/#default/g' $kdump_conf
    if [ $? -ne 0 ]; then
        LogErr "Failed to comment default behaviour in /etc/kdump_conf. Probably kdump is not installed."
        SetTestStateAborted
        exit 0
    else
        echo 'default reboot' >>  $kdump_conf
        UpdateSummary "Success: Updated the default behaviour to reboot."
    fi

    boot_filepath="/boot/mariner.cfg"
    # Enable kdump service
    LogMsg "Enabling kdump"
    chkconfig kdump on --level 35
    if [ $? -ne 0 ]; then
        LogErr "Failed to enable kdump."
        SetTestStateAborted
        exit 0
    else
        UpdateSummary "Success: kdump enabled."
    fi
}

function version_gt() {
	test "$(printf '%s\n' "$@" | sort -V | head -n 1)" != "$1"
}

#######################################################################
#
# Main script body
#
#######################################################################

if [ "$crashkernel" == "" ];then
    LogErr "crashkernel parameter is null."
    SetTestStateAborted
    exit 0
fi
LogMsg "INFO: crashkernel=$crashkernel; vm2ipv4=$vm2ipv4"
#
# Checking the negotiated VMBus version
#
vmbus_string=$(dmesg | grep "Vmbus version:")

if [ "$vmbus_string" = "" ]; then
    LogMsg "WARNING: Negotiated VMBus version is not 3.0. Kernel might be old or patches not included."
    LogMsg "Test will continue but it might not work properly."
    UpdateSummary "WARNING: Full support for kdump is not present, test execution might not work as expected"
fi

GetDistro

Install_Kexec

#
# Configure kdump - this has distro specific behaviour
#
config_path=$(get_bootconfig_path)
if [[ $DISTRO != "redhat_8" ]];then
    if ! grep CONFIG_KEXEC_AUTO_RESERVE=y "$config_path" && [[ "$crashkernel" == "auto" ]];then
        LogErr "crashkernel=auto doesn't work for this distro. Please use this pattern: crashkernel=X@Y."
        SetTestStateSkipped
        exit 0
    fi
fi

Config_"${OS_FAMILY}"

# Remove old crashkernel params
sed -i --follow-symlinks "s/crashkernel=\S*//g" $boot_filepath

# Add the crashkernel param
if [[ $DISTRO != "redhat_8" ]] && [[ $DISTRO != "centos_8" ]] && [[ $DISTRO != "almalinux_8" ]]; then
    sed -i --follow-symlinks "/vmlinuz-$(uname -r)/ s/$/ crashkernel=$crashkernel/" $boot_filepath
elif [[ $DISTRO = "mariner" ]]; then
    sed -i --follow-symlinks "/mariner_cmdline=init/s/$/ crashkernel=$crashkernel/" $boot_filepath
else
    sed -i --follow-symlinks "/kernelopts=root/s/$/ crashkernel=$crashkernel/" $boot_filepath
fi

if [ $? -ne 0 ]; then
    LogErr "Could not set the new crashkernel value in $boot_filepath"
    SetTestStateAborted
    exit 0
else
    LogMsg "Success: updated the crashkernel value to: $crashkernel."
fi

# Cleaning up any previous crash dump files
mkdir -p /var/crash
rm -rf /var/crash/*
SetTestStateCompleted
exit 0
