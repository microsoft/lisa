from typing import cast
from lisa import (
    Logger,
    TestCaseMetadata,
    TestSuite,
    TestSuiteMetadata,
    simple_requirement,
    Environment,
    RemoteNode
)
from lisa.features import NetworkInterface
import time

@TestSuiteMetadata(
    area="networking",
    category="functional",
    description="""
    This test suite verifies marking in conntrack.
    """,
    requirement=simple_requirement(min_count=3, min_nic_count=3)
)
class FunctionalityTest(TestSuite):
    @TestCaseMetadata(
        description="""
        This test will add a Unknown Connection to conntrack and then remove the mark from it.
        """,
        priority=1
    )
    def verify_conntrack_mark_removal(self, environment: Environment, log: Logger) -> None:
        node0 = cast(RemoteNode, environment.nodes[0])
        # Install required tools
        node0.execute("sudo tdnf install -y iptables conntrack", sudo=True)

        # Add Unknown Connection to conntrack
        result = node0.execute(
                    "sudo conntrack -I -s 192.168.7.10 -d 10.1.1.1 --protonum 2 --timeout 120 --mark=0x1", 
                    sudo=True
                )
        if "1 flow entries have been created" not in result.stdout:
            raise Exception("Not able to add Unknown Connection in conntrack")
        
        log.info("Removing mark from existing conntrack entries")

        # Remove conntrack marking
        result = node0.execute("sudo conntrack -U --mark 0/0x1", sudo=True)
        if "1 flow entries have been updated" in result.stdout:
            log.info("Marking removed from conntrack entries")
        else: 
            raise Exception("Marking failed", result.stdout)
    
    @TestCaseMetadata(
        description="""
        This test will verify that the conntrack mark is removed after a timeout.
        """,
        priority=1
    )
    def verify_rsyslog_logrotate(self, environment: Environment, log: Logger) -> None:
        node0 = cast(RemoteNode, environment.nodes[0])
        packages = ["rsyslog", "logrotate", "vim"]
        fileNames = ["azfw-logrotate", "00-test.conf", "runloggerinloop.py"]
        
        # Install required packages
        for package in packages:
            installandsetuppackages(package, node0, log)
        
        
        #Login to Azure CLI using Managed Identity
        GsaTestStorageBlobReaderIdentity = "/subscriptions/e7eb2257-46e4-4826-94df-153853fea38f/resourcegroups/gsatestresourcegroup/providers/Microsoft.ManagedIdentity/userAssignedIdentities/gsateststorage-blobreader"
        result = node0.execute("tdnf install -y azure-cli", sudo=True)
        log.info("Azure CLI:", result)
        result = node0.execute(f"az login --identity --resource-id {GsaTestStorageBlobReaderIdentity}", sudo=True)

        # Download required files
        for fileName in fileNames:
            downloadfiles(fileName, node0, log)

        log.info("Move files to appropriate directories")
        node0.execute("mv /tmp/azfw-logrotate /etc/logrotate.d/azfw-logrotate", sudo=True)
        node0.execute("mv /tmp/00-test.conf /etc/rsyslog.d/00-test.conf", sudo=True)
        node0.execute("systemctl restart rsyslog", sudo=True)


        log.info("Creating azfw_*.log and kern.log files of size 300MB")
        node0.execute("fallocate -l 260M /var/log/azfw_test.log", sudo=True)
        node0.execute("fallocate -l 260M /var/log/kern.log", sudo=True)
        result = node0.execute("python3 /tmp/runloggerinloop.py &", sudo=True)
        log.info("Logger in loop started:", result)

        result = node0.execute("logrotate -f /etc/logrotate.d/azfw-logrotate", sudo=True)
        log.info("Logrotate result:", result)

        result = node0.execute("du -sh /var/log/azfw_test.log /var/log/azfw_test.log.1", sudo=True)

        if ("azfw_test.log.1" not in result.stdout):
            raise Exception("Log rotation failed, log files are not rotated", result.stdout)
        
        result =  node0.execute("du -sh /var/log/kern.log /var/log/kern.log.1", sudo=True)
        if("0" not in result.stdout and "kern.log.1" not in result.stdout):
            raise Exception("Log rotation failed, log files are not rotated", result.stdout)
        
        log.info("Log rotation successful, log files are rotated successfully.")
        node0.execute("logger -t \"testlogs\" \"test log logging using logger\"", sudo=True)
        result = node0.execute("du -sh /var/log/azfw_test.log", sudo=True)

        if("0" in result.stdout):
            raise Exception("Log rotation failed, azfw_test.log file is empty", result.stdout)
    @TestCaseMetadata(
        description= """
            This test will create three VMs
        """
    )
    def createresources(self, environment: Environment, log: Logger) -> None:
        print("Done creating the resources")

def installandsetuppackages(packageName, node, log):
    node.execute(f"sudo tdnf install -y {packageName}", sudo=True)
    node.execute(f"sudo systemctl enable {packageName}", sudo=True)
    node.execute(f"sudo systemctl start {packageName}", sudo=True)
    log.info(f"{packageName} installed and enabled successfully.")

def downloadfiles(fileName, node, log):
    log.info(f"Downloading {fileName} file")
    result = node.execute(f"az storage blob download --auth-mode login --account-name lisatestresourcestorage -c fwcreateconfigfiles -n {fileName} -f /tmp/{fileName}", sudo=True)
    log.info(f"{fileName} file downloaded successfully.", result)
    return f"/tmp/{fileName}"


