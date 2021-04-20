#!/bin/bash -
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.

###########################################################################################
#
# Description:
#
# This script contains all distro-specific functions, as well as
# other common functions used in the LISAv2 test scripts.
# Private variables used in scripts should use the __VAR_NAME notation.
# Using the bash built-in `declare' statement also restricts the variable's scope.
# Same for "private" functions.
#
###########################################################################################

# Set IFS to space\t\n
IFS=$' \t\n'

# Include guard
[ -n "$__LIS_UTILS_SH_INCLUDE_GUARD" ] && exit 200 || readonly __LIS_UTILS_SH_INCLUDE_GUARD=1

##################################### Global variables #####################################

# Because functions can only return a status code,
# global vars will be used for communicating with the caller
# All vars are first defined here

# Directory containing all files pushed by LIS framework
declare LIS_HOME=$(pwd)

# LIS state file used by powershell to get the test's state
declare __LIS_STATE_FILE="$LIS_HOME/state.txt"

# LIS possible states recorded in state file
declare __LIS_TESTRUNNING="TestRunning"      # The test is running
declare __LIS_TESTCOMPLETED="TestCompleted"  # The test completed successfully
declare __LIS_TESTSKIPPED="TestSkipped"      # The test is not supported by this scenario
declare __LIS_TESTABORTED="TestAborted"      # Error during setup of test
declare __LIS_TESTFAILED="TestFailed"        # Error during execution of test

# LIS constants file which contains the paramaters passed to the test
declare __LIS_CONSTANTS_FILE="$LIS_HOME/constants.sh"

# LIS log file.
declare __LIS_LOG_FILE="$LIS_HOME/TestExecution.log"

# LIS error log file.
declare __LIS_ERROR_LOG_FILE="$LIS_HOME/TestExecutionError.log"

# LIS summary file. Should be less verbose than the separate log file
declare __LIS_SUMMARY_FILE="$LIS_HOME/summary.log"

# DISTRO used for setting the distro used to run the script
declare DISTRO=''

# SYNTH_NET_INTERFACES is an array containing all synthetic network interfaces found
declare -a SYNTH_NET_INTERFACES

# LEGACY_NET_INTERFACES is an array containing all legacy network interfaces found
declare -a LEGACY_NET_INTERFACES

# Location that package blobs are stored
declare PACKAGE_BLOB_LOCATION="https://eosgpackages.blob.core.windows.net/testpackages/tools"

######################################## Functions ########################################

# Convenience function used to set-up most common variables
function UtilsInit() {
	if [ -d "$LIS_HOME" ]; then
		cd "$LIS_HOME"
	else
		LogErr "LIS_HOME $LIS_HOME directory missing. Unable to initialize testscript"
		return 1
	fi

	# clean-up any remaining files
	if [ -e "$__LIS_LOG_FILE" ]; then
		if [ -d "$__LIS_LOG_FILE" ]; then
			rm -rf "$__LIS_LOG_FILE"
			LogMsg "Found $__LIS_LOG_FILE directory"
		else
			rm -f "$__LIS_LOG_FILE"
		fi
	fi

	if [ -e "$__LIS_ERROR_LOG_FILE" ]; then
		if [ -d "$__LIS_ERROR_LOG_FILE" ]; then
			rm -rf "$__LIS_ERROR_LOG_FILE"
			LogMsg "Found $__LIS_ERROR_LOG_FILE directory"
		else
			rm -f "$__LIS_ERROR_LOG_FILE"
		fi
	fi

	if [ -e "$__LIS_SUMMARY_FILE" ]; then
		if [ -d "$__LIS_SUMMARY_FILE" ]; then
			rm -rf "$__LIS_SUMMARY_FILE"
			LogMsg "Found $__LIS_SUMMARY_FILE directory"
		else
			rm -f "$__LIS_SUMMARY_FILE"
		fi
	fi

	# Set standard umask for root
	umask 022
	# Create state file and update test state
	touch "$__LIS_STATE_FILE"
	SetTestStateRunning || {
		LogErr "Unable to update test state-file. Cannot continue initializing testscript"
		return 1
	}

	touch "$__LIS_LOG_FILE"
	touch "$__LIS_ERROR_LOG_FILE"
	touch "$__LIS_SUMMARY_FILE"

	if [ -f "$__LIS_CONSTANTS_FILE" ]; then
		. "$__LIS_CONSTANTS_FILE"
	else
		LogMsg "Constants file $__LIS_CONSTANTS_FILE missing or not a regular file. Cannot source it!"
	fi

	GetDistro && LogMsg "Testscript running on $DISTRO" || LogMsg "Test running on unknown distro!"

	LogMsg "Successfully initialized testscript!"
	return 0
}

# Functions used to update the current test state

# Should not be used directly. $1 should be one of __LIS_TESTRUNNING __LIS_TESTCOMPLETE __LIS_TESTABORTED __LIS_TESTFAILED
function __SetTestState() {
	if [ -f "$__LIS_STATE_FILE" ]; then
		if [ -w "$__LIS_STATE_FILE" ]; then
			echo "$1" > "$__LIS_STATE_FILE"
		else
			LogMsg "State file $__LIS_STATE_FILE exists and is a normal file, but is not writable"
			chmod u+w "$__LIS_STATE_FILE" && { echo "$1" > "$__LIS_STATE_FILE" && return 0 ; } || LogMsg "Warning: unable to make $__LIS_STATE_FILE writeable"
			return 1
		fi
	else
		LogMsg "State file $__LIS_STATE_FILE either does not exist or is not a regular file. Trying to create it..."
		echo "$1" > "$__LIS_STATE_FILE" || return 1
	fi

	return 0
}

function SetTestStateFailed() {
	__SetTestState "$__LIS_TESTFAILED"
	return $?
}

function SetTestStateSkipped() {
	__SetTestState "$__LIS_TESTSKIPPED"
	return $?
}

function SetTestStateAborted() {
	__SetTestState "$__LIS_TESTABORTED"
	return $?
}

function SetTestStateCompleted() {
	__SetTestState "$__LIS_TESTCOMPLETED"
	return $?
}

function SetTestStateRunning() {
	__SetTestState "$__LIS_TESTRUNNING"
	return $?
}

# Echos the date and $1 to stdout.
function __EchoWithDate() {
    echo $(date "+%a %b %d %T %Y") : "$1"
}

# Logging function. The way LIS currently runs scripts and collects log files, just echo the message
# $1 == Message
function LogMsg() {
    __EchoWithDate "$1"
    __EchoWithDate "$1" >> "./TestExecution.log"
}

# Error Logging function. The way LIS currently runs scripts and collects log files, just echo the message
# $1 == Message
function LogErr() {
    __EchoWithDate "$1"
    __EchoWithDate "$1" >> "./TestExecutionError.log"
    UpdateSummary "$1"
}

# Update summary file with message $1
# Summary should contain only a few lines
function UpdateSummary() {
    if [ -f "$__LIS_SUMMARY_FILE" ]; then
        if [ -w "$__LIS_SUMMARY_FILE" ]; then
            echo "$1" >> "$__LIS_SUMMARY_FILE"
        else
            LogMsg "Summary file $__LIS_SUMMARY_FILE exists and is a normal file, but is not writable"
            chmod u+w "$__LIS_SUMMARY_FILE" && echo "$1" >> "$__LIS_SUMMARY_FILE" || LogMsg "Warning: unable to make $__LIS_SUMMARY_FILE writeable"
            return 1
        fi
    else
        LogMsg "Summary file $__LIS_SUMMARY_FILE either does not exist or is not a regular file. Trying to create it..."
        echo "$1" >> "$__LIS_SUMMARY_FILE" || return 1
    fi

    __EchoWithDate "$1" >> "./TestExecution.log"

    return 0
}


# Function to get current distro and distro family
# Sets the $DISTRO variable to one of the following: suse, centos_{5, 6, 7}, redhat_{5, 6, 7}, fedora, ubuntu
# Sets the $OS_FAMILY variable to one of the following: Rhel, Debian, Suse
# The naming scheme will be distroname_version
# Takes no arguments
function GetDistro() {
	# Make sure we don't inherit anything
	declare __DISTRO
	#Get distro (snipper take from alsa-info.sh)
	__DISTRO=$(grep -ihs "Ubuntu\|SUSE\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux\|clear-linux-os\|CoreOS" /{etc,usr/lib}/{issue,*release,*version})
	case $__DISTRO in
		*Ubuntu*14.04*)
			DISTRO=ubuntu_14.04
			;;
		*Ubuntu*)
			DISTRO=ubuntu_x
			;;
		*Debian*7*)
			DISTRO=debian_7
			;;
		*Debian*)
			DISTRO=debian_x
			;;
		*SLE*15* | *SUSE*15*)
			DISTRO=suse_15
			;;
		*SUSE*12*)
			DISTRO=suse_12
			;;
		*SUSE*11*)
			DISTRO=suse_11
			;;
		*SUSE*)
			DISTRO=suse_x
			;;
		*CentOS*release*5.*Final)
			DISTRO=centos_5
			;;
		*CentOS*release*6\.*Final*)
			DISTRO=centos_6
			;;
		*CentOS*release*7\.*\.*)
			DISTRO=centos_7
			;;
		*CentOS*release*8\.*\.*)
			DISTRO=centos_8
			;;
		*CentOS*)
			DISTRO=centos_x
			;;
		*Fedora*18*)
			DISTRO=fedora_18
			;;
		*Fedora*19*)
			DISTRO=fedora_19
			;;
		*Fedora*20*)
			DISTRO=fedora_20
			;;
		*Fedora*)
			DISTRO=fedora_x
			;;
		*Red*5.*)
			DISTRO=redhat_5
			;;
		*Red*6\.*)
			DISTRO=redhat_6
			;;
		*Red*7\.*)
			DISTRO=redhat_7
			;;
		*Red*8.*)
			DISTRO=redhat_8
			;;
		*Red*9.*)
			DISTRO=redhat_9
			;;
		*Red*)
			DISTRO=redhat_x
			;;
		*ID=clear-linux-os*)
			DISTRO=clear-linux-os
			;;
		*ID=*CoreOS*)
			DISTRO=coreos
			;;
		*)
			DISTRO=unknown
			return 1
			;;
	esac
	case $DISTRO in
		centos* | redhat* | fedora*)
			OS_FAMILY="Rhel"
		;;
		ubuntu* | debian*)
			OS_FAMILY="Debian"
		;;
		suse*)
			OS_FAMILY="Sles"
		;;
		coreos*)
			OS_FAMILY="CoreOS"
		;;
		*)
			OS_FAMILY="unknown"
			return 1
		;;
	esac
	echo "OS family: $OS_FAMILY"
	return 0
}

# Check kernel version is above/equal to feature supported version
# eg. CheckVMFeatureSupportStatus "3.10.0-513"
# Return value:
#   0: current version equals or above supported version
#   1: current version is below supported version, or no param
function CheckVMFeatureSupportStatus() {
    specifiedKernel=$1
    if [ $specifiedKernel == "" ];then
        LogErr "Kernel version is required in the argument"
        return 1
    fi
    # for example 3.10.0-514.el7.x86_64
    # get kernel version array is (3 10 0 514)
    local kernel_array=($(uname -r | awk -F '[.-]' '{print $1,$2,$3,$4}'))
    local specifiedKernel_array=($(echo $specifiedKernel | awk -F '[.-]' '{print $1,$2,$3,$4}'))
    local index=${!kernel_array[@]}
    local n=0
    for n in $index
    do
        # above support version, returns 0
        if [ ${kernel_array[$n]} -gt ${specifiedKernel_array[$n]} ];then
            return 0
        elif [ ${kernel_array[$n]} -lt ${specifiedKernel_array[$n]} ];then
        # below support version, returns 1
            return 1
        fi
    done
    # strictly equal to support version, returns 0
    return 0
}

