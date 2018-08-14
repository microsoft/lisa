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
declare LIS_HOME="$HOME"

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

# Link of sshpass RPM for SLES 12
declare SLES_12_SSHPASS_LINK="https://download.opensuse.org/repositories/network/SLE_12_SP3/x86_64/sshpass-1.06-7.1.x86_64.rpm"

######################################## Functions ########################################

# Convenience function used to set-up most common variables
UtilsInit()
{
	if [ -d "$LIS_HOME" ]; then
		cd "$LIS_HOME"
	else
		LogMsg "Warning: LIS_HOME $LIS_HOME directory missing. Unable to initialize testscript"
		return 1
	fi

	# clean-up any remaining files
	if [ -e "$__LIS_LOG_FILE" ]; then
		if [ -d "$__LIS_LOG_FILE" ]; then
			rm -rf "$__LIS_LOG_FILE"
			LogMsg "Warning: Found $__LIS_LOG_FILE directory"
		else
			rm -f "$__LIS_LOG_FILE"
		fi
	fi

	if [ -e "$__LIS_ERROR_LOG_FILE" ]; then
		if [ -d "$__LIS_ERROR_LOG_FILE" ]; then
			rm -rf "$__LIS_ERROR_LOG_FILE"
			LogMsg "Warning: Found $__LIS_ERROR_LOG_FILE directory"
		else
			rm -f "$__LIS_ERROR_LOG_FILE"
		fi
	fi

	if [ -e "$__LIS_SUMMARY_FILE" ]; then
		if [ -d "$__LIS_SUMMARY_FILE" ]; then
			rm -rf "$__LIS_SUMMARY_FILE"
			LogMsg "Warning: Found $__LIS_SUMMARY_FILE directory"
		else
			rm -f "$__LIS_SUMMARY_FILE"
		fi
	fi

	# Set standard umask for root
	umask 022
	# Create state file and update test state
	touch "$__LIS_STATE_FILE"
	SetTestStateRunning || {
		LogMsg "Warning: unable to update test state-file. Cannot continue initializing testscript"
		return 2
	}

	touch "$__LIS_LOG_FILE"
	touch "$__LIS_ERROR_LOG_FILE"
	touch "$__LIS_SUMMARY_FILE"

	if [ -f "$__LIS_CONSTANTS_FILE" ]; then
		. "$__LIS_CONSTANTS_FILE"
	else
		LogMsg "Error: constants file $__LIS_CONSTANTS_FILE missing or not a regular file. Cannot source it!"
		SetTestStateAborted
		UpdateSummary "Error: constants file $__LIS_CONSTANTS_FILE missing or not a regular file. Cannot source it!"
		return 3
	fi

	[ -n "$TC_COVERED" ] && UpdateSummary "Test covers $TC_COVERED" || UpdateSummary "Starting unknown test due to missing TC_COVERED variable"

	GetDistro && LogMsg "Testscript running on $DISTRO" || LogMsg "Warning: test running on unknown distro!"

	LogMsg "Successfully initialized testscript!"
	return 0

}

# Functions used to update the current test state

# Should not be used directly. $1 should be one of __LIS_TESTRUNNING __LIS_TESTCOMPLETE __LIS_TESTABORTED __LIS_TESTFAILED
__SetTestState()
{
	if [ -f "$__LIS_STATE_FILE" ]; then
		if [ -w "$__LIS_STATE_FILE" ]; then
			echo "$1" > "$__LIS_STATE_FILE"
		else
			LogMsg "Warning: state file $__LIS_STATE_FILE exists and is a normal file, but is not writable"
			chmod u+w "$__LIS_STATE_FILE" && { echo "$1" > "$__LIS_STATE_FILE" && return 0 ; } || LogMsg "Warning: unable to make $__LIS_STATE_FILE writeable"
			return 1
		fi
	else
		LogMsg "Warning: state file $__LIS_STATE_FILE either does not exist or is not a regular file. Trying to create it..."
		echo "$1" > "$__LIS_STATE_FILE" || return 2
	fi

	return 0
}

SetTestStateFailed()
{
	__SetTestState "$__LIS_TESTFAILED"
	return $?
}

SetTestStateSkipped()
{
	__SetTestState "$__LIS_TESTSKIPPED"
	return $?
}

SetTestStateAborted()
{
	__SetTestState "$__LIS_TESTABORTED"
	return $?
}

SetTestStateCompleted()
{
	__SetTestState "$__LIS_TESTCOMPLETED"
	return $?
}

SetTestStateRunning()
{
	__SetTestState "$__LIS_TESTRUNNING"
	return $?
}

# Logging function. The way LIS currently runs scripts and collects log files, just echo the message
# $1 == Message
LogMsg()
{
	echo $(date "+%a %b %d %T %Y") : "${1}"
	echo $(date "+%a %b %d %T %Y") : "${1}" >> "./TestExecution.log"
}

# Error Logging function. The way LIS currently runs scripts and collects log files, just echo the message
# $1 == Message
LogErr()
{
	echo $(date "+%a %b %d %T %Y") : "${1}"
	echo $(date "+%a %b %d %T %Y") : "${1}" >> "./TestExecutionError.log"
}

# Update summary file with message $1
# Summary should contain only a few lines
UpdateSummary()
{
	if [ -f "$__LIS_SUMMARY_FILE" ]; then
		if [ -w "$__LIS_SUMMARY_FILE" ]; then
			echo "$1" >> "$__LIS_SUMMARY_FILE"
		else
			LogMsg "Warning: summary file $__LIS_SUMMARY_FILE exists and is a normal file, but is not writable"
			chmod u+w "$__LIS_SUMMARY_FILE" && echo "$1" >> "$__LIS_SUMMARY_FILE" || LogMsg "Warning: unable to make $__LIS_SUMMARY_FILE writeable"
			return 1
		fi
	else
		LogMsg "Warning: summary file $__LIS_SUMMARY_FILE either does not exist or is not a regular file. Trying to create it..."
		echo "$1" >> "$__LIS_SUMMARY_FILE" || return 2
	fi

	return 0
}


# Function to get current distro
# Sets the $DISTRO variable to one of the following: suse, centos_{5, 6, 7}, redhat_{5, 6, 7}, fedora, ubuntu
# The naming scheme will be distroname_version
# Takes no arguments

GetDistro()
{
	# Make sure we don't inherit anything
	declare __DISTRO
	#Get distro (snipper take from alsa-info.sh)
	__DISTRO=$(grep -ihs "Ubuntu\|SUSE\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux" /etc/{issue,*release,*version})
	case $__DISTRO in
		*Ubuntu*12*)
			DISTRO=ubuntu_12
			;;
		*Ubuntu*13*)
			DISTRO=ubuntu_13
			;;
		*Ubuntu*14*)
			DISTRO=ubuntu_14
			;;
		# ubuntu 14 in current beta state does not use the number 14 in its description
		*Ubuntu*Trusty*)
			DISTRO=ubuntu_14
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
		*SLE*15*)
			DISTRO=suse_15
			;;
		*SUSE*15*)
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
		*CentOS*release*6.*)
			DISTRO=centos_6
			;;
		*CentOS*Linux*7.*)
			DISTRO=centos_7
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
		*Red*6.*)
			DISTRO=redhat_6
			;;
		*Red*7.*)
			DISTRO=redhat_7
			;;
		*Red*8.*)
			DISTRO=redhat_8
			;;
		*Red*)
			DISTRO=redhat_x
			;;
		*)
			DISTRO=unknown
			return 1
			;;
	esac

	return 0
}

