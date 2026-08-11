#!/bin/sh

set -x
log_file="${1:-$HOME/modprobe_reloader.log}"    # Default log file path in the home directory
pid_file="${2:-$HOME/modprobe_reloader.pid}"    # Default PID file path in the home directory
module_name="${3:-hv_netvsc}"                   # Default module name
times="${4:-1}"                                 # Default number of iterations
dhclient_command="${5:-dhclient}"               # Default DHCP client command
interface="${6:-eth0}"                          # Default network interface

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
      { modprobe -r -v "$module_name"; modprobe -v "$module_name"; } >> "$log_file" 2>&1
      j=$((j + 1))
    done
    sleep 1
    # shellcheck disable=SC2086,SC2129
    ip link set $interface down >> $log_file 2>&1
    # shellcheck disable=SC2086,SC2129
    ip link set $interface up >> $log_file 2>&1
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
      { modprobe -r -v "$module_name"; modprobe -v "$module_name"; } >> "$log_file" 2>&1
      j=$((j + 1))
    done
  ) &
  echo $! > "$pid_file"
fi