# Function to get all synthetic network interfaces
# Sets the $SYNTH_NET_INTERFACES array elements to an interface name suitable for network tools use
# Takes no arguments
function GetSynthNetInterfaces() {
    # Check for distribuion version
    case $DISTRO in
        redhat_5)
            check="net:*"
            ;;
        *)
            check="net"
            ;;
    esac

    extraction() {
        case $DISTRO in
        redhat_5)
            SYNTH_NET_INTERFACES[$1]=$(echo "${__SYNTH_NET_ADAPTERS_PATHS[$1]}" | awk -F: '{print $2}')
            ;;
        *)
            SYNTH_NET_INTERFACES[$1]=$(ls "${__SYNTH_NET_ADAPTERS_PATHS[$1]}" | head -n 1)
            ;;
        esac
    }

    # declare array
    declare -a __SYNTH_NET_ADAPTERS_PATHS
    # Add synthetic netadapter paths into __SYNTH_NET_ADAPTERS_PATHS array
    if [ -d '/sys/devices' ]; then
        while IFS= read -d $'\0' -r path ; do
            __SYNTH_NET_ADAPTERS_PATHS=("${__SYNTH_NET_ADAPTERS_PATHS[@]}" "$path")
        done < <(find /sys/devices -name $check -a -ipath '*vmbus*' -print0)
    else
        LogErr "Cannot find synthetic network interface. No /sys/devices directory."
        return 1
    fi

    # Check if we found anything
    if [ 0 -eq ${#__SYNTH_NET_ADAPTERS_PATHS[@]} ]; then
        LogErr "No synthetic network adapter found."
        return 1
    fi

    # Loop __SYNTH_NET_ADAPTERS_PATHS and get interfaces
    declare -i __index
    for __index in "${!__SYNTH_NET_ADAPTERS_PATHS[@]}"; do
        if [ ! -d "${__SYNTH_NET_ADAPTERS_PATHS[$__index]}" ]; then
            LogErr "Synthetic netadapter dir ${__SYNTH_NET_ADAPTERS_PATHS[$__index]} disappeared during processing!"
            return 1
        fi
        # extract the interface names
        extraction $__index
        if [ -z "${SYNTH_NET_INTERFACES[$__index]}" ]; then
            LogErr "No network interface found in ${__SYNTH_NET_ADAPTERS_PATHS[$__index]}"
            return 1
        fi
    done

    unset __SYNTH_NET_ADAPTERS_PATHS
    # Everything OK
    return 0
}

# Function to get all legacy network interfaces
# Sets the $LEGACY_NET_INTERFACES array elements to an interface name suitable for network tools use
# Takes no arguments
function GetLegacyNetInterfaces() {
	# declare array
	declare -a __LEGACY_NET_ADAPTERS_PATHS
	# Add legacy netadapter paths into __LEGACY_NET_ADAPTERS_PATHS array
	if [ -d '/sys/devices' ]; then
		while IFS= read -d $'\0' -r path ; do
			__LEGACY_NET_ADAPTERS_PATHS=("${__LEGACY_NET_ADAPTERS_PATHS[@]}" "$path")
		done < <(find /sys/devices -name net -a ! -path '*VMBUS*' -print0)
	else
		LogErr "Cannot find Legacy network interfaces. No /sys/devices directory."
		return 1
	fi

	# Check if we found anything
	if [ 0 -eq ${#__LEGACY_NET_ADAPTERS_PATHS[@]} ]; then
		LogErr "No synthetic network adapters found."
		return 1
	fi

	# Loop __LEGACY_NET_ADAPTERS_PATHS and get interfaces
	declare -i __index
	for __index in "${!__LEGACY_NET_ADAPTERS_PATHS[@]}"; do
		if [ ! -d "${__LEGACY_NET_ADAPTERS_PATHS[$__index]}" ]; then
			LogErr "Legacy netadapter dir ${__LEGACY_NET_ADAPTERS_PATHS[$__index]} disappeared during processing!"
			return 1
		fi
		# ls should not yield more than one interface, but doesn't hurt to be sure
		LEGACY_NET_INTERFACES[$__index]=$(ls ${__LEGACY_NET_ADAPTERS_PATHS[$__index]} | head -n 1)
		if [ -z "${LEGACY_NET_INTERFACES[$__index]}" ]; then
			LogErr "No network interface found in ${__LEGACY_NET_ADAPTERS_PATHS[$__index]}"
			return 1
		fi
	done

	# Everything OK
	return 0
}

# Validate that $1 is an IPv4 address
function CheckIP() {
    if [ 1 -ne $# ]; then
        LogErr "Required 1 arguments: IP address"
        return 1
    fi

    declare ip
    declare stat
    ip=$1
    stat=1

    if [[ $ip =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
        OIFS="$IFS"
        IFS='.'
        ip=($ip)
        IFS="$OIFS"
        [[ ${ip[0]} -le 255 && ${ip[1]} -le 255 \
            && ${ip[2]} -le 255 && ${ip[3]} -le 255 ]]
        stat=$?
    fi

    return $stat

}

# Validate that $1 is an IPv6 address
function CheckIPV6() {
    if [ 1 -ne $# ]; then
        LogErr "Required 1 arguments: IPV6 address"
        return 1
    fi

    declare ip
    declare stat
    ip=$1
    stat=1

    if [[ $ip =~ ^(([0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:)|fe80:(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}|::(ffff(:0{1,4}){0,1}:){0,1}((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])|([0-9a-fA-F]{1,4}:){1,4}:((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9]))$ ]]; then
        stat=$?
    fi

    return $stat

}

# Check that $1 is a MAC address
# Unused
function CheckMAC() {
	if [ 1 -ne $# ]; then
		LogErr "Required 1 arguments: IP address"
		return 1
	fi

	# allow lower and upper-case, as well as : (colon) or - (hyphen) as separators
	echo "$1" | grep -E '^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$' >/dev/null 2>&1

	return $?

}

# Function to set interface $1 to whatever the dhcp server assigns
# Unused
function SetIPfromDHCP(){
	if [ 1 -ne $# ]; then
		LogErr "Required 1 argument: network interface to assign the ip to"
		return 1
	fi

	# Check first argument
	ip link show "$1" >/dev/null 2>&1
	if [ 0 -ne $? ]; then
		LogErr "Network adapter $1 is not working."
		return 1
	fi

	ip -4 addr flush "$1"

	GetDistro
	case $DISTRO in
		redhat*|fedora*|centos*|ubuntu*|debian*)
			dhclient -r "$1" ; dhclient "$1"
			if [ 0 -ne $? ]; then
				LogErr "Unable to get dhcpd address for interface $1"
				return 1
			fi
			;;
		suse*)
			dhcpcd -k "$1" ; dhcpcd "$1"
			if [ 0 -ne $? ]; then
				LogErr "Unable to get dhcpd address for interface $1"
				return 1
			fi
			;;
		*)
			LogErr "Platform not supported yet!"
			return 1
			;;
	esac

	declare __IP_ADDRESS
	# Get IP-Address
	__IP_ADDRESS=$(ip -o addr show "$1" | grep -vi inet6 | cut -d '/' -f1 | awk '{print $NF}')

	if [ -z "$__IP_ADDRESS" ]; then
		LogErr "IP address did not get assigned to $1"
		return 1
	fi
	# OK
	return 0

}

# Set static IP $1 on interface $2
# It's up to the caller to make sure the interface is shut down in case this function fails
# Parameters:
# $1 == static ip
# $2 == interface
# $3 == netmask optional
function SetIPstatic() {
	if [ 2 -gt $# ]; then
		LogErr "Required 3 arguments: 1. static IP, 2. network interface, 3. (optional) netmask"
		return 1
	fi

	CheckIP "$1"
	if [ 0 -ne $? ]; then
		LogErr "Parameter $1 is not a valid IPv4 Address"
		return 1
	fi

	ip link show "$2" > /dev/null 2>&1
	if [ 0 -ne $? ]; then
		LogErr "Network adapter $2 is not working."
		return 1
	fi

	declare __netmask
	declare __interface
	declare __ip

	__netmask=${3:-255.255.255.0}
	__interface="$2"
	__ip="$1"

	echo "$__netmask" | grep '.' >/dev/null 2>&1
	if [ 0 -eq $? ]; then
		__netmask=$(NetmaskToCidr "$__netmask")
		if [ 0 -ne $? ]; then
			LogErr "$__netmask is not a valid netmask"
			return 1
		fi
	fi

	if [ "$__netmask" -ge 32 -o "$__netmask" -le 0 ]; then
		LogErr "$__netmask is not a valid cidr netmask"
		return 1
	fi

	ip link set "$__interface" down
	ip addr flush "$__interface"
	ip addr add "$__ip"/"$__netmask" dev "$__interface"
	ip link set "$__interface" up

	if [ 0 -ne $? ]; then
		LogErr "Unable to assign address $__ip/$__netmask to $__interface."
		return 5
	fi

	# Get IP-Address
	declare __IP_ADDRESS
	__IP_ADDRESS=$(ip -o addr show "${SYNTH_NET_INTERFACES[$__iterator]}" | grep -vi inet6 | cut -d '/' -f1 | awk '{print $NF}' | grep -vi '[a-z]')

	if [ -z "$__IP_ADDRESS" ]; then
		LogErr "IP address $__ip did not get assigned to $__interface"
		return 1
	fi

	# Check that addresses match
	if [ "$__IP_ADDRESS" != "$__ip" ]; then
		LogErr "New address $__IP_ADDRESS differs from static ip $__ip on interface $__interface"
		return 1
	fi

	# OK
	return 0
}

# translate network mask to CIDR notation
# Parameters:
# $1 == valid network mask
function NetmaskToCidr() {
    if [ 1 -ne $# ]; then
        LogErr "Required 1 argument: a valid network mask"
        return 1
    fi

    declare -i netbits=0
    IFS=.

    # TODO: change to another way mathmatically later.
    for dec in $1; do
        case $dec in
            255)
                netbits=$((netbits+8))
                ;;
            254)
                netbits=$((netbits+7))
                ;;
            252)
                netbits=$((netbits+6))
                ;;
            248)
                netbits=$((netbits+5))
                ;;
            240)
                netbits=$((netbits+4))
                ;;
            224)
                netbits=$((netbits+3))
                ;;
            192)
                netbits=$((netbits+2))
                ;;
            128)
                netbits=$((netbits+1))
                ;;
            0)	#nothing to add
                ;;
            *)
                LogErr "$1 is not a valid netmask"
                return 1
                ;;
        esac
    done

    echo $netbits

    return 0
}

# Remove all default gateways
function RemoveDefaultGateway() {
	while ip route del default >/dev/null 2>&1
	do : #nothing
	done

	return 0
}

# Create default gateway
# Parameters:
# $1 == gateway ip
# $2 == interface
function CreateDefaultGateway() {
	if [ 2 -ne $# ]; then
		LogErr "Required 2 arguments"
		return 1
	fi

	# check that $1 is an IP address
	CheckIP "$1"

	if [ 0 -ne $? ]; then
		LogErr "$1 is not a valid IP Address"
		return 1
	fi

	# check interface exists
	ip link show "$2" >/dev/null 2>&1
	if [ 0 -ne $? ]; then
		LogErr "No interface $2 found."
		return 1
	fi

	declare __interface
	declare __ipv4

	__ipv4="$1"
	__interface="$2"

	# before creating the new default route, delete any old route
	RemoveDefaultGateway

	# create new default gateway
	ip route add default via "$__ipv4" dev "$__interface"

	if [ 0 -ne $? ]; then
		LogErr "Unable to set $__ipv4 as a default gateway for interface $__interface"
		return 1
	fi

	# check to make sure default gateway actually was created
	ip route show | grep -i "default via $__ipv4 dev $__interface" >/dev/null 2>&1

	if [ 0 -ne $? ]; then
		LogErr "Route command succeded, but gateway does not appear to have been set."
		return 1
	fi

	return 0
}

# Create Vlan Config
# Parameters:
# $1 == interface for which to create the vlan config file
# $2 == static IP to set for vlan interface
# $3 == netmask for that interface
# $4 == vlan ID
function CreateVlanConfig() {
	if [ 4 -ne $# ]; then
		LogErr "Required 4 arguments"
		return 1
	fi

	# check interface exists
	ip link show "$1" >/dev/null 2>&1
	if [ 0 -ne $? ]; then
		LogErr "No interface $1 found."
		return 1
	fi

	# check that $2 is an IP address
	CheckIP "$2"
	if [[ $? -eq 0 ]]; then
	    netmaskConf="NETMASK"
	else
		CheckIPV6 "$2"
		if [[ $? -eq 0 ]]; then
	    	netmaskConf="PREFIX"
	    else
	    	LogErr "$2 is not a valid IP Address"
			return 1
		fi
	fi

	declare __noreg='^[0-4096]+'
	# check $4 for valid vlan range
	if ! [[ $4 =~ $__noreg ]] ; then
		LogErr "Invalid vlan ID $4 received."
		return 1
	fi

	# check that vlan driver is loaded
	if ! lsmod | grep 8021q
	then
		modprobe 8021q
	fi

	declare __interface
	declare __ip
	declare __netmask
	declare __vlanID
	declare __file_path
	declare __vlan_file_path

	__interface="$1"
	__ip="$2"
	__netmask="$3"
	__vlanID="$4"

	# consider a better cleanup of environment if an existing interfaces setup exists
	__file_path="/etc/sysconfig/network-scripts/ifcfg-$__interface"
	if [ -e "$__file_path" ]; then
		LogErr "Warning, $__file_path already exists."
		if [ -d "$__file_path" ]; then
			rm -rf "$__file_path"
		else
			rm -f "$__file_path"
		fi
	fi

	__vlan_file_path="/etc/sysconfig/network-scripts/ifcfg-$__interface.$__vlanID"
	if [ -e "$__vlan_file_path" ]; then
		LogErr "Warning, $__vlan_file_path already exists."
		if [ -d "$__vlan_file_path" ]; then
			rm -rf "$__vlan_file_path"
		else
			rm -f "$__vlan_file_path"
		fi
	fi

	GetDistro
	case $DISTRO in
		redhat*|centos*|fedora*|debian*|ubuntu*)
			ip link add link "$__interface" name "$__interface.$__vlanID" type vlan id "$__vlanID"
			ip addr add "$__ip/$__netmask" dev "$__interface.$__vlanID"
			ip link set dev "$__interface" up
			ip link set dev "$__interface.$__vlanID" up

			;;
		suse_12*)
			cat <<-EOF > "$__file_path"
				TYPE=Ethernet
				BOOTPROTO=none
				STARTMODE=auto
			EOF

			if [[ $netmaskConf == "NETMASK" ]]; then
				cat <<-EOF > "$__vlan_file_path"
					ETHERDEVICE=$__interface
					BOOTPROTO=static
					IPADDR=$__ip
					$netmaskConf=$__netmask
					STARTMODE=auto
					VLAN=yes
				EOF
			else
				cat <<-EOF > "$__vlan_file_path"
					ETHERDEVICE=$__interface
					BOOTPROTO=static
					IPADDR=$__ip/$__netmask
					STARTMODE=auto
					VLAN=yes
				EOF
			fi

			# bring real interface down and up again
			wicked ifdown "$__interface"
			wicked ifup "$__interface"
			# bring also vlan interface up
			wicked ifup "$__interface.$__vlanID"

			;;
		suse*)
			cat <<-EOF > "$__file_path"
				BOOTPROTO=static
				IPADDR=0.0.0.0
				STARTMODE=auto
			EOF

			if [[ $netmaskConf == "NETMASK" ]]; then
				cat <<-EOF > "$__vlan_file_path"
					BOOTPROTO=static
					IPADDR=$__ip
					$netmaskConf=$__netmask
					STARTMODE=auto
					VLAN=yes
					ETHERDEVICE=$__interface
				EOF
			else
				cat <<-EOF > "$__vlan_file_path"
					BOOTPROTO=static
					IPADDR=$__ip/$__netmask
					STARTMODE=auto
					VLAN=yes
					ETHERDEVICE=$__interface
				EOF
			fi

			ip link set "$__interface" down
			ip link set "$__interface" up
			ip link set "$__interface.$__vlanID" up

			;;
		*)
			LogErr "Platform not supported yet!"
			return 1
			;;
	esac

	sleep 5

	# verify change took place
	grep "$__vlanID" /proc/net/vlan/config
	if [ 0 -ne $? ]; then
		LogMsg "/proc/net/vlan/config has no vlanID of $__vlanID"
		return 1
	fi

	return 0
}

# Remove Vlan Config
# Parameters:
# $1 == interface from which to remove the vlan config file
# $2 == vlan ID
# Unused
function RemoveVlanConfig() {
	if [ 2 -ne $# ]; then
		LogErr "Required 2 arguments"
		return 1
	fi

	# check interface exists
	ip link show "$1" >/dev/null 2>&1
	if [ 0 -ne $? ]; then
		LogErr "No interface $1 found."
		return 1
	fi

	declare __noreg='^[0-4096]+'
	# check $2 for valid vlan range
	if ! [[ $2 =~ $__noreg ]] ; then
		LogErr "Invalid vlan ID $2 received."
		return 2
	fi

	declare __interface
	declare __ip
	declare __netmask
	declare __vlanID
	declare __file_path

	__interface="$1"
	__vlanID="$2"

	GetDistro
	case $DISTRO in
		redhat*|fedora*)
			__file_path="/etc/sysconfig/network-scripts/ifcfg-$__interface.$__vlanID"
			if [ -e "$__file_path" ]; then
				LogErr "Found $__file_path ."
				if [ -d "$__file_path" ]; then
					rm -rf "$__file_path"
				else
					rm -f "$__file_path"
				fi
			fi
			service network restart 2>&1

			# make sure the interface is down
			ip link set "$__interface.$__vlanID" down
			;;
		suse_12*)
			__file_path="/etc/sysconfig/network/ifcfg-$__interface.$__vlanID"
			if [ -e "$__file_path" ]; then
				LogErr "Found $__file_path ."
				if [ -d "$__file_path" ]; then
					rm -rf "$__file_path"
				else
					rm -f "$__file_path"
				fi
			fi
			wicked ifdown "$__interface.$__vlanID"
			# make sure the interface is down
			ip link set "$__interface.$__vlanID" down
			;;
		suse*)
			__file_path="/etc/sysconfig/network/ifcfg-$__interface.$__vlanID"
			if [ -e "$__file_path" ]; then
				LogErr "Found $__file_path ."
				if [ -d "$__file_path" ]; then
					rm -rf "$__file_path"
				else
					rm -f "$__file_path"
				fi
			fi

			ip link set "$__interface.$__vlanID" down
			ip link set "$__interface" down
			ip link set "$__interface" up

			# make sure the interface is down
			ip link set "$__interface.$__vlanID" down
			;;
		debian*|ubuntu*)
			__file_path="/etc/network/interfaces"
			if [ ! -e "$__file_path" ]; then
				LogErr "Warning, $__file_path does not exist."
				return 0
			fi
			if [ ! -d "$(dirname $__file_path)" ]; then
				LogErr "Warning, $(dirname $__file_path) does not exist."
				return 0
			else
				rm -f "$(dirname $__file_path)"
				LogErr "Warning $(dirname $__file_path) is not a directory"
				mkdir -p "$(dirname $__file_path)"
				touch "$__file_path"
			fi

			declare __first_iface
			declare __last_line
			declare __second_iface
			# delete any previously existing lines containing the desired vlan interface
			# get first line number containing our interested interface
			__first_iface=$(awk "/iface $__interface.$__vlanID/ { print NR; exit }" "$__file_path")
			# if there was any such line found, delete it and any related config lines
			if [ -n "$__first_iface" ]; then
				# get the last line of the file
				__last_line=$(wc -l $__file_path | cut -d ' ' -f 1)
				# sanity check
				if [ "$__first_iface" -gt "$__last_line" ]; then
					LogErr "Error while parsing $__file_path . First iface line is gt last line in file"
					return 1
				fi

				# get the last x lines after __first_iface
				__second_iface=$((__last_line-__first_iface))

				# if the first_iface was also the last line in the file
				if [ "$__second_iface" -eq 0 ]; then
					__second_iface=$__last_line
				else
					# get the line number of the seconf iface line
					__second_iface=$(tail -n $__second_iface $__file_path | awk "/iface/ { print NR; exit }")

					if [ -z $__second_iface ]; then
						__second_iface="$__last_line"
					else
						__second_iface=$((__first_iface+__second_iface-1))
					fi


					if [ "$__second_iface" -gt "$__last_line" ]; then
						LogErr "Error while parsing $__file_path . Second iface line is gt last line in file"
						return 1
					fi

					if [ "$__second_iface" -le "$__first_iface" ]; then
						LogErr "Error while parsing $__file_path . Second iface line is gt last line in file"
						return 1
					fi
				fi
				# now delete all lines between the first iface and the second iface
				sed -i "$__first_iface,${__second_iface}d" "$__file_path"
			fi

			sed -i "/auto $__interface.$__vlanID/d" "$__file_path"

			;;
		*)
			LogErr "Platform not supported yet!"
			return 3
			;;
	esac

	return 0
}

