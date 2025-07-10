#!/bin/sh


log_file="$1"
pid_file="$2"
module_name="$3"
times="$4"                      # 100
verbose="$5"                          # true/false
dhclient_renew_command="$6"     # dhcpcd -k eth0; dhcpcd eth0

# Convert verbose parameter to a flag
if [ "$verbose" = "true" ]; then
    v="-v"
else
    v=""
fi

if [ "$module_name" = "hv_netvsc" ]; then
echo "running the modprobe reloader along with dhcpcd renew command"
echo "with verbose: $verbose, times: $times, module_name: $module_name, dhclient_renew_command: $dhclient_renew_command"
echo "v: $v"

echo "Executing command:"
echo "sudo nohup sh -c '(
  for i in \$(seq 1 $times); do
    modprobe -r $v $module_name >> $log_file 2>&1
    modprobe $v $module_name >> $log_file 2>&1
  done
  sleep 1
  ip link set eth0 down >> $log_file 2>&1
  ip link set eth0 up >> $log_file 2>&1
  dhcpcd -k eth0 >> $log_file 2>&1
  dhcpcd eth0 >> $log_file 2>&1
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
    dhcpcd -k eth0 >> "'"$log_file"'" 2>&1
    dhcpcd eth0 >> "'"$log_file"'" 2>&1
    sudo service ssh status >> "'"$log_file"'" 2>&1
    ip a >> "'"$log_file"'" 2>&1
  ) &
  echo $! > "'"$pid_file"'"
'

# sudo nohup sh -c '
#   (
#     for i in $(seq 1 '$times'); do
#       modprobe -r '$v' '"$module_name"' >> "'"$log_file"'" 2>&1
#       modprobe '$v' '"$module_name"' >> "'"$log_file"'" 2>&1
#     done
#     sleep 1
#     ip link set eth0 down >> "'"$log_file"'" 2>&1
#     ip link set eth0 up >> "'"$log_file"'" 2>&1
#     dhcpcd -k eth0 >> "'"$log_file"'" 2>&1
#     dhcpcd eth0 >> "'"$log_file"'" 2>&1
#     sudo service ssh status >> "'"$log_file"'" 2>&1
#     ip a >> "'"$log_file"'" 2>&1
#   ) &
#   echo $! > "'"$pid_file"'"
# '


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