# Check kernel version is above/equal to feature supported version
# eg. CheckVMFeatureSupportStatus "3.10.0-513"
# Return value:
#   0: current version equals or above supported version
#   1: current version is below supported version, or no param
CheckVMFeatureSupportStatus()
{
    specifiedKernel=$1
    if [ $specifiedKernel == "" ];then
        return 1
    fi
    # for example 3.10.0-514.el7.x86_64
    # get kernel version array is (3 10 0 514)
    local kernel_array=(`uname -r | awk -F '[.-]' '{print $1,$2,$3,$4}'`)
    local specifiedKernel_array=(`echo $specifiedKernel | awk -F '[.-]' '{print $1,$2,$3,$4}'`)
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
# Sets the $SYNTH_NET_INTERFACES array elements to an interface name suitable for ifconfig etc.
# Takes no arguments
GetSynthNetInterfaces()
{
	#Check for distribuion version
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
             SYNTH_NET_INTERFACES[$1]=`echo "${__SYNTH_NET_ADAPTERS_PATHS[$1]}" | awk -F: '{print $2}'`
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
            LogMsg "Cannot find synthetic network interfaces. No /sys/devices directory."
            return 1
    fi

    # Check if we found anything
    if [ 0 -eq ${#__SYNTH_NET_ADAPTERS_PATHS[@]} ]; then
            LogMsg "No synthetic network adapters found."
            return 2
    fi

    # Loop __SYNTH_NET_ADAPTERS_PATHS and get interfaces
    declare -i __index
    for __index in "${!__SYNTH_NET_ADAPTERS_PATHS[@]}"; do
            if [ ! -d "${__SYNTH_NET_ADAPTERS_PATHS[$__index]}" ]; then
                    LogMsg "Synthetic netadapter dir ${__SYNTH_NET_ADAPTERS_PATHS[$__index]} disappeared during processing!"
                    return 3
            fi
            # extract the interface names
            extraction $__index
            if [ -z "${SYNTH_NET_INTERFACES[$__index]}" ]; then
                    LogMsg "No network interface found in ${__SYNTH_NET_ADAPTERS_PATHS[$__index]}"
                    return 4
            fi
    done

    unset __SYNTH_NET_ADAPTERS_PATHS
    # Everything OK
    return 0
}

# Function to get all legacy network interfaces
# Sets the $LEGACY_NET_INTERFACES array elements to an interface name suitable for ifconfig/ip commands.
# Takes no arguments
GetLegacyNetInterfaces()
{

	# declare array
	declare -a __LEGACY_NET_ADAPTERS_PATHS
	# Add legacy netadapter paths into __LEGACY_NET_ADAPTERS_PATHS array
	if [ -d '/sys/devices' ]; then
		while IFS= read -d $'\0' -r path ; do
			__LEGACY_NET_ADAPTERS_PATHS=("${__LEGACY_NET_ADAPTERS_PATHS[@]}" "$path")
		done < <(find /sys/devices -name net -a ! -path '*VMBUS*' -print0)
	else
		LogMsg "Cannot find Legacy network interfaces. No /sys/devices directory."
		return 1
	fi

	# Check if we found anything
	if [ 0 -eq ${#__LEGACY_NET_ADAPTERS_PATHS[@]} ]; then
		LogMsg "No synthetic network adapters found."
		return 2
	fi

	# Loop __LEGACY_NET_ADAPTERS_PATHS and get interfaces
	declare -i __index
	for __index in "${!__LEGACY_NET_ADAPTERS_PATHS[@]}"; do
		if [ ! -d "${__LEGACY_NET_ADAPTERS_PATHS[$__index]}" ]; then
			LogMsg "Legacy netadapter dir ${__LEGACY_NET_ADAPTERS_PATHS[$__index]} disappeared during processing!"
			return 3
		fi
		# ls should not yield more than one interface, but doesn't hurt to be sure
		LEGACY_NET_INTERFACES[$__index]=$(ls ${__LEGACY_NET_ADAPTERS_PATHS[$__index]} | head -n 1)
		if [ -z "${LEGACY_NET_INTERFACES[$__index]}" ]; then
			LogMsg "No network interface found in ${__LEGACY_NET_ADAPTERS_PATHS[$__index]}"
			return 4
		fi
	done

	# Everything OK
	return 0
}

# Validate that $1 is an IPv4 address
CheckIP()
{
	if [ 1 -ne $# ]; then
		LogMsg "CheckIP accepts 1 arguments: IP address"
		return 100
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
CheckIPV6()
{
	if [ 1 -ne $# ]; then
		LogMsg "CheckIPV6 accepts 1 arguments: IPV6 address"
		return 100
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
CheckMAC()
{
	if [ 1 -ne $# ]; then
		LogMsg "CheckIP accepts 1 arguments: IP address"
		return 100
	fi

	# allow lower and upper-case, as well as : (colon) or - (hyphen) as separators
	echo "$1" | grep -E '^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$' >/dev/null 2>&1

	return $?

}

# Function to set interface $1 to whatever the dhcp server assigns
SetIPfromDHCP()
{
	if [ 1 -ne $# ]; then
		LogMsg "SetIPfromDHCP accepts 1 argument: network interface to assign the ip to"
		return 100
	fi

	# Check first argument
	ip link show "$1" >/dev/null 2>&1
	if [ 0 -ne $? ]; then
		LogMsg "Network adapter $1 is not working."
		return 1
	fi

	ip -4 addr flush "$1"

	GetDistro
	case $DISTRO in
		redhat*|fedora*|centos*|ubuntu*|debian*)
			dhclient -r "$1" ; dhclient "$1"
			if [ 0 -ne $? ]; then
				LogMsg "Unable to get dhcpd address for interface $1"
				return 2
			fi
			;;
		suse*)
			dhcpcd -k "$1" ; dhcpcd "$1"
			if [ 0 -ne $? ]; then
				LogMsg "Unable to get dhcpd address for interface $1"
				return 2
			fi
			;;
		*)
			LogMsg "Platform not supported yet!"
			return 3
			;;
	esac

	declare __IP_ADDRESS
	# Get IP-Address
	__IP_ADDRESS=$(ip -o addr show "$1" | grep -vi inet6 | cut -d '/' -f1 | awk '{print $NF}')

	if [ -z "$__IP_ADDRESS" ]; then
		LogMsg "IP address did not get assigned to $1"
		return 3
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
SetIPstatic()
{
	if [ 2 -gt $# ]; then
		LogMsg "SetIPstatic accepts 3 arguments: 1. static IP, 2. network interface, 3. (optional) netmask"
		return 100
	fi

	CheckIP "$1"
	if [ 0 -ne $? ]; then
		LogMsg "Parameter $1 is not a valid IPv4 Address"
		return 1
	fi

	ip link show "$2" > /dev/null 2>&1
	if [ 0 -ne $? ]; then
		LogMsg "Network adapter $2 is not working."
		return 2
	fi

	declare __netmask
	declare __interface
	declare __ip

	__netmask=${3:-255.255.255.0}
	__interface="$2"
	__ip="$1"

	echo "$__netmask" | grep '.' >/dev/null 2>&1
	if [  0 -eq $? ]; then
		__netmask=$(NetmaskToCidr "$__netmask")
		if [ 0 -ne $? ]; then
			LogMsg "SetIPstatic: $__netmask is not a valid netmask"
			return 3
		fi
	fi

	if [ "$__netmask" -ge 32 -o "$__netmask" -le 0 ]; then
		LogMsg "SetIPstatic: $__netmask is not a valid cidr netmask"
		return 4
	fi

	ip link set "$__interface" down
	ip addr flush "$__interface"
	ip addr add "$__ip"/"$__netmask" dev "$__interface"
	ip link set "$__interface" up

	if [ 0 -ne $? ]; then
		LogMsg "Unable to assign address $__ip/$__netmask to $__interface."
		return 5
	fi

	# Get IP-Address
	declare __IP_ADDRESS
	__IP_ADDRESS=$(ip -o addr show "${SYNTH_NET_INTERFACES[$__iterator]}" | grep -vi inet6 | cut -d '/' -f1 | awk '{print $NF}' | grep -vi '[a-z]')

	if [ -z "$__IP_ADDRESS" ]; then
		LogMsg "IP address $__ip did not get assigned to $__interface"
		return 3
	fi

	# Check that addresses match
	if [ "$__IP_ADDRESS" != "$__ip" ]; then
		LogMsg "New address $__IP_ADDRESS differs from static ip $__ip on interface $__interface"
		return 6
	fi

	# OK
	return 0
}

# translate network mask to CIDR notation
# Parameters:
# $1 == valid network mask
NetmaskToCidr()
{
	if [ 1 -ne $# ]; then
		LogMsg "NetmaskToCidr accepts 1 argument: a valid network mask"
		return 100
	fi

	declare -i netbits=0
	oldifs="$IFS"
	IFS=.

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
				LogMsg "NetmaskToCidr: $1 is not a valid netmask"
				return 1
				;;
		esac
	done

	echo $netbits

	return 0
}

# Remove all default gateways
RemoveDefaultGateway()
{
	while ip route del default >/dev/null 2>&1
	do : #nothing
	done

	return 0
}

# Create default gateway
# Parameters:
# $1 == gateway ip
# $2 == interface
CreateDefaultGateway()
{
	if [ 2 -ne $# ]; then
		LogMsg "CreateDefaultGateway expects 2 arguments"
		return 100
	fi

	# check that $1 is an IP address
	CheckIP "$1"

	if [ 0 -ne $? ]; then
		LogMsg "CreateDefaultGateway: $1 is not a valid IP Address"
		return 1
	fi

	# check interface exists
	ip link show "$2" >/dev/null 2>&1
	if [ 0 -ne $? ]; then
		LogMsg "CreateDefaultGateway: no interface $2 found."
		return 2
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
		LogMsg "CreateDefaultGateway: unable to set $__ipv4 as a default gateway for interface $__interface"
		return 3
	fi

	# check to make sure default gateway actually was created
	ip route show | grep -i "default via $__ipv4 dev $__interface" >/dev/null 2>&1

	if [ 0 -ne $? ]; then
		LogMsg "CreateDefaultGateway: Route command succeded, but gateway does not appear to have been set."
		return 4
	fi

	return 0
}

# Create Vlan Config
# Parameters:
# $1 == interface for which to create the vlan config file
# $2 == static IP to set for vlan interface
# $3 == netmask for that interface
# $4 == vlan ID
CreateVlanConfig()
{
	if [ 4 -ne $# ]; then
		LogMsg "CreateVlanConfig expects 4 arguments"
		return 100
	fi

	# check interface exists
	ip link show "$1" >/dev/null 2>&1
	if [ 0 -ne $? ]; then
		LogMsg "CreateVlanConfig: no interface $1 found."
		return 1
	fi

	# check that $2 is an IP address
	CheckIP "$2"
	if [[ $? -eq 0 ]]; then
	    netmaskConf="NETMASK"
	    ifaceConf="inet"
	    ipAddress="IPADDR"
	else
		CheckIPV6 "$2"
		if [[ $? -eq 0 ]]; then
	    	netmaskConf="PREFIX"
	    	ifaceConf="inet6"
	    	ipAddress="IPV6ADDR"
	    else
	    	LogMsg "CreateVlanConfig: $2 is not a valid IP Address"
			return 2
		fi
	fi

	declare __noreg='^[0-4096]+'
	# check $4 for valid vlan range
	if ! [[ $4 =~ $__noreg ]] ; then
		LogMsg "CreateVlanConfig: invalid vlan ID $4 received."
		return 3
	fi

	# check that vlan driver is loaded
	lsmod | grep 8021q

	if [ 0 -ne $? ]; then
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

	GetDistro
	case $DISTRO in
		redhat*|centos*|fedora*)
			__file_path="/etc/sysconfig/network-scripts/ifcfg-$__interface"
			if [ -e "$__file_path" ]; then
				LogMsg "CreateVlanConfig: warning, $__file_path already exists."
				if [ -d "$__file_path" ]; then
					rm -rf "$__file_path"
				else
					rm -f "$__file_path"
				fi
			fi

			__vlan_file_path="/etc/sysconfig/network-scripts/ifcfg-$__interface.$__vlanID"
			if [ -e "$__vlan_file_path" ]; then
				LogMsg "CreateVlanConfig: warning, $__vlan_file_path already exists."
				if [ -d "$__vlan_file_path" ]; then
					rm -rf "$__vlan_file_path"
				else
					rm -f "$__vlan_file_path"
				fi
			fi

			cat <<-EOF > "$__file_path"
				DEVICE=$__interface
				TYPE=Ethernet
				BOOTPROTO=none
				ONBOOT=yes
			EOF

			cat <<-EOF > "$__vlan_file_path"
				DEVICE=$__interface.$__vlanID
				BOOTPROTO=none
				$ipAddress=$__ip
				$netmaskConf=$__netmask
				ONBOOT=yes
				VLAN=yes
			EOF

			ifdown "$__interface"
			ifup "$__interface"
			ifup "$__interface.$__vlanID"

			;;
		suse_12*)
			__file_path="/etc/sysconfig/network/ifcfg-$__interface"
			if [ -e "$__file_path" ]; then
				LogMsg "CreateVlanConfig: warning, $__file_path already exists."
				if [ -d "$__file_path" ]; then
					rm -rf "$__file_path"
				else
					rm -f "$__file_path"
				fi
			fi

			__vlan_file_path="/etc/sysconfig/network/ifcfg-$__interface.$__vlanID"
			if [ -e "$__vlan_file_path" ]; then
				LogMsg "CreateVlanConfig: warning, $__vlan_file_path already exists."
				if [ -d "$__vlan_file_path" ]; then
					rm -rf "$__vlan_file_path"
				else
					rm -f "$__vlan_file_path"
				fi
			fi

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
			__file_path="/etc/sysconfig/network/ifcfg-$__interface"
			if [ -e "$__file_path" ]; then
				LogMsg "CreateVlanConfig: warning, $__file_path already exists."
				if [ -d "$__file_path" ]; then
					rm -rf "$__file_path"
				else
					rm -f "$__file_path"
				fi
			fi

			__vlan_file_path="/etc/sysconfig/network/ifcfg-$__interface.$__vlanID"
			if [ -e "$__vlan_file_path" ]; then
				LogMsg "CreateVlanConfig: warning, $__vlan_file_path already exists."
				if [ -d "$__vlan_file_path" ]; then
					rm -rf "$__vlan_file_path"
				else
					rm -f "$__vlan_file_path"
				fi
			fi

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

			ifdown "$__interface"
			ifup "$__interface"
			ifup "$__interface.$__vlanID"
			;;
		debian*|ubuntu*)
			#Check for vlan package and install it in case of absence
			dpkg -s vlan
			if [ 0 -ne $? ]; then
				apt -y install vlan
				if [ 0 -ne $? ]; then
					LogMsg "Failed to install VLAN package. Please try manually."
					return 90
				fi
			fi
			__file_path="/etc/network/interfaces"
			if [ ! -e "$__file_path" ]; then
				LogMsg "CreateVlanConfig: warning, $__file_path does not exist. Creating it..."
				if [ -d "$(dirname $__file_path)" ]; then
					touch "$__file_path"
				else
					rm -f "$(dirname $__file_path)"
					LogMsg "CreateVlanConfig: Warning $(dirname $__file_path) is not a directory"
					mkdir -p "$(dirname $__file_path)"
					touch "$__file_path"
				fi
			fi

			declare __first_iface
			declare __last_line
			declare __second_iface
			# delete any previously existing lines containing the desired vlan interface
			# get first line number containing our interested interface
			__first_iface=$(awk "/iface $__interface/ { print NR; exit }" "$__file_path")
			# if there was any such line found, delete it and any related config lines
			if [ -n "$__first_iface" ]; then
				# get the last line of the file
				__last_line=$(wc -l $__file_path | cut -d ' ' -f 1)
				# sanity check
				if [ "$__first_iface" -gt "$__last_line" ]; then
					LogMsg "CreateVlanConfig: error while parsing $__file_path . First iface line is gt last line in file"
					return 100
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
						LogMsg "CreateVlanConfig: error while parsing $__file_path . Second iface line is gt last line in file"
						return 100
					fi

					if [ "$__second_iface" -le "$__first_iface" ]; then
						LogMsg "CreateVlanConfig: error while parsing $__file_path . Second iface line is gt last line in file"
						return 100
					fi
				fi
				# now delete all lines between the first iface and the second iface
				sed -i "$__first_iface,${__second_iface}d" "$__file_path"
			fi

			sed -i "/auto $__interface/d" "$__file_path"
			# now append our config to the end of the file
			cat << EOF >> "$__file_path"
auto $__interface
iface $__interface inet static
	address 0.0.0.0

auto $__interface.$__vlanID
iface $__interface.$__vlanID $ifaceConf static
	address $__ip
	netmask $__netmask
EOF

			ifdown "$__interface"
			ifup $__interface
			ifup $__interface.$__vlanID
			;;
		*)
			LogMsg "Platform not supported yet!"
			return 4
			;;
	esac

	sleep 5

	# verify change took place
	cat /proc/net/vlan/config | grep " $__vlanID "

	if [ 0 -ne $? ]; then
		LogMsg "/proc/net/vlan/config has no vlanID of $__vlanID"
		return 5
	fi

	return 0
}

# Remove Vlan Config
# Parameters:
# $1 == interface from which to remove the vlan config file
# $2 == vlan ID
RemoveVlanConfig()
{
	if [ 2 -ne $# ]; then
		LogMsg "RemoveVlanConfig expects 2 arguments"
		return 100
	fi

	# check interface exists
	ip link show "$1" >/dev/null 2>&1
	if [ 0 -ne $? ]; then
		LogMsg "RemoveVlanConfig: no interface $1 found."
		return 1
	fi

	declare __noreg='^[0-4096]+'
	# check $2 for valid vlan range
	if ! [[ $2 =~ $__noreg ]] ; then
		LogMsg "RemoveVlanConfig: invalid vlan ID $2 received."
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
				LogMsg "RemoveVlanConfig: found $__file_path ."
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
				LogMsg "RemoveVlanConfig: found $__file_path ."
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
				LogMsg "RemoveVlanConfig: found $__file_path ."
				if [ -d "$__file_path" ]; then
					rm -rf "$__file_path"
				else
					rm -f "$__file_path"
				fi
			fi

			ifdown $__interface.$__vlanID
			ifdown $__interface
			ifup $__interface

			# make sure the interface is down
			ip link set "$__interface.$__vlanID" down
			;;
		debian*|ubuntu*)
			__file_path="/etc/network/interfaces"
			if [ ! -e "$__file_path" ]; then
				LogMsg "RemoveVlanConfig: warning, $__file_path does not exist."
				return 0
			fi
			if [ ! -d "$(dirname $__file_path)" ]; then
				LogMsg "RemoveVlanConfig: warning, $(dirname $__file_path) does not exist."
				return 0
			else
				rm -f "$(dirname $__file_path)"
				LogMsg "CreateVlanConfig: Warning $(dirname $__file_path) is not a directory"
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
					LogMsg "CreateVlanConfig: error while parsing $__file_path . First iface line is gt last line in file"
					return 100
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
						LogMsg "CreateVlanConfig: error while parsing $__file_path . Second iface line is gt last line in file"
						return 100
					fi

					if [ "$__second_iface" -le "$__first_iface" ]; then
						LogMsg "CreateVlanConfig: error while parsing $__file_path . Second iface line is gt last line in file"
						return 100
					fi
				fi
				# now delete all lines between the first iface and the second iface
				sed -i "$__first_iface,${__second_iface}d" "$__file_path"
			fi

			sed -i "/auto $__interface.$__vlanID/d" "$__file_path"

			;;
		*)
			LogMsg "Platform not supported yet!"
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
CreateIfupConfigFile()
{
	if [ 2 -gt $# -o 4 -lt $# ]; then
		LogMsg "CreateIfupConfigFile accepts between 2 and 4 arguments"
		return 100
	fi

	# check interface exists
	ip link show "$1" >/dev/null 2>&1
	if [ 0 -ne $? ]; then
		LogMsg "CreateIfupConfigFile: no interface $1 found."
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
			LogMsg "CreateIfupConfigFile: \$2 needs to be either static or dhcp (received $2)"
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
					LogMsg "CreateIfupConfigFile: $(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 3
				fi

				if [ -e "$__file_path" ]; then
					LogMsg "CreateIfupConfigFile: Warning will overwrite $__file_path ."
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
					LogMsg "CreateIfupConfigFile: $(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 3
				fi

				if [ -e "$__file_path" ]; then
					LogMsg "CreateIfupConfigFile: Warning will overwrite $__file_path ."
				fi

				cat <<-EOF > "$__file_path"
					STARTMODE=manual
					BOOTPROTO=dhcp
				EOF

				ifdown "$__interface_name"
				ifup "$__interface_name"

				;;
			redhat_7|redhat_8|centos_7|centos_8|fedora*)
				__file_path="/etc/sysconfig/network-scripts/ifcfg-$__interface_name"
				if [ ! -d "$(dirname $__file_path)" ]; then
					LogMsg "CreateIfupConfigFile: $(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 3
				fi

				if [ -e "$__file_path" ]; then
					LogMsg "CreateIfupConfigFile: Warning will overwrite $__file_path ."
				fi

				cat <<-EOF > "$__file_path"
					DEVICE="$__interface_name"
					BOOTPROTO=dhcp
				EOF

				ifdown "$__interface_name"
				ifup "$__interface_name"

				;;
			redhat_6|centos_6)
				__file_path="/etc/sysconfig/network-scripts/ifcfg-$__interface_name"
				if [ ! -d "$(dirname $__file_path)" ]; then
					LogMsg "CreateIfupConfigFile: $(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 3
				fi

				if [ -e "$__file_path" ]; then
					LogMsg "CreateIfupConfigFile: Warning will overwrite $__file_path ."
				fi

				cat <<-EOF > "$__file_path"
					DEVICE="$__interface_name"
					BOOTPROTO=dhcp
					IPV6INIT=yes
				EOF

				ifdown "$__interface_name"
				ifup "$__interface_name"

				;;
			redhat_5|centos_5)
				__file_path="/etc/sysconfig/network-scripts/ifcfg-$__interface_name"
				if [ ! -d "$(dirname $__file_path)" ]; then
					LogMsg "CreateIfupConfigFile: $(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 3
				fi

				if [ -e "$__file_path" ]; then
					LogMsg "CreateIfupConfigFile: Warning will overwrite $__file_path ."
				fi

				cat <<-EOF > "$__file_path"
					DEVICE="$__interface_name"
					BOOTPROTO=dhcp
					IPV6INIT=yes
				EOF

				cat <<-EOF >> "/etc/sysconfig/network"
					NETWORKING_IPV6=yes
				EOF

				ifdown "$__interface_name"
				ifup "$__interface_name"

				;;
			debian*|ubuntu*)
				__file_path="/etc/network/interfaces"
				if [ ! -d "$(dirname $__file_path)" ]; then
					LogMsg "CreateIfupConfigFile: $(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 3
				fi

				if [ -e "$__file_path" ]; then
					LogMsg "CreateIfupConfigFile: Warning will overwrite $__file_path ."
				fi

				#Check if interface is already configured. If so, delete old config
				if grep -q "$__interface_name" $__file_path
				then
					LogMsg "CreateIfupConfigFile: Warning will delete older configuration of interface $__interface_name"
				    sed -i "/$__interface_name/d" $__file_path
				fi

				cat <<-EOF >> "$__file_path"
					auto $__interface_name
					iface $__interface_name inet dhcp
				EOF

				service network-manager restart
				ifdown "$__interface_name"
				ifup "$__interface_name"

				;;
			*)
				LogMsg "CreateIfupConfigFile: Platform not supported yet!"
				return 3
				;;
		esac
	else
		# create config file for static
		if [ $# -ne 4 ]; then
			LogMsg "CreateIfupConfigFile: if static config is selected, please provide 4 arguments"
			return 100
		fi

		if [[ $3 == *":"* ]]; then
			CheckIPV6 "$3"
			if [ 0 -ne $? ]; then
				LogMsg "CreateIfupConfigFile: $3 is not a valid IPV6 Address"
				return 2
			fi
			ipv6=true
		else
			CheckIP "$3"
			if [ 0 -ne $? ]; then
				LogMsg "CreateIfupConfigFile: $3 is not a valid IP Address"
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
					LogMsg "CreateIfupConfigFile: $(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 3
				fi

				if [ -e "$__file_path" ]; then
					LogMsg "CreateIfupConfigFile: Warning will overwrite $__file_path ."
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
					LogMsg "CreateIfupConfigFile: $(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 3
				fi

				if [ -e "$__file_path" ]; then
					LogMsg "CreateIfupConfigFile: Warning will overwrite $__file_path ."
				fi

				cat <<-EOF > "$__file_path"
					STARTMODE=manual
					BOOTPROTO=static
					IPADDR="$__ip"
					NETMASK="$__netmask"
				EOF

				ifdown "$__interface_name"
				ifup "$__interface_name"
				;;
			redhat*|centos*|fedora*)
				__file_path="/etc/sysconfig/network-scripts/ifcfg-$__interface_name"
				if [ ! -d "$(dirname $__file_path)" ]; then
					LogMsg "CreateIfupConfigFile: $(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 3
				fi

				if [ -e "$__file_path" ]; then
					LogMsg "CreateIfupConfigFile: Warning will overwrite $__file_path ."
				fi

				if [[ $ipv6 == false ]]; then
					cat <<-EOF > "$__file_path"
						DEVICE="$__interface_name"
						BOOTPROTO=none
						IPADDR="$__ip"
						NETMASK="$__netmask"
						NM_CONTROLLED=no
					EOF
				else
					cat <<-EOF > "$__file_path"
						DEVICE="$__interface_name"
						BOOTPROTO=none
						IPV6ADDR="$__ip"
						IPV6INIT=yes
						PREFIX="$__netmask"
						NM_CONTROLLED=no
					EOF
				fi

				ifdown "$__interface_name"
				ifup "$__interface_name"
				;;

			debian*|ubuntu*)
				__file_path="/etc/network/interfaces"
				if [ ! -d "$(dirname $__file_path)" ]; then
					LogMsg "CreateIfupConfigFile: $(dirname $__file_path) does not exist! Something is wrong with the network config!"
					return 3
				fi

				if [ -e "$__file_path" ]; then
					LogMsg "CreateIfupConfigFile: Warning will overwrite $__file_path ."
				fi

				#Check if interface is already configured. If so, delete old config
				if grep -q "$__interface_name" $__file_path
				then
					LogMsg "CreateIfupConfigFile: Warning will delete older configuration of interface $__interface_name"
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

				service network-manager restart
				ifdown "$__interface_name"
				ifup "$__interface_name"

				;;
			*)
				LogMsg "CreateIfupConfigFile: Platform not supported yet!"
				return 3
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
ControlNetworkManager()
{
	if [ 1 -ne $# ]; then
		LogMsg "ControlNetworkManager accepts 1 argument: start | stop"
		return 100
	fi

	# Check first argument
	if [ x"$1" != xstop ]; then
		if [ x"$1" != xstart ]; then
			LogMsg "ControlNetworkManager accepts 1 argument: start | stop."
			return 100
		fi
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
			LogMsg "Platform not supported yet!"
			return 3
			;;
	esac

	return 0
}

# Convenience Function to disable NetworkManager
DisableNetworkManager()
{
	ControlNetworkManager stop
	# propagate return value from ControlNetworkManager
	return $?
}

# Convenience Function to enable NetworkManager
EnableNetworkManager()
{
	ControlNetworkManager start
	# propagate return value from ControlNetworkManager
	return $?
}

# Setup a bridge named br0
# $1 == Bridge IP Address
# $2 == Bridge netmask
# $3 - $# == Interfaces to attach to bridge
# if no parameter is given outside of IP and Netmask, all interfaces will be added (except lo)
SetupBridge()
{
	if [ $# -lt 2 ]; then
		LogMsg "SetupBridge needs at least 2 parameters"
		return 1
	fi

	declare -a __bridge_interfaces
	declare __bridge_ip
	declare __bridge_netmask

	CheckIP "$1"

	if [ 0 -ne $? ]; then
		LogMsg "SetupBridge: $1 is not a valid IP Address"
		return 2
	fi

	__bridge_ip="$1"
	__bridge_netmask="$2"

	echo "$__bridge_netmask" | grep '.' >/dev/null 2>&1
	if [  0 -eq $? ]; then
		__bridge_netmask=$(NetmaskToCidr "$__bridge_netmask")
		if [ 0 -ne $? ]; then
			LogMsg "SetupBridge: $__bridge_netmask is not a valid netmask"
			return 3
		fi
	fi

	if [ "$__bridge_netmask" -ge 32 -o "$__bridge_netmask" -le 0 ]; then
		LogMsg "SetupBridge: $__bridge_netmask is not a valid cidr netmask"
		return 4
	fi

	if [ 2 -eq $# ]; then
		LogMsg "SetupBridge received no interface argument. All network interfaces found will be attached to the bridge."
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
			LogMsg "SetupBridge: No interfaces found"
			return 3
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
				LogMsg "SetupBridge: Interface $__iterator not working or not present"
				return 4
			fi
			__bridge_interfaces=("${__bridge_interfaces[@]}" "$__iterator")
		done
	fi

	# create bridge br0
	brctl addbr br0
	if [ 0 -ne $? ]; then
		LogMsg "SetupBridge: unable to create bridge br0"
		return 5
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
			LogMsg "SetupBridge: unable to add interface $__iface to bridge br0"
			return 6
		fi
		LogMsg "SetupBridge: Added $__iface to bridge"
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
	LogMsg "SetupBridge: Successfull"
	# done
	return 0
}

# TearDown Bridge br0
TearDownBridge()
{
	ip link show br0 >/dev/null 2>&1
	if [ 0 -ne $? ]; then
		LogMsg "TearDownBridge: No interface br0 found"
		return 1
	fi

	brctl show br0
	if [ 0 -ne $? ]; then
		LogMsg "TearDownBridge: No bridge br0 found"
		return 2
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
			msg="TearDownBridge: MAC Address $__mac does not belong to any interface."
			LogMsg "$msg"
			UpdateSummary "$msg"
			SetTestStateFailed
			return 3
		fi

		# get just the interface name from the path
		__bridge_interfaces=$(basename "$(dirname "$__sys_interface")")

		ip link show "$__bridge_interfaces" >/dev/null 2>&1
		if [ 0 -ne $? ]; then
			LogMsg "TearDownBridge: Could not find interface $__bridge_interfaces"
			return 4
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

IsFreeSpace()
{
	if [ 2 -ne $# ]; then
		LogMsg "IsFreeSpace takes 2 arguments: path/to/dir to check for free space and number of bytes needed free"
		return 100
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
    if [[ -x "`which sw_vers 2>/dev/null`" ]]; then
        # OS/X
        os_VENDOR=`sw_vers -productName`
        os_RELEASE=`sw_vers -productVersion`
        os_UPDATE=${os_RELEASE##*.}
        os_RELEASE=${os_RELEASE%.*}
        os_PACKAGE=""
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
            if [[ -n "`grep \"$r\" /etc/redhat-release`" ]]; then
                ver=`sed -e 's/^.* \([0-9].*\) (\(.*\)).*$/\1\|\2/' /etc/redhat-release`
                os_CODENAME=${ver#*|}
                os_RELEASE=${ver%|*}
                os_UPDATE=${os_RELEASE##*.}
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
        os_VENDOR=`head -1 /etc/S*SE-brand`
        os_VERSION=`cat /etc/S*SE-brand | awk '/VERSION/ {print $NF}'`
        os_RELEASE=$os_VERSION
        os_PACKAGE="rpm"

    elif [[ -r /etc/SuSE-release ]]; then
        for r in openSUSE "SUSE Linux"; do
            if [[ "$r" = "SUSE Linux" ]]; then
                os_VENDOR="SUSE LINUX"
            else
                os_VENDOR=$r
            fi

            if [[ -n "`grep \"$r\" /etc/SuSE-release`" ]]; then
                os_CODENAME=`grep "CODENAME = " /etc/SuSE-release | sed 's:.* = ::g'`
                os_RELEASE=`grep "VERSION = " /etc/SuSE-release | sed 's:.* = ::g'`
                os_UPDATE=`grep "PATCHLEVEL = " /etc/SuSE-release | sed 's:.* = ::g'`
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
    fi
    export os_VENDOR os_RELEASE os_UPDATE os_PACKAGE os_CODENAME
}

#######################################################################
# Determine if current distribution is a Fedora-based distribution
# (Fedora, RHEL, CentOS, etc).
#######################################################################
function is_fedora {
    if [[ -z "$os_VENDOR" ]]; then
        GetOSVersion
    fi

    [ "$os_VENDOR" = "Fedora" ] || [ "$os_VENDOR" = "Red Hat" ] || \
        [ "$os_VENDOR" = "CentOS" ] || [ "$os_VENDOR" = "OracleServer" ]
}

#######################################################################
# Determine if current distribution is a Rhel/CentOS 7 distribution
#######################################################################

function is_rhel7 {
    if [[ -z "$os_RELEASE" ]]; then
        GetOSVersion
    fi

    [ "$os_VENDOR" = "Red Hat" ] || \
        [ "$os_VENDOR" = "CentOS" ] || [ "$os_VENDOR" = "OracleServer" ] && \
        [[ $os_RELEASE =~ 7.* ]] && [[ $os_RELEASE != 6.7 ]]
}

#######################################################################
# Determine if current distribution is a SUSE-based distribution
# (openSUSE, SLE).
#######################################################################
function is_suse {
    if [[ -z "$os_VENDOR" ]]; then
        GetOSVersion
    fi

    [ "$os_VENDOR" = "openSUSE" ] || [ "$os_VENDOR" = "SUSE LINUX" ] || \
    [ "$os_VENDOR" = "SUSE" ] || [ "$os_VENDOR" = "SLE" ] || \
    [ "$os_VENDOR" = "SLES" ]
}

#######################################################################
# Determine if current distribution is an Ubuntu-based distribution
# It will also detect non-Ubuntu but Debian-based distros
#######################################################################
function is_ubuntu {
    if [[ -z "$os_PACKAGE" ]]; then
        GetOSVersion
    fi
    [ "$os_PACKAGE" = "deb" ]
}

GetGuestGeneration()
{
    if [ -d /sys/firmware/efi/ ]; then
        os_GENERATION=2
    else
        os_GENERATION=1
    fi
}

#######################################################################
# Perform a minor kernel upgrade on CentOS/RHEL distros
#######################################################################
UpgradeMinorKernel() {
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

VerifyIsEthtool()
{
    # Check for ethtool. If it's not on the system, install it.
    ethtool --version
    if [ $? -ne 0 ]; then
        LogMsg "INFO: Ethtool not found. Trying to install it."
        GetDistro
        case "$DISTRO" in
            suse*)
                zypper --non-interactive in ethtool
                if [ $? -ne 0 ]; then
                    msg="ERROR: Failed to install Ethtool"
                    LogMsg "$msg"
                    UpdateSummary "$msg"
                    SetTestStateFailed
                    exit 1
                fi
                ;;
            ubuntu*|debian*)
                apt install ethtool -y
                if [ $? -ne 0 ]; then
                    msg="ERROR: Failed to install Ethtool"
                    LogMsg "$msg"
                    UpdateSummary "$msg"
                    SetTestStateFailed
                    exit 1
                fi
                ;;
            redhat*|centos*)
                yum install ethtool -y
                if [ $? -ne 0 ]; then
                    msg="ERROR: Failed to install Ethtool"
                    LogMsg "$msg"
                    UpdateSummary "$msg"
                    SetTestStateFailed
                    exit 1
                fi
                ;;
                *)
                    msg="ERROR: OS Version not supported"
                    LogMsg "$msg"
                    UpdateSummary "$msg"
                    SetTestStateFailed
                    exit 1
                ;;
        esac
    fi
    LogMsg "Info: Ethtool is installed!"
}


#list all network interfaces without eth0
ListInterfaces()
{
    # Parameter provided in constants file
    #    ipv4 is the IP Address of the interface used to communicate with the VM, which needs to remain unchanged
    #    it is not touched during this test (no dhcp or static ip assigned to it)

    if [ "${ipv4:-UNDEFINED}" = "UNDEFINED" ]; then
        msg="The test parameter ipv4 is not defined in constants file!"
        LogMsg "$msg"
        UpdateSummary "$msg"
        SetTestStateAborted
        exit 30
    else

        CheckIP "$ipv4"
        if [ 0 -ne $? ]; then
            msg="Test parameter ipv4 = $ipv4 is not a valid IP Address"
            LogMsg "$msg"
            UpdateSummary "$msg"
            SetTestStateAborted
            exit 10
        fi

        # Get the interface associated with the given ipv4
        __iface_ignore=$(ip -o addr show | grep "$ipv4" | cut -d ' ' -f2)
    fi

    GetSynthNetInterfaces
    if [ 0 -ne $? ]; then
        msg="No synthetic network interfaces found"
        LogMsg "$msg"
        UpdateSummary "$msg"
        SetTestStateFailed
        exit 10
    fi
    # Remove interface if present
    SYNTH_NET_INTERFACES=(${SYNTH_NET_INTERFACES[@]/$__iface_ignore/})

    if [ ${#SYNTH_NET_INTERFACES[@]} -eq 0 ]; then
        msg="The only synthetic interface is the one which LIS uses to send files/commands to the VM."
        LogMsg "$msg"
        UpdateSummary "$msg"
        SetTestStateAborted
        exit 10
    fi
    LogMsg "Found ${#SYNTH_NET_INTERFACES[@]} synthetic interface(s): ${SYNTH_NET_INTERFACES[*]} in VM"
}

# Function that will check for Call Traces on VM after 2 minutes
# This function assumes that check_traces.sh is already on the VM
CheckCallTracesWithDelay()
{
    dos2unix -q check_traces.sh
    echo 'sleep 5 && bash ~/check_traces.sh ~/check_traces.log &' > runtest_traces.sh
    bash runtest_traces.sh > check_traces.log 2>&1
    sleep $1
    cat ~/check_traces.log | grep ERROR
    if [ $? -eq 0 ]; then
        msg="ERROR: Call traces have been found on VM after the test run"
        LogMsg "$msg"
        UpdateSummary "$msg"
        SetTestStateFailed
        exit 1
    else
        return 0
    fi
}


# Get the verison of LIS
function get_lis_version ()
{
	lis_version=$(modinfo hv_vmbus | grep "^version:"| awk '{print $2}')
	if [ "$lis_version" == "" ]; then
		lis_version="Default_LIS"
	fi
	echo $lis_version
}

# Get the version of host
function get_host_version ()
{
	dmesg | grep "Host Build" | sed "s/.*Host Build://"| awk '{print  $1}'| sed "s/;//"
}

# Validate the exit status of previous execution
function check_exit_status ()
{
	exit_status=$?
	message=$1

	cmd="echo"
	if [ ! -z $2 ]; then
		cmd=$2
	fi

	if [ $exit_status -ne 0 ]; then
		$cmd "$message: Failed (exit code: $exit_status)"
		if [ "$2" == "exit" ]; then
			exit $exit_status
		fi
	else
		$cmd "$message: Success"
	fi
}

# Detect the version of Linux distribution, it gets the version only
function detect_linux_distribution_version() {
	local distro_version="Unknown"
	if [ -f /etc/centos-release ]; then
		distro_version=`cat /etc/centos-release | sed s/.*release\ // | sed s/\ .*//`
	elif [ -f /etc/oracle-release ]; then
		distro_version=`cat /etc/oracle-release | sed s/.*release\ // | sed s/\ .*//`
	elif [ -f /etc/redhat-release ]; then
		distro_version=`cat /etc/redhat-release | sed s/.*release\ // | sed s/\ .*//`
	elif [ -f /etc/os-release ]; then
		distro_version=`cat /etc/os-release|sed 's/"//g'|grep "VERSION_ID="| sed 's/VERSION_ID=//'| sed 's/\r//'`
	fi
	echo $distro_version
}

# Detect the Linux distribution name, it gets the name in lowercase
function detect_linux_distribution() {
	local linux_distribution=`cat /etc/*release*|sed 's/"//g'|grep "^ID="| sed 's/ID=//'`
	local temp_text=`cat /etc/*release*`
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
			yum makecache
			;;
		ubuntu|debian)
			apt-get update
			;;
		suse|opensuse|sles)
			zypper refresh
			;;
		*)
			echo "Unknown distribution"
			return 1
	esac
}

# Install RPM package
function install_rpm () {
	package_name=$1
	sudo rpm -ivh --nodeps  $package_name
	check_exit_status "install_rpm $package_name"
}

# Install DEB package
function install_deb () {
	package_name=$1
	sudo dpkg -i $package_name
	check_exit_status "dpkg -i $package_name"
	sudo apt-get install -f
	check_exit_status "install_deb $package_name"
}

# Apt-get install packages, parameter: package name
function apt_get_install ()
{
	package_name=$1
	sudo DEBIAN_FRONTEND=noninteractive apt-get install -y  --force-yes $package_name
	check_exit_status "apt_get_install $package_name"
}

# Yum install packages, parameter: package name
function yum_install ()
{
	package_name=$1
	sudo yum -y --nogpgcheck install $package_name
	check_exit_status "yum_install $package_name"
}

# Zypper install packages, parameter: package name
function zypper_install ()
{
	package_name=$1
	sudo zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys in $package_name
	check_exit_status "zypper_install $package_name"
}

# Install packages, parameter: package name
function install_package ()
{
	local package_name=$@
	for i in "${package_name[@]}"; do
		case "$DISTRO_NAME" in
			oracle|rhel|centos)
				yum_install "$package_name"
				;;

			ubuntu|debian)
				apt_get_install "$package_name"
				;;

			suse|opensuse|sles)
				zypper_install "$package_name"
				;;

			*)
				echo "Unknown distribution"
				return 1
		esac
	done
}

# Install EPEL repository on RHEL based distros
function install_epel () {
	case "$DISTRO_NAME" in
		oracle|rhel|centos)
			if [[ $DISTRO_VERSION =~ 6\. ]]; then
				epel_rpm_url="https://dl.fedoraproject.org/pub/epel/epel-release-latest-6.noarch.rpm"
			elif [[ $DISTRO_VERSION =~ 7\. ]]; then
				epel_rpm_url="https://dl.fedoraproject.org/pub/epel/epel-release-latest-7.noarch.rpm"
			else
				echo "Unsupported version to install epel repository"
				return 1
			fi
			;;
		*)
			echo "Unsupported distribution to install epel repository"
			return 1
	esac
	sudo rpm -ivh $epel_rpm_url
	check_exit_status "install_epel"
}

# Install sshpass
function install_sshpass () {
	which sshpass
	if [ $? -ne 0 ]; then
		echo "sshpass not installed\n Installing now..."
		if [ $DISTRO_NAME == "sles" ] && [[ $DISTRO_VERSION =~ 12 ]]; then
			rpm -ivh $SLES_12_SSHPASS_LINK
		else
			install_package "sshpass"
		fi
		check_exit_status "install_sshpass"
	fi
}

# Add benchmark repo on SLES
function add_sles_benchmark_repo () {
	if [ $DISTRO_NAME == "sles" ]; then
		case $DISTRO_VERSION in
			11*)
				repo_url="https://download.opensuse.org/repositories/benchmark/SLE_11_SP4/benchmark.repo"
				;;
			12*)
				repo_url="https://download.opensuse.org/repositories/benchmark/SLE_12_SP3_Backports/benchmark.repo"
				;;
			*)
				echo "Unsupported SLES version $DISTRO_VERSION for add_sles_benchmark_repo"
				return 1
		esac
		zypper addrepo $repo_url
	else
		echo "Unsupported distribution for add_sles_benchmark_repo"
		return 1
	fi
}

