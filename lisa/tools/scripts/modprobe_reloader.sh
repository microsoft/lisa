#!/bin/sh

set -x

# Ensure modprobe is in PATH and detect modprobe location
export PATH="/usr/sbin:/sbin:$PATH"

# Find modprobe location using LISA's standard approach
if command -v modprobe >/dev/null 2>&1; then
    MODPROBE_CMD=$(command -v modprobe)
else
    MODPROBE_CMD="modprobe"  # fallback, will likely fail but let's try
fi
log_file="${1:-$HOME/modprobe_reloader.log}"    # Default log file path in the home directory
pid_file="${2:-$HOME/modprobe_reloader.pid}"    # Default PID file path in the home directory
module_name="${3:-hv_netvsc}"                   # Default module name
times="${4:-1}"                                 # Default number of iterations
verbose="${5:-true}"                            # Default verbosity (true)
dhclient_command="${6:-dhclient}"               # Default DHCP client command
interface="${7:-eth0}"                          # Default network interface



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
      echo "Iteration $j of $times" >> "$log_file"
      
      # Try to remove module up to 5 times or until successfully removed
      remove_attempt=1
      while [ $remove_attempt -le 5 ]; do
        echo "Remove attempt $remove_attempt" >> "$log_file"
        sudo "$MODPROBE_CMD" -r $v "$module_name" >> "$log_file" 2>&1
        check_module_removed=$(lsmod | grep hv_netvsc || true)
        echo "After remove attempt $remove_attempt: '$check_module_removed'" >> "$log_file"
        if [ -z "$check_module_removed" ]; then
          echo "SUCCESS: Module removed successfully on attempt $remove_attempt" >> "$log_file"
          break
        else
          echo "WARNING: Module still present after removal attempt $remove_attempt: $check_module_removed" >> "$log_file"
          if [ $remove_attempt -eq 5 ]; then
            echo "ERROR: Failed to remove module after 5 attempts" >> "$log_file"
          fi
        fi
        remove_attempt=$((remove_attempt + 1))
        sleep 0.5
      done
      
      sudo "$MODPROBE_CMD" "$v" "$module_name" >> "$log_file" 2>&1
      check_module_loaded=$(lsmod | grep hv_netvsc || true)
      echo "After load: '$check_module_loaded'" >> "$log_file"
      if [ -n "$check_module_loaded" ]; then
        echo "SUCCESS: Module loaded successfully: $check_module_loaded" >> "$log_file"
      else
        echo "ERROR: Module not found after loading" >> "$log_file"
      fi
      echo "---" >> "$log_file"
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
      { sudo "$MODPROBE_CMD" -r $v "$module_name"; sudo "$MODPROBE_CMD" $v "$module_name"; } >> "$log_file" 2>&1
      j=$((j + 1))
    done
  ) &
  echo $! > "$pid_file"
fi