#!/bin/sh

set -x
log_file="$1"
pid_file="$2"
module_name="$3"
times="$4"                      # 100
verbose="$5"                    # true/false
dhclient_command="$6"           # dhcpcd/dhclient
interface="$7"                  # eth0

# Convert verbose parameter to a flag
if [ "$verbose" = "true" ]; then
    v="-v"
else
    v=""
fi

if [ "$dhclient_command" = "dhcpcd" ]; then
    dhcp_stop_command="dhcpcd -k $interface"
    dhcp_start_command="dhcpcd $interface"
else
    dhcp_stop_command="dhclient -r $interface"
    dhcp_start_command="dhclient $interface"
fi

if [ "$module_name" = "hv_netvsc" ]; then
  (
    j=1
    while [ $j -le "$times" ]; do
      { modprobe -r "$v" "$module_name"; modprobe "$v" "$module_name"; } >> "$log_file" 2>&1
      j=$((j + 1))
    done
    sleep 1
    # shellcheck disable=SC2086,SC2129
    ip link set eth0 down >> $log_file 2>&1
    # shellcheck disable=SC2086,SC2129
    ip link set eth0 up >> $log_file 2>&1
    # shellcheck disable=SC2086,SC2129
    $dhcp_stop_command >> $log_file 2>&1
    # shellcheck disable=SC2086,SC2129
    $dhcp_start_command >> $log_file 2>&1
    # shellcheck disable=SC2086,SC2129
    service ssh status >> $log_file 2>&1
    # shellcheck disable=SC2086,SC2129
    ip a >> $log_file 2>&1
  ) &
  echo $! > "$pid_file"
else
  (
    j=1
    while [ $j -le "$times" ]; do
      { modprobe -r "$v" "$module_name"; modprobe "$v" "$module_name"; } >> "$log_file" 2>&1
      j=$((j + 1))
    done
  ) &
  echo $! > "$pid_file"
fi