# dpdk-devname

Print info about DPDK ports on a system.

## NOTE: This is a frozen copy from https://www.github.com/mcgov/devname

## build
clone into dpdk/examples
``` bash
git clone https://www.github.com/DPDK/dpdk.git
cd ./dpdk/examples
git clone https://github.com/mcgov/devname.git
cd ..
meson setup -Dexamples=devname [other options] build
cd build && ninja && ninja install
```

## usage:
```
$ ./build/examples/dpdk-devname
EAL: Detected CPU lcores: 32
EAL: Detected NUMA nodes: 1
EAL: Detected static linkage of DPDK
EAL: Multi-process socket /var/run/dpdk/rte/mp_socket
EAL: Selected IOVA mode 'PA'
EAL: Probe PCI driver: net_mana (1414:ba) device: 7870:00:00.0 (socket 0)
mana_init_once(): MP INIT PRIMARY
TELEMETRY: No legacy callbacks, legacy socket not created
dpdk-devname found port=0 driver=net_mana eth_dev_info_name=7870:00:00.0 get_name_by_port_name=7870:00:00.0_port3 owner_id=0x0000000000000002 owner_name=f8615163-0002-1000-2000-6045bda6bbc0 macaddr=60:45:bd:a6:bb:c0
dpdk-devname found port=1 driver=net_mana eth_dev_info_name=7870:00:00.0 get_name_by_port_name=7870:00:00.0_port2 owner_id=0x0000000000000001 owner_name=f8615163-0001-1000-2000-6045bda6bd76 macaddr=60:45:bd:a6:bd:76
dpdk-devname found port=2 driver=net_netvsc eth_dev_info_name=f8615163-0001-1000-2000-6045bda6bd76 get_name_by_port_name=f8615163-0001-1000-2000-6045bda6bd76 owner_id=0x0000000000000000 owner_name=null macaddr=60:45:bd:a6:bd:76
dpdk-devname found port=3 driver=net_netvsc eth_dev_info_name=f8615163-0002-1000-2000-6045bda6bbc0 get_name_by_port_name=f8615163-0002-1000-2000-6045bda6bbc0 owner_id=0x0000000000000000 owner_name=null macaddr=60:45:bd:a6:bb:c0
```
