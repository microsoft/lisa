#!/bin/sh

log_file="$1"
pid_file="$2"
module_name="$3"
times="$4"                      # 100
verbose="$5"                    # true/false
dhclient_command="$6"           # dhcpcd/dhclient
interface="$7"                  # eth0

if [ "$dhclient_command" = "dhcpcd" ]; then
    dhcp_stop_command="dhcpcd -k $interface"
    dhcp_start_command="dhcpcd $interface"
else
    dhcp_stop_command="dhclient -r $interface"
    dhcp_start_command="dhclient $interface"
fi

# Convert verbose parameter to a flag
if [ "$verbose" = "true" ]; then
    v="-v"
else
    v=""
fi

echo "with verbose: $verbose, times: $times, module_name: $module_name, dhcp_stop_command: $dhcp_stop_command, dhcp_start_command: $dhcp_start_command"
echo "v: $v"
set -x
echo "starrting time: $(date)"
if [ "$module_name" = "hv_netvsc" ]; then
echo "Running the modprobe reloader along with dhcpcd renew command for module: $module_name"

# (for i in $(seq 1 $times); do
#   modprobe -r $v "$module_name" >> "$log_file" 2>&1
#   modprobe $v "$module_name" >> "$log_file" 2>&1
#   done
#   sleep 1
#   ip link set eth0 down >> "$log_file" 2>&1
#   ip link set eth0 up >> "$log_file" 2>&1
#   $dhcp_stop_command >> "$log_file" 2>&1
#   $dhcp_start_command >> "$log_file" 2>&1
#   service ssh status >> "$log_file" 2>&1
#   ip a >> "$log_file" 2>&1
# ) &
# echo $! > "$pid_file"



(
  j=1
  while [ $j -le $times ]; do
    echo "interation start: $j"
    modprobe -r $v $module_name >> $log_file 2>&1
    modprobe $v $module_name >> $log_file 2>&1
    j=$((j + 1))
    echo "interation end: $j"
  done
  echo "End of loop"
  sleep 1
  ip link set eth0 down >> $log_file 2>&1
  ip link set eth0 up >> $log_file 2>&1
  $dhcp_stop_command >> $log_file 2>&1
  $dhcp_start_command >> $log_file 2>&1
  service ssh status >> $log_file 2>&1
  ip a >> $log_file 2>&1
) &
echo $! > $pid_file


else
echo "Running the modprobe reloader for module: $module_name"

# (for i in $(seq 1 $times); do
#   modprobe -r $v "$module_name" >> "$log_file" 2>&1
#   modprobe $v "$module_name" >> "$log_file" 2>&1
#   done
# ) &
# echo $! > "$pid_file"


#modprobe -r $v $module_name >> "log1" 2>&1
#modprobe $v $module_name >> "log1" 2>&1


#modprobe -r $v $module_name >> $log_file 2>&1
#modprobe $v $module_name >> $log_file 2>&1

echo "before the loop with sudo"
sudo modprobe -r $v $module_name
sudo modprobe $v $module_name
echo "before the loop without sudo"
modprobe -r $v $module_name
modprobe $v $module_name
echo "just before the loop"
(
  j=1
  while [ $j -le $times ]; do
    echo "interation start: $j"

    ls

    sudo modprobe -r $v $module_name
    sudo modprobe $v $module_name

    # modprobe -r $v $module_name >> log3 2>&1
    # modprobe $v $module_name >> log3 2>&1

    # modprobe -r $v $module_name >> "$log_file" 2>&1
    # modprobe $v $module_name >> "$log_file" 2>&1

    j=$((j + 1))
    echo "interation end: $j"
  done
  echo "End of loop"
)
# ) &
echo $! > $pid_file

fi

echo "stopped time: $(date)"
