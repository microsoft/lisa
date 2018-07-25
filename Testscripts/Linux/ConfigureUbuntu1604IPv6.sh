# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the Apache License.
echo 'iface eth0 inet6 auto' >> /etc/network/interfaces.d/50-cloud-init.cfg
echo 'up sleep 5' >> /etc/network/interfaces.d/50-cloud-init.cfg
echo 'up dhclient -1 -6 -cf /etc/dhcp/dhclient6.conf -lf /var/lib/dhcp/dhclient6.eth0.leases -v eth0 || true' >> /etc/network/interfaces.d/50-cloud-init.cfg
ifdown eth0 && ifup eth0