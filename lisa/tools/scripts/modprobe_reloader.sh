#!/bin/sh


log_file="$1"
pid_file="$2"
module_name="$3"
times="$4"                      # 100
verbose="$5"                          # true/false
dhclient_command="$6"     # dhcpcd/dhclient
interface="$7"                # eth0

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



if [ "$module_name" = "hv_netvsc" ]; then
echo "running the modprobe reloader along with dhcpcd renew command"
# hv_netvsc needs a special case, since reloading it has the potential
# to leave the node without a network connection if things go wrong.

# These commands must be sent together, bundle them up as one line
# If the VM is disconnected after running below command, wait 60s is enough.
# however, go with bigger timeout if times > 1 (multiple times of reload)

echo "Executing command:"
echo "sudo nohup sh -c '(
  for i in \$(seq 1 $times); do
    modprobe -r $v $module_name >> $log_file 2>&1
    modprobe $v $module_name >> $log_file 2>&1
  done
  sleep 1
  ip link set eth0 down >> $log_file 2>&1
  ip link set eth0 up >> $log_file 2>&1
  $dhcp_stop_command >> $log_file 2>&1
  $dhcp_start_command >> $log_file 2>&1
  sudo service ssh status >> $log_file 2>&1
  ip a >> $log_file 2>&1
) &
echo \$! > $pid_file'"


sudo nohup sh -c '
  (
    for i in $(seq 1 '$times'); do
      modprobe -r '$v' '"$module_name"' >> "'"$log_file"'" 2>&1
      modprobe '$v' '"$module_name"' >> "'"$log_file"'" 2>&1
    done
    sleep 1
    ip link set eth0 down >> "'"$log_file"'" 2>&1
    ip link set eth0 up >> "'"$log_file"'" 2>&1
    '"$dhcp_stop_command"' >> "'"$log_file"'" 2>&1
    '"$dhcp_start_command"' >> "'"$log_file"'" 2>&1
    sudo service ssh status >> "'"$log_file"'" 2>&1
    ip a >> "'"$log_file"'" 2>&1
  ) &
  echo $! > "'"$pid_file"'"
'

else
echo "running the modprobe reloader for module: $module_name"
sudo nohup sh -c '
  (
    for i in $(seq 1 '$times'); do
      modprobe -r '$v' '"$module_name"' >> "'"$log_file"'" 2>&1
      modprobe '$v' '"$module_name"' >> "'"$log_file"'" 2>&1
    done
  ) &
  echo $! > "'"$pid_file"'"
'
fi

# sudo sh -c '(for i in \$(seq 1 $times); do modprobe -r $verbose $mod_name >> $nohup_output_log_file_name 2>&1; modprobe $verbose $mod_name >> $nohup_output_log_file_name 2>&1; done; sleep 1; ip link set eth0 down; ip link set eth0 up; $renew_command)' & echo \$! > $loop_process_pid_file_name"