# Add network utilities repo on SLES
function add_sles_network_utilities_repo () {
	if [ $DISTRO_NAME == "sles" ]; then
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
				echo "Unsupported SLES version $DISTRO_VERSION for add_sles_network_utilities_repo"
				return 1
		esac
		zypper addrepo $repo_url
	else
		echo "Unsupported distribution for add_sles_network_utilities_repo"
		return 1
	fi
}

function dpkg_configure () {
	retry=5
	until [ $retry -le 0 ]; do
		sudo dpkg --force-all --configure -a && break
		retry=$[$retry - 1]
		sleep 5
		echo 'Trying again to run dpkg --configure ...'
	done
}

# Install fio and required packages
function install_fio () {
	echo "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of fio"
	update_repos
	case "$DISTRO_NAME" in
		rhel|centos)
			install_epel
			yum -y --nogpgcheck install wget sysstat mdadm blktrace libaio fio
			check_exit_status "install_fio"
			mount -t debugfs none /sys/kernel/debug
			;;

		ubuntu|debian)
			dpkg_configure
			apt-get install -y pciutils gawk mdadm wget sysstat blktrace bc fio
			check_exit_status "install_fio"
			mount -t debugfs none /sys/kernel/debug
			;;

		sles)
			if [[ $DISTRO_VERSION =~ 12|15 ]]; then
				add_sles_benchmark_repo
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install wget mdadm blktrace libaio1 sysstat
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install fio
			else
				echo "Unsupported SLES version"
				return 1
			fi
			# FIO is not available in the repository of SLES 15
			which fio
			if [ $? -ne 0 ]; then
				echo "Info: fio is not available in repository. So, Installing fio using rpm"
				fio_url="$PACKAGE_BLOB_LOCATION/fio-sles-x86_64.rpm"
				fio_file="fio-sles-x86_64.rpm"
				curl -o $fio_file $fio_url
				echo "zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install $fio_file"
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install $fio_file
				which fio
				if [ $? -ne 0 ]; then
					echo "Error: Unable to install fio from source/rpm"
					return 1
				fi
			else
				echo "Info: fio installed from repository"
			fi
			;;

		clear-linux-os)
			swupd bundle-add dev-utils-dev sysadmin-basic performance-tools os-testsuite-phoronix network-basic openssh-server dev-utils os-core os-core-dev
			;;

		*)
			echo "Unsupported distribution for install_fio"
			return 1
	esac
}

