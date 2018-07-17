########################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
########################################################################

########################################################################
#
# provisionLinuxForLisa.sh
#
# Description:
#    Provision a Linux VM for use with the LISA test framework.  The
#    LISA framework requires the following as a minimum:
#        SSH daemon configured to start on boot.
#        root login is allowd via SSH
#        The dos2unix utility is installed
#        The atd service is installed
#    In addition, SELinux should be disabled, all appropriate ports
#    opened in the firewall, or the firewall disabled.  Various
#    test cases will utilize features from specific packages.
#
#    This test case script will attempt to disable SELinux, disable
#    the firewall, and install the packages required by the majority
#    of the LIS test cases.
#
#    This test case is intended to run with the ProvisionSshKeys.ps1
#    setup script.  The LISA test framework uses the Putty SSH utilities.
#    This setup script will verify the public key exists in the .\ssh\
#    directory, start the Linux VM, create the .ssh directory on the
#    Linux VM, copy the public to the Linux VM, create the
#    .ssh/authorized_keys file.  In addition, the ProvisionSshKeys.ps1
#    script will install the dos2unix and at packages, and ensure the
#    atd service is configured to start on boot.
#
#    The ProvisionSshKeys.ps1 setup script, and this test case script
#    assume the Linux test VM was installed with the Hyper-V LIS
#    drivers, and SSH is installed and configured.
#
#    The test case definition to run this script as a test case would
#    look similar to the following:
#
#    <test>
#        <testName>ProvisionVmForLisa</testName>
#        <testScript>provisionLinuxForLisa.sh</testScript>
#        <setupScript>setupScripts\ProvisionSshKeys.ps1</setupScript>
#        <files>remote-scripts\ica\provisionLinuxForLisa.sh</files>
#        <timeout>1800</timeout>
#        <onError>Abort</onError>
#        <noReboot>False</noReboot>
#        <testparams>
#            <param>TC_COVERED=Provisioning</param>
#            <param>publicKey=demo_id_rsa.pub</param>
#        </testparams>
#    </test>
#
#
########################################################################


ICA_TESTRUNNING="TestRunning"      # The test is running
ICA_TESTCOMPLETED="TestCompleted"  # The test completed successfully
ICA_TESTABORTED="TestAborted"      # Error during setup of test
ICA_TESTFAILED="TestFailed"        # Error while performing the test

CONSTANTS_FILE="constants.sh"

LogMsg()
{
    echo `date "+%a %b %d %T %Y"` : ${1}    # To add the timestamp to the log file
}


UpdateTestState()
{
    echo $1 > $HOME/state.txt
}


#######################################################################
#
#
#
#######################################################################
LogMsg()
{
    echo `date "+%a %b %d %T %Y"` ": ${1}"
    echo "${1}" >> ~/provisionLinux.log
}


#######################################################################
#
# LinuxRelease()
#
#######################################################################
LinuxRelease()
{
    DISTRO=`grep -ihs "buntu\|Suse\|Fedora\|Debian\|CentOS\|Red Hat Enterprise Linux\|Oracle" /etc/{issue,*release,*version}`

    case $DISTRO in
        *buntu*)
            echo "UBUNTU";;
        Fedora*)
            echo "FEDORA";;
        *CentOS*6.*)
            echo "CENTOS6";;
        *CentOS*7*)
            echo "CENTOS7";;
        *SUSE*)
            echo "SLES";;
        *Red*6.*)
            echo "RHEL6";;
        *Red*7*)
            echo "RHEL7";;
        Debian*)
            echo "DEBIAN";;
		Oracle*)
		    echo "ORACLE";;
    esac
}


#######################################################################
#
# Provision SSH Keys
#
# Note: Moved to the setup script
#
#######################################################################
#function ProvisionSshKeys
#{
#    if [ ! -e ~/${public_ssh_key} ]; then
#	    LogMsg "Error: The public SSH key '~/${public_ssh_key}' does not exist"
#		exit 1
#	fi
#
#	if [ ! -e ~/.ssh ]; then
#	    mkdir ~/.ssh
#		if [ $? -ne 0 ]; then
#		    LogMsg "Error: Unable to create the ~/.ssh directory"
#			UpdateTestState $ICA_TESTFAILED
#			exit 1
#		fi
#	fi
#
#	mv ~/${public_ssh_key} ~/.ssh
#	if [ $? -ne 0 ]; then
#	    LogMsg "Error: Unable to copy ~/${public_ssh_key} to the ~/.ssh directory"
#		UpdateTestState $ICA_TESTFAILED
#		exit 1
#	fi
#
#	chmod 600 ~/.ssh/${public_ssh_key}
#	if [ $? -ne 0 ]; then
#	    LogMsg "Error: Unable to chmod 600 ~/.ssh/${public_ssh_key}"
#	fi
#
	#
	# Add, or append, the public key to the authorized_keys file
	#