# Create ifup config file
# Parameters:
# $1 == interface name
# $2 == static | dhcp
# $3 == IP Address
# $4 == Subnet Mask
# if $2 is set to dhcp, $3 and $4 are ignored
function CreateIfupConfigFile() {
	if [ 2 -gt $# -o 4 -lt $# ]; then
		LogErr "Required 2 or 4 arguments"
		return 1
	fi

	# check interface exists
	ip link show "$1" >/dev/null 2>&1
	if [ 0 -ne $? ]; then
		LogErr "Found no interface $1"
		return 1
	fi

	declare __interface_name="$1"
	declare __create_static=0
	declare __ip
	declare __netmask
	declare __file_path
	ipv6=false

	case "$2" in
		static)
			__create_static=1
			;;
		dhcp)
			__create_static=0
			;;
		*)
			LogErr "\$2 needs to be either static or dhcp (received $2)"
			return 2
			;;
	esac

	if [ "$__create_static" -eq 0 ]; then
		# create config file for dhcp
		GetDistro
		case $DISTRO in
			suse_12*)
				__file_path="/etc/sysconfig/network/ifcfg-$__interface_name"
				if [ ! -d "$(dirname $__file_path)" ]; then
					LogErr "$(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 3
				fi

				if [ -e "$__file_path" ]; then
					LogErr "Warning will overwrite $__file_path ."
				fi

				cat <<-EOF > "$__file_path"
					STARTMODE='auto'
					BOOTPROTO='dhcp'
				EOF

				wicked ifdown "$__interface_name"
				wicked ifup "$__interface_name"
				;;
			suse*)
				__file_path="/etc/sysconfig/network/ifcfg-$__interface_name"
				if [ ! -d "$(dirname $__file_path)" ]; then
					LogErr "$(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 3
				fi

				if [ -e "$__file_path" ]; then
					LogErr "Warning will overwrite $__file_path ."
				fi

				cat <<-EOF > "$__file_path"
					STARTMODE=manual
					BOOTPROTO=dhcp
				EOF

				ip link set "$__interface_name" down
				ip link set "$__interface_name" up
				;;
			redhat_6|centos_6|redhat_7|redhat_8|centos_7|centos_8|fedora*)
				__file_path="/etc/sysconfig/network-scripts/ifcfg-$__interface_name"
				if [ ! -d "$(dirname $__file_path)" ]; then
					LogErr "$(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 3
				fi

				if [ -e "$__file_path" ]; then
					LogErr "Warning will overwrite $__file_path ."
				fi

				cat <<-EOF > "$__file_path"
					DEVICE="$__interface_name"
					BOOTPROTO=dhcp
				EOF

				ip link set "$__interface_name" down
				ip link set "$__interface_name" up
				service network restart || service networking restart || service NetworkManager restart

				;;
			redhat_5|centos_5)
				__file_path="/etc/sysconfig/network-scripts/ifcfg-$__interface_name"
				if [ ! -d "$(dirname $__file_path)" ]; then
					LogErr "$(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 3
				fi

				if [ -e "$__file_path" ]; then
					LogErr "Warning will overwrite $__file_path ."
				fi

				cat <<-EOF > "$__file_path"
					DEVICE="$__interface_name"
					BOOTPROTO=dhcp
					IPV6INIT=yes
				EOF

				cat <<-EOF >> "/etc/sysconfig/network"
					NETWORKING_IPV6=yes
				EOF

				ip link set "$__interface_name" up

				;;
			debian*|ubuntu*)
				if [ -d /etc/netplan/ ]; then
					__file_path="/etc/netplan/01-network.yaml"
					rm -rf $__file_path
					echo "network:" >> $__file_path
					echo "    ethernets:" >> $__file_path
					echo "        $__interface_name:" >> $__file_path
					echo "            dhcp4: true" >> $__file_path
					echo "    version: 2" >> $__file_path
					LogMsg "Generate file $__file_path, then run netplan apply."
					netplan apply
					if [ 0 -ne $? ]; then
						LogErr "Fail to run netplan apply!"
						return 1
					fi
				else
					__file_path="/etc/network/interfaces"
					if [ ! -d "$(dirname $__file_path)" ]; then
						LogErr "$(dirname $__file_path) does not exist! Something is wrong with the network config!"
						return 3
					fi

					if [ -e "$__file_path" ]; then
						LogErr "Warning will overwrite $__file_path ."
					fi

					#Check if interface is already configured. If so, delete old config
					if grep -q "$__interface_name" $__file_path
					then
						LogErr "Warning will delete older configuration of interface $__interface_name"
						sed -i "/$__interface_name/d" $__file_path
					fi

					cat <<-EOF >> "$__file_path"
						auto $__interface_name
						iface $__interface_name inet dhcp
					EOF

					ip link set "$__interface_name" up
					service networking restart || service network restart
					if $(ifup --help > /dev/null 2>&1) ; then
						ifup "$__interface_name"
					fi
				fi
				;;
			*)
				LogErr "Platform not supported yet!"
				return 1
				;;
		esac
	else
		# create config file for static
		if [ $# -ne 4 ]; then
			LogErr "if static config is selected, please provide 4 arguments"
			return 1
		fi

		if [[ $3 == *":"* ]]; then
			CheckIPV6 "$3"
			if [ 0 -ne $? ]; then
				LogErr "$3 is not a valid IPV6 Address"
				return 1
			fi
			ipv6=true
		else
			CheckIP "$3"
			if [ 0 -ne $? ]; then
				LogErr "$3 is not a valid IP Address"
				return 2
			fi
		fi

		__ip="$3"
		__netmask="$4"
		declare -i lineNumber

		GetDistro

		case $DISTRO in
			suse_12*|suse_15*)
				__file_path="/etc/sysconfig/network/ifcfg-$__interface_name"
				if [ ! -d "$(dirname $__file_path)" ]; then
					LogErr "$(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 1
				fi

				if [ -e "$__file_path" ]; then
					LogErr "Warning will overwrite $__file_path ."
				fi
				if [[ $ipv6 == false ]]; then
					cat <<-EOF > "$__file_path"
						STARTMODE=manual
						BOOTPROTO=static
						IPADDR="$__ip"
						NETMASK="$__netmask"
					EOF
				else
					cat <<-EOF > "$__file_path"
						STARTMODE=manual
						BOOTPROTO=static
						IPADDR="$__ip/$__netmask"
					EOF
				fi

				wicked ifdown "$__interface_name"
				wicked ifup "$__interface_name"
				;;
			suse*)
				__file_path="/etc/sysconfig/network/ifcfg-$__interface_name"
				if [ ! -d "$(dirname $__file_path)" ]; then
					LogErr "$(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 1
				fi

				if [ -e "$__file_path" ]; then
					LogErr "Warning will overwrite $__file_path ."
				fi

				cat <<-EOF > "$__file_path"
					STARTMODE=manual
					BOOTPROTO=static
					IPADDR="$__ip"
					NETMASK="$__netmask"
				EOF

				ip link set "$__interface_name" down
				ip link set "$__interface_name" up
				;;
			redhat*|centos*|fedora*)
				__file_path="/etc/sysconfig/network-scripts/ifcfg-$__interface_name"
				if [ ! -d "$(dirname $__file_path)" ]; then
					LogErr "$(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 1
				fi

				if [ -e "$__file_path" ]; then
					LogErr "Warning will overwrite $__file_path ."
				fi

				if [[ $ipv6 == false ]]; then
					cat <<-EOF > "$__file_path"
						DEVICE="$__interface_name"
						BOOTPROTO=none
						IPADDR="$__ip"
						NETMASK="$__netmask"
					EOF
				else
					cat <<-EOF > "$__file_path"
						DEVICE="$__interface_name"
						BOOTPROTO=none
						IPV6ADDR="$__ip"
						IPV6INIT=yes
						PREFIX="$__netmask"
					EOF
				fi

				ip link set "$__interface_name" down
				ip link set "$__interface_name" up
				service network restart || service networking restart || service NetworkManager restart
				;;

			debian*|ubuntu*)
				if [ -d /etc/netplan/ ]; then
					__file_path="/etc/netplan/01-static-network.yaml"
					rm -rf $__file_path
					echo "network:" >> "$__file_path"
					echo "    version: 2" >> "$__file_path"
					echo "    ethernets:" >> "$__file_path"
					echo "        $__interface_name:" >> "$__file_path"
					echo "            dhcp4: no" >> "$__file_path"
					echo "            addresses: [$__ip/24]" >> "$__file_path"
					LogMsg "Generate file $__file_path, then run netplan apply."
					netplan apply
					if [ 0 -ne $? ]; then
						LogErr "Fail to run netplan apply!"
						return 1
					fi
				else
					__file_path="/etc/network/interfaces"
					if [ ! -d "$(dirname $__file_path)" ]; then
						LogErr "$(dirname $__file_path) does not exist! Something is wrong with the network config!"
						return 1
					fi

					if [ -e "$__file_path" ]; then
						LogErr "Warning will overwrite $__file_path ."
					fi

					#Check if interface is already configured. If so, delete old config
					if [ grep -q "$__interface_name" $__file_path ]; then
						LogErr "Warning will delete older configuration of interface $__interface_name"
						lineNumber=$(cat -n $__file_path |grep "iface $__interface_name"| awk '{print $1;}')
						if [ $lineNumber ]; then
							lineNumber=$lineNumber+1
							sed -i "${lineNumber},+1 d" $__file_path
						fi
						sed -i "/$__interface_name/d" $__file_path
					fi

					if [[ $ipv6 == false ]]; then
						cat <<-EOF >> "$__file_path"
							auto $__interface_name
							iface $__interface_name inet static
							address $__ip
							netmask $__netmask
						EOF
					else
						cat <<-EOF >> "$__file_path"
							auto $__interface_name
							iface $__interface_name inet6 static
							address $__ip
							netmask $__netmask
						EOF
					fi

					ip link set "$__interface_name" up
					service networking restart || service network restart
					if $(ifup --help > /dev/null 2>&1) ; then
						ifup "$__interface_name"
					fi
				fi
				;;
			*)
				LogErr "Platform not supported!"
				return 1
				;;
		esac
	fi

	sysctl -w net.ipv4.conf.all.rp_filter=0
	sysctl -w net.ipv4.conf.default.rp_filter=0
	sysctl -w net.ipv4.conf.eth0.rp_filter=0
	sysctl -w net.ipv4.conf.$__interface_name.rp_filter=0
	sleep 5

	return 0
}

# Control Network Manager
# Parameters:
# $1 == start | stop
# Unusued
function ControlNetworkManager() {
    if [ 1 -ne $# ]; then
        LogErr "Required 1 argument: start | stop"
        return 1
    fi

    # Check first argument
    if [ x"$1" != xstop ] && [ x"$1" != xstart ]; then
        LogErr "Required 1 argument: start | stop."
        return 1
    fi

    GetDistro
    case $DISTRO in
        redhat*|fedora*|centos*)
            # check that we have a NetworkManager service running
            service NetworkManager status
            if [ 0 -ne $? ]; then
                LogMsg "NetworkManager does not appear to be running."
                return 0
            fi
            # now try to start|stop the service
            service NetworkManager $1
            if [ 0 -ne $? ]; then
                LogMsg "Unable to $1 NetworkManager."
                return 1
            else
                LogMsg "Successfully ${1}ed NetworkManager."
            fi
            ;;
        suse*)
            # no service file
            # edit /etc/sysconfig/network/config and set NETWORKMANAGER=no
            declare __nm_activated
            if [ x"$1" = xstart ]; then
                __nm_activated=yes
            else
                __nm_activated=no
            fi

            if [ -f /etc/sysconfig/network/config ]; then
                grep '^NETWORKMANAGER=' /etc/sysconfig/network/config
                if [ 0 -eq $? ]; then
                    sed -i "s/^NETWORKMANAGER=.*/NETWORKMANAGER=$__nm_activated/g" /etc/sysconfig/network/config
                else
                    echo "NETWORKMANAGER=$__nm_activated" >> /etc/sysconfig/network/config
                fi

                # before restarting service, save the LIS network interface details and restore them after restarting. (or at least try)
                # this needs to be done in the caller, as this function cannot be expected to read the constants file and know which interface to reconfigure.
                service network restart
            else
                LogMsg "No network config file found at /etc/sysconfig/network/config"
                return 1
            fi

            LogMsg "Successfully ${1}ed NetworkManager."
            ;;
        debian*|ubuntu*)
            # check that we have a NetworkManager service running
            service network-manager status
            if [ 0 -ne $? ]; then
                LogMsg "NetworkManager does not appear to be running."
                return 0
            fi
            # now try to start|stop the service
            service network-manager $1
            if [ 0 -ne $? ]; then
                LogMsg "Unable to $1 NetworkManager."
                return 1
            else
                LogMsg "Successfully ${1}ed NetworkManager."
            fi
            ;;
        *)
            LogMsg "Platform not supported!"
            return 1
            ;;
    esac

    return 0
}

# Convenience Function to disable NetworkManager
function DisableNetworkManager() {
	ControlNetworkManager stop
	# propagate return value from ControlNetworkManager
	return $?
}

# Convenience Function to enable NetworkManager
# Unused
function EnableNetworkManager() {
	ControlNetworkManager start
	# propagate return value from ControlNetworkManager
	return $?
}