# Install iperf3 and required packages
function install_iperf3 () {
	ip_version=$1
	echo "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of iperf3"
	update_repos
	case "$DISTRO_NAME" in
		rhel|centos)
			install_epel
			yum -y --nogpgcheck install iperf3 sysstat bc psmisc
			iptables -F
			;;

		ubuntu)
			dpkg_configure
			apt-get -y install iperf3 sysstat bc psmisc
			if [ $ip_version -eq 6 ] && [[ $DISTRO_VERSION =~ 16 ]]; then
				nic_name=$(get_active_nic_name)
				echo "iface $nic_name inet6 auto" >> /etc/network/interfaces.d/50-cloud-init.cfg
				echo "up sleep 5" >> /etc/network/interfaces.d/50-cloud-init.cfg
				echo "up dhclient -1 -6 -cf /etc/dhcp/dhclient6.conf -lf /var/lib/dhcp/dhclient6.$nic_name.leases -v $nic_name || true" >> /etc/network/interfaces.d/50-cloud-init.cfg
				ifdown $nic_name && ifup $nic_name
			fi
			;;

		sles)
			if [[ $DISTRO_VERSION =~ 12|15 ]]; then
				add_sles_network_utilities_repo
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install sysstat git bc make gcc psmisc iperf3
			else
				echo "Unsupported SLES version"
				return 1
			fi
			# iperf3 is not available in the repository of SLES 12
			which iperf3
			if [ $? -ne 0 ]; then
				LogMsg "Info: iperf3 is not installed. So, Installing iperf3 using rpm"
				iperf_url="$PACKAGE_BLOB_LOCATION/iperf-sles-x86_64.rpm"
				libiperf_url="$PACKAGE_BLOB_LOCATION/libiperf0-sles-x86_64.rpm"
				rpm -ivh $iperf_url $libiperf_url
				which iperf3
				if [ $? -ne 0 ]; then
					LogMsg "Error: Unable to install iperf3 from source/rpm"
					UpdateTestState "TestAborted"
					return 1
				fi
			else
				echo "Info: iperf3 installed from repository"
			fi
			iptables -F
			;;


		clear-linux-os)
			swupd bundle-add dev-utils-dev sysadmin-basic performance-tools os-testsuite-phoronix network-basic openssh-server dev-utils os-core os-core-dev
			iptables -F
			;;

		*)
			echo "Unsupported distribution for install_iperf3"
			return 1
	esac
}