#	if [ ! -e ~/.ssh/authorized_keys ]; then
#	    LogMsg "Info : Creating .ssh/authorized_keys"
#	    cat ~/.ssh/${public_ssh_key} > ~/.ssh/authorized_keys
#		chmod 600 ~/.ssh/authorized_keys
#	else
#	    LogMsg "Info : Append public key to authorized_keys"
#	    cat ~/.ssh/${public_ssh_key} >> ~/.ssh/authorized_keys
#	fi
#
	#
	# If a private key was provided, copy it to the .ssh directory
	# If the default id_rsa or id_dsa key does not exist, create
	# it using the private key.
	#
#	if [ -e ~/${private_ssh_key} ]; then
#	    mv ~/${private_ssh_key} ~/.ssh/
#
#		if [[ "${private_ssh_key}"  == *id_rsa ]]; then
#		    if [ ! -e ~/.ssh/id_rsa ]; then
#		        cp ~/.ssh/${private_ssh_key} ~/.ssh/id_rsa
#			fi
#		fi
#
#		if [[ "${private_ssh_key}"  == *id_dsa ]]; then
#		    if [ ! -e ~/.ssh/id_dsa ]; then
#		        cp ~/.ssh/${private_ssh_key} ~/.ssh/id_dsa
#			fi
#		fi
#	fi
#}


#######################################################################
#
# Provision Debian
#
#######################################################################
function DebianTasks
{
    LogMsg "Info : Support for Debian Linux is not yet implemented"
	UpdateTestState $ICA_TESTFAILED
	exit 1
}


#######################################################################
#
# Provision Oracle
#
#######################################################################
function OracleTasks
{
    LogMsg "Info : Support for Oracle Linux is not yet implemented"
	#exit 1

	#
	# Create a list of packages to install, then ensure they are all installed
	#
	installError=0
	packagesToInstall=(at bridge-utils btrfsprogs crash dos2unix dosfstools e2fsprogs e2progs-libs util-linux gpm kdump libaio-devel ntp parted wget xfsprogs kernel-devel kernel-headers net-tools bc make)
    for p in "${packagesToInstall[@]}"
	do
	    LogMsg "Info : Processing package '${p}'"
		yum list installed "${p}" > /dev/null
		if [ $? -ne 0 ]; then
		    LogMsg "Info : Installing package '${p}'"
			yum -y install "${p}"
			if [ $? -ne 0 ]; then
			    LogMsg "Error: failed to install package '${p}'"
				installError=1
			fi
		fi
	done

	#
	# Development tools are a group install
	#
	yum groupinfo "Development Tools" > /dev/null
	if [ $? -ne 0 ]; then
	    LogMsg "Info : Installing group 'Development Tools'"
		yum -y groupinstall "Development Tools"
		if [ $? -ne 0 ]; then
	    	LogMsg "Error: failed to groupinstall 'Development Tools'"
			installError=1
		fi
	fi

	if [ $installError -eq 1 ]; then
	    LogMsg "Error: Not all packages successfully installed - terminating"
		UpdateTestState $ICA_TESTFAILED
		exit 1
	fi
}


#######################################################################
#
# Provision RHEL
#
#######################################################################
function RhelTasks
{
    LogMsg "Info : Rhel Tasks"
	#
	# Disable the firewall
	#
	LogMsg "Info : Disabling the firewall"
    if [ $1 -eq 7 ]; then
        systemctl stop firewalld
        systemctl disable firewalld
    fi
    if [ $1 -eq 6 ]; then
        service iptables stop
    	chkconfig iptables off

    	service ip6tables stop
    	chkconfig ip6tables off
    fi

	#
	# Disable SELinux
	#
	LogMsg "Info : Disabling SELinux"
    sed -i '/^SELINUX=/cSELINUX=disabled' /etc/selinux/config

	#
	# Create a list of packages to install, then ensure they are installed
	#
	installError=0
    if [ $1 -eq 7 ]; then
	    packagesToInstall=(at bridge-utils btrfs-progs crash dos2unix dosfstools e2fsprogs e2fsprogs-libs util-linux gpm dump system-config-kdump libaio-devel nano ntp ntpdate parted wget xfsprogs iscsi-initiator-utils bc)
    fi
    if [ $1 -eq 6 ]; then
	    packagesToInstall=(at bridge-utils btrfs-progs crash dos2unix dosfstools e2fsprogs e2fsprogs-libs util-linux gpm dump system-config-kdump libaio-devel nano ntp ntpdate parted wget iscsi-initiator-utils bc)
    fi
	for p in "${packagesToInstall[@]}"
	do
	    LogMsg "Info : Processing package '${p}'"
		rpm -q "${p}" > /dev/null
		if [ $? -ne 0 ]; then
		    LogMsg "Info : Installing package '${p}'"
			yum -y install "${p}"
			if [ $? -ne 0 ]; then
			    LogMsg "Error: failed to install package '${p}'"
				installError=1
			fi
		fi
	done

	#
	# Group Install the Development tools
	#
	LogMsg "Info : groupinstall of 'Development Tools'"
	yum -y groupinstall "Development Tools"
	if [ $? -ne 0 ]; then
	    LogMsg "Error: Unable to groupinstall 'Development Tools'"
		installError=1
	fi

	if [ $installError -eq 1 ]; then
	    LogMsg "Error: Not all packages successfully installed - terminating"
		UpdateTestState $ICA_TESTFAILED
		exit 1
	fi

	#
	# reiserfs support is in a separate repository
	#
	LogMsg "Info : Adding the elrepo key"
	rpm --import https://www.elrepo.org/RPM-GPG-KEY-elrepo.org
	if [ $? -ne 0 ]; then
	    LogMsg "Error: Unable to import key for elrepo"
		UpdateTestState $ICA_TESTFAILED
		exit 1
	fi

    if [ $1 -eq 7 ]; then
        LogMsg "Info : Adding the elrepo-7 rpm"
        rpm -Uvh http://www.elrepo.org/elrepo-release-7.0-2.el7.elrepo.noarch.rpm
    fi
    if [ $1 -eq 6 ]; then
        LogMsg "Info : Adding the elrepo-6 rpm"
	    rpm -Uvh http://www.elrepo.org/elrepo-release-6-6.el6.elrepo.noarch.rpm
    fi
	if [ $? -ne 0 ]; then
	    LogMsg "Error: Unable to install elrepo rpm"
		UpdateTestState $ICA_TESTFAILED
		exit 1
	fi

	LogMsg "Info : Installing the reiserfs-utils from the elrepo repository"
	yum -y install reiserfs-utils
	if [ $? -ne 0 ]; then
	    LogMsg "Error: Unable to install the reiserfs-utils"
		UpdateTestState $ICA_TESTFAILED
		exit 1
	fi
}


#######################################################################
#
# Provision SLES
#
#######################################################################
function SlesTasks
{
	#
	# Disable firewall
	#
	/sbin/SuSEfirewall2 off
	if [ $? -ne 0 ]; then
	    LogMsg "Error: Unable to disable the firewall"
		UpdateTestState $ICA_TESTFAILED
		exit 1
	fi

	#
	# Disable SELinux
	#
	# SLES does not use SELinux by default - nothing to do
	#

	#
	# Create a list of packages to install, then ensure they are installed
    #
	installError=0
	packagesToInstall=(at bridge-utils btrfsprogs crash dos2unix dosfstools e2fsprogs util-linux gpm kdump libaio-devel ntp parted reiserfs wget xfsprogs kernel-devel linux-glibc-devel bc make)
    for p in "${packagesToInstall[@]}"
	do
	    LogMsg "Info : Processing package '${p}'"
		rpm -q "${p}" > /dev/null
		if [ $? -ne 0 ]; then
		    LogMsg "Info : Installing package '${p}'"
			zypper --non-interactive install "${p}"
			if [ $? -ne 0 ]; then
			    LogMsg "Error: failed to install package '${p}'"
				installError=1
			fi
		fi
	done

	if [ $installError -eq 1 ]; then
	    LogMsg "Error: Not all packages successfully installed - terminating"
		UpdateTestState $ICA_TESTFAILED
		exit 1
	fi
}


