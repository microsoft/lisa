#!/usr/bin/env bash
#######################################################################
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
# validate-da.sh
# Description:
#    Validate the installation and uninstallation of the Dependency Agent.
#    Validate the enable and disable of the Dependency Agent.
#######################################################################

set -e
set -x

# Source utils.sh
. utils.sh || {
    echo "ERROR: unable to source utils.sh!"
    echo "TestAborted" > state.txt
    exit 0
}

function check_prereqs() {
	LogMsg "Checking for preconditions"

	if [[ $EUID -ne 0 ]]; then
	   LogErr "This script must be run as root" 
	   exit 1
	fi

	[ -d "/opt/microsoft/dependency-agent" ] && LogErr "Directory /opt/microsoft/dependency-agent exists." && exit 1
	[ -d "/var/opt/microsoft/dependency-agent" ] && LogErr "Directory /var/opt/microsoft/dependency-agent exists." && exit 1
	[ -d "/etc/opt/microsoft/dependency-agent" ] && LogErr "Directory /etc/opt/microsoft/dependency-agent exists." && exit 1
	[ -d "/lib/microsoft-dependency-agent" ] && LogErr "Directory /lib/microsoft-dependency-agent exists." && exit 1
	[ -d "/etc/init.d/microsoft-dependency-agent" ] && LogErr "Directory /etc/init.d/microsoft-dependency-agent exists." && exit 1

	LogMsg "Preconditions met"
}

function download_da_linux_installer() {
	LogMsg "Download Dependency Agent Linux installer"

	curl -L https://aka.ms/dependencyagentlinux -o InstallDependencyAgent-Linux64.bin

	chmod +x InstallDependencyAgent-Linux64.bin
}

function verify_install_da() {
	./InstallDependencyAgent-Linux64.bin -vme

	ret=$?
	if [ $ret -ne 0 ]; then
	        LogErr "Install failed with exit code ${ret}"
	        exit 1
	else
	        LogMsg "Installed with exit code 0"
	fi

	[ ! -f "/opt/microsoft/dependency-agent/uninstall" ] && LogErr "/opt/microsoft/dependency-agent/uninstall does not exist." && exit 1
	[ ! -f "/etc/init.d/microsoft-dependency-agent" ] && LogErr "/etc/init.d/microsoft-dependency-agent does not exist." && exit 1
	[ ! -f "/var/opt/microsoft/dependency-agent/log/install.log" ] && LogErr "/var/opt/microsoft/dependency-agent/log/install.log does not exist." && exit 1

	bin_version=$(./InstallDependencyAgent-Linux64.bin --version | awk '{print $5}')
	install_log_version=$(awk "NR==3" /var/opt/microsoft/dependency-agent/log/install.log | grep 'Dependency Agent version.revision'|cut -f2 -d ":")
	if [ "$bin_version" -ne "$install_log_version" ]; then
	        LogErr "Version mismatch between bin version and install log version"
	        exit 1
	else
	        LogMsg "Version matches between bin version and install log version"
	fi

	LogMsg "Install tests passed successfully"
}

function verify_uninstall_da() {

	bash /opt/microsoft/dependency-agent/uninstall
	
	ret=$?
	if [ $ret -ne 0 ]; then
	        LogErr "Uninstall failed with exit code ${ret}"
	        exit 1
	else
	        LogMsg "Uninstalled with exit code 0"
	fi

	[ -d "/opt/microsoft/dependency-agent" ] && LogErr "Directory /opt/microsoft/dependency-agent exists." && exit 1
	[ -d "/var/opt/microsoft/dependency-agent" ] && LogErr "Directory /var/opt/microsoft/dependency-agent exists." && exit 1
	[ -d "/etc/opt/microsoft/dependency-agent" ] && LogErr "Directory /etc/opt/microsoft/dependency-agent exists." && exit 1
	[ -d "/lib/microsoft-dependency-agent" ] && LogErr "Directory /lib/microsoft-dependency-agent exists." && exit 1
	[ -d "/etc/init.d/microsoft-dependency-agent" ] && LogErr "Directory /etc/init.d/microsoft-dependency-agent exists." && exit 1

	LogMsg "Uninstall tests passed successfully"
}

