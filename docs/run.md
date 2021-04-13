# Run LISA

- [Quick start](#quick-start)
  - [Run locally](#run-locally)
  - [Run in Azure](#run-in-azure)
  - [Run in Ready computers](#run-in-ready-computers)
- [Run Microsoft tests](#run-microsoft-tests)
- [Run legacy LISAv2 test cases](#run-legacy-lisav2-test-cases)

## Quick start

In Linux, define an alias to simplify the command. If you want it effective every time, add to `.bashrc`.

```bash
alias lisa="./lisa.sh"
```

### Run locally

If no argument specified, LISA runs test cases on the local computer. Those cases are helpful to validate LISA installation, and won't modify the local computer.

```bash
lisa
```

The end of output is like below, after completed. If there is any error, check [FAQ and troubleshooting](troubleshooting.md).

The log shows five test cases are scheduled, two passed, and three skipped. For each skipped case, there is a reason, why it's skipped. There is a html test report, and its link shows at end of log.

```text
2021-03-04 06:32:30.904 INFO LISA.RootRunner ________________________________________
2021-03-04 06:32:30.904 INFO LISA.RootRunner                                   HelloWorld.hello: PASSED
2021-03-04 06:32:30.905 INFO LISA.RootRunner                                     HelloWorld.bye: PASSED
2021-03-04 06:32:30.905 INFO LISA.RootRunner                          MultipleNodesDemo.os_info: SKIPPED  no available environment: ['no enough nodes, requirement: 2, capability: 1. ']
2021-03-04 06:32:30.906 INFO LISA.RootRunner MultipleNodesDemo.perf_network_tcp_ipv4_throughput_ntttcp_synthetic_singleconnection: SKIPPED  no available environment: ['no enough nodes, requirement: 2, capability: 1. ']
2021-03-04 06:32:30.906 INFO LISA.RootRunner                                  WithScript.script: SKIPPED  no available environment: ["os_type: requirements excludes ['Windows']"]
2021-03-04 06:32:30.907 INFO LISA.RootRunner test result summary
2021-03-04 06:32:30.907 INFO LISA.RootRunner   TOTAL      : 5
2021-03-04 06:32:30.908 INFO LISA.RootRunner     NOTRUN   : 0
2021-03-04 06:32:30.908 INFO LISA.RootRunner     RUNNING  : 0
2021-03-04 06:32:30.908 INFO LISA.RootRunner     FAILED   : 0
2021-03-04 06:32:30.908 INFO LISA.RootRunner     PASSED   : 2
2021-03-04 06:32:30.910 INFO LISA.RootRunner     SKIPPED  : 3
2021-03-04 06:32:30.913 INFO LISA.notifier[Html] report: D:\code\LISAv2\runtime\runs\20210304\20210304-063226-496\lisa.html
2021-03-04 06:32:30.923 INFO LISA completed in 4.428 sec
```

### Run in Azure

Below commands show how to run Microsoft tier 0 (t0) tests on an Azure
Marketplace image (as in
https://docs.microsoft.com/en-us/azure/virtual-machines/linux/cli-ps-findimage):

1. Sign in to Azure

    Make sure [Azure CLI](https://docs.microsoft.com/en-us/cli/azure/install-azure-cli) or [Azure PowerShell](https://docs.microsoft.com/en-us/powershell/azure/install-az-ps) installed. It needs to sign in to run LISA on the current computer. LISA supports other Azure credential mechanisms, refer to [runbook reference](runbook.md).

    Here uses Azure CLI as the example. Open a terminal, and execute,

    ```bash
    az login
    ```

2. Get the subscription id

    If you have multiple Azure subscriptions. Use below command to set default subscription. LISA will create resource groups in it. To prevent mistakes, the subscription id is a required parameter to run LISA.

    Run below command to retrieve subscription information.

    ```bash
    az account show --subscription "<Subscription Name to run LISA>"
    ```

    You will see output like below, find `<subscription id>` for next steps.

    ```json
    {
        "environmentName": "AzureCloud",
        "homeTenantId": "<tenant id>",
        "id": "<subscription id>",
        "isDefault": true,
        "managedByTenants": [],
        "name": "<subscription name>",
        "state": "Enabled",
        "tenantId": "<tenant id>",
        "user": {
            "name": "<user account>",
            "type": "user"
        }
    }
    ```

3. Prepare ssh key pair

    LISA connects to VMs by SSH, and a public/private key pair is necessary for authentication. If you don't have a key pair, follow this step to create one.

    Run below command and follow prompt to create a key pair. Most Linux distributions have SSH client installed. On windows, follow [install OpenSSH](https://docs.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse).

    Note, don't use passphrase to generate the key. LISA doesn't support passphrase.

    ```bash
    ssh-keygen
    ```

    Find `<private key file>` for next steps. If you want to move key files, keep public/private key files are in same folder, and keep the same base file name.

    ```bash
    Enter passphrase (empty for no passphrase):
    Enter same passphrase again:
    Your identification has been saved in <private key file>.
    Your public key has been saved in <public key file>.
    The key fingerprint is:
    SHA256:OIzc1yE7joL2Bzy8!gS0j8eGK7bYaH1FmF3sDuMeSj8 username@server@LOCAL-HOSTNAME

    The key's randomart image is:
    +--[ED25519 256]--+
    |        .        |
    |         o       |
    |    . + + .      |
    |   o B * = .     |
    |   o= B S .      |
    |   .=B O o       |
    |  + =+% o        |
    | *oo.O.E         |
    |+.o+=o. .        |
    +----[SHA256]-----+
    ```

4. Run LISA

    Use above `<subscription id>` and `<private key file>` to replace in below command. It may take several minutes to complete. Marketplace VM images can be found according to the instructions [here](https://docs.microsoft.com/en-us/azure/virtual-machines/linux/cli-ps-findimage)

    ```bash
    lisa -r ./microsoft/runbook/azure.yml -v subscription_id:<subscription id> -v "admin_private_key_file:<private key file>" -v "gallery_image:<marketplace image string>"
    ```
  


5. Verify test results

    After test completed, the html report is like below. The t0 includes the smoke test case, run on an Ubuntu image.

    ![image](img/smoke_test_result.png)

It doesn't need to create new VMs every time. The test Linux
distribution can be another Marketplace image or a VHD. Learn more
from [runbook reference](runbook.md).

### Run in Ready computers

The tests can run in an existing environment in lab or cloud. LISA calls the platform as `ready`.

1. Get IP address which can be accessed by LISA.

2. Get the SSH public/private key pair which can access the computers.

3. Run LISA in existing VM.

    Fill in related arguments and run. Note, since the existing VM doesn't support serial log, so smoke test cannot run in ready environment.

    ```bash
    lisa -r ./microsoft/runbook/ready.yml -v public_address:<public address> -v "user_name:<user name>" -v "admin_private_key_file:<private key file>"
    ```

The existing VMs can be multiple ones to support networking testing, and it also support authenticate by password. Learn more from [runbook reference](runbook.md).

## Run Microsoft tests

LISA is an end-to-end solution to validate Linux in Azure, Hyper-V or other Microsoft virtualization platforms. The quick start introduces how to run t0 Microsoft tests in Azure. It tests an image can boot up and reboot without kernel panic.

Refer to [Microsoft tests](microsoft_tests.md) know more about how test tiers defined.

If you want to validate more scenarios, run with `<tier id>` from 1 to 4. To run tier 1 to 4, it needs legacy LISAv2 tests. The LISA must be run in a Windows computer, and prepare a secret file. Learn more from [how to run legacy test cases](run_legacy.md).

```bash
lisa -r ./microsoft/runbook/azure.yml -v subscription_id:<subscription id> -v "admin_private_key_file:<private key file>" -v tier:<tier id>
```

Learn more from [command-line arguments](command_line.md) and the [runbook reference](runbook.md).

## Run legacy LISAv2 test cases

Learn more from [how to run legacy LISAv2 tests](run_legacy.md).
