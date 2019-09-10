#!/bin/bash
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
# This script will set up RDMA over IB environment.
# To run this script following things are must.
# 1. constants.sh
# 2. All VMs in cluster have infiniband hardware.
# 3. This script should run for MPI setup prior to running MPI testing.
#   mpi_type: ibm, open, intel
########################################################################################################
# Source utils.sh
. utils.sh || {
	echo "Error: unable to source utils.sh!"
	echo "TestAborted" >state.txt
	exit 0
}
# Source constants file and initialize most common variables
UtilsInit

# Constants/Globals
HOMEDIR="/root"
# Get distro information
GetDistro

function Verify_File {
	# Verify if the file exists or not.
	# The first parameter is absolute path
	if [ -e $1 ]; then
		LogMsg "File found $1"
	else
		LogErr "File not found $1"
	fi
}

function Found_File {
	# The first parameter is file name, the second parameter is filtering
	target_path=$(find / -name $1 | grep $2)
	if [ -n $target_path ]; then
		LogMsg "Verified $1 binary in $target_path successfully"
	else
		LogErr "Could not verify $1 binary in the system"
	fi
}

function Verify_Result {
	if [ $? -eq 0 ]; then
		LogMsg "OK"
	else
		LogErr "FAIL"
	fi
}

function Main() {
	LogMsg "Starting RDMA required packages and software setup in VM"
	update_repos
	# Install common packages
	install_package "gcc git make zip"
	# Change memory limits
	echo "* soft memlock unlimited" >> /etc/security/limits.conf
	echo "* hard memlock unlimited" >> /etc/security/limits.conf
	hpcx_ver=""
	source /etc/os-release
	case $DISTRO in
		redhat_7|centos_7|redhat_8|centos_8)
			# install required packages regardless VM types.
			LogMsg "Starting RHEL/CentOS setup"
			LogMsg "Installing required packages ..."
			install_package "kernel-devel-$(uname -r) valgrind-devel redhat-rpm-config rpm-build gcc gcc-gfortran libdb-devel gcc-c++ glibc-devel zlib-devel numactl-devel libmnl-devel binutils-devel iptables-devel libstdc++-devel libselinux-devel elfutils-devel libtool libnl3-devel java libstdc++.i686 gtk2 atk cairo tcl tk createrepo byacc.x86_64 net-tools"
			# libibverbs-devel and libibmad-devel have broken dependecies on Centos 7.6
			# Switching to direct install instead of using the function
			yum install -y libibverbs-devel libibmad-devel
			# Install separate packages for 7.x and 8.x
			case $DISTRO in
				redhat_7|centos_7)
					install_package "python-devel dapl python-setuptools"
				;;
				redhat_8|centos_8)
					install_package "python3-devel python2-devel python2-setuptools"
				;;
			esac
			yum -y groupinstall "InfiniBand Support"
			Verify_Result
			LogMsg "Installed group packages for InfiniBand Support"
			LogMsg "Completed the required packages installation"

			LogMsg "Enabling rdma service"
			systemctl enable rdma
			Verify_Result
			LogMsg "Enabled rdma service"

			# This is required for new HPC VM HB- and HC- size deployment, Dec/2018
			# Get redhat/centos version. Using custom commands instead of utils.sh function
			# because we have seen some inconsistencies in getting the exact OS version.
			if [[ "$install_ofed" == "yes" ]];then
				distro_version=$(sed 's/[^.0-9]//g' /etc/redhat-release)
				distro_version=$(echo ${distro_version:0:3})
				hpcx_ver="redhat"$distro_version
				mlx5_ofed_link="$mlx_ofed_partial_link$distro_version-x86_64.tgz"
				cd
				LogMsg "Downloading MLX driver"
				wget $mlx5_ofed_link
				Verify_Result
				LogMsg "Downloaded MLNX_OFED_LINUX driver, $mlx5_ofed_link"

				LogMsg "Opening MLX OFED driver tar ball file"
				file_nm=${mlx5_ofed_link##*/}
				tar zxvf $file_nm
				Verify_Result
				LogMsg "Untar MLX driver tar ball file, $file_nm"

				LogMsg "Installing MLX OFED driver"
				./${file_nm%.*}/mlnxofedinstall --add-kernel-support
				Verify_Result
				LogMsg "Installed MLX OFED driver with kernel support modules"
			fi

			# Restart IB driver after enabling the eIPoIB Driver
			LogMsg "Changing LOAD_EIPOIB to yes"
			sed -i -e 's/LOAD_EIPOIB=no/LOAD_EIPOIB=yes/g' /etc/infiniband/openib.conf
			Verify_Result
			LogMsg "Configured openib.conf file"

			LogMsg "Unloading ib_isert rpcrdma ib_Srpt services"
			modprobe -rv ib_isert rpcrdma ib_srpt
			Verify_Result
			LogMsg "Removed ib_isert rpcrdma ib_srpt services"

			LogMsg "Restarting openibd service"
			/etc/init.d/openibd restart
			Verify_Result
			LogMsg "Restarted Open IB Driver"

			# remove or disable firewall and selinux services, if needed
			LogMsg "Disabling Firewall and SELinux services"
			systemctl stop iptables.service
			systemctl disable iptables.service
			systemctl mask firewalld
			systemctl stop firewalld.service
			Verify_Result
			systemctl disable firewalld.service
			Verify_Result
			iptables -nL
			Verify_Result
			sed -i -e 's/SELINUX=enforcing/SELINUX=disabled/g' /etc/selinux/config
			Verify_Result
			LogMsg "Completed RHEL Firewall and SELinux disabling"
			;;
		suse*|sles*)
			# install required packages
			LogMsg "This is SUSE"
			LogMsg "Installing required packages ..."
			install_package "bzip expect glibc-32bit glibc-devel libgcc_s1 libgcc_s1-32bit libpciaccess-devel gcc-c++ gcc-fortran rdma-core libibverbs-devel librdmacm1 libibverbs-utils bison flex"
			# force install package that is known to have broken dependencies
			zypper --non-interactive in libibmad-devel
			if [ $? -eq 4 ]; then
				expect -c "spawn zypper in libibmad-devel
					expect -timeout -1 \"Choose from\"
					send \"2\r\"
					expect -timeout -1 \"Continue\"
					send \"y\r\"
					interact
				"
			fi
			# Enable mlx5_ib module on boot
			echo "mlx5_ib" >> /etc/modules-load.d/mlx5_ib.conf
			if [ $VERSION_ID -eq "15" ]; then
				hpcx_ver="suse"$VERSION_ID".0"
			else
				hpcx_ver="suse"$VERSION_ID
			fi
			;;
		ubuntu*)
			LogMsg "This is Ubuntu"
			hpcx_ver="ubuntu"$VERSION_ID
			LogMsg "Installing required packages ..."
			install_package "build-essential python-setuptools libibverbs-dev bison flex ibverbs-utils net-tools libdapl2 libmlx5 libmlx4-dev rdmacm-utils rdma-core bc"
			LogMsg "*** Adding kernel modules to /etc/modules"
			echo rdma_ucm >> /etc/modules
			echo ib_ipoib >> /etc/modules
			LogMsg "*** Adding Canoncial ppa for temporary fix"
			add-apt-repository -y ppa:ci-train-ppa-service/3760
			LogMsg "*** System updating with the customized ppa"
			apt update
			apt upgrade -y			
			;;
		*)
			LogErr "MPI type $mpi_type does not support on '$DISTRO' or not implement"
			SetTestStateFailed
			exit 0
			;;
	esac

	LogMsg "Proceeding to MPI installation"

	# install MPI packages
	if [ $mpi_type == "ibm" ]; then
		LogMsg  "IBM Platform MPI installation running ..."
		# IBM platform MPI installation
		cd ~
		LogMsg "Downloading bin file, $ibm_platform_mpi"
		wget $ibm_platform_mpi
		Verify_Result
		LogMsg  "Downloaded IBM Platform MPI bin file"
		LogMsg "$(ls)"
		chmod +x $HOMEDIR/$(echo $ibm_platform_mpi | cut -d'/' -f5)
		Verify_Result
		LogMsg "Added the execution mode to BIN file"

		# create a temp file for key stroke event handle
		keystroke_filename=$HOMEDIR/ibm_keystroke
		LogMsg "Building keystroke event file for IBM Platform MPI silent installation"
		echo '\n' > $keystroke_filename
		echo 1 >> /$keystroke_filename
		echo /opt/ibm/platform_mpi/ >> $keystroke_filename
		echo Y >> $keystroke_filename
		echo '\n' >> $keystroke_filename
		echo '\n' >> $keystroke_filename
		echo '\n' >> $keystroke_filename
		echo '\n' >> $keystroke_filename
		LogMsg "$(cat $keystroke_filename)"

		LogMsg "Executing silent installation"
		cat ibm_keystroke | $HOMEDIR/$(echo $ibm_platform_mpi | cut -d'/' -f5)
		Verify_Result
		LogMsg "Completed IBM Platform MPI installation"

		# set path string to verify IBM MPI binaries
		target_bin=/opt/ibm/platform_mpi/bin/mpirun
		ping_pong_help=/opt/ibm/platform_mpi/help
		ping_pong_bin=/opt/ibm/platform_mpi/help/ping_pong

		# file validation
		Verify_File $target_bin

		# compile ping_pong
		cd $ping_pong_help
		LogMsg "Compiling ping_pong binary in Platform help directory"
		make -j $(nproc)
		if [ $? -ne 0 ]; then
			pkey=$(cat /sys/class/infiniband/*/ports/1/pkeys/0)
			export MPI_IB_PKEY=${pkey}
			make -j $(nproc)
		fi
		LogMsg "Ping-pong compilation completed"

		# verify ping_pong binary
		Verify_File $ping_pong_bin

		# add IBM Platform MPI path to PATH
		export MPI_ROOT=/opt/ibm/platform_mpi
		export PATH=$PATH:$MPI_ROOT
		export PATH=$PATH:$MPI_ROOT/bin
	elif [ $mpi_type == "intel" ]; then
		# if HPC images comes with MPI binary pre-installed, (CentOS HPC)
		#   there is no action required except binary verification
		mpirun_path=$(find / -name mpirun | grep intel64)		# $mpirun_path is not empty or null and file path should exists
		if [[ -f $mpirun_path && ! -z "$mpirun_path" ]]; then
			LogMsg "Found pre-installed mpirun binary"

			# mostly IMB-MPI1 comes with mpirun binary, but verify its existence
			Found_File "IMB-MPI1" "intel64"
		# if this is HPC images with MPI installer rpm files, (SUSE HPC)
		#   then it should be install those rpm files
		elif [ -d /opt/intelMPI ]; then
			LogMsg "Found intelMPI directory. This has an installable rpm ready image"
			LogMsg "Installing all rpm files in /opt/intelMPI/intel_mpi_packages/"

			rpm -v -i --nodeps /opt/intelMPI/intel_mpi_packages/*.rpm
			Verify_Result

			mpirun_path=$(find / -name mpirun | grep intel64)

			Found_File "mpirun" "intel64"
			Found_File "IMB-MPI1" "intel64"
		else
			# none HPC image case, need to install Intel MPI
			# Intel MPI installation of tarball file
			LogMsg "Intel MPI installation running ..."
			LogMsg "Downloading Intel MPI source code, $intel_mpi"
			wget $intel_mpi

			tar xvzf $(echo $intel_mpi | cut -d'/' -f5)
			cd $(echo "${intel_mpi%.*}" | cut -d'/' -f5)

			LogMsg "Executing silent installation"
			sed -i -e 's/ACCEPT_EULA=decline/ACCEPT_EULA=accept/g' silent.cfg
			./install.sh -s silent.cfg
			Verify_Result
			LogMsg "Completed Intel MPI installation"

			mpirun_path=$(find / -name mpirun | grep intel64)

			Found_File "mpirun" "intel64"
			Found_File "IMB-MPI1" "intel64"
		fi

		# file validation
		Verify_File $mpirun_path

		# add Intel MPI path to PATH
		export PATH=$PATH:"${mpirun_path%/*}"
		# add sourcing file in each session
		echo "source ${mpirun_path%/*}/mpivars.sh" >> $HOMEDIR/.bashrc
		echo "source ${mpirun_path%/*}/mpivars.sh" >> /home/lisa/.bashrc

		LogMsg "Completed Intel MPI installation"

	elif [ $mpi_type == "open" ]; then
		# Open MPI installation
		LogMsg "Open MPI installation running ..."
		LogMsg "Downloading the target openmpi source code, $open_mpi"
		wget $open_mpi
		Verify_Result

		tar xvzf $(echo $open_mpi | cut -d'/' -f5)
		cd $(echo "${open_mpi%.*}" | cut -d'/' -f5 | sed -n '/\.tar$/s///p')

		LogMsg "Running configuration"
		./configure --enable-mpirun-prefix-by-default
		Verify_Result

		LogMsg "Compiling Open MPI"
		make -j $(nproc)
		Verify_Result

		LogMsg "Installing new binaries in /usr/local/bin directory"
		make install
		Verify_Result

		LogMsg "Reloading config"
		ldconfig
		Verify_Result

		LogMsg "Adding default installed path to system path"
		export PATH=$PATH:/usr/local/bin

		# set path string to verify IBM MPI binaries
		target_bin=/usr/local/bin/mpirun

		# file validation
		Verify_File $target_bin
		LogMsg "Completed Open MPI installation"
	elif [ $mpi_type == "hpcx" ]; then
		# HPC-X MPI installation
		LogMsg "HPC-X MPI installation running ..."
		case $DISTRO in
			redhat*|centos*)
				hpcx_mpi=$hpcx_mpi_ofed
			;;
			ubuntu*|suse*|sles*)
				hpcx_mpi=$hpcx_mpi_inbox
			;;
		esac
		LogMsg "Downloading the target hpcx binary tbz, $hpcx_mpi$hpcx_ver-x86_64.tbz"

		wget $hpcx_mpi$hpcx_ver-x86_64.tbz
		Verify_Result

		tar xvf $(echo $hpcx_mpi$hpcx_ver-x86_64.tbz | cut -d'/' -f8)
		cd $(echo $hpcx_mpi$hpcx_ver-x86_64 | cut -d'/' -f8)
		export HPCX_HOME=$PWD

		LogMsg "Loading HPC-X initial values"
		source $HPCX_HOME/hpcx-init.sh
		Verify_Result

		LogMsg "Loading HPC-X binaries"
		hpcx_load
		Verify_Result

		LogMsg "Displaying env variales"
		env | grep HPCX
		Verify_Result
		LogMsg "Completed HPC-X MPI loading"
	else
		# MVAPICH MPI installation
		LogMsg "MVAPICH MPI installation running ..."
		LogMsg "Downloading the target MVAPICH source code, $mvapich_mpi"
		wget $mvapich_mpi
		Verify_Result
		# in newer kernels, mad.h is missing from /usr/include/infiniband
		ls /usr/include/infiniband/ | grep -w mad.h
		if [[ $? -ne 0 ]]; then
			madh_location=$(find / -name "mad.h" | tail -1)
			cp $madh_location /usr/include/infiniband/
		fi
		tar xvzf $(echo $mvapich_mpi | cut -d'/' -f5)
		cd $(echo "${mvapich_mpi%.*}" | cut -d'/' -f5 | sed -n '/\.tar$/s///p')

		LogMsg "Running configuration"
		if [[ $DISTRO == "ubuntu"* ]]; then
			./configure --disable-fortran --disable-mcast
		else
			./configure
		fi
		Verify_Result

		LogMsg "Compiling MVAPICH MPI"
		make -j $(nproc)
		Verify_Result

		LogMsg "Installing new binaries in /usr/local/bin directory"
		make install
		Verify_Result

		#LogMsg "Adding default installed path to system path"
		export PATH=$PATH:/usr/local/bin

		# set path string to verify IBM MPI binaries
		target_bin=/usr/local/bin/mpirun

		# file validation
		Verify_File $target_bin
		LogMsg "Completed MVAPICH MPI installation"
	fi

	# Enable OS.RDMA and AutoUpdate.Enable in waagent configuration
	cd ~

	LogMsg "Eanble EnableRDMA parameter in waagent.config"
	sed -i -e 's/# OS.EnableRDMA=y/OS.EnableRDMA=y/g' /etc/waagent.conf
	Verify_Result

	LogMsg "Enable AutoUpdate parameter in waagent.config"
	sed -i -e 's/# AutoUpdate.Enabled=y/AutoUpdate.Enabled=y/g' /etc/waagent.conf
	Verify_Result

	LogMsg "Restart waagent service"
	if [[ $DISTRO == "ubuntu"* ]]; then
		service walinuxagent restart
	else
		service waagent restart
	fi
	Verify_Result

	cd ~
	LogMsg "Proceeding Intel MPI Benchmark test installation"

	# Intel MPI has its own IMB-MPI1, IMB-NBC and IMB-RMA binaries
	if [ $mpi_type != "intel" ]; then
		# install Intel MPI benchmark package
		LogMsg "Cloning mpi-benchmarks repo, $intel_mpi_benchmark"
		git clone $intel_mpi_benchmark
		Verify_Result
		LogMsg "Cloned Intel MPI Benchmark gitHub repo"
		cd mpi-benchmarks/src_c
		LogMsg "Building Intel MPI Benchmarks tests"
		make -j $(nproc)
		Verify_Result

		# install P2P test
		LogMsg "Change directory to P2P"
		cd P2P
		LogMsg "Renaming from mpiicc to mpicc in Makefile"
		sed -i -e 's/CC=mpiicc/CC=mpicc/g' Makefile
		LogMsg "Building P2P binary"
		make -j $(nproc)
		LogMsg "Completed P2P2 binary compilation"
		Verify_Result
		LogMsg "Intel MPI Benchmark test installation completed"

		# set string to verify Intel Benchmark binary
		benchmark_bin=$HOMEDIR/mpi-benchmarks/src_c/IMB-MPI1

		# verify benchmark binary
		Verify_File $benchmark_bin
	fi

	echo "setup_completed=0" >> /root/constants.sh

	LogMsg "Main function completed"
}

function post_verification() {
	# Assumption: all paths are default setting
	LogMsg "Post_verification starting"

	# Validate if the platform MPI binaries work in the system.
	_hostname=$(cat /etc/hostname)
	_ipaddress=$(hostname -i | awk '{print $1}')
	LogMsg "Found hostname from system - $_hostname"
	LogMsg "Found _ipaddress from system - $_ipaddress"

	# MPI hostname cmd for initial test
	if [ $mpi_type == "ibm" ]; then
		_res_hostname=$(/opt/ibm/platform_mpi/bin/mpirun -TCP -hostlist $_ipaddress:1 hostname)
	elif [ $mpi_type == "intel" ]; then
		_res_hostname=$(mpirun --host $_ipaddress hostname)
	elif [ $mpi_type == "open" ]; then
		_res_hostname=$(mpirun --allow-run-as-root -np 1 --host $_ipaddress hostname)
	else
		_res_hostname=$(mpirun_rsh -np 1 $_ipaddress hostname)
	fi
	LogMsg "_res_hostname $_res_hostname"

	if [ $_hostname = $_res_hostname ]; then
		LogMsg "Verified hostname from MPI successfully"
	else
		LogErr "Verification of hostname failed."
	fi

	# MPI ping_pong cmd for initial test
	if [ $mpi_type == "ibm" ]; then
		LogMsg "Running ping_pong testing ..."
		_res_pingpong=$(/opt/ibm/platform_mpi/bin/mpirun -TCP -hostlist $_ipaddress:1,$_ipaddress:1 /opt/ibm/platform_mpi/help/ping_pong 4096)
		LogMsg "_res_pingpong $_res_pingpong"

		_res_tx=$(echo $_res_pingpong | cut -d' ' -f7)
		_res_rx=$(echo $_res_pingpong | cut -d' ' -f11)
		LogMsg "_res_tx $_res_tx"
		LogMsg "_res_rx $_res_rx"

		if [[ "$_res_tx" != "0" && "$_res_rx" != "0" ]]; then
			LogMsg "PASSED: Found non-zero value in self ping_pong test"
		else
			LogErr "Found zero ping_pong test result"
		fi

	elif [ $mpi_type == "intel" ]; then
		LogMsg "TBD: This is intel MPI and no verification defined yet"
	else
		LogMsg "TBD: This is Open and MVAPICH MPI, and no verification defined yet"
	fi
	LogMsg "Post_verification completed"
}

# main body
Main
post_verification $mpi_type
cp /root/TestExecution.log /root/Setup-TestExecution.log
cp /root/TestExecutionError.log /root/Setup-TestExecutionError.log
SetTestStateCompleted
exit 0