#######################################################################
#
# Provision Ubuntu
#
#######################################################################
function UbuntuTasks
{
    LogMsg "Info : Performing Ubuntu specific tasks"

	#
	# Disable the firewall
	#
	LogMsg "Info : Disabling the firewall"
	ufw disable &> ~/firewall.log
	if [ $? -ne 0 ]; then
	    LogMsg "Error: Unable to disable the Ubuntu firewall"
		UpdateTestState $ICA_TESTFAILED
		exit 1
	fi

	#
	# Disable SELinus - Ubuntu uses AppArmor rather than SELinux
	#
	LogMsg "Info : Disabling AppArmor"
	/etc/init.d/apparmor stop &> ~/apparmor.log

	#
	# Create a list of packages to install, then ensure they are all installed
	#
	KernelRelease=$(uname -r | sed 's/-generic//g')
	installError=0
	packagesToInstall=(dos2unix dosfstools util-linux parted linux-headers-$KernelRelease build-essential ntp ntpdate e2fsprogs e2fslibs reiserfsprogs at bridge-utils btrfs-tools libgpm2 libaio-dev nano wget xfsprogs bc make)
	
	# Add packages for Linux Integration Services depending on Ubuntu version
	UbuntuVersion=$(lsb_release -r -s)
	case $UbuntuVersion in
		12.* | 13.*)
			packagesToInstall+=(linux-tools-$KernelRelease hv-kvp-daemon-init)
			;;
		14.04)
			packagesToInstall+=(linux-tools-$KernelRelease linux-cloud-tools-$KernelRelease hv-kvp-daemon-init)
			;;
		*)
			packagesToInstall+=(linux-tools-$KernelRelease linux-cloud-tools-$KernelRelease linux-cloud-tools-common)
			;;
	esac

    for p in "${packagesToInstall[@]}"
	do
	    LogMsg "Info : Processing package '${p}'"
		dpkg -s ${p} &> /dev/null
		if [ $? -ne 0 ]; then
		    LogMsg "Info : Installing package '${p}'"
			apt-get -y install "${p}"
			if [ $? -ne 0 ]; then
			    LogMsg "Error: failed to install package '${p}'"
				installError=1
			fi
		fi

	done

	if [ $installError -eq 1 ]; then
	    LogMsg "Error: Not all packages successfully installed - terminating"
		UpdateTestState $ICA_TESTFAILED
		exit 1
	fi

	# If Ubuntu version 12.04 or 13.04 then we need to rename the Hyper-V daemon
	if [[ $UbuntuVersion =~ 12.*|13.* ]]; then
		LogMsg "Info : Copying /usr/sbin/hv_kvp_daemon_${KernelRelease} to /usr/sbin/hv_kvp_daemon"
		cp /usr/sbin/hv_kvp_daemon_$KernelRelease /usr/sbin/hv_kvp_daemon
	fi
}


#######################################################################
#
# Main script body
#
#######################################################################

LogMsg "Updating test case state to running"
UpdateTestState $ICA_TESTRUNNING

#
# Cleanup any summary log files left behind by a separate test case
#
if [ -e ~/summary.log ]; then
    LogMsg "Cleaning up previous copies of summary.log"
    rm -rf ~/summary.log
fi

#
# Source the constants file
#
if [ -e ~/${CONSTANTS_FILE} ]; then
    source ~/${CONSTANTS_FILE}
fi

#
# Display contents of constants.sh so it is captured in the log file
#
cat ~/${CONSTANTS_FILE}

#
#
# Determine the Linux distro, and perform distro specific tasks
#
distro=`LinuxRelease`
case $distro in
    "CENTOS6" | "RHEL6")
	    RhelTasks 6
	;;
    "CENTOS7" | "RHEL7")
	    RhelTasks 7
	;;
	"UBUNTU")
	    UbuntuTasks
	;;
	"DEBIAN")
	    DebianTasks
	;;
	"SLES")
	    SlesTasks
	;;
	"ORACLE")
	    OracleTasks
	;;
	*)
	    msg="Error: Distro '${distro}' not supported"
		LogMsg "${msg}"
		UpdateTestState $ICA_TESTFAILED
		exit 1
	;;
esac

#
# Provision the SSH keys
#   Note: This is now performed in the setup script.
#LogMsg "Info : Provisioning SSH keys"
#ProvisionSshKeys

UpdateTestState $ICA_TESTCOMPLETED

exit 0
