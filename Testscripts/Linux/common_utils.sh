#!/bin/bash
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#

function get_lis_version ()
{
	lis_version=`modinfo hv_vmbus | grep "^version:"| awk '{print $2}'`
	if [ "$lis_version" == "" ]; then
		lis_version="Default_LIS"
	fi
	echo $lis_version
}

function get_host_version ()
{
	dmesg | grep "Host Build" | sed "s/.*Host Build://"| awk '{print  $1}'| sed "s/;//"
}

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

function install_rpm () {
	package_name=$1
	rpm -ivh --nodeps  $package_name
	check_exit_status "install_rpm $package_name"
}

function install_deb () {
	package_name=$1
	dpkg -i  $package_name
	apt-get install -f
	check_exit_status "install_deb $package_name"
}

function apt_get_install ()
{
	package_name=$1
	DEBIAN_FRONTEND=noninteractive apt-get install -y  --force-yes $package_name
	check_exit_status "apt_get_install $package_name"
}

function yum_install ()
{
	package_name=$1
	yum -y --nogpgcheck install $package_name
	check_exit_status "yum_install $package_name"
}

function zypper_install ()
{
	package_name=$1
	zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys in $package_name
	check_exit_status "zypper_install $package_name"
}

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
	rpm -ivh $epel_rpm_url
	check_exit_status "install_epel"
}

function install_sshpass () {
	which sshpass
	if [ $? -ne 0 ]; then
		echo "sshpass not installed\n Installing now..."
		if [ $DISTRO_NAME == "sles" ] && [[ $DISTRO_VERSION =~ 12 ]]; then
			rpm -ivh "https://download.opensuse.org/repositories/network/SLE_12_SP3/x86_64/sshpass-1.06-7.1.x86_64.rpm"
		else
			install_package "sshpass"
		fi
		check_exit_status "install_sshpass"
	fi
}

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
			until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done
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
				wget --no-check-certificate $fio_url
				echo "zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install ${fio_url##*/}"
				zypper --no-gpg-checks --non-interactive --gpg-auto-import-keys install ${fio_url##*/}
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
			until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done
			apt-get -y install iperf3 sysstat bc psmisc
			if [ $ip_version -eq 6 ] && [[ $DISTRO_VERSION =~ 16 ]]; then	
				echo 'iface eth0 inet6 auto' >> /etc/network/interfaces.d/50-cloud-init.cfg
				echo 'up sleep 5' >> /etc/network/interfaces.d/50-cloud-init.cfg
				echo 'up dhclient -1 -6 -cf /etc/dhcp/dhclient6.conf -lf /var/lib/dhcp/dhclient6.eth0.leases -v eth0 || true' >> /etc/network/interfaces.d/50-cloud-init.cfg
				ifdown eth0 && ifup eth0
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

function build_lagscope () {
	rm -rf lagscope
	git clone https://github.com/Microsoft/lagscope
	cd lagscope/src && make && make install
	cd ../..
}

function install_lagscope () {
	echo "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of lagscope"
	update_repo
	case "$DISTRO_NAME" in
		rhel|centos)
			install_epel
			yum -y --nogpgcheck install libaio sysstat git bc make gcc
			build_lagscope
			iptables -F
			;;

		ubuntu)
			until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done
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

function build_ntttcp () {
	wget https://github.com/Microsoft/ntttcp-for-linux/archive/v1.3.4.tar.gz
	tar -zxvf v1.3.4.tar.gz
	cd ntttcp-for-linux-1.3.4/src/ && make && make install
	cd ../..
}

function install_ntttcp () {
	echo "Detected $DISTRO_NAME $DISTRO_VERSION; installing required packages of ntttcp"
	update_repo
	case "$DISTRO_NAME" in
		rhel|centos)
			install_epel
			yum -y --nogpgcheck install wget libaio sysstat git bc make gcc dstat psmisc
			build_ntttcp
			build_lagscope
			iptables -F
			;;

		ubuntu)
			until dpkg --force-all --configure -a; sleep 10; do echo 'Trying again...'; done
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

function get_active_nic_name () {
	if [ $DISTRO_NAME == "sles" ] && [[ $DISTRO_VERSION =~ 15 ]]; then
		zypper_install "net-tools-deprecated" > /dev/null
	fi
	echo $(route | grep '^default' | grep -o '[^ ]*$')
}

function creat_partitions () {
	disk_list=($@)
	echo "Creating partitions on ${disk_list[@]}"

	count=0
	while [ "x${disk_list[count]}" != "x" ]; do
		echo ${disk_list[$count]}
		(echo n; echo p; echo 2; echo; echo; echo t; echo fd; echo w;) | fdisk ${disk_list[$count]}
		count=$(( $count + 1 ))
	done
}

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

function create_raid_and_mount() {
# Creats RAID using unused data disks attached to the VM.
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

function set_user_password {
	# This routine can set root or any user's password. 
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

function collect_VM_properties () {
# This routine collects the information in .csv format.
# Anyone can expand this with useful details.
# Better if it can collect details without su permission.

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

function generate_random_mac_addr () {
	echo "52:54:00:$(dd if=/dev/urandom bs=512 count=1 2>/dev/null | md5sum | sed 's/^\(..\)\(..\)\(..\).*$/\1:\2:\3/')"
}

DISTRO_NAME=$(detect_linux_distribution)
DISTRO_VERSION=$(detect_linux_distribution_version)
PACKAGE_BLOB_LOCATION="https://eosgpackages.blob.core.windows.net/testpackages/tools"