# Build and install lagscope
function build_lagscope () {
	rm -rf lagscope
	git clone https://github.com/Microsoft/lagscope
	pushd lagscope/src && make && make install
	popd
}

# Install lagscope and required packages
function install_lagscope () {
	echo "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of lagscope"
	update_repos
	case "$DISTRO_NAME" in
		rhel|centos)
			install_epel
			yum -y --nogpgcheck install libaio sysstat git bc make gcc
			build_lagscope
			iptables -F
			;;

		ubuntu)
			dpkg_configure
			apt-get -y install libaio1 sysstat git bc make gcc
			build_lagscope
			;;

		sles)
			if [[ $DISTRO_VERSION =~ 12|15 ]]; then
				add_sles_network_utilities_repo
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install sysstat git bc make gcc dstat psmisc
				build_lagscope
				iptables -F
			else
				echo "Unsupported SLES version"
				return 1
			fi
			;;

		clear-linux-os)
			swupd bundle-add dev-utils-dev sysadmin-basic performance-tools os-testsuite-phoronix network-basic openssh-server dev-utils os-core os-core-dev
			iptables -F
			;;

		*)
			echo "Unsupported distribution for install_lagscope"
			return 1
	esac
}

# Build and install ntttcp
function build_ntttcp () {
	wget https://github.com/Microsoft/ntttcp-for-linux/archive/v1.3.4.tar.gz
	tar -zxvf v1.3.4.tar.gz
	pushd ntttcp-for-linux-1.3.4/src/ && make && make install
	popd
}

