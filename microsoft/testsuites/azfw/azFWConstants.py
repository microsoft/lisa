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
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: netRule" -j LOG --log-prefix "name_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: netRule" -j LOG --log-prefix "name_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: netRule" -j LOG --log-prefix "name_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: netRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -j LOG_DROP_OTHER'
    ]

class FirewallConstants:
    RUNTIMEDEPSFILENAME = "install_runtime_deps.sh"
    RUNTIMEDEPSFILEPATH = f"/tmp/{RUNTIMEDEPSFILENAME}"
    GETVMDETAILSFILENAME = "importdatafromjson.py"
    GETVMDETAILSFILEPATH = f"/tmp/{GETVMDETAILSFILENAME}"
    MDSMETADATAFILENAME = "mdsMetadata.txt"
    MDSMETADATAFILEPATH = f"/tmp/{MDSMETADATAFILENAME}"

class StorageConfigurations:
    GSAMANAGEDIDENTITY =""
    LISASTORAGEACCOUNTNAME = "lisatestresourcestorage"
    LISACONTAINERNAME = "fwcreateconfigfiles"
    FIREWALLAPPVERSION = "app"
    BOOTSTRAPFILENAME = f"app/{app}/bootstrap.tar"
    GSACONTAINERNAME = "app"
    GSAMSICLIENTID = ""
    GSASTORAGEACCOUNTNAME = "gsateststorage"

class TCPProtocolConstants:
    RULEFILENAME = "tcpRule.json"
    PREROUTINGCHAIN = [
        '-A PREROUTING -i eth0 -p tcp -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j L4_ALLOWED',
        '-A PREROUTING -i eth0 -p udp -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j L4_ALLOWED'
    ]
    FORWARDCHAIN = [
        '-A FORWARD -i eth0 -p tcp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j LOG --log-prefix "name_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j LOG --log-prefix "name_NR_ACCEPT_1: " --log-level 6',
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
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: allowICMPRule" -j LOG --log-prefix "name_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: allowICMPRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p icmp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: allowICMPRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p tcp -m multiport --dports 5201 -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: allowTCPRule" -j LOG --log-prefix "name_NR_ACCEPT_2: " --log-level 6',
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
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: allowUDPRule" -j LOG --log-prefix "name_NR_ACCEPT_1: " --log-level 6',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: allowUDPRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -p udp -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: allowUDPRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -m conntrack --ctstate NEW -m comment --comment "RC: netRuleCollection Rule: allowAllRule" -j LOG --log-prefix "name_NR_ACCEPT_2: " --log-level 6',
        '-A FORWARD -i eth0 -m conntrack --ctstate NEW,ESTABLISHED --ctdir ORIGINAL -m comment --comment "RC: netRuleCollection Rule: allowAllRule" -j MARK_ALLOWED_AND_ACCEPT',
        '-A FORWARD -i eth0 -m conntrack --ctstate ESTABLISHED --ctdir REPLY -m comment --comment "RC: netRuleCollection Rule: allowAllRule" -j MARK_ALLOWED_AND_ACCEPT'
    ]