function setup_network_trace() {
    LogMsg "Setup network trace"
	watch -n 5 curl https://microsoft.com &>/dev/null &
	watch_pid=$!
}

function enable_disable_da(){
	verify_install_da
	
	sleep 30
	[ ! -f "/var/opt/microsoft/dependency-agent/log/service.log" ] && LogErr "/var/opt/microsoft/dependency-agent/log/service.log does not exist." && exit 1

	service_log_time=$(date -r /var/opt/microsoft/dependency-agent/log/service.log +%s)
	current_time=$(date +%s)
	time_elapsed=$(($current_time - $service_log_time))
	sleep $((120-$time_elapsed))

	[ ! -f "/var/opt/microsoft/dependency-agent/log/service.log.1" ] && LogErr "/var/opt/microsoft/dependency-agent/log/service.log.1 does not exist." && exit 1
	[ -f "/var/opt/microsoft/dependency-agent/log/service.log.2" ] && LogErr "/var/opt/microsoft/dependency-agent/log/service.log.2 exist." && exit 1
	[ ! -c "/dev/msda" ] && LogErr "/dev/msda does not exist." && exit 1

	! grep -iq "driver setup status=0" /var/opt/microsoft/dependency-agent/log/service.log.1 && LogErr "driver setup status=0 not found" && exit 1
	! grep -iq "starting the dependency agent" /var/opt/microsoft/dependency-agent/log/service.log && LogErr "starting the dependency agent not found" && exit 1
	
	sleep 60
	[ ! -f "/var/opt/microsoft/dependency-agent/log/MicrosoftDependencyAgent.log" ] && LogErr "/var/opt/microsoft/dependency-agent/log/MicrosoftDependencyAgent.log does not exist." && exit 1
	[ ! -f "/etc/opt/microsoft/dependency-agent/config/DA_PID" ] && LogErr "/etc/opt/microsoft/dependency-agent/config/DA_PID does not exist." && exit 1
	
	if grep -iq "^[1-9][0-9]*$" /etc/opt/microsoft/dependency-agent/config/DA_PID; then
        x=$(grep -i "^[1-9][0-9]*$" /etc/opt/microsoft/dependency-agent/config/DA_PID)
        strings /proc/$x/cmdline | grep "/opt/microsoft/dependency-agent/bin/microsoft-dependency-agent-manager" && LogMsg "PID matched" || (LogErr "PID not matched" && exit 1)
	else
		LogErr "PID not found in DA_PID"
		exit 1 
	fi
	
	sleep 120
	! ls /var/opt/microsoft/dependency-agent/storage/*.bb && LogErr "/var/opt/microsoft/dependency-agent/storage/*.bb does not exist." && exit 1

	sleep 90
	! ls /var/opt/microsoft/dependency-agent/storage/*.hb && LogErr "/var/opt/microsoft/dependency-agent/storage/*.hb does not exist." && exit 1
	[ ! -f "/etc/opt/microsoft/dependency-agent/config/DA_PID" ] && LogErr "/etc/opt/microsoft/dependency-agent/config/DA_PID does not exist." && exit 1

	if grep -iq "^[1-9][0-9]*$" /etc/opt/microsoft/dependency-agent/config/DA_PID; then
        x=$(grep -i "^[1-9][0-9]*$" /etc/opt/microsoft/dependency-agent/config/DA_PID)
        strings /proc/$x/cmdline | grep "/opt/microsoft/dependency-agent/bin/microsoft-dependency-agent-manager" && LogMsg "PID matched" || (LogErr "PID not matched" && exit 1)
	else
		LogErr "PID not found in DA_PID"
		exit 1 
	fi

	dmesg | egrep -w "BUG:|Modules linked in:|Call Trace:​" && LogErr "Found BUG/Modules linked in/Call Trace in dmesg" && exit 1

	verify_uninstall_da
	pkill $watch_pid

	LogMsg "Enable/Disable DA tests passed successfully"
}

check_prereqs
download_da_linux_installer
verify_install_da
verify_uninstall_da
setup_network_trace
enable_disable_da

LogMsg "Validate DA tests completed"
SetTestStateCompleted
exit 0
