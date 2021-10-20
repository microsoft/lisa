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
	echo "TestAborted" > state.txt
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
	# Return OK string, if the latest result is 0
	if [ $? -eq 0 ]; then
		LogMsg "OK"
	else
		LogErr "FAIL"
	fi
}

function Upgrade_waagent {
	# This is only temporary solution, WILL BE REMOVED as soon as 2.2.45 release in each image.
	LogMsg "Starting waagent upgrade"
	ln -s /usr/bin/python3 /usr/bin/python
	if [[ $DISTRO =~ "suse" ]] || [[ $DISTRO =~  "sles" ]]; then
		# add net-tools-deprecated package to work around https://github.com/Azure/WALinuxAgent/issues/1712
		check_package "net-tools-deprecated"
			if [ $? -eq 0 ]; then
				install_package net-tools-deprecated
			fi
	else
		install_package net-tools
	fi

	git clone https://github.com/Azure/WALinuxAgent
	cd WALinuxAgent
	sed -i -e 's/# OS.EnableRDMA=y/OS.EnableRDMA=y/g' ./config/waagent.conf
	sed -i -e 's/# AutoUpdate.Enabled=y/AutoUpdate.Enabled=y/g' ./config/waagent.conf
	waagent -version | grep -i "Python: 2." && python2 setup.py install --force
	waagent -version | grep -i "Python: 3." && python3 setup.py install --force
	LogMsg "$?: Completed the waagent upgrade"
	LogMsg "Restart waagent service"
	# Run this command to reload the upgraded waagent
	systemctl daemon-reload
	if [[ $DISTRO == "ubuntu"* ]]; then
		service walinuxagent restart
	else
		service waagent restart
	fi
	Verify_Result
	# Later, VM reboot completes the service upgrade
	cd ..
	LogMsg "Ended waagent upgrade"
}

function Main() {
	# another rhel 8.0 repo bug workaround, https://bugzilla.redhat.com/show_bug.cgi?id=1787637
	if [ $DISTRO == 'redhat_8' ]; then
		echo 8 > /etc/yum/vars/releasever
		LogMsg "$?: Applied a mitigation for $DISTRO to /etc/yum/vars/releasever"
	fi

	mj=$(echo "$DISTRO_VERSION" | cut -d '.' -f 1)
	mn=$(echo "$DISTRO_VERSION" | cut -d '.' -f 2)

	# only CentOS-HPC 7.6 or older versions support ND device. This lis-next has a bug.
	# https://github.com/LIS/lis-next/blob/master/hv-rhel7.x/hv/Makefile#L20
	if [[ $is_nd == "yes" && $DISTRO == 'centos_7' && $mj -eq 7 && $mn -gt 6 ]]; then
		LogErr "ND test only support CentOS-HPC 7.5 or earlier version. Abort!"
		SetTestStateAborted
		exit 0
	fi

	LogMsg "Starting RDMA required packages and software setup in VM"
	update_repos
	# Install common packages
	install_package "gcc git make zip python3"
	LogMsg "Installed the common required packages, gcc git make zip"
	# Change memory limits
	echo "* soft memlock unlimited" >> /etc/security/limits.conf
	echo "* hard memlock unlimited" >> /etc/security/limits.conf
	LogMsg "$?: Set memlock values to unlimited for both soft and hard"
	hpcx_ver=""
	source /etc/os-release
	# Upgrade waagent to latest (without this step, all the IB nics doesnt get IP address assigned).
	Upgrade_waagent
	case $DISTRO in
		redhat_7|centos_7|redhat_8|centos_8|almalinux_8|rockylinux_8)
			# install required packages regardless VM types.
			LogMsg "Starting RDMA setup for RHEL/CentOS"
			# required dependencies
			grep 7.5 /etc/redhat-release || grep 7.6 /etc/redhat-release && curl https://partnerpipelineshare.blob.core.windows.net/kernel-devel-rpms/CentOS-Vault.repo > /etc/yum.repos.d/CentOS-Vault.repo
			req_pkg="kernel-devel-$(uname -r) redhat-rpm-config rpm-build gcc gcc-gfortran libdb-devel gcc-c++ glibc-devel zlib-devel numactl numactl-devel binutils-devel iptables-devel libstdc++-devel libselinux-devel elfutils-devel libtool java libstdc++.i686 gtk2 atk cairo tcl tk createrepo byacc.x86_64 tcsh"
			install_package $req_pkg
			LogMsg "$?: Installed required packages $req_pkg"
			if ! [[ $DISTRO_VERSION =~ ^7\.[8-9] ]]; then
				req_pkg="valgrind-devel libmnl-devel libnl3-devel"
				install_package $req_pkg
				LogMsg "$?: Installed required packages $req_pkg"
			fi
			install_package $req_pkg
			LogMsg "$?: Installed required packages $req_pkg"
			# libibverbs-devel and libibmad-devel have broken dependencies on Centos 7.6
			# Switching to direct install instead of using the function
			req_pkg="libibverbs-devel libibmad-devel"
			yum install -y $req_pkg
			LogMsg "$?: Installed $req_pkg"
			# Install separate packages for 7.x and 8.x
			case $DISTRO in
				redhat_7|centos_7)
					req_pkg="python-devel dapl python-setuptools wget"
					install_package $req_pkg
					LogMsg "$?: Installed $req_pkg"
				;;
				redhat_8|centos_8|almalinux_8|rockylinux_8)
					req_pkg="python3-devel python2-devel python2-setuptools"
					install_package $req_pkg
					LogMsg "$?: Installed $req_pkg"
				;;
			esac
			if [ ! -f /usr/bin/python ]; then
				ln -s /usr/bin/python3 /usr/bin/python
			fi
			yum -y groupinstall "InfiniBand Support"
			Verify_Result
			LogMsg "Installed InfiniBand Support"

			LogMsg "Completed the required packages installation"

			LogMsg "Enabling rdma service"
			systemctl enable rdma
			Verify_Result
			LogMsg "Enabled rdma service"
			sleep 5

			# Restart IB driver after enabling the eIPoIB Driver
			LogMsg "Changing LOAD_EIPOIB to yes"
			sed -i -e 's/LOAD_EIPOIB=no/LOAD_EIPOIB=yes/g' /etc/infiniband/openib.conf
			Verify_Result
			LogMsg "Configured openib.conf file"

			LogMsg "Unloading ib_isert rpcrdma ib_Srpt services"
			modprobe -rv ib_isert rpcrdma ib_srpt
			Verify_Result
			LogMsg "Removed ib_isert rpcrdma ib_srpt services"
			sleep 1

			LogMsg "Restarting openibd service"
			/etc/init.d/openibd restart
			Verify_Result
			LogMsg "Restarted Open IB Driver"
			# Ignore the openibd service restart. Known issue in Mellanox 773774
			# VM will reboot later and resolve automatically.

			# remove or disable firewall and selinux services, if needed
			LogMsg "Disabling Firewall and SELinux services"
			systemctl stop iptables.service
			systemctl disable iptables.service
			systemctl mask firewalld
			systemctl stop firewalld.service
			Verify_Result
			LogMsg "Stopped firewall service"
			systemctl disable firewalld.service
			Verify_Result
			LogMsg "Disabled firewall service"
			iptables -nL
			Verify_Result
			sed -i -e 's/SELINUX=enforcing/SELINUX=disabled/g' /etc/selinux/config
			Verify_Result
			LogMsg "Completed RHEL Firewall and SELinux disabling"
			;;
		suse*|sles*)
			# install required packages
			LogMsg "Starting RDMA setup for SUSE"
			req_pkg="bzip expect glibc-32bit glibc-devel libgcc_s1 libgcc_s1-32bit libpciaccess-devel gcc-c++ gcc-fortran rdma-core libibverbs-devel librdmacm1 libibverbs-utils bison flex numactl"
			LogMsg "Installing required packages, $req_pkg"
			install_package $req_pkg
			# force install package that is known to have broken dependencies
			LogMsg "Installating libibmad-devel"
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
			LogMsg "Set mlx5_ib module in the kernel"
			echo "mlx5_ib" >> /etc/modules-load.d/mlx5_ib.conf
			if [ $VERSION_ID -eq "15" ]; then
				hpcx_ver="suse"$VERSION_ID".0"
			else
				hpcx_ver="suse"$VERSION_ID
			fi
			LogMsg "$?: Set hpcx version, $hpcx_ver"
			;;
		ubuntu*)
			LogMsg "Disable rename ib0 on Ubuntu by adding net.ifnames=0 biosdevname=0 into kernel parameter."
			sed -ie 's/GRUB_CMDLINE_LINUX="\(.*\)"/GRUB_CMDLINE_LINUX="\1 net.ifnames=0 biosdevname=0"/' /etc/default/grub
			sed -ie 's/GRUB_CMDLINE_LINUX="\(.*\)"/GRUB_CMDLINE_LINUX="\1 net.ifnames=0 biosdevname=0"/' /etc/default/grub.d/50-cloudimg-settings.cfg
			update-grub
			LogMsg "Starting RDMA setup for Ubuntu"
			hpcx_ver="ubuntu"$VERSION_ID
			LogMsg "Installing required packages ..."
			# the old fix integrated to dpdk-18.11 repo
			add-apt-repository ppa:canonical-server/dpdk-azure-18.11 -y
			if [ $? -ne 0 ]; then
				LogErr "Failed to add the required dpdk-azure-18.11 repo to apt source"
			else
				LogMsg "Successfully added the required dpdk-azure-18.11 repo"
			fi

			LogMsg "*** System updating with the customized ppa repo"
			update_repos
			Update_Kernel
			Verify_Result
			LogMsg "Required 32-bit java"
			dpkg --add-architecture i386

			req_pkg="build-essential python-setuptools libibverbs-dev bison flex ibverbs-utils net-tools libdapl2 rdmacm-utils bc numactl"
			install_package $req_pkg
			LogMsg "Installed the required packages, $req_pkg"
			os_RELEASE=$(awk '/VERSION_ID=/' /etc/os-release | sed 's/VERSION_ID=//' | sed 's/\"//g')
			if [ $mpi_type == "ibm" ]; then
				if [[ "$os_RELEASE" == "18.04" ]]; then
					req_pkg="openjdk-8-jdk:i386"
				else
					req_pkg="openjdk-9-jre:i386"
				fi
				install_package $req_pkg
				LogMsg "IBM MPI required 32-bit Java in the system, $req_pkg"
			fi
			# In case, kernel did not load the required modules
			LogMsg "Adding kernel modules to /etc/modules"
			for ex_module in rdma_cm rdma_ucm ib_ipoib ib_umad
			do
				lsmod | grep -i $ex_module
				if [ $? != 0 ]; then
					echo $ex_module >> /etc/modules
					modprobe $ex_module
					if [ $? == 0 ]; then
						LogMsg "Loaded $ex_module successfully"
					else
						LogErr "Failed to load $ex_module"
					fi
				else
					LogMsg "Module $ex_module already loaded"
				fi
			done
			;;
		*)
			LogErr "MPI type $mpi_type does not support on '$DISTRO' or not implement"
			SetTestStateFailed
			exit 0
			;;
	esac

	# This is required for new HPC VM HB- and HC- size deployment, Dec/2018
	# Get redhat/centos version. Using custom commands instead of utils.sh function
	# because we have seen some inconsistencies in getting the exact OS version.
	if [[ "$install_ofed" == "yes" ]];then
		source /etc/os-release
		distro_name=$ID
		distro_version=$VERSION_ID
		if [[ $ID_LIKE == "suse" ]]; then
			if [[ $VERSION_ID == "15" ]]; then
				distro_version=${distro_version}sp0
			else
				distro_version=${distro_version%.*}sp${VERSION_ID##*.}
			fi
		fi
		# OFED driver for Ubuntu version conflicts to those 3 dependencies. Recommended to remove.
		if [[ $ID == "ubuntu" ]]; then
			apt remove -f -y librdmacm1 ibverbs-providers libibverbs-dev
			LogMsg "$?: Removed the dependencies, librdmacm1 ibverbs-providers libibverbs-dev"
		fi
		hpcx_ver=$distro_name$distro_version
		mlx5_ofed_link="$mlx_ofed_partial_link$distro_name$distro_version-x86_64.tgz"
		cd
		LogMsg "Downloading MLX driver, $mlx5_ofed_link"
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

	LogMsg "Proceeding to the MPI installation"

	# install MPI packages
	if [ $mpi_type == "ibm" ]; then
		LogMsg "IBM Platform MPI installation running ..."
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

		LogMsg "Executing the silent installation"
		cat ibm_keystroke | $HOMEDIR/$(echo $ibm_platform_mpi | cut -d'/' -f5)
		Verify_Result
		LogMsg "Completed IBM Platform MPI installation"

		# set path string to verify IBM MPI binaries
		target_bin=/opt/ibm/platform_mpi/bin/mpirun
		LogMsg "Set target_bin path, $target_bin"
		Verify_File $target_bin

		ping_pong_help=/opt/ibm/platform_mpi/help
		LogMsg "Set ping_pong_help path, $ping_pong_help"
		Verify_File $ping_pong_help

		ping_pong_bin=/opt/ibm/platform_mpi/help/ping_pong
		LogMsg "Set ping_pong_bin path, $ping_pong_bin"
		Verify_File $ping_pong_bin

		# compile ping_pong
		cd $ping_pong_help
		LogMsg "Compiling ping_pong binary in Platform help directory"
		make -j $(nproc)
		if [ $? -ne 0 ]; then
			pkey=$(cat /sys/class/infiniband/*/ports/1/pkeys/0)
			export MPI_IB_PKEY=${pkey}
			LogMsg "Exporting MPI_IB_PKEY, $pkey"
			make -j $(nproc)
			LogMsg "Ping-pong compilation completed"
		fi
		# verify ping_pong binary
		Verify_File $ping_pong_bin

		# add IBM Platform MPI path to PATH
		LogMsg "Exporting MPI_ROOT and PATH variables"
		export MPI_ROOT=/opt/ibm/platform_mpi
		LogMsg "MPI_ROOT: $MPI_ROOT"
		export PATH=$PATH:$MPI_ROOT
		export PATH=$PATH:$MPI_ROOT/bin
		LogMsg "PATH: $PATH"
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
			LogMsg "Found intel MPI directory. This has an installable rpm ready image"
			LogMsg "Installing all rpm files in /opt/intelMPI/intel_mpi_packages/"

			rpm -v -i --nodeps /opt/intelMPI/intel_mpi_packages/*.rpm
			Verify_Result

			mpirun_path=$(find / -name mpirun | grep intel64)
			LogMsg "Searching $mpirun_path ..."
			Found_File "mpirun" "intel64"
			Found_File "IMB-MPI1" "intel64"
		else
			# none HPC image case, need to install Intel MPI
			# Intel MPI installation of tarball file
			intel_mpi_installer="$(basename $intel_mpi)"
			LogMsg "Intel MPI installation running ..."
			LogMsg "Downloading Intel MPI source code: $intel_mpi"
			LogMsg "Intel MPI installer name: $intel_mpi_installer"
			wget $intel_mpi

			LogMsg "Executing the silent installation"
			bash ./$intel_mpi_installer -s -a -s --eula accept
			Verify_Result
			LogMsg "Completed Intel MPI installation"

			mpirun_path=$(find / -name mpirun | grep oneapi)
			LogMsg "Searching $mpirun_path ..."
			Found_File "mpirun" "intel64"
			Found_File "IMB-MPI1" "intel64"
		fi

		# file validation
		Verify_File $mpirun_path

		# add Intel MPI path to PATH
		export PATH=$PATH:"${mpirun_path%/*}"
		LogMsg "$?: Set $mpirun_path to PATH, $PATH"
		# add sourcing file in each session
		setvars=$(find / -name setvars.sh)
		echo "source ${setvars} > /dev/null 2>&1 " >> $HOMEDIR/.bashrc
		LogMsg "$?: Completed Intel MPI installation"

	elif [ $mpi_type == "open" ]; then
		# Open MPI installation
		LogMsg "Open MPI installation running ..."
		LogMsg "Downloading the target openmpi source code, $open_mpi"
		wget $open_mpi
		Verify_Result

		tar_filename=$(echo $open_mpi | rev | cut -d'/' -f1 | rev)
		LogMsg "Untarring the downloaded file, $tar_filename"
		tar xvzf $tar_filename
		cd ${tar_filename%.*.*}

		LogMsg "Running configuration, ./configure --enable-mpirun-prefix-by-default"
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
		LogMsg "$?: PATH is $PATH"

		# set path string to verify IBM MPI binaries
		target_bin=/usr/local/bin/mpirun

		# file validation
		LogMsg "Searching $target_bin"
		Verify_File $target_bin
		LogMsg "Completed Open MPI installation"
	elif [ $mpi_type == "hpcx" ]; then
		# HPC-X MPI installation
		LogMsg  "HPC-X MPI installation running ..."
		case $DISTRO in
			redhat*|centos*|almalinux*|rockylinux*)
				hpcx_mpi=$hpcx_mpi_ofed
				LogMsg "Use $hpcx_mpi in RHEL or CentOS"
			;;
			ubuntu*|suse*|sles*)
				hpcx_mpi=$hpcx_mpi_inbox
				LogMsg "Use $hpcx_mpi_inbox in SUSE or Ubuntu"
			;;
		esac

		LogMsg "Downloading the target hpcx binary tbz, $hpcx_mpi$hpcx_ver-x86_64.tbz"
		wget $hpcx_mpi$hpcx_ver-x86_64.tbz
		Verify_Result

		LogMsg "Untarring $hpcx_mpi$hpcx_ver-x86_64.tbz"
		tar xvf $(echo $hpcx_mpi$hpcx_ver-x86_64.tbz | cut -d'/' -f8)
		cd $(echo $hpcx_mpi$hpcx_ver-x86_64 | cut -d'/' -f8)
		export HPCX_HOME=$PWD
		LogMsg "Set HPCX_HOME $HPCX_HOME"

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
			LogMsg "Found mad.h file is missing in /usr/include/infiniband/. Copied one from $madh_location"
			cp $madh_location /usr/include/infiniband/
			Verify_Result
		fi
		tar_filename=$(echo $mvapich_mpi | rev | cut -d'/' -f1 | rev)
		tar xvzf $tar_filename
		LogMsg "Untarred $tar_filename"
		cd ${tar_filename%.*.*}

		LogMsg "Running configuration"
		if [[ $DISTRO == "ubuntu"* ]]; then
			LogMsg "Running ./configure --disable-fortran --disable-mcast"
			./configure --disable-fortran --disable-mcast
		else
			LogMsg "Running ./configure"
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
		LogMsg "Exported to $PATH"

		# set path string to verify IBM MPI binaries
		target_bin=/usr/local/bin/mpirun
		LogMsg "Set target_bin $target_bin"

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

	if [[ $benchmark_type == "OMB" && $mpi_type != "mvapich" ]]; then
		currentDir=$(pwd)
		cd ~
		LogMsg "Proceeding OSU MPI Benchmark (OMB) test installation"
		LogMsg "Downloading mpi-benchmarks from $osu_mpi_benchmark"
		wget $osu_mpi_benchmark
		tar_filename=$(echo $osu_mpi_benchmark | rev | cut -d'/' -f1 | rev)
		tar xvzf tar_filename
		LogMsg "Untarred $tar_filename"
		cd ${tar_filename%.*.*}

		LogMsg "Running configuration ./configure CC=/usr/local/bin/mpicc CXX=/usr/local/bin/mpicxx --prefix=$(pwd)"
		./configure CC=/usr/local/bin/mpicc CXX=/usr/local/bin/mpicxx --prefix=$(pwd)
		Verify_Result
		LogMsg "Compiling OSU Microbenchmarks"
		make
		Verify_Result
		LogMsg "Installing new binaries in /usr/local/bin directory"
		make install
		Verify_Result
		LogMsg "OSU mpi-benchmarks $osu_mpi_benchmark installation completed"
		# set string to verify osu benchmark is downloaded
		osu_benchmark_bin=/usr/local/libexec/osu-micro-benchmarks/mpi/pt2pt/osu_latency
		Verify_File $osu_benchmark_bin
		cd $currentDir
	fi

	echo "setup_completed=0" >> /root/constants.sh
	LogMsg "Completed SetupRDMA process"
	LogMsg "Main function completed"
}

function post_verification() {
	# Assumption: all paths are default setting
	LogMsg "Post_verification starting"

	# Validate if the platform MPI binaries work in the system.
	_hostname=$(cat /etc/hostname)
	_ipaddress=$(hostname -i | awk '{print $1}')
	LogMsg "Found hostname from system: $_hostname"
	LogMsg "Found _ipaddress from system: $_ipaddress"

	# MPI hostname cmd for initial test
	if [ $mpi_type == "ibm" ]; then
		_res_hostname=$(/opt/ibm/platform_mpi/bin/mpirun -TCP -hostlist $_ipaddress:1 hostname)
	elif [ $mpi_type == "intel" ]; then
		_res_hostname=$(mpirun --host $_ipaddress hostname | head -1)
	elif [ $mpi_type == "open" ]; then
		_res_hostname=$(mpirun --allow-run-as-root -np 1 --host $_ipaddress hostname)
	else
		_res_hostname=$(mpirun_rsh -np 1 $_ipaddress hostname)
	fi
	LogMsg "queried value of _res_hostname: $_res_hostname"

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
	else
		LogMsg "TBD: This is $mpi_type MPI and no verification of ping_pong defined yet. Skipped"
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
