class ProtocolConstants:
    TCP = "tcp"
    UDP = "udp"
    ICMP = "icmp"

class GenevaConfigurationConstants:
    SETTINGSFILENAME = "kvsettings.json"
    SETTINGSFILEPATH = "/tmp/kvsettings.json"

class TrafficConfigurations:
    PACKETCOUNT = 40
    PACKETLENGTH = 128000
    TOTALBYTES = 5120000
    IPERF3PORT = 5201
    BITRATE = f"{(PACKETLENGTH * 8) / (1024*1024)}M/{PACKETCOUNT}" 

class ConnTrackMarks:
    ACTIVE = "256"
    RESET = "0"

class VMConfigurations:
    VMCOUNT = 3
    NICCOUNT = 3

class NetworkRules:
    PREROUTINGCHAIN = [
        '-A PREROUTING -i eth0 -p tcp -m comment --comment "RC: netRuleCollection Rule: netRule" -j L4_ALLOWED',
        '-A PREROUTING -i eth0 -p udp -m comment --comment "RC: netRuleCollection Rule: netRule" -j L4_ALLOWED',
        '-A PREROUTING -i eth0 -p icmp -m comment --comment "RC: netRuleCollection Rule: netRule" -j L4_ALLOWED'
    ]
    FORWARDCHAIN = [
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: netRule" -j LOG --log-prefix "AZFW_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: netRule" -j LOG --log-prefix "AZFW_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: netRule" -j LOG --log-prefix "AZFW_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -j LOG_DROP_OTHER'
    ]



class StorageConfigurations:
    GSAMANAGEDIDENTITY ="/subscriptions/e7eb2257-46e4-4826-94df-153853fea38f/resourcegroups/gsatestresourcegroup/providers/Microsoft.ManagedIdentity/userAssignedIdentities/gsateststorage-blobreader"
    LISASTORAGEACCOUNTNAME = "lisatestresourcestorage"
    LISACONTAINERNAME = "fwcreateconfigfiles"
    FIREWALLAPPVERSION = "app-15817278"
    BOOTSTRAPFILENAME = f"app/{FIREWALLAPPVERSION}/bootstrap.tar"
    GSACONTAINERNAME = "app"
    GSAMSICLIENTID = "6f5a4b4b-8ca9-47b8-a65b-50b249dafa6b"
    GSASTORAGEACCOUNTNAME = "gsateststorage"

class TCPProtocolConstants:
    RULEFILENAME = "tcpRule.json"
    PREROUTINGCHAIN = [
        '-A PREROUTING -i eth0 -p tcp -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j L4_ALLOWED',
        '-A PREROUTING -i eth0 -p udp -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j L4_ALLOWED'
    ]
    FORWARDCHAIN = [
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j LOG --log-prefix "AZFW_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j LOG --log-prefix "AZFW_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j MARK_ALLOWED_AND_ACCEPT'
    ]

class ICMPProtocolConstants:
    RULEFILENAME = "icmpRule.json"
    PREROUTINGCHAIN = [
        '-A PREROUTING -i eth0 -p icmp -m comment --comment "RC: netRuleCollection Rule: allowICMPRule" -j L4_ALLOWED',
        '-A PREROUTING -i eth0 -p tcp -m multiport --dports 5201 -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j L4_ALLOWED'
    ]
    FORWARDCHAIN = [
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: allowICMPRule" -j LOG --log-prefix "AZFW_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: allowICMPRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: allowICMPRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p tcp -m multiport --dports 5201 -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j LOG --log-prefix "AZFW_NR_ACCEPT_2: " --log-level 6',
        '-A FORWARD -i eth0 -p tcp -m multiport --dports 5201 -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p tcp -m multiport --sports 5201 -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j MARK_ALLOWED_AND_ACCEPT'        
    ]

class UDPProtocolConstants:
    RULEFILENAME = "udpRule.json"
    PREROUTINGCHAIN = [
        '-A PREROUTING -i eth0 -p udp -m comment --comment "RC: netRuleCollection Rule: allowUDPRule" -j L4_ALLOWED',
        '-A PREROUTING -i eth0 -m comment --comment "RC: netRuleCollection Rule: allowAllRule" -j L4_ALLOWED'
    ]
    FORWARDCHAIN = [
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: allowUDPRule" -j LOG --log-prefix "AZFW_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: allowUDPRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: allowUDPRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: allowAllRule" -j LOG --log-prefix "AZFW_NR_ACCEPT_2: " --log-level 6',
        '-A FORWARD -i eth0 -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: allowAllRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: allowAllRule" -j MARK_ALLOWED_AND_ACCEPT'
    ]