# Setup a bridge named br0
# $1 == Bridge IP Address
# $2 == Bridge netmask
# $3 - $# == Interfaces to attach to bridge
# if no parameter is given outside of IP and Netmask, all interfaces will be added (except lo)
# Unused
function SetupBridge() {
	if [ $# -lt 2 ]; then
		LogErr "Required at least 2 parameters"
		return 1
	fi

	declare -a __bridge_interfaces
	declare __bridge_ip
	declare __bridge_netmask

	CheckIP "$1"

	if [ 0 -ne $? ]; then
		LogErr "$1 is not a valid IP Address"
		return 1
	fi

	__bridge_ip="$1"
	__bridge_netmask="$2"

	echo "$__bridge_netmask" | grep '.' >/dev/null 2>&1
	if [  0 -eq $? ]; then
		__bridge_netmask=$(NetmaskToCidr "$__bridge_netmask")
		if [ 0 -ne $? ]; then
			LogErr "$__bridge_netmask is not a valid netmask"
			return 1
		fi
	fi

	if [ "$__bridge_netmask" -ge 32 -o "$__bridge_netmask" -le 0 ]; then
		LogErr "$__bridge_netmask is not a valid cidr netmask"
		return 1
	fi

	if [ 2 -eq $# ]; then
		LogMsg "Received no interface argument. All network interfaces found will be attached to the bridge."
		# Get all synthetic interfaces
		GetSynthNetInterfaces
		# Remove the loopback interface
		SYNTH_NET_INTERFACES=(${SYNTH_NET_INTERFACES[@]/lo/})

		# Get the legacy interfaces
		GetLegacyNetInterfaces
		# Remove the loopback interface
		LEGACY_NET_INTERFACES=(${LEGACY_NET_INTERFACES[@]/lo/})
		# Remove the bridge itself
		LEGACY_NET_INTERFACES=(${LEGACY_NET_INTERFACES[@]/br0/})

		# concat both arrays and use this new variable from now on.
		__bridge_interfaces=("${SYNTH_NET_INTERFACES[@]}" "${LEGACY_NET_INTERFACES[@]}")

		if [ ${#__bridge_interfaces[@]} -eq 0 ]; then
			LogErr "No interfaces found"
			return 1
		fi

	else
		# get rid of the first two parameters
		shift
		shift
		# and loop through the remaining ones
		declare __iterator
		for __iterator in "$@"; do
			ip link show "$__iterator" >/dev/null 2>&1
			if [ 0 -ne $? ]; then
				LogErr "Interface $__iterator not working or not present"
				return 1
			fi
			__bridge_interfaces=("${__bridge_interfaces[@]}" "$__iterator")
		done
	fi

	# create bridge br0
	brctl addbr br0
	if [ 0 -ne $? ]; then
		LogErr "Unable to create bridge br0"
		return 1
	fi

	# turn off stp
	brctl stp br0 off

	declare __iface
	# set all interfaces to 0.0.0.0 and then add them to the bridge
	for __iface in ${__bridge_interfaces[@]}; do
		ip link set "$__iface" down
		ip addr flush dev "$__iface"
		ip link set "$__iface" up
		ip link set dev "$__iface" promisc on
		#add interface to bridge
		brctl addif br0 "$__iface"
		if [ 0 -ne $? ]; then
			LogErr "Unable to add interface $__iface to bridge br0"
			return 1
		fi
		LogErr "Added $__iface to bridge"
		echo "1" > /proc/sys/net/ipv4/conf/"$__iface"/proxy_arp
		echo "1" > /proc/sys/net/ipv4/conf/"$__iface"/forwarding

	done

	#setup forwarding on bridge
	echo "1" > /proc/sys/net/ipv4/conf/br0/forwarding
	echo "1" > /proc/sys/net/ipv4/conf/br0/proxy_arp
	echo "1" > /proc/sys/net/ipv4/ip_forward

	ip link set br0 down
	ip addr add "$__bridge_ip"/"$__bridge_netmask" dev br0
	ip link set br0 up
	LogMsg "$(brctl show br0)"
	LogMsg "Successfully create a new bridge"
	# done
	return 0
}

# TearDown Bridge br0
# Unused
function TearDownBridge() {
	ip link show br0 >/dev/null 2>&1
	if [ 0 -ne $? ]; then
		LogErr "No interface br0 found"
		return 1
	fi

	brctl show br0
	if [ 0 -ne $? ]; then
		LogErr "No bridge br0 found"
		return 1
	fi

	# get Mac Addresses of interfaces attached to the bridge
	declare __bridge_macs
	__bridge_macs=$(brctl showmacs br0 | grep -i "yes" | cut -f 2)

	# get the interfaces associated with those macs
	declare __mac
	declare __bridge_interfaces

	for __mac in $__bridge_macs; do
		__bridge_interfaces=$(grep -il "$__mac" /sys/class/net/*/address)
		if [ 0 -ne $? ]; then
			LogErr "MAC Address $__mac does not belong to any interface."
			UpdateSummary "$msg"
			SetTestStateFailed
			return 1
		fi

		# get just the interface name from the path
		__bridge_interfaces=$(basename "$(dirname "$__sys_interface")")

		ip link show "$__bridge_interfaces" >/dev/null 2>&1
		if [ 0 -ne $? ]; then
			LogErr "Could not find interface $__bridge_interfaces"
			return 1
		fi

		brctl delif br0 "$__bridge_interfaces"
	done

	# remove the bridge itself
	ip link set br0 down
	brctl delbr br0

	return 0
}

# Check free space
# $1 path to directory to check for free space
# $2 number of bytes to compare
# return == 0 if total free space is greater than $2
# return 1 otherwise
function IsFreeSpace() {
	if [ 2 -ne $# ]; then
		LogMsg "IsFreeSpace takes 2 arguments: path/to/dir to check for free space and number of bytes needed free"
		return -1
	fi

	declare -i __total_free_bytes=0
	__total_free_bytes=$(($(df "$1" | awk '/[0-9]%/{print $(NF-2)}')*1024))		#df returnes size in kb-blocks
	if [ "$2" -gt "$__total_free_bytes" ]; then
		return 1
	fi
	return 0
}

declare os_VENDOR os_RELEASE os_UPDATE os_PACKAGE os_CODENAME

########################################################################
# Determine what OS is running
########################################################################
# GetOSVersion
function GetOSVersion {
    # Figure out which vendor we are
    if [[ -x "$(which sw_vers 2>/dev/null)" ]]; then
        # OS/X
        os_VENDOR=$(sw_vers -productName)
        os_RELEASE=$(sw_vers -productVersion)
        os_UPDATE=${os_RELEASE##*.}
        os_RELEASE=${os_RELEASE%.*}
        if [[ "$os_RELEASE" =~ "10.7" ]]; then
            os_CODENAME="lion"
        elif [[ "$os_RELEASE" =~ "10.6" ]]; then
            os_CODENAME="snow leopard"
        elif [[ "$os_RELEASE" =~ "10.5" ]]; then
            os_CODENAME="leopard"
        elif [[ "$os_RELEASE" =~ "10.4" ]]; then
            os_CODENAME="tiger"
        elif [[ "$os_RELEASE" =~ "10.3" ]]; then
            os_CODENAME="panther"
        else
            os_CODENAME=""
        fi

    elif [[ -r /etc/redhat-release ]]; then
        # Red Hat Enterprise Linux Server release 5.5 (Tikanga)
        # Red Hat Enterprise Linux Server release 7.0 Beta (Maipo)
        # CentOS release 5.5 (Final)
        # CentOS Linux release 6.0 (Final)
        # Fedora release 16 (Verne)
        # XenServer release 6.2.0-70446c (xenenterprise)
        os_CODENAME=""
        for r in "Red Hat" CentOS Fedora XenServer; do
            os_VENDOR=$r
            if [[ -n $(grep "${r}" "/etc/redhat-release") ]]; then
                ver=$(sed -e 's/^.* \([0-9].*\) (\(.*\)).*$/\1\|\2/' /etc/redhat-release)
                os_CODENAME=${ver#*|}
                os_RELEASE=${ver%|*}
                os_UPDATE=${os_RELEASE##*.}
                # Fix when os_UPDATE not only contains number, e.g. '7.0 Beta (Maipo)'
                os_UPDATE_pattern='^[0-9].* .*[^0-9].*'
                if [[ $os_VENDOR == "Red Hat" ]] && [[ $os_UPDATE =~ $os_UPDATE_pattern ]]; then
                    os_UPDATE=${os_UPDATE% *}
                fi
                os_RELEASE=${os_RELEASE%.*}
                break
            fi
            os_VENDOR=""
        done
        os_PACKAGE="rpm"

    elif [[ -x $(which lsb_release 2>/dev/null) ]]; then
        os_VENDOR=$(lsb_release -i -s)
        os_RELEASE=$(lsb_release -r -s)
        os_UPDATE=""
        os_PACKAGE="rpm"
        if [[ "Debian,Ubuntu,LinuxMint" =~ $os_VENDOR ]]; then
            os_PACKAGE="deb"
        elif [[ "SUSE LINUX" =~ $os_VENDOR ]]; then
            lsb_release -d -s | grep -q openSUSE
            if [[ $? -eq 0 ]]; then
                os_VENDOR="openSUSE"
            fi
        elif [[ $os_VENDOR == "openSUSE project" ]]; then
            os_VENDOR="openSUSE"
        elif [[ $os_VENDOR =~ Red.*Hat ]]; then
            os_VENDOR="Red Hat"
        fi
        os_CODENAME=$(lsb_release -c -s)

    elif [[ -r /etc/SuSE-brand || -r /etc/SUSE-brand ]]; then
        os_VENDOR=$(head -1 /etc/S*SE-brand)
        os_VERSION=$(cat /etc/S*SE-brand | awk '/VERSION/ {print $NF}')
        os_RELEASE=$os_VERSION
        os_PACKAGE="rpm"

    elif [[ -r /etc/SuSE-release ]]; then
        for r in openSUSE "SUSE Linux"; do
            if [[ "$r" = "SUSE Linux" ]]; then
                os_VENDOR="SUSE LINUX"
            else
                os_VENDOR=$r
            fi

            if [[ -n "$(grep "${r}" /etc/SuSE-release)" ]]; then
                os_CODENAME=$(grep "CODENAME = " /etc/SuSE-release | sed 's:.* = ::g')
                os_RELEASE=$(grep "VERSION = " /etc/SuSE-release | sed 's:.* = ::g')
                os_UPDATE=$(grep "PATCHLEVEL = " /etc/SuSE-release | sed 's:.* = ::g')
                break
            fi
            os_VENDOR=""
        done
        os_PACKAGE="rpm"
    # If lsb_release is not installed, we should be able to detect Debian OS
    elif [[ -f /etc/debian_version ]] && [[ $(cat /proc/version) =~ "Debian" ]]; then
        os_VENDOR="Debian"
        os_PACKAGE="deb"
        os_CODENAME=$(awk '/VERSION=/' /etc/os-release | sed 's/VERSION=//' | sed -r 's/\"|\(|\)//g' | awk '{print $2}')
        os_RELEASE=$(awk '/VERSION_ID=/' /etc/os-release | sed 's/VERSION_ID=//' | sed 's/\"//g')
    elif [[ -f /etc/os-release ]] && [[ $(cat /etc/os-release) =~ "SUSE Linux Enterprise Server 15" ]]; then
        os_VENDOR="SLES"
        os_PACKAGE="rpm"
        os_CODENAME=""
        os_RELEASE=$(awk '/VERSION_ID=/' /etc/os-release | sed 's/VERSION_ID=//' | sed 's/\"//g')
    elif [[ -f /etc/os-release ]] && [[ $(cat /etc/os-release) =~ "SUSE Linux Enterprise High Performance Computing" ]]; then
        os_VENDOR="SLEHPC"
        os_PACKAGE="rpm"
        os_CODENAME=""
        os_RELEASE=$(awk '/VERSION_ID=/' /etc/os-release | sed 's/VERSION_ID=//' | sed 's/\"//g')
    fi
    export os_VENDOR os_RELEASE os_UPDATE os_PACKAGE os_CODENAME
}

function GetGuestGeneration() {
    if [ -d /sys/firmware/efi/ ]; then
        os_GENERATION=2
    else
        os_GENERATION=1
    fi
	LogMsg "Generation: $os_GENERATION"
}

#######################################################################
# Perform a minor kernel upgrade on CentOS/RHEL distros
#######################################################################
function UpgradeMinorKernel() {
	os_version=$(sed -e 's/^.* \([0-9].*\) (\(.*\)).*$/\1/' /etc/redhat-release)

	grep CentOS /etc/redhat-release
	if [ $? -eq 0 ]; then
		# Make changes to CentOS-Vault.repo
		sed -i "s/enabled=\S*/enabled=1/g" /etc/yum.repos.d/CentOS-Vault.repo

		# A CentOS 6.x specific command
		sed -i "s/6.0/$os_version/g" /etc/yum.repos.d/CentOS-Vault.repo

		# Get kernel version
		kernel_version=$(sed 's/.el.*//' <<< "$(uname -r)")
		sts=$(yum install kernel-${kernel_version}* -y)
		if [ $? -ne 0 ]; then
			sed -i "s/enabled=\S*/enabled=0/g" /etc/yum.repos.d/CentOS-Vault.repo
			sts=$(yum install kernel-${kernel_version}* -y)
		fi
	fi

	grep "Red Hat" /etc/redhat-release
	if [ $? -eq 0 ]; then
		sts=$(yum install -y --releasever=${os_version} kernel)
	fi

	if [ $sts -ne 0 ]; then
		return 1
	fi

	return 0
}

function VerifyIsEthtool() {
	# Should have "return" value: 0, if existed. Otherwise, 1.
	# Check for ethtool. If it's not on the system, install it.
	ethtool --version
	if [ $? -ne 0 ]; then
		LogMsg "Ethtool not found. Trying to install it."
		update_repos
		install_package "ethtool"
	fi
	which ethtool
	if [ $? -eq 0 ]; then
		LogMsg "Ethtool is successfully installed!"
		return 0
	else
		LogErr "Ethtool installation failed"
		return 1
	fi
}

# Function that will check for Call Traces on VM after 2 minutes
# This function assumes that check_traces.sh is already on the VM
function CheckCallTracesWithDelay() {
    dos2unix -q check_traces.sh
    echo 'sleep 5 && bash check_traces.sh check_traces.log &' > runtest_traces.sh
    bash runtest_traces.sh > check_traces.log 2>&1
    sleep $1
    cat check_traces.log | grep ERROR
    if [ $? -eq 0 ]; then
        msg="ERROR: Call traces have been found on VM after the test run"
        LogErr "$msg"
        UpdateSummary "$msg"
        SetTestStateFailed
        exit 1
    else
        return 0
    fi
}

# Get the verison of LIS
function get_lis_version() {
	lis_version=$(modinfo hv_vmbus 2>/dev/null | grep "^version:"| awk '{print $2}')
	if [ "$lis_version" == "" ]; then
		lis_version="Default_LIS"
	fi
	echo $lis_version
}

# Get the version of host
function get_host_version() {
	dmesg | grep "Host Build" | sed "s/.*Host Build://"| awk '{print  $1}'| sed "s/;//"
}

# Validate the exit status of previous execution
function check_exit_status() {
	# The failed/aborted options are used when Linux script is the testscript,
	# to check the checkpoint and set test result.
	exit_status=$?
	message=$1
	test_state=$2

	cmd="echo"
	if [ $exit_status -ne 0 ]; then
		$cmd "$message: Failed (exit code: $exit_status)"
		UpdateSummary "$message Failed·(exit·code:·$exit_status)"
		case "${test_state}" in
			failed)
				SetTestStateFailed
				exit 0
				;;
			aborted)
				SetTestStateAborted
				exit 0
				;;
			exit)
				SetTestStateAborted
				exit $exit_status
				;;
			*)
				LogErr "Unsupported check_exit_status option: ${test_state}"
				;;
		esac
	else
		$cmd "$message: Success"
		UpdateSummary "$message: Success"
	fi
}

# Validate the previous command exit code is 0
function VerifyExitCodeZero() {
	check_exit_status "$1" "failed" "$2"
}

# Validate the previous command exit code is not 0
function VerifyExitCodeNotZero() {
	[ $? -ne 0 ]
	check_exit_status "$1" "failed" "$2"
}

# Detect the version of Linux distribution, it gets the version only
function detect_linux_distribution_version() {
	local distro_version="Unknown"
	if [ -f /etc/centos-release ]; then
		distro_version=$(cat /etc/centos-release | sed s/.*release\ // | sed s/\ .*//)
	elif [ -f /etc/oracle-release ]; then
		distro_version=$(cat /etc/oracle-release | sed s/.*release\ // | sed s/\ .*//)
	elif [ -f /etc/redhat-release ]; then
		distro_version=$(cat /etc/redhat-release | sed s/.*release\ // | sed s/\ .*//)
	elif [ -f /etc/os-release ]; then
		distro_version=$(cat /etc/os-release|sed 's/"//g'|grep "VERSION_ID="| sed 's/VERSION_ID=//'| sed 's/\r//')
	elif [ -f /usr/share/clear/version ]; then
		distro_version=$(cat /usr/share/clear/version)
	fi
	echo $distro_version
}

# Detect the Linux distribution name, it gets the name in lowercase
function detect_linux_distribution() {
	if ls /etc/*release* 1> /dev/null 2>&1; then
		local linux_distribution=$(cat /etc/*release*|sed 's/"//g'|grep "^ID="| sed 's/ID=//')
		local temp_text=$(cat /etc/*release*)
	elif [ -f "/usr/lib/os-release" ]; then
		local linux_distribution=$(cat /usr/lib/os-release|sed 's/"//g'|grep "^ID="| sed 's/ID=//')
		local temp_text=$(cat /usr/lib/os-release)
	fi
	if [ "$linux_distribution" == "" ]; then
		if echo "$temp_text" | grep -qi "ol"; then
			linux_distribution='oracle'
		elif echo "$temp_text" | grep -qi "Ubuntu"; then
			linux_distribution='ubuntu'
		elif echo "$temp_text" | grep -qi "SUSE Linux"; then
			linux_distribution='suse'
		elif echo "$temp_text" | grep -qi "openSUSE"; then
			linux_distribution='opensuse'
		elif echo "$temp_text" | grep -qi "centos"; then
			linux_distribution='centos'
		elif echo "$temp_text" | grep -qi "Oracle"; then
			linux_distribution='oracle'
		elif echo "$temp_text" | grep -qi "Red Hat"; then
			linux_distribution='rhel'
		else
			linux_distribution='unknown'
		fi
	elif [ "$linux_distribution" == "ol" ]; then
		linux_distribution='oracle'
	elif echo "$linux_distribution" | grep -qi "debian"; then
		linux_distribution='debian'
	fi
	echo "$(echo "$linux_distribution" | awk '{print tolower($0)}')"
}

# Update reposiotry
function update_repos() {
	case "$DISTRO_NAME" in
		oracle|rhel|centos)
			yum clean all
			;;
		ubuntu|debian)
			dpkg_configure
			apt-get update
			;;
		suse|opensuse|sles|sle_hpc)
			_ret=$(zypper refresh)
			_azure_kernel=$(uname -r)
			if [[ $_ret == *"Warning"* && $_azure_kernel == *"default"* ]]; then
				LogErr "SAP or BYOS do not have repo configuration. Abort the test"
				return 1
			fi
			;;
		clear-linux-os)
			swupd update
			;;
		*)
			LogErr "Unknown distribution"
			return 1
	esac
}

# Install RPM package
function install_rpm () {
	package_name=$1
	sudo rpm -ivh --nodeps  $package_name
	check_exit_status "install_rpm $package_name" "exit"
}

# Install DEB package
function install_deb () {
	package_name=$1
	sudo dpkg -i $package_name
	check_exit_status "dpkg -i $package_name"
	sudo apt-get install -f
	check_exit_status "install_deb $package_name" "exit"
}

# Apt-get install packages, parameter: package name
function apt_get_install () {
	package_name=$1
	dpkg_configure
	sudo DEBIAN_FRONTEND=noninteractive apt --fix-broken install -y
	sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --force-yes $package_name
	check_exit_status "apt_get_install $package_name" "exit"
}

# Apt-get remove packages, parameter: package name
function apt_get_remove () {
	package_name=$1
	dpkg_configure
	sudo DEBIAN_FRONTEND=noninteractive apt-get remove -y --force-yes $package_name
	check_exit_status "apt_get_remove $package_name" "exit"
}

# Yum install packages, parameter: package name
function yum_install () {
	package_name=$1
	sudo yum -y --nogpgcheck install $package_name
	check_exit_status "yum_install $package_name" "exit"
}

# Yum remove packages, parameter: package name
function yum_remove () {
	package_name=$1
	sudo yum -y remove $package_name
	check_exit_status "yum_remove $package_name" "exit"
}

# Zypper install packages, parameter: package name
function zypper_install () {
	package_name=$1
	CheckInstallLockSLES
	sudo zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys in $package_name
	check_exit_status "zypper_install $package_name" "exit"
}

# Zypper remove packages, parameter: package name
function zypper_remove () {
	package_name=$1
	sudo zypper --non-interactive rm $package_name
	check_exit_status "zypper_remove $package_name" "exit"
}

# swupd bundle install packages, parameter: package name
function swupd_bundle_install () {
	package_name=$1
	sudo swupd bundle-add $package_name
	check_exit_status "swupd_bundle_install $package_name" "exit"
}

# swupd bundle remove packages, parameter: package name
function swupd_bundle_remove () {
	package_name=$1
	sudo swupd bundle-remove $package_name
	check_exit_status "swupd_bundle_remove $package_name" "exit"
}

# Install packages, parameter: package name
function install_package () {
	local package_list=("$@")
	for package_name in "${package_list[@]}"; do
		case "$DISTRO_NAME" in
			oracle|rhel|centos)
				yum_install "$package_name"
				;;

			ubuntu|debian)
				apt_get_install "$package_name"
				;;

			suse|opensuse|sles|sle_hpc)
				zypper_install "$package_name"
				;;

			clear-linux-os)
				swupd_bundle_install "$package_name"
				;;
			*)
				LogErr "Unknown distribution"
				return 1
		esac
	done
}

# Remove packages, parameter: package name
function remove_package () {
	local package_list=("$@")
	for package_name in "${package_list[@]}"; do
		case "$DISTRO_NAME" in
			oracle|rhel|centos)
				yum_remove "$package_name"
				;;

			ubuntu|debian)
				apt_get_remove "$package_name"
				;;

			suse|opensuse|sles|sle_hpc)
				zypper_remove "$package_name"
				;;

			clear-linux-os)
				swupd_bundle_remove "$package_name"
				;;
			*)
				LogErr "Unknown distribution"
				return 1
		esac
	done
}

# Install EPEL repository on RHEL based distros
function install_epel () {
	case "$DISTRO_NAME" in
		oracle|rhel|centos)
			yum -y install epel-release
			if [ $? != 0 ]; then
				if [[ $DISTRO_VERSION =~ ^6\. ]]; then
					epel_rpm_url="https://dl.fedoraproject.org/pub/epel/epel-release-latest-6.noarch.rpm"
				elif [[ $DISTRO_VERSION =~ ^7\. ]]; then
					epel_rpm_url="https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm"
				elif [[ $DISTRO_VERSION == "8.0" ]]; then
					epel_rpm_url="https://dl.fedoraproject.org/pub/epel/epel-release-latest-8.noarch.rpm"
				else
					LogErr "Unsupported version to install epel repository"
					return 1
				fi
				sudo rpm -ivh $epel_rpm_url
			fi
			;;
		*)
			LogErr "Unsupported distribution to install epel repository"
			return 1
	esac
	check_exit_status "install_epel"
}

function enable_nfs_rhel() {
    if [[ $DISTRO_NAME == "rhel" ]];then
        firewall-cmd --permanent --add-port=111/tcp
        firewall-cmd --permanent --add-port=54302/tcp
        firewall-cmd --permanent --add-port=20048/tcp
        firewall-cmd --permanent --add-port=2049/tcp
        firewall-cmd --permanent --add-port=46666/tcp
        firewall-cmd --permanent --add-port=42955/tcp
        firewall-cmd --permanent --add-port=875/tcp

        firewall-cmd --reload
    fi
}

# Install sshpass
function install_sshpass () {
	which sshpass
	if [ $? -ne 0 ]; then
		LogMsg "sshpass not installed\n Installing now..."
		check_package "sshpass"
		if [ $? -ne 0 ]; then
			install_package "gcc make wget"
			LogMsg "sshpass not installed\n Build it from source code now..."
			package_name="sshpass-1.06"
			source_url="https://sourceforge.net/projects/sshpass/files/sshpass/1.06/$package_name.tar.gz"
			wget $source_url
			tar -xf "$package_name.tar.gz"
			cd $package_name
			./configure --prefix=/usr/ && make && make install
			cd ..
		else
			install_package sshpass
		fi
		which sshpass
		check_exit_status "install_sshpass"
	fi
}

# Add benchmark repo on SLES
function add_sles_benchmark_repo () {
	source /etc/os-release
	IFS='- ' read -r -a array <<< "$VERSION"
	repo_url="https://download.opensuse.org/repositories/benchmark/SLE_${array[0]}_${array[1]}/benchmark.repo"
	wget $repo_url -O /dev/null -o /dev/null
	# if no judgement for repo url not existing, the script will hung when execute zypper --no-gpg-checks refresh
	if [ $? -eq 0 ]; then
		LogMsg "add_sles_benchmark_repo - $repo_url"
		zypper addrepo $repo_url
		zypper --no-gpg-checks refresh
	else
		LogMsg "$repo_url doesn't exist"
	fi
	return 0
}

# Add network utilities repo on SLES
function add_sles_network_utilities_repo () {
	if [[ $DISTRO_NAME == "sles" || $DISTRO_NAME == "sle_hpc" ]]; then
		case $DISTRO_VERSION in
			11*)
				repo_url="https://download.opensuse.org/repositories/network:/utilities/SLE_11_SP4/network:utilities.repo"
				;;
			12*)
				repo_url="https://download.opensuse.org/repositories/network:utilities/SLE_12_SP3/network:utilities.repo"
				;;
			15*)
				repo_url="https://download.opensuse.org/repositories/network:utilities/SLE_15/network:utilities.repo"
				;;
			*)
				LogErr "Unsupported SLES version $DISTRO_VERSION for add_sles_network_utilities_repo"
				return 1
		esac
		CheckInstallLockSLES
		zypper addrepo $repo_url
		zypper --no-gpg-checks refresh
		return 0
	else
		LogErr "Unsupported distribution for add_sles_network_utilities_repo"
		return 1
	fi
}

function dpkg_configure () {
	retry=100
	until [ $retry -le 0 ]; do
		sudo dpkg --force-all --configure -a && break
		retry=$[$retry - 1]
		sleep 6
		LogMsg 'Trying again to run dpkg --configure ...'
	done
}

# Install fio and required packages
function install_fio () {
	LogMsg "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of fio"
	update_repos
	case "$DISTRO_NAME" in
		oracle|rhel|centos)
			install_epel
			if [[ "${DISTRO_VERSION}" == "7.8" ]]; then
				yum install -y libpmem-devel
			fi
			yum -y --nogpgcheck install wget sysstat mdadm blktrace libaio fio bc libaio-devel gcc gcc-c++ kernel-devel
			if ! command -v fio; then
				LogMsg "fio is not installed\n Build it from source code now..."
				fio_version="3.13"
				wget https://github.com/axboe/fio/archive/fio-${fio_version}.tar.gz
				tar xvf fio-${fio_version}.tar.gz
				pushd fio-fio-${fio_version} && ./configure && make && make install
				popd
				yes | cp -f /usr/local/bin/fio /bin/
			fi
			check_exit_status "install_fio"
			mount -t debugfs none /sys/kernel/debug
			;;

		ubuntu|debian)
			export DEBIAN_FRONTEND=noninteractive
			dpkg_configure
			install_package "pciutils gawk mdadm wget sysstat blktrace bc fio"
			check_exit_status "install_fio"
			mount -t debugfs none /sys/kernel/debug
			;;

		sles|sle_hpc)
			if [[ $DISTRO_VERSION =~ 12|15* ]]; then
				zypper refresh
				add_sles_benchmark_repo
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install wget mdadm blktrace libaio1 sysstat bc
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install fio
			else
				LogErr "Unsupported SLES version"
				return 1
			fi
			# FIO is not available in the repository of SLES 15
			which fio
			if [ $? -ne 0 ]; then
				LogMsg "fio is not installed\n Build it from source code now..."
				fio_version="3.13"
				wget https://github.com/axboe/fio/archive/fio-${fio_version}.tar.gz
				tar xvf fio-${fio_version}.tar.gz
				pushd fio-fio-${fio_version} && ./configure && make && make install
				popd
				yes | cp -f /usr/local/bin/fio /bin/
				which fio
				if [ $? -ne 0 ]; then
					LogErr "Error: Unable to install fio from zypper repo"
					return 1
				fi
			else
				LogMsg "fio installed from repository"
			fi
			;;

		clear-linux-os)
			swupd_bundle_install "performance-tools os-core-dev fio"
			iptables -F
			;;

		coreos)
			docker pull lisms/fio
			docker pull lisms/toolbox
			;;

		*)
			LogErr "Unsupported distribution for install_fio"
			return 1
	esac
	if [[ $(detect_linux_distribution) == coreos ]]; then
		docker images | grep -i lisms/fio
	else
		which fio
	fi
	if [ $? -ne 0 ]; then
		return 1
	fi
}

# Install iperf3 and required packages
function install_iperf3 () {
	ip_version=$1
	LogMsg "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of iperf3"
	update_repos
	case "$DISTRO_NAME" in
		oracle|rhel|centos)
			install_epel
			yum -y --nogpgcheck install iperf3 sysstat bc psmisc wget
			iptables -F
			;;

		ubuntu|debian)
			dpkg_configure
			apt-get -y install sysstat bc psmisc
			if [[ "${DISTRO_NAME}" == "ubuntu" ]]; then
				apt-get -y install iperf3
			elif [[ "${DISTRO_NAME}" == "debian" ]]; then
				# Debian default repositories has 3.0 iperf3 version, which is not supported by automation.
				wget https://iperf.fr/download/ubuntu/iperf3_3.1.3-1_amd64.deb
				wget https://iperf.fr/download/ubuntu/libiperf0_3.1.3-1_amd64.deb
				dpkg -i iperf3_3.1.3-1_amd64.deb libiperf0_3.1.3-1_amd64.deb
			fi
			if [ $ip_version -eq 6 ] && [[ $DISTRO_VERSION =~ 16 ]]; then
				nic_name=$(get_active_nic_name)
				echo "iface $nic_name inet6 auto" >> /etc/network/interfaces.d/50-cloud-init.cfg
				echo "up sleep 5" >> /etc/network/interfaces.d/50-cloud-init.cfg
				echo "up dhclient -1 -6 -cf /etc/dhcp/dhclient6.conf -lf /var/lib/dhcp/dhclient6.$nic_name.leases -v $nic_name || true" >> /etc/network/interfaces.d/50-cloud-init.cfg
				ip link set $nic_name down
				ip link set $nic_name up
			fi
			;;

		sles|sle_hpc)
			if [[ $DISTRO_VERSION =~ 12|15 ]]; then
				add_sles_network_utilities_repo
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install sysstat git bc make gcc psmisc iperf
			else
				LogErr "Unsupported SLES version"
				return 1
			fi
			# For SUSE, keep iperf and iperf3 in the same way
			ln -s /usr/bin/iperf3 /usr/bin/iperf
			# iperf3 is not available in the repository of SLES 12
			command -v iperf3
			if [ $? -ne 0 ]; then
				iperf3_version=3.2
				iperf3_url=https://github.com/esnet/iperf/archive/$iperf3_version.tar.gz
				update_repos
				gcc -v
				if [ $? -ne 0 ]; then
					install_package "gcc"
				fi
				make -v
				if [ $? -ne 0 ]; then
					install_package "make"
				fi
				rm -rf $iperf3_version.tar.gz
				wget $iperf3_url
				if [ $? -ne 0 ]; then
					LogErr "Failed to download iperf3 from $iperf3_url"
					return 1
				fi
				rm -rf iperf-$iperf3_version
				tar xf $iperf3_version.tar.gz
				pushd iperf-$iperf3_version

				./configure; make; make install
				# update shared libraries links
				ldconfig
				popd
				PATH="$PATH:/usr/local/bin"
				iperf3 -v > /dev/null 2>&1
				if [ $? -ne 0 ]; then
					LogErr "Unable to install iperf3 from $iperf3_url"
					return 1
				fi
			else
				LogMsg "iperf3 installed from repository"
			fi
			iptables -F
			;;


		clear-linux-os)
			swupd_bundle_install "performance-tools os-core-dev"
			iptables -F
			;;

		coreos)
			docker pull lisms/iperf3
			;;

		*)
			LogErr "Unsupported distribution for install_iperf3"
			return 1
	esac
	if [[ $(detect_linux_distribution) == coreos ]]; then
		docker images | grep -i lisms/iperf3
	else
		command -v iperf3
	fi
	if [ $? -ne 0 ]; then
		return 1
	fi
}

# Build and install lagscope
function build_lagscope () {
	lagscope_version="v0.2.0"
	# If the lagscopeVersion is provided in xml then it will go for that version, otherwise default to v0.2.0.
	if [ "${1}" ]; then
		lagscope_version=${1}
	fi
	rm -rf lagscope
	git clone https://github.com/Microsoft/lagscope
	if [ $lagscope_version ] && [[ $lagscope_version == v* ]]; then
		currentVersion="${lagscope_version:1}"
	else
		currentVersion="${lagscope_version}"
	fi
	if [ $currentVersion ] && ( [ $currentVersion \> "0.2.0" ] || [ $currentVersion == "master" ] ); then
		pushd lagscope && ./do-cmake.sh build && ./do-cmake.sh install
		popd
		ln -sf /usr/local/bin/lagscope /usr/bin/lagscope
	else
		pushd lagscope/src && git checkout "$lagscope_version" && make && make install
		popd
	fi
}

# Install lagscope and required packages
function install_lagscope () {
	LogMsg "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of lagscope"
	update_repos
	case "$DISTRO_NAME" in
		oracle|rhel|centos)
			install_epel
			yum -y --nogpgcheck install libaio sysstat git bc make gcc wget cmake
			build_lagscope "${1}"
			iptables -F
			systemctl stop firewalld.service || service firewalld stop
			;;

		ubuntu|debian)
			dpkg_configure
			install_package "libaio1 sysstat git bc make gcc cmake"
			build_lagscope "${1}"
			;;

		sles|sle_hpc)
			if [[ $DISTRO_VERSION =~ 12|15 ]]; then
				add_sles_network_utilities_repo
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install sysstat git bc make gcc dstat psmisc cmake
				build_lagscope "${1}"
				iptables -F
			else
				LogErr "Unsupported SLES version"
				return 1
			fi
			;;

		clear-linux-os)
			swupd_bundle_install "performance-tools os-core-dev"
			build_lagscope "${1}"
			iptables -F
			;;

		coreos)
			docker pull lisms/lagscope
			;;

		*)
			LogErr "Unsupported distribution for install_lagscope"
			return 1
	esac
	if [[ $(detect_linux_distribution) == coreos ]]; then
		docker images | grep -i lisms/lagscope
	else
		which lagscope
	fi
	if [ $? -ne 0 ]; then
		return 1
	fi
}

# Build and install ntttcp
function build_ntttcp () {
	ntttcp_version="1.4.0"
	# If the ntttcpVersion is provided in xml then it will go for that version, otherwise default to 1.4.0.
	if [ "${1}" ]; then
		ntttcp_version=${1}
	fi
	if [ $ntttcp_version == "master" ]; then
		git clone https://github.com/Microsoft/ntttcp-for-linux.git
		pushd ntttcp-for-linux/src/ && make && make install
	else
		wget https://github.com/Microsoft/ntttcp-for-linux/archive/${ntttcp_version}.tar.gz
		tar -zxvf ${ntttcp_version}.tar.gz
		pushd ntttcp-for-linux-${ntttcp_version/v/}/src/ && make && make install
	fi
	popd
}

# Install ntttcp and required packages
function install_ntttcp () {
	LogMsg "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of ntttcp"
	update_repos
	case "$DISTRO_NAME" in
		oracle|rhel|centos)
			install_epel
			yum -y --nogpgcheck install wget libaio sysstat git bc make gcc dstat psmisc lshw cmake
			build_ntttcp "${1}"
			build_lagscope "${2}"
			iptables -F
			;;

		ubuntu|debian)
			dpkg_configure
			install_package "wget libaio1 sysstat git bc make gcc dstat psmisc lshw cmake"
			build_ntttcp "${1}"
			build_lagscope "${2}"
			;;

		sles|sle_hpc)
			if [[ $DISTRO_VERSION =~ 12|15 ]]; then
				add_sles_network_utilities_repo
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install wget sysstat git bc make gcc dstat psmisc lshw cmake
				build_ntttcp "${1}"
				build_lagscope "${2}"
				iptables -F
			else
				LogErr "Unsupported SLES version"
				return 1
			fi
			;;

		clear-linux-os)
			swupd_bundle_install "performance-tools os-core-dev"
			build_ntttcp "${1}"
			build_lagscope "${2}"
			iptables -F
			;;

		coreos)
			docker pull lisms/ntttcp
			docker pull lisms/toolbox
			docker pull lisms/lagscope
			;;

		*)
			LogErr "Unsupported distribution for install_ntttcp"
			return 1
	esac
	if [[ $(detect_linux_distribution) == coreos ]]; then
		docker images | grep -i lisms/ntttcp
	else
		which ntttcp
	fi
	if [ $? -ne 0 ]; then
		return 1
	fi
}

# Install apache and required packages
function install_apache () {
	LogMsg "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of apache"
	update_repos
	case "$DISTRO_NAME" in
		oracle|rhel|centos)
			install_epel
			yum clean dbcache
			yum -y --nogpgcheck install sysstat zip httpd httpd-tools dstat
			;;

		ubuntu|debian)
			dpkg_configure
			install_package "libaio1 sysstat zip apache2 apache2-utils dstat"
			;;

		sles|suse)
			if [[ $DISTRO_VERSION =~ 12|15 ]]; then
				add_sles_network_utilities_repo
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install libaio1 dstat sysstat zip apache2 apache2-utils
			else
				LogErr "Unsupported SLES version"
				return 1
			fi
			;;

		*)
			LogErr "Unsupported distribution for install_apache"
			return 1
	esac
	if [ $? -ne 0 ]; then
		return 1
	fi
}

# Install memcached and required packages
function install_memcached () {
	LogMsg "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of memcached"
	update_repos
	case "$DISTRO_NAME" in
		oracle|rhel|centos)
			install_epel
			yum clean dbcache
			yum -y --nogpgcheck install git sysstat zip memcached libmemcached dstat openssl-devel autoconf automake \
			make gcc-c++ pcre-devel libevent-devel pkgconfig zlib-devel
			export PATH=$PATH:/usr/local/bin
			;;

		ubuntu|debian)
			dpkg_configure
			install_package "git libaio1 sysstat zip memcached libmemcached-tools libssl-dev build-essential autoconf automake libpcre3-dev libevent-dev pkg-config zlib1g-dev"
			;;

		sles|suse)
			if [[ $DISTRO_VERSION =~ 12|15 ]]; then
				add_sles_network_utilities_repo
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install git libaio1 dstat sysstat zip \
				memcached libmemcached openssl-devel autoconf automake pcre-devel libevent-devel pkg-config zlib-devel \
				make gcc-c++
			else
				LogErr "Unsupported SLES version"
				return 1
			fi
			;;

		*)
			LogErr "Unsupported distribution for install_memcached"
			return 1
	esac
	if [ $? -ne 0 ]; then
		return 1
	fi
}

# Install MariaDB and sysbench required packages
function install_mariadb() {
	LogMsg "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of mariadb and sysbench"
	update_repos
	case "$DISTRO_NAME" in
		oracle|rhel|centos)
			install_epel
			install_package "make git sysstat gcc automake openssl-devel libtool wget \
							mariadb mariadb-devel mariadb-server"
			;;
		ubuntu|debian)
			dpkg_configure
			DEBIAN_FRONTEND=noninteractive apt-get install -y make sysstat mysql-client*
			DEBIAN_FRONTEND=noninteractive apt-get install -y mariadb-server pkg-config git automake libtool libmysqlclient-dev -o Acquire::ForceIPv4=true
			exit_status=$?
			message="Install MariaDB test dependency packages"
			if [ $exit_status -ne 0 ]; then				
				echo "$message faild (exit code: $exit_status)"
				UpdateSummary "$message faild (exit code: $exit_status)"
				SetTestStateAborted
			else
				echo "$message success"
				UpdateSummary "$message: Success"
			fi
			;;
		*)
			LogErr "Unsupported distribution"
			return 1
	esac
	if [ $? -ne 0 ]; then
		return 1
	fi
}

function build_netperf () {
	rm -rf lagscope
	wget https://github.com/HewlettPackard/netperf/archive/netperf-2.7.0.tar.gz
	tar -xzf netperf-2.7.0.tar.gz
	pushd netperf-netperf-2.7.0 && ./configure && make && make install
	popd
}

# Install ntttcp and required packages
function install_netperf () {
	LogMsg "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of netperf"
	update_repos
	case "$DISTRO_NAME" in
		oracle|rhel|centos)
			install_epel
			yum -y --nogpgcheck install sysstat make gcc wget
			build_netperf
			iptables -F
			;;

		ubuntu|debian)
			dpkg_configure
			apt-get -y install sysstat make gcc
			build_netperf
			;;

		sles)
			if [[ $DISTRO_VERSION =~ 12|15 ]]; then
				add_sles_network_utilities_repo
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install sysstat make gcc
				build_netperf
				iptables -F
			else
				LogErr "Unsupported SLES version"
				return 1
			fi
			;;

		clear-linux-os)
			swupd_bundle_install "dev-utils-dev sysadmin-basic performance-tools os-testsuite-phoronix network-basic openssh-server dev-utils os-core os-core-dev"
			build_netperf
			iptables -F
			;;

		coreos)
			docker pull lisms/netperf
			docker pull lisms/toolbox
			;;

		*)
			LogErr "Unsupported distribution for build_netperf"
			return 1
	esac
	if [[ $(detect_linux_distribution) == coreos ]]; then
		docker images | grep -i lisms/netperf
	else
		which netperf
	fi
	if [ $? -ne 0 ]; then
		return 1
	fi
}

function install_net_tools () {
	if [[ $DISTRO_NAME == "sles" ]] && [[ $DISTRO_VERSION =~ 15 ]] || [[ $DISTRO_NAME == "sle_hpc" ]]; then
		zypper_install "net-tools-deprecated" > /dev/null 2>&1
	fi
	if [[ "${DISTRO_NAME}" == "ubuntu" ]]; then
		apt_get_install "net-tools" > /dev/null 2>&1
	fi
}

# Get the active NIC name
function get_active_nic_name () {
	install_net_tools
	echo $(route | grep '^default' | grep -o '[^ ]*$')
}

# Create partitions
# Unused
function create_partitions () {
	disk_list=($@)
	LogMsg "Creating partitions on ${disk_list[@]}"

	count=0
	while [ "x${disk_list[count]}" != "x" ]; do
		echo ${disk_list[$count]}
		(echo n; echo p; echo 2; echo; echo; echo t; echo fd; echo w;) | fdisk ${disk_list[$count]}
		count=$(( $count + 1 ))
	done
}

# Remove partitions
# Unused
function remove_partitions () {
	disk_list=($@)
	LogMsg "Removing partitions on ${disk_list[@]}"

	count=0
	while [ "x${disk_list[count]}" != "x" ]; do
		echo ${disk_list[$count]}
		(echo p; echo d; echo w;) | fdisk ${disk_list[$count]}
		count=$(( $count + 1 ))
	done
}

#Create raid0
function create_raid0() {
	if [[ $# == 2 ]]; then
		local disks=$1
		local deviceName=$2
	else
		LogErr "create_raid0 accepts 2 arguments: 1. disks name, separated by whitespace 2. deviceName for raid"
		return 100
	fi
	count=0
	for disk in ${disks}
	do
		LogMsg "Partition disk /dev/${disk}"
		(echo d; echo n; echo p; echo 1; echo; echo; echo t; echo fd; echo w;) | fdisk /dev/${disk}
		raidDevices="${raidDevices} /dev/${disk}1"
		count=$(( $count + 1 ))
	done
	LogMsg "Creating RAID of ${count} devices."
	sleep 1
	LogMsg "Run cmd: yes | mdadm --create ${deviceName} --level 0 --raid-devices $count $raidDevices"
	yes | mdadm --create ${deviceName} --level 0 --raid-devices $count $raidDevices
	if [ $? -ne 0 ]; then
		LogErr "Unable to create raid ${deviceName}"
		return 1
	else
		LogMsg "Raid ${deviceName} create successfully."
	fi
}

# Copy/download files to/from remote server
# Usage:
#   remote_copy -user <username> -passwd <password> -host <host IP> -port <host port> -filename <filename> -remote_path <file path on remote vm> -cmd <put/get>
function remote_copy () {
	remote_path="~"

	while echo $1 | grep -q ^-; do
		declare $( echo $1 | sed 's/^-//' )=$2
		shift
		shift
	done

	if [ "x$host" == "x" ] || [ "x$user" == "x" ] || [ "x$filename" == "x" ] ; then
		LogErr "Usage: remote_copy -user <username> -passwd <user password> -host <host ipaddress> -filename <filename> -remote_path <location of the file on remote vm> -cmd <put/get>"
		return
	fi

	if [ "x$port" == "x" ]; then
		port=22
	fi

	if [ "$cmd" == "get" ] || [ "x$cmd" == "x" ]; then
		source_path="$user@$host:$remote_path/$filename"
		destination_path="."
	elif [ "$cmd" == "put" ]; then
		source_path=$filename
		destination_path=$user@$host:$remote_path/
	fi

	if [ "x$passwd" == "x" ]; then
		status=$(scp -o StrictHostKeyChecking=no -P $port $source_path $destination_path 2>&1)
	else
		install_sshpass
		status=$(sshpass -p $passwd scp -o StrictHostKeyChecking=no -P $port $source_path $destination_path 2>&1)
	fi

	exit_status=$?
	LogMsg $status
	return $exit_status
}

# Execute command on remote server
# Usage:
#   remote_exec -user <username> -passwd <user password> -host <host ipaddress> -port <host port> command
function remote_exec () {
	while echo $1 | grep -q ^-; do
		declare $( echo $1 | sed 's/^-//' )=$2
		shift
		shift
	done
	cmd=$@

	install_sshpass

	if [ "x$host" == "x" ] || [ "x$user" == "x" ] || [ "x$passwd" == "x" ] || [ "x$cmd" == "x" ] ; then
		LogErr "Usage: remote_exec -user <username> -passwd <user password> -host <host ipaddress> <onlycommand>"
		return
	fi

	if [ "x$port" == "x" ]; then
		port=22
	fi

	status=$(sshpass -p $passwd ssh -t -o StrictHostKeyChecking=no -p $port $user@$host $cmd 2>&1)
	exit_status=$?
	LogMsg $status
	return $exit_status
}

# Set root or any user's password
# Unused
function set_user_password {
	if [[ $# == 3 ]]; then
		user=$1
		user_password=$2
		sudo_password=$3
	else
		LogErr "Usage: user user_password sudo_password"
		return -1
	fi

	hash=$(openssl passwd -1 $user_password)

	string=$(echo $sudo_password | sudo -S cat /etc/shadow | grep $user)

	if [ "x$string" == "x" ]; then
		LogErr "$user not found in /etc/shadow"
		return -1
	fi

	IFS=':' read -r -a array <<< "$string"
	line="${array[0]}:$hash:${array[2]}:${array[3]}:${array[4]}:${array[5]}:${array[6]}:${array[7]}:${array[8]}"

	echo $sudo_password | sudo -S sed -i "s#^${array[0]}.*#$line#" /etc/shadow

	if [ $(echo $sudo_password | sudo -S cat /etc/shadow| grep $line|wc -l) != "" ]; then
		LogMsg "Password set succesfully"
	else
		LogErr "failed to set password"
	fi
}

# Collects the information in .csv format.
# Anyone can expand this with useful details.
# Better if it can collect details without su permission.
function collect_VM_properties () {
	local output_file=$1

	if [ "x$output_file" == "x" ]; then
		output_file="VM_properties.csv"
	fi

	echo "" > $output_file
	echo ",OS type,"$(detect_linux_distribution) $(detect_linux_distribution_version) >> $output_file
	echo ",Kernel version,"$(uname -r) >> $output_file
	echo ",LIS Version,"$(get_lis_version) >> $output_file
	echo ",Host Version,"$(get_host_version) >> $output_file
	echo ",Total CPU cores,"$(nproc) >> $output_file
	echo ",Total Memory,"$(free -h | grep Mem | awk '{print $2}') >> $output_file
	echo ",Resource disks size,"$(lsblk | grep "^sdb" | awk '{print $4}') >> $output_file
	echo ",Data disks attached,"$(lsblk | grep "^sd" | awk '{print $1}' | sort | grep -v "sd[ab]$" | wc -l) >> $output_file
	IFACES=($(ls /sys/class/net/))
	for i in "${!IFACES[@]}"; do
		if [[ "${IFACES[$i]}" != *"lo"* ]]; then
			echo ",${IFACES[$i]} MTU,"$(cat /sys/class/net/${IFACES[$i]}/mtu) >> $output_file
		fi
	done
}

# Add command in startup files
# Unused
function keep_cmd_in_startup () {
	testcommand=$*
	startup_files="/etc/rc.d/rc.local /etc/rc.local /etc/SuSE-release"
	count=0
	for file in $startup_files; do
		if [[ -f $file ]]; then
			if ! grep -q "${testcommand}" $file; then
				sed "/^\s*exit 0/i ${testcommand}" $file -i
				if ! grep -q "${testcommand}" $file; then
					echo $testcommand >> $file
				fi
				LogMsg "Added $testcommand >> $file"
				((count++))
			fi
		fi
	done
	if [ $count == 0 ]; then
		LogErr "Cannot find $startup_files files"
	fi
}

# Remove command from startup files
# Unused
function remove_cmd_from_startup () {
	testcommand=$*
	startup_files="/etc/rc.d/rc.local /etc/rc.local /etc/SuSE-release"
	count=0
	for file in $startup_files; do
		if [[ -f $file ]]; then
			if grep -q "${testcommand}" $file; then
				sed "s/${testcommand}//" $file -i
				((count++))
				LogMsg "Removed $testcommand from $file"
			fi
		fi
	done
	if [ $count == 0 ]; then
		LogErr "Cannot find $testcommand in $startup_files files"
	fi
}

# Generate randon MAC address
function generate_random_mac_addr () {
	echo "52:54:00:$(dd if=/dev/urandom bs=512 count=1 2>/dev/null | md5sum | sed 's/^\(..\)\(..\)\(..\).*$/\1:\2:\3/')"
}

declare DISTRO_NAME=$(detect_linux_distribution)
declare DISTRO_VERSION=$(detect_linux_distribution_version)

# Gets Synthetic - VF pairs by comparing MAC addresses.
#   Will ignore the default route interface even if it has accelerated networking,
#   which should be the primaryNIC with pubilc ip to which you SSH
# Recommend to capture output in array like so
#   pairs=($(getSyntheticVfPair))
#   then synthetic ${pairs[n]} maps to vf pci address ${pairs[n+1]}
#   when starting from zero i.e. index 1 and 2 have no relation
#   if captured output is empty then no VFs exist
function get_synthetic_vf_pairs() {
	local ignore_if=$(ip route | grep default | awk '{print $5}')
	local interfaces=$(ls /sys/class/net | grep -v lo | grep -v ${ignore_if})

	local synth_ifs=""
	local vf_ifs=""
	local interface
	for interface in ${interfaces}; do
		# alternative is, but then must always know driver name
		# readlink -f /sys/class/net/<interface>/device/driver/
		local bus_addr=$(ethtool -i ${interface} | grep bus-info | awk '{print $2}')
		if [ -z "${bus_addr}" ]; then
			synth_ifs="${synth_ifs} ${interface}"
		else
			vf_ifs="${vf_ifs} ${interface}"
		fi
	done

	local synth_if
	local vf_if
	for synth_if in ${synth_ifs}; do
		local synth_mac=$(ip link show ${synth_if} | grep ether | awk '{print $2}')

		for vf_if in ${vf_ifs}; do
			local vf_mac=$(ip link show ${vf_if} | grep ether | awk '{print $2}')
			# single = is posix compliant
			if [ "${synth_mac}" = "${vf_mac}" ]; then
				bus_addr=$(ethtool -i ${vf_if} | grep bus-info | awk '{print $2}')
				echo "${synth_if} ${bus_addr}"
			fi
		done
	done
}

function test_rsync() {
    . net_constants.sh
    ping -I vxlan0 242.0.0.11 -c 3
    if [ $? -ne 0 ]; then
        LogErr "Failed to ping the second vm through vxlan0 after configurations."
        SetTestStateAborted
        exit 1
    else
        LogMsg "Successfuly pinged the second vm through vxlan0 after configurations."
        LogMsg "Starting to transfer files with rsync"
        rsyncPara="ssh -o StrictHostKeyChecking=no -i /root/.ssh/$SSH_PRIVATE_KEY"
        echo "rsync -e '$rsyncPara' -avz /root/test root@242.0.0.11:/root" | at now +1 minutes
        SetTestStateCompleted
        exit 0
    fi
}

function test_rsync_files() {
    ping -I vxlan0 242.0.0.12 -c 3
    if [ $? -ne 0 ]; then
        LogErr "Failed to ping the first VM through the vxlan interface"
        SetTestStateAborted
        exit 1
    else
        LogMsg "Checking if the directory was transfered corectly."
        if [ -d "/root/test" ]; then
            echo "Test directory was found." >> summary.log
            size=$(du -h /root/test | awk '{print $1;}')
            if [ $size == "10G" ] || [ $size == "11G" ]; then
                LogMsg "Test directory has the proper size. Test ended successfuly."
                SetTestStateCompleted
                exit 0
            else
                LogErr "Test directory doesn't have the proper size. Test failed."
                SetTestStateFailed
                exit 1
            fi
        else
            LogErr "Test directory was not found"
            SetTestStateFailed
            exit 1
        fi
    fi
}

function change_mtu_increment() {
    test_iface=$1
    iface_ignore=$2

    __iterator=0
    declare -i current_mtu=0
    declare -i const_max_mtu=61440
    declare -i const_increment_size=4096
    while [ "$current_mtu" -lt "$const_max_mtu" ]; do
        sleep 2
        current_mtu=$((current_mtu+const_increment_size))
        ip link set dev "$test_iface" mtu "$current_mtu"
        if [ 0 -ne $? ]; then
            # we reached the maximum mtu for this interface. break loop
            current_mtu=$((current_mtu-const_increment_size))
            break
        fi
        # make sure mtu was set. otherwise, set test to failed
        actual_mtu=$(ip -o link show "$test_iface" | cut -d ' ' -f5)
        if [ x"$actual_mtu" != x"$current_mtu" ]; then
            LogErr "Error: Set mtu on interface $test_iface to $current_mtu but ip reports mtu to be $actual_mtu"
            return 1
        fi
        LogMsg "Successfully set mtu to $current_mtu on interface $test_iface"
    done
    max_mtu="$current_mtu"

    # Hyper-V does not support multiple MTUs per endpoint, so we need to set the max MTU on all interfaces,
    # including the interface ignored because it's used by the LIS framework.
    # This can fail (e.g. the LIS connection uses a legacy adapter), but the test will continue
    # and only issue a warning
    if [ -n "$iface_ignore" ]; then
        ip link set dev "$iface_ignore" mtu "$max_mtu"
        # make sure mtu was set. otherwise, issue a warning
        actual_mtu=$(ip -o link show "$iface_ignore" | cut -d ' ' -f5)
        if [ x"$actual_mtu" != x"$max_mtu" ]; then
            LogMsg "Set mtu on interface $iface_ignore to $max_mtu but ip reports mtu to be $actual_mtu"
        fi
    fi

    return 0
}

function stop_firewall() {
	GetDistro
	case "$DISTRO" in
		suse*)
			status=$(systemctl is-active SuSEfirewall2)
			if [ "$status" = "active" ]; then
				service SuSEfirewall2 stop
				if [ $? -ne 0 ]; then
					return 1
				fi
			fi
			;;
		ubuntu*|debian*)
			ufw disable
			if [ $? -ne 0 ]; then
				return 1
			fi
			;;
		redhat* | centos* | fedora*)
			service firewalld stop
			if [ $? -ne 0 ]; then
				exit 1
			fi
			iptables -F
			iptables -X
			;;
		coreos)
			LogMsg "No extra steps need here."
			;;
		*)
			LogErr "OS Version not supported!"
			return 1
		;;
	esac
	return 0
}

function Update_Kernel() {
    GetDistro
    case "$DISTRO" in
        suse*)
            zypper ar -f $opensuselink kernel
            zypper --gpg-auto-import-keys --non-interactive dup -r kernel
            retVal=$?
            ;;
        ubuntu*|debian*)
            sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"
            retVal=$?
            ;;
        redhat* | centos* | fedora*)
            yum install -y kernel
            retVal=$?
            ;;
        *)
            LogErr "Platform not supported yet!"
            retVal=1
            ;;
    esac
    return $retVal
}

Kill_Process() {
    ips=$1
    IFS=',' read -r -a array <<< "$ips"
    for ip in "${array[@]}"
    do
        if [[ $(detect_linux_distribution) == coreos ]]; then
            output="default"
            while [[ ${#output} != 0 ]]; do
                output=$(ssh $ip "docker ps -a | grep $2 ")
                if [[ ${#output} == 0 ]]; then
                    break
                fi
                pid=$(echo $output | awk '{print $1}')
                ssh $ip "docker stop $pid; docker rm $pid"
            done
        else
            ssh $ip "killall $2"
        fi
    done
}

Delete_Containers() {
    containers=$(docker ps -a | grep -v 'CONTAINER ID' | awk '{print $1}')
    for containerID in ${containers}
    do
        docker stop $containerID > /dev/null 2>&1
        docker rm $containerID > /dev/null 2>&1
    done
}

Get_BC_Command() {
    bc_cmd=""
    if [[ $(detect_linux_distribution) != coreos ]]; then
        bc_cmd="bc"
    else
        Delete_Containers
        docker run -t -d lisms/toolbox > /dev/null 2>&1
        containerID=$(docker ps | grep -v 'CONTAINER ID' | awk '{print $1}')
        bc_cmd="docker exec -i $containerID bc"
    fi
    echo $bc_cmd
}

function ConsumeMemory() {
    if [ ! -e /proc/meminfo ]; then
        echo "Error: ConsumeMemory no meminfo found. Make sure /proc is mounted" >> HotAdd.log 2>&1
        return 1
    fi
    rm ~/HotAdd.log -f
    __totalMem=$(cat /proc/meminfo | grep -i MemTotal | awk '{ print $2 }')
    __totalMem=$((__totalMem/1024))
    echo "ConsumeMemory: Total Memory found $__totalMem MB" >> HotAdd.log 2>&1
    declare -i __chunks
    declare -i __threads
    declare -i duration
    declare -i timeout
    if [ $chunk -le 0 ]; then
        __chunks=128
    else
        __chunks=512
    fi
    __threads=$(($memMB/__chunks))
    if [ $timeoutStress -eq 0 ]; then
        timeout=10000000
        duration=$((10*__threads))
    elif [ $timeoutStress -eq 1 ]; then
        timeout=5000000
        duration=$((5*__threads))
    elif [ $timeoutStress -eq 2 ]; then
        timeout=1000000
        duration=$__threads
    else
        timeout=1
        duration=30
        __threads=4
        __chunks=2048
    fi
    if [ $duration -ne 0 ]; then
        duration=$duration
    fi
    echo "Stress-ng info: $__threads threads :: $__chunks MB chunk size :: $(($timeout/1000000)) seconds between chunks :: $duration seconds total stress time" >> HotAdd.log 2>&1
    stress-ng -m $__threads --vm-bytes ${__chunks}M -t $duration --backoff $timeout
    wait
    return 0
}

function Format_Mount_NVME() {
    if [[ $# == 2 ]]; then
        local namespace=$1
        local filesystem=$2
    else
        return 1
    fi
    install_package xfsprogs
    # Partition disk
    echo "Creating  partition on ${namespace} disk "
    (echo n; echo p; echo 1; echo ; echo; echo ; echo w) | fdisk /dev/"${namespace}"
    check_exit_status "${namespace} partition creation"
    sleep 1
    # Create fileSystem
    echo "Creating ${filesystem} filesystem on ${namespace} disk "
    echo "y" | mkfs."${filesystem}" -f "/dev/${namespace}p1"
    check_exit_status "${filesystem} filesystem creation"
    sleep 1
    # Mount the disk
    LogMsg "Mounting ${namespace}p1 disk "
    mkdir "$namespace"
    mount "/dev/${namespace}p1" "$namespace"
    check_exit_status "${filesystem} filesystem Mount"
    sleep 1
    return 0
}


# Remove and reattach PCI devices of a certain type inside the VM
# @param1 DeviceType: supported values are "NVME", "SR-IOV", "GPU"
# and "ALL" for all 3 previous types
# @return 0 if the devices were removed and reattached successfully
function DisableEnablePCI () {
    case "$1" in
        "SR-IOV") vf_pci_type="Ethernet\|Network" ;;
        "NVME")   vf_pci_type="Non-Volatile" ;;
        "GPU")    vf_pci_type="NVIDIA" ;;
        "ALL")    vf_pci_type="NVIDIA\|Non-Volatile\|Ethernet\|Network" ;;
        *)        LogErr "Unsupported device type for DisableEnablePCI." ; return 1 ;;
    esac

	LogMsg "Disable and re-enable device: $1"

    if ! lspci --version > /dev/null 2>&1; then
		LogMsg "This distro needs to get lspci. Installing pciutils"
        update_repos
        install_package "pciutils"
    fi

    LogMsg "Attempting to disable and enable the $vf_pci_type PCI devices."
    # Get the VF address
    vf_pci_addresses=$(lspci | grep -i "$vf_pci_type" | awk '{ print $1 }')
    IFS=$'\n'; vf_pci_addresses=("$vf_pci_addresses"); unset IFS;

    if [ -z "$vf_pci_addresses" ]; then
        LogErr "No PCI devices of type $vf_pci_type were found."
        return 1
    else
        LogMsg "Found the following $vf_pci_type devices:"
        # Identify the PCI device for each address
        for addr in ${vf_pci_addresses[@]}; do
            LogMsg "$(lspci | grep $addr)"
        done
    fi

    # Verify and remove PCI device path for each address
    for addr in ${vf_pci_addresses[@]}; do
        vf_pci_remove_path="/sys/bus/pci/devices/${addr}/remove"
        if [ ! -f "$vf_pci_remove_path" ]; then
            LogErr "Could not to disable the PCI device, because the $vf_pci_remove_path doesn't exist."
            return 1
        else
			LogMsg "Found the PCI device remove pathg: $vf_pci_remove_path"
		fi
		LogMsg "Removing $addr device"
        echo 1 > "$vf_pci_remove_path"
    done

    sleep 5

    # Check if all VFs have been disabled
    for addr in ${vf_pci_addresses[@]}; do
        vf_pci_device_path="/sys/bus/pci/devices/${addr}"
        if [ -d "$vf_pci_device_path" ] || [ "$(lspci | grep -ic $addr)" -ne 0 ]; then
            LogErr "Could not disable the PCI device: $addr"
            return 1
        else
			LogMsg "Successfully verified the PCI device removal"
		fi
    done

    # Check if all VFs has been re-enabled
    retry=1
    while [ $retry -le 5 ]; do
	LogMsg "Trying count: $retry"
        # Enable the VF
		LogMsg "Rescanning PCI devices in the system"
        echo 1 > /sys/bus/pci/rescan
        sleep 5
        #Search for all addresses and folder structures
        searchFor=$(echo "$vf_pci_addresses" | wc -l)
        found=0
        for addr in ${vf_pci_addresses[@]}; do
            vf_pci_device_path="/sys/bus/pci/devices/${addr}"
            if [ -d "$vf_pci_device_path" ] && [ "$(lspci | grep -ic $addr)" -ne 0 ]; then
                LogMsg "Found PCI device addr: $addr on try: $retry"
                found=$((found + 1))
            fi
        done
        if [ "$found" -eq "$searchFor" ]; then
            LogMsg "All $found PCI devices have been reattached."
            return 0
        fi
        retry=$((retry + 1))
    done
    LogErr "PCI device is not present, enabling the $vf_pci_type device failed."
    return 1
}

# This function creates file using fallocate command
# which is significantly faster than dd command.
# Examples -
# CreateFile 1G /root/abc.out
# CreateFile 100M ./test.file
function CreateFile() {
	size=$1
	file_path=$2
	fallocate -l $size $file_path
	if [ $? -eq 0 ]; then
		LogMsg "$file_path created with size $size"
	else
		LogMsg "Error: $file_path failed to create with size $size"
	fi
}

# Check available packages
function check_package () {
	local package_list=("$@")
	for package_name in "${package_list[@]}"; do
		case "$DISTRO_NAME" in
			oracle|rhel|centos)
				yum --showduplicates list "$package_name" > /dev/null 2>&1
				return $?
				;;

			ubuntu|debian)
				apt-cache policy "$package_name" | grep "Candidate" | grep -v "none"
				return $?
				;;

			suse|opensuse|sles|sle_hpc)
				zypper search "$package_name"
				return $?
				;;

			clear-linux-os)
				swupd search "$package_name" | grep -v "failed"
				return $?
				;;
			*)
				echo "Unknown distribution"
				return 1
		esac
	done
}

# Install nvme
function install_nvme_cli() {
    which nvme
    if [ $? -ne 0 ]; then
        echo "nvme is not installed\n Installing now..."
        check_package "nvme-cli"
        if [ $? -ne 0 ]; then
            packages="gcc gcc-c++ kernel-devel make"
            for package in $packages; do
                check_package "$package"
                if [ $? -eq 0 ]; then
                    install_package "$package"
                fi
            done
            wget https://github.com/linux-nvme/nvme-cli/archive/${nvme_version}.tar.gz
            tar xvf ${nvme_version}.tar.gz
            pushd nvme-cli-${nvme_version/v/} && make && make install
            popd
            yes | cp -f /usr/local/sbin/nvme /sbin
        else
            install_package "nvme-cli"
        fi
    fi
    which nvme
    check_exit_status "install_nvme"
}

function CheckInstallLockUbuntu() {
    if pidof dpkg;then
        LogMsg "Another install is in progress. Waiting 10 seconds."
        sleep 10
        CheckInstallLockUbuntu
    else
        LogMsg "No apt lock present."
    fi
}

function CheckInstallLockSLES() {
    if pidof zypper;then
        LogMsg "Another install is in progress. Waiting 1 seconds."
        sleep 1
        CheckInstallLockSLES
    else
        LogMsg "No zypper lock present."
    fi
}

function get_OSdisk() {
	for driveName in /dev/sd*[^0-9];
	do
		# Get the OS disk based on "Linux filesystem" string or BootFlag(*) of a partition
		fdisk -l $driveName 2> /dev/null | grep -i "Linux filesystem\|/dev/sd[a-z][0-9]\+[ ]*\*" > /dev/null
		if [ 0 -eq $? ]; then
			os_disk=$(echo $driveName | awk -v FS=/ '{print $NF}')
			break
		fi
	done

	echo "$os_disk"
}

# Function to get current platform (Azure/HyperV) by checking if the metadata route 169.254.169.254 exists
# Sets the $PLATFORM variable to one of the following: Azure, HyperV
# Takes no arguments
function GetPlatform() {
	which route
	if [ $? -ne 0 ]; then
		install_net_tools
	fi
	route -n | grep "169.254.169.254" > /dev/null
	if [[ $? == 0 ]];then
		http_code=$(curl -H Metadata:true "http://169.254.169.254/metadata/instance?api-version=2019-06-01" -w "%{http_code}" -o /dev/null -s -m 3)
		if [[ "$http_code" == "200" ]];then
			PLATFORM="Azure"
		else
			PLATFORM="HyperV"
		fi
	else
		PLATFORM="HyperV"
	fi
	LogMsg "Running on platform: $PLATFORM"
}

# This function returns name of vf pair against specific synthetic interface
function get_vf_name() {
	if [ -z "${1}" ]; then
		LogErr "ERROR: must provide interface name to get_name_synthetic_vf_pairs()"
		SetTestStateAborted
		exit 1
	fi
	local synth_if=$1
	local ignore_if=$(ip route | grep default | awk '{print $5}')
	local interfaces=$(ls /sys/class/net | grep -v lo | grep -v ${ignore_if})

	local synth_ifs=""
	local vf_ifs=""
	local interface
	for interface in ${interfaces}; do
		# alternative is, but then must always know driver name
		# readlink -f /sys/class/net/<interface>/device/driver/
		local bus_addr=$(ethtool -i ${interface} | grep bus-info | awk '{print $2}')
		if [ -z "${bus_addr}" ]; then
			synth_ifs="${synth_ifs} ${interface}"
		else
			vf_ifs="${vf_ifs} ${interface}"
		fi
	done

	local vf_if
	local synth_mac=$(ip link show ${synth_if} | grep ether | awk '{print $2}')
	for vf_if in ${vf_ifs}; do
		local vf_mac=$(ip link show ${vf_if} | grep ether | awk '{print $2}')
		# single = is posix compliant
		if [ "${synth_mac}" = "${vf_mac}" ]; then
			echo "${vf_if}"
		fi
	done
}

# Run ssh command
# $1 == ips
# $2 == command
function Run_SSHCommand()
{
	ips=${1}
	cmd=${2}
	localaddress=$(hostname -i)
	IFS=',' read -r -a array <<< "$ips"
	for ip in "${array[@]}"
	do
		LogMsg "Execute ${cmd} on ${ip}"
		if [[ ${localaddress} = ${ip} ]]; then
			bash -c "${cmd}"
		else
			ssh "${ip}" "${cmd}"
		fi
	done
}

function get_AvailableDisks() {
	for disk in $(lsblk | grep "sd[a-z].*disk" | cut -d ' ' -f1); do
		if [ $(df | grep -c $disk) -eq 0 ]; then
			echo $disk
		fi
	done
}

function delete_partition() {
	all_disks=$(get_AvailableDisks)

	declare -A TEST_DICT
	for disk in ${all_disks}; do
		count=0
		count=$(cat /proc/partitions | grep "$disk" | wc -l)
		TEST_DICT["$disk"]=$((count-1))
	done

	for disk in "${!TEST_DICT[@]}"; do
		count="${TEST_DICT[$disk]}"
		LogMsg "Disk /dev/$disk has ${TEST_DICT[$disk]} partition"
		for ((c=1 ; c<=$((count-1)); c++)); do
			LogMsg "Delete the $c partition of disk /dev/$disk"
			(echo d; echo $c ; echo ; echo w) | fdisk "/dev/$disk"
			sleep 5
		done
		if [[ $count -ne 0 ]]; then
			LogMsg "Delete the last partition of disk /dev/$disk"
			(echo d; echo ; echo w) | fdisk "/dev/$disk"
			sleep 5
		fi
	done
}

function make_partition() {
	os_disk=$(get_OSdisk)
	paratition_count="$1"
	for driveName in /dev/sd*[^0-9]; do
		if [ $driveName == "/dev/${os_disk}" ] ; then
			continue
		fi
		for ((c=1 ; c<="$paratition_count"; c++)); do
			if [ $c -eq 1 ]; then
				(echo n; echo p; echo $c; echo ; echo +500M; echo ; echo w) | fdisk $driveName
			else
				(echo n; echo p; echo $c; echo ; echo; echo ; echo w) | fdisk $driveName
			fi
			check_exit_status "Make the ${c} partition for disk $driveName" "exit"
		done
	done
}

function make_filesystem() {
	os_disk=$(get_OSdisk)
	paratition_count="$1"
	filesys="$2"
	option="-f"
	if [ "$filesys" = "ext4" ]; then
		option="-F"
	fi
	for driveName in /dev/sd*[^0-9]; do
		if [ $driveName == "/dev/${os_disk}" ] ; then
			continue
		fi
		for ((c=1 ; c<="$paratition_count"; c++)); do
			echo "y" | mkfs.$filesys $option "${driveName}$c"
			check_exit_status "Creating FileSystem $filesys on disk ${driveName}${c}" "exit"
		done
	done
}

function mount_disk() {
	os_disk=$(get_OSdisk)
	paratition_count="$1"
	for driveName in /dev/sd*[^0-9]; do
		if [ $driveName == "/dev/${os_disk}" ] ; then
			continue
		fi
		for ((c=1 ; c<="$paratition_count"; c++)); do
			MountName="/mnt/$c"
			if [ ! -e ${MountName} ]; then
				mkdir $MountName
			fi
			sleep 1
			mount  "${driveName}$c" $MountName
			check_exit_status "Mounting disk ${driveName}${c} on $MountName" "exit"
		done
	done
}

function get_bootconfig_path() {
	config_path="/boot/config-$(uname -r)"
	if [[ $(detect_linux_distribution) == clear-linux-os ]]; then
		config_path="/usr/lib/kernel/config-$(uname -r)"
	elif [[ $(detect_linux_distribution) == coreos ]];then
		config_path="/usr/boot/config-$(uname -r)"
	fi
	echo "$config_path"
}

# check if lsvmbus exists, or the running kernel does not match installed version of linux-tools
# If lsvmbus doesn't exist, lsvmbus will be installed.
# If installation is failed, the script will be exited.
function check_lsvmbus() {
	lsvmbus_path=$(which lsvmbus)
	if [[ -z "$lsvmbus_path" ]] || ! $lsvmbus_path > /dev/null 2>&1; then
		install_package wget
		wget https://raw.githubusercontent.com/torvalds/linux/master/tools/hv/lsvmbus
		chmod +x lsvmbus
		if [[ "$DISTRO" =~ "coreos" ]]; then
			export PATH=$PATH:/usr/share/oem/python/bin/
			lsvmbus_path="./lsvmbus"
		else
			mv lsvmbus /usr/sbin
			lsvmbus_path=$(which lsvmbus)
		fi
	fi

	if [ -z "$lsvmbus_path" ]; then
		LogErr "lsvmbus tool not found!"
		SetTestStateFailed
		exit 0
	fi

	# lsvmbus requires python
	which python || [ -f /usr/libexec/platform-python ] && ln -s /usr/libexec/platform-python /sbin/python || which python3 && ln -s $(which python3) /sbin/python
	if ! which python; then
		update_repos
		install_package python
	fi
}

# Check if this VM is IB over ND, IB over SR-IOV or non-HPC VM.
# Return 0, if VM is IB over ND.
# Return 1, if VM is IB over SR-IOV.
# Return 2, if VM is non HPC VM.
# Return 3, if unknown.
# Ubuntu is used for HPC SKU but manual configuration required. It's exceptional.
function is_hpc_vm() {
	GetDistro
	if [ -d /sys/class/infiniband/ ] && [[ $DISTRO != "ubuntu"* ]]; then
		if [ -n "$(lspci | grep "Virtual Function")" ] && [ -n "$(dmesg | grep "IB Infiniband driver")" ]; then
			return 1
		elif [ -n "$(dmesg | grep hvnd_try_bind_nic)" ]; then
			return 0
		else
			return 3
		fi
	else
		return 2
	fi
}

# Get name of additional synthetic interface
function get_extra_synth_nic {
    local ignore_if=$(ip route | grep default | awk '{print $5}')
    local interfaces=$(ls /sys/class/net | grep -v lo | grep -v ${ignore_if})

    local synth_ifs=""
    for interface in ${interfaces}; do
        # alternative is, but then must always know driver name
        # readlink -f /sys/class/net/<interface>/device/driver/
        local bus_addr=$(ethtool -i ${interface} | grep bus-info | awk '{print $2}')
        if [ -z "${bus_addr}" ]; then
            synth_ifs="${synth_ifs} ${interface}"
        fi
    done
    echo "${synth_ifs}"
}

# Return the string from the dmesg, messages or syslog
# Depending on distro, system logs are different.
# if found, return 1. Otherwise, 0.
function found_sys_log() {
	if [ -f /var/log/messages ]; then
		_ret=$(sudo cat /var/log/messages | grep -i "$1")
	elif [ -f /var/log/syslog ]; then
		_ret=$(sudo cat /var/log/syslog | grep -i "$1")
	else
		_ret=$(sudo dmesg | grep -i "$1")
	fi
	if [[ "$_ret" == *"$1"* ]]; then
		return 1
	else
		return 0
	fi
}