# Install ntttcp and required packages
function install_ntttcp () {
	echo "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of ntttcp"
	update_repos
	case "$DISTRO_NAME" in
		rhel|centos)
			install_epel
			yum -y --nogpgcheck install wget libaio sysstat git bc make gcc dstat psmisc
			build_ntttcp
			build_lagscope
			iptables -F
			;;

		ubuntu)
			dpkg_configure
			apt-get -y install wget libaio1 sysstat git bc make gcc dstat psmisc
			build_ntttcp
			build_lagscope
			;;

		sles)
			if [[ $DISTRO_VERSION =~ 12|15 ]]; then
				add_sles_network_utilities_repo
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install wget sysstat git bc make gcc dstat psmisc
				build_ntttcp
				build_lagscope
				iptables -F
			else
				echo "Unsupported SLES version"
				return 1
			fi
			;;

		clear-linux-os)
			swupd bundle-add dev-utils-dev sysadmin-basic performance-tools os-testsuite-phoronix network-basic openssh-server dev-utils os-core os-core-dev
			iptables -F
			;;

		*)
			echo "Unsupported distribution for install_ntttcp"
			return 1
	esac
}

# Get the active NIC name
function get_active_nic_name () {
	if [ $DISTRO_NAME == "sles" ] && [[ $DISTRO_VERSION =~ 15 ]]; then
		zypper_install "net-tools-deprecated" > /dev/null
	fi
	echo $(route | grep '^default' | grep -o '[^ ]*$')
}

