chmod +x nested_kvm_perf_fio.sh
./nested_kvm_perf_fio.sh &> fioConsoleLogs.txt
. utils.sh
collect_VM_properties nested_properties.csv