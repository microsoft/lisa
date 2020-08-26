#!/bin/bash

#######################################################################
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
#
#######################################################################

#######################################################################
#
# perf_mariadb.sh
# Description:
#    Install mariadb and sysbench.
#    Run performance test of MariaDB using sysbench.
#    This script needs to be run on client VM.
#
# Supported Distros:
#    Ubuntu/Suse/Centos/RedHat/Debian
#######################################################################
CONSTANTS_FILE="./constants.sh"
UTIL_FILE="./utils.sh"
HOMEDIR=$(pwd)
LOG_FOLDER="${HOMEDIR}/mariadb_log"
MARIADB_RESULT="${LOG_FOLDER}/report.csv"
MARIADB_LOG_NAME="mariadb.bench.log"
COMMON_LOG_FILE="${LOG_FOLDER}/common.log"
SYSBENCH_VERSION=1.0.20

db_path="/maria/db"
db_parent_path="/maria"
escaped_path=$(echo "${db_path}" | sed 's/\//\\\//g')
user="lisa"

. ${CONSTANTS_FILE} || {
	LogErr "Error: missing ${CONSTANTS_FILE} file"
	SetTestStateAborted
	exit 0
}

. ${UTIL_FILE} || {
	LogErr "Missing ${UTIL_FILE} file"
	SetTestStateAborted
	exit 0
}

if [ ! "${server}" ]; then
	LogErr "Please add/provide value for server in constants.sh. server=<server ip>"
	SetTestStateAborted
	exit 0
fi
if [ ! "${client}" ]; then
	LogErr "Please add/provide value for client in constants.sh. client=<client ip>"
	SetTestStateAborted
	exit 0
fi

if [ ! "${THREADS}" ]; then
	THREADS=(1 2 4 8 16 32 64 128 256)
fi

if [ ! "${MAX_TIME}" ]; then
	MAX_TIME=300
fi

function install_sysbench () {
	LogMsg "Getting sysbench"
	wget https://github.com/akopytov/sysbench/archive/${SYSBENCH_VERSION}.tar.gz
	if [ $? -gt 0 ]; then
		LogErr "Failed to download sysbench"
		SetTestStateAborted
		exit 0
	fi

	tar -xzvf ${SYSBENCH_VERSION}.tar.gz
	if [ $? -gt 0 ]; then
		LogErr "Failed to unzip sysbench"
		SetTestStateAborted
		exit 0
	fi

	LogMsg "Building sysbench"
	pushd "${HOMEDIR}/sysbench-${SYSBENCH_VERSION}"
	./autogen.sh && ./configure && make && make install
	if [ $? -gt 0 ]; then
		LogErr "Failed to build sysbench"
		SetTestStateAborted
		exit 0
	fi
	popd
	export PATH="/usr/local/bin:${PATH}"
	LogMsg "Sysbench installed successfully"
}

function create_data_dir () {
	disks=$(ssh "${server}" ". $UTIL_FILE && get_AvailableDisks")
	# We just use only one disk
	for disk in ${disks}
	do
		Run_SSHCommand "${server}" "mkdir -p ${db_path}"
		Run_SSHCommand "${server}" "yes | mkfs.ext4 /dev/${disk}"
		Run_SSHCommand "${server}" "mount /dev/${disk} ${db_path}"
		Run_SSHCommand "${server}" "cp -rf /var/lib/mysql/* ${db_path}"
		Run_SSHCommand "${server}" "chown -R mysql:mysql ${db_path}"
		Run_SSHCommand "${server}" "chmod 0755 -R ${db_path}"
		# We also need to ensure that all the parent directories of the datadir upwards 
		# have "x" (execute) permissions for all (user, group, and other)
		# Refer to https://mariadb.com/kb/en/what-to-do-if-mariadb-doesnt-start/#cant-create-test-file
		Run_SSHCommand "${server}" "chmod 0755 -R ${db_parent_path}"
		break
	done
}

function config_mariadb () {
	case "$DISTRO_NAME" in
		oracle|rhel|centos)
			# Mariadb is not enabled by default
			#Run_SSHCommand "${server}" "service mariadb start"
			Run_SSHCommand "${server}" "service mariadb stop"
			Run_SSHCommand "${server}" "echo datadir = ${db_path} | sudo tee --append /etc/my.cnf.d/mariadb-server.cnf"
			Run_SSHCommand "${server}" "echo bind-address = 0.0.0.0 | sudo tee --append /etc/my.cnf.d/mariadb-server.cnf"
			Run_SSHCommand "${server}" "echo max_connections = 1024 | sudo tee --append /etc/my.cnf.d/mariadb-server.cnf"
			# Config the systemd service to set the open files limit as infinity
			# Refer to https://mariadb.com/kb/en/systemd/
			Run_SSHCommand "${server}" "echo LimitNOFILE=infinity | sudo tee --append /lib/systemd/system/mariadb.service"
			Run_SSHCommand "${server}" "systemctl daemon-reload"
			# Config selinux to set enforcing to permissive
			# Refer to https://blogs.oracle.com/jsmyth/selinux-and-mysql
			Run_SSHCommand "${server}" "setenforce 0"
			Run_SSHCommand "${server}" "service mariadb start"
			;;
		ubuntu|debian)
			Run_SSHCommand "${server}" "service mysql stop"
			Run_SSHCommand "${server}" "sed -i '/datadir/c\datadir = ${escaped_path}' /etc/mysql/mariadb.conf.d/50-server.cnf"
			Run_SSHCommand "${server}" "sed -i '/bind-address/c\bind-address = 0\.0\.0\.0' /etc/mysql/mariadb.conf.d/50-server.cnf"
			Run_SSHCommand "${server}" "sed -i '/max_connections/c\max_connections = 1024' /etc/mysql/mariadb.conf.d/50-server.cnf"
			Run_SSHCommand "${server}" "service mariadb start"
			;;
		*)
			LogErr "Unsupported distribution"
			return 1
	esac
	if [ $? -ne 0 ]; then
		return 1
	fi
}

function config_mariadb_for_remote_access () {
	# We can refer to https://webdock.io/en/docs/how-guides/how-enable-remote-access-your-mariadbmysql-database
	# to get the meaning of these sql commands.
	Run_SSHCommand "${server}" "mysql -e \"GRANT ALL PRIVILEGES ON *.* TO '${user}'@'${client}' IDENTIFIED BY 'lisapassword' WITH GRANT OPTION;\""
	Run_SSHCommand "${server}" "mysql -e \"DROP DATABASE sbtest;\""
	Run_SSHCommand "${server}" "mysql -e \"CREATE DATABASE sbtest;\""
	Run_SSHCommand "${server}" "mysql -e \"FLUSH PRIVILEGES;\""
}

function start_monitor()
{
	lteration=${1}
	mpstat_cmd="mpstat"
	iostat_cmd="iostat"
	sar_cmd="sar"
	vmstat_cmd="vmstat"
	Run_SSHCommand "${server}" "pkill -f iostat"
	Run_SSHCommand "${server}" "pkill -f mpstat"
	Run_SSHCommand "${server}" "pkill -f sar"
	Run_SSHCommand "${server}" "pkill -f vmstat"
	Run_SSHCommand "${server}" "${iostat_cmd} -x -d 1" > "${LOG_FOLDER}/${lteration}.iostat.server.log" &
	Run_SSHCommand "${server}" "${sar_cmd} -n DEV 1" > "${LOG_FOLDER}/${lteration}.sar.server.log" &
	Run_SSHCommand "${server}" "${mpstat_cmd} -P ALL 1" > "${LOG_FOLDER}/${lteration}.mpstat.server.log" &
	Run_SSHCommand "${server}" "${vmstat_cmd} 1" > "${LOG_FOLDER}/${lteration}.vmstat.server.log" &

	pkill -f iostat
	pkill -f mpstat
	pkill -f sar
	pkill -f vmstat
	${iostat_cmd} -x -d 1 > ${LOG_FOLDER}/${lteration}.iostat.client.log &
	${sar_cmd} -n DEV 1 > ${LOG_FOLDER}/${lteration}.sar.client.log &
	${mpstat_cmd} -P ALL 1 > ${LOG_FOLDER}/${lteration}.mpstat.client.log &
	${vmstat_cmd} 1 > ${LOG_FOLDER}/${lteration}.vmstat.client.log &
}

function stop_monitor()
{
	Run_SSHCommand "${server}" "pkill -f dstat"
	Run_SSHCommand "${server}" "pkill -f mpstat"
	Run_SSHCommand "${server}" "pkill -f sar"
	Run_SSHCommand "${server}" "pkill -f vmstat"
	pkill -f dstat
	pkill -f mpstat
	pkill -f sar
	pkill -f vmstat
}

function parse_log () {
	threads=${1}
	mariadb_log_file="${LOG_FOLDER}/${threads}.${MARIADB_LOG_NAME}"
	Threads=$(grep "Number of threads:" $mariadb_log_file | awk '{print $NF}')
	TotalQueries=$(grep "total:" $mariadb_log_file | awk '{print $NF}')
	TransactionsPerSec=$(grep "transactions:" $mariadb_log_file | awk -F '(' '{print $2}' | awk '{print $1}')
	Latency95Percentile_ms=$(grep "95th percentile:" $mariadb_log_file | awk '{print $NF}')

	LogMsg "Test Results: "
	LogMsg "---------------"
	LogMsg "Threads: $Threads"
	LogMsg "Total Queries: $TotalQueries"
	LogMsg "Transactions Per Sec: $TransactionsPerSec"
	LogMsg "95 Percentile latency(ms): $Latency95Percentile_ms"

	echo "$Threads,$TotalQueries,$TransactionsPerSec,$Latency95Percentile_ms" >> "${MARIADB_RESULT}"
}

function run_mariadb () {
	threads=$1

	LogMsg "======================================"
	LogMsg "Running mariadb test with current threads: ${threads}"
	LogMsg "======================================"
	start_monitor ${threads}

	sysbench ${oltp_path} --mysql-host=${server} --mysql-user=${user} --mysql-password=lisapassword \
--mysql-db=sbtest --time=${MAX_TIME} --oltp-test-mode=complex --mysql-table-engine=innodb --oltp-read-only=off \
--max-requests=1000000 --num-threads=${threads} run > "${LOG_FOLDER}/${threads}.${MARIADB_LOG_NAME}"

	stop_monitor
	parse_log ${threads}
}

Run_SSHCommand "${server}" "rm -rf ${LOG_FOLDER}"
Run_SSHCommand "${server}" "mkdir -p ${LOG_FOLDER}"
rm -rf ${LOG_FOLDER}
mkdir -p ${LOG_FOLDER}

# Install mariadb in client and server machine
LogMsg "Configuring client ${client}..."
install_mariadb
if [ $? -ne 0 ]; then
	LogErr "Mariadb installation failed in ${client}.."
	SetTestStateAborted
	exit 0
fi

LogMsg "Configuring server ${server}..."
Run_SSHCommand "${server}" ". $UTIL_FILE && install_mariadb"
if [ $? -ne 0 ]; then
	LogErr "Mariadb installation failed in ${server}..."
	SetTestStateAborted
	exit 0
fi

# Install sysbench in client machine
LogMsg "Installing sysbench in client ${client}..."
install_sysbench

# Create data directory of mysql on server machine
LogMsg "Creating data directory of mysql in server ${server}..."
create_data_dir
if [ $? -ne 0 ]; then
	LogErr "Creating data directory of mysql failed in server ${server}.."
	SetTestStateAborted
	exit 0
fi

# Config MariaDB
LogMsg "Configing MarinaDB in server ${server}..."
config_mariadb
if [ $? -ne 0 ]; then
	LogErr "Configing MarinaDB failed in server ${server}.."
	SetTestStateAborted
	exit 0
fi

# Config MariaDB for remote access
LogMsg "Configing MarinaDB for remote access in server ${server}..."
config_mariadb_for_remote_access
if [ $? -ne 0 ]; then
	LogErr "Configing MarinaDB for remote access failed in server ${server}.."
	SetTestStateAborted
	exit 0
fi

# Prepare for mariadb test
LogMsg "Prepare for MarinaDB test in client ${client}..."
oltp_path="${HOMEDIR}/sysbench-${SYSBENCH_VERSION}/tests/include/oltp_legacy/oltp.lua"
sysbench ${oltp_path} --mysql-host=${server} --mysql-user=${user} --mysql-password=lisapassword \
--mysql-db=sbtest --oltp-table-size=1000000 prepare >> ${COMMON_LOG_FILE}

echo "Threads,TotalQueries,TransactionsPerSec,Latency95Percentile_ms" > "${MARIADB_RESULT}"

# Run mariadb test
LogMsg "Running MariaDB performance test using sysbench in client ${client}..."
for threads in "${THREADS[@]}"
do
    run_mariadb ${threads}
done

LogMsg "Kernel Version : $(uname -r)"
LogMsg "Guest OS : ${distro}"

column -s, -t "${MARIADB_RESULT}" > "${LOG_FOLDER}"/report.log
cp "${LOG_FOLDER}"/* .
cat report.log
SetTestStateCompleted