# Create partitions
function create_partitions () {
	disk_list=($@)
	echo "Creating partitions on ${disk_list[@]}"

	count=0
	while [ "x${disk_list[count]}" != "x" ]; do
		echo ${disk_list[$count]}
		(echo n; echo p; echo 2; echo; echo; echo t; echo fd; echo w;) | fdisk ${disk_list[$count]}
		count=$(( $count + 1 ))
	done
}

# Remove partitions
function remove_partitions () {
	disk_list=($@)
	echo "Creating partitions on ${disk_list[@]}"

	count=0
	while [ "x${disk_list[count]}" != "x" ]; do
		echo ${disk_list[$count]}
		(echo p; echo d; echo w;) | fdisk ${disk_list[$count]}
		count=$(( $count + 1 ))
	done
}

# Create RAID using unused data disks attached to the VM.
function create_raid_and_mount() {
	if [[ $# == 3 ]]; then
		local deviceName=$1
		local mountdir=$2
		local format=$3
	else
		local deviceName="/dev/md1"
		local mountdir=/data-dir
		local format="ext4"
	fi

	local uuid=""
	local list=""

	echo "IO test setup started.."
	list=(`fdisk -l | grep 'Disk.*/dev/sd[a-z]' |awk  '{print $2}' | sed s/://| sort| grep -v "/dev/sd[ab]$" `)

	lsblk
	install_package mdadm
	echo "--- Raid $deviceName creation started ---"
	(echo y)| mdadm --create $deviceName --level 0 --raid-devices ${#list[@]} ${list[@]}
	check_exit_status "$deviceName Raid creation"

	time mkfs -t $format $deviceName
	check_exit_status "$deviceName Raid format"

	mkdir $mountdir
	uuid=`blkid $deviceName| sed "s/.*UUID=\"//"| sed "s/\".*\"//"`
	echo "UUID=$uuid $mountdir $format defaults 0 2" >> /etc/fstab
	mount $deviceName $mountdir
	check_exit_status "RAID ($deviceName) mount on $mountdir as $format"
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

	install_sshpass

	if [ "x$host" == "x" ] || [ "x$user" == "x" ] || [ "x$passwd" == "x" ] || [ "x$filename" == "x" ] ; then
		echo "Usage: remote_copy -user <username> -passwd <user password> -host <host ipaddress> -filename <filename> -remote_path <location of the file on remote vm> -cmd <put/get>"
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

	status=`sshpass -p $passwd scp -o StrictHostKeyChecking=no -P $port $source_path $destination_path 2>&1`
	exit_status=$?
	echo $status
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
		echo "Usage: remote_exec -user <username> -passwd <user password> -host <host ipaddress> <onlycommand>"
		return
	fi

	if [ "x$port" == "x" ]; then
		port=22
	fi

	status=`sshpass -p $passwd ssh -t -o StrictHostKeyChecking=no -p $port $user@$host $cmd 2>&1`
	exit_status=$?
	echo $status
	return $exit_status
}

# Set root or any user's password
function set_user_password {
	if [[ $# == 3 ]]; then
		user=$1
		user_password=$2
		sudo_password=$3
	else
		echo "Usage: user user_password sudo_password"
		return -1
	fi

	hash=$(openssl passwd -1 $user_password)

	string=`echo $sudo_password | sudo -S cat /etc/shadow | grep $user`

	if [ "x$string" == "x" ]; then
		echo "$user not found in /etc/shadow"
		return -1
	fi

	IFS=':' read -r -a array <<< "$string"
	line="${array[0]}:$hash:${array[2]}:${array[3]}:${array[4]}:${array[5]}:${array[6]}:${array[7]}:${array[8]}"

	echo $sudo_password | sudo -S sed -i "s#^${array[0]}.*#$line#" /etc/shadow

	if [ `echo $sudo_password | sudo -S cat /etc/shadow| grep $line|wc -l` != "" ]; then
		echo "Password set succesfully"
	else
		echo "failed to set password"
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
	echo ",OS type,"`detect_linux_distribution` `detect_linux_distribution_version` >> $output_file
	echo ",Kernel version,"`uname -r` >> $output_file
	echo ",LIS Version,"`get_lis_version` >> $output_file
	echo ",Host Version,"`get_host_version` >> $output_file
	echo ",Total CPU cores,"`nproc` >> $output_file
	echo ",Total Memory,"`free -h|grep Mem|awk '{print $2}'` >> $output_file
	echo ",Resource disks size,"`lsblk|grep "^sdb"| awk '{print $4}'`  >> $output_file
	echo ",Data disks attached,"`lsblk | grep "^sd" | awk '{print $1}' | sort | grep -v "sd[ab]$" | wc -l`  >> $output_file
	echo ",eth0 MTU,"`ifconfig eth0|grep MTU|sed "s/.*MTU:\(.*\) .*/\1/"` >> $output_file
	echo ",eth1 MTU,"`ifconfig eth1|grep MTU|sed "s/.*MTU:\(.*\) .*/\1/"` >> $output_file
}

# Add command in startup files
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
				echo "Added $testcommand >> $file"
				((count++))
			fi
		fi
	done
	if [ $count == 0 ]; then
		echo "Cannot find $startup_files files"
	fi
}

# Remove command from startup files
function remove_cmd_from_startup () {
	testcommand=$*
	startup_files="/etc/rc.d/rc.local /etc/rc.local /etc/SuSE-release"
	count=0
	for file in $startup_files; do
		if [[ -f $file ]]; then
			if grep -q "${testcommand}" $file; then
				sed "s/${testcommand}//" $file -i
				((count++))
				echo "Removed $testcommand from $file"
			fi
		fi
	done
	if [ $count == 0 ]; then
		echo "Cannot find $testcommand in $startup_files files"
	fi
}

# Generate randon MAC address
function generate_random_mac_addr () {
	echo "52:54:00:$(dd if=/dev/urandom bs=512 count=1 2>/dev/null | md5sum | sed 's/^\(..\)\(..\)\(..\).*$/\1:\2:\3/')"
}

declare DISTRO_NAME=$(detect_linux_distribution)
declare DISTRO_VERSION=$(detect_linux_distribution_version)