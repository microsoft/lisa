# Partner Jenkins Pipeline Operation Instruction

## Objective

This document provides instructions for partners to create their own customized menu for the Jenkins pipeline and to run Microsoft-provided tests and/or customized test cases in Jenkins. This instruction has 2 major parts; creating the menu from xml files and executing the tests. Creating a custom menu may be optional for your test development. If you keep the same menu structure and add new tests into the existing menu, you will only update the existing XML files in **./XML/TestCases/**

If you add a custom test menu, you will need to re-build the Jenkins menu, and then can run new tests.

## Develop tests in GitHub

`Source: https://github.com/LIS/LISAv2`

    1. ./XML folder: pre-defined global configuration and account information as well as Region information. 
        This folder also has two sub folders; 'TestCases' and 'VMConfigurations'. 'VMConfigurations' has the 
        list of xml files for each test case, which require the list of VM configuration information. 
        'TestCases' folder has the list of xml files for each test category. The master branch is owned by 
        Microsoft, and actively manages changes in LISAv2. New test case development and/or new menu 
        development must be approved by Microsoft.
    2. 'Testscripts' folder has the number of test scripts used in TestCases, and separated by OS type.
    3. 'Tools' folder has binary files required for test execution.
    4. This repo will provide Microsoft-provided test cases as well as capability of Partner-developed test cases.
        a. Microsoft will share the test development plan and its log with partners. If you only execute 
            Microsoft-provided tests, you can skip to the next section ‘Verify a published image on Azure’.
        b. Partner-developed test cases should follow these steps:
            i.   Sync up the local 'master' branch from remote 'master' branch in the GitHub project, 
                 if new work branch is in the LISAv2. Otherwise, you can folk the LISAv2 repo to your own GitHub 
                 account.
            ii.  Branch out for work and pull down to your local system.
            iii. Once a change is ready to review, create a Pull Request from LISAv2 in your account to LIS account. 
                 Or, new working branch to master in LISAv2 repo.
            iv.  Add ‘LisaSupport@microsoft.com’ to ‘Reviewers’, or send email to 'lisasupport@microsoft.com'.
            v.   Once it is approved, you can merge the Pull Request to master branch. In this case, you will need 
                 to rebuild the menu by ‘<Partner name>-Refresh-Test-Selection-Menus’.
    5. LISAv2 has defined some global variables. Test cases can use them as needed.
        a. Read-only global variables
            i. Common
                $TestID : The unique ID of the test run
                $WorkingDirectory: The current working directory of test run
                $LogDir: The logging directory
                $detectedDistro: The distro name of the test VM
                $BaseOsVHD : The VHD name if the test runs with a VHD
                $RGIdentifier: The ID included in the resource group name or HyperV group name
                $TestLocation: The Azure region or HyperV servers
                $TestPlatform: Azure or HyperV
                $user: The user name of the VM
                $password: The password of the VM
                $GlobalConfig: The global configuration xml
                $XmlSecrets: The secret file xml
                $resultPass: PASS
                $resultFail: FAIL
                $resultAborted: ABORTED
                $resultSkipped: SKIPPED
                $IsWindowsImage: Whether the test image is Windows

            ii. For Azure
                $ARMImageName: The ARM image name

            iii. For HyperV
                $HyperVInstanceSize: The VM size of VM on HyperV
                $DependencyVmName: The name of the dependency VM for test on HyperV
                $DependencyVmHost: The host name of the dependency VM for test on HyperV
                $VMGeneration: VM generation, 1 or 2

        b. Writeable global variables
                $LogFileName: The name of the log file

## Verify a published image on Azure

`Web Browser Instructions`

        1. Sign into Jenkins page with the assigned username & password
        2. Browse to '<Partner name>-Refresh-Test-Selection-Menu', if you would like to apply new menu or test cases 
           before test execution.
        3. Click 'Build with Parameters' in left panel menu
            a. Enter the git repo URL and branch name of new menu's xml file. We recommend keeping the default Repo 
               URL and branch name.
            b. Click 'Build' button.
            c. Click the working icon of the running job in 'Build History' and verify "SUCCESS" via 'Console Output' 
               details. You have new menu/test cases in Jenkins.
        4. Browse to '<Partner name>-Launch-Tests' and submit the job for test execution.
        5. Click 'Build with Parameters' in left panel menu
            a. Select 'ImageSource' or navigate to 'CustomVHD'. If you have external source URL, you can enter it in 
               'CustomVHDURL' text box.
            b. Leave 'Kernel' unchanged unless you would like to use customized kernel code or linux-next.
            c. Update the 3 options regarding how to select test cases; TestName, Category and Tag.
                i. Supported platform: Azure, HyperV, etc.
                ii. Available Category: BVT, Community, Functional, Performance, and Smoke.
                iii. Available Tags: boot, bvt, disk, ext4, gpu, hv_netvsc, etc.
        6. Enter partner's email address for report notification.


`API/cmdline Instruction`

A single script executes the test launch/execute with pre-defined parameters. It also offers a parameter file mode, which all parameters are set before execution. The test script loads all paramenters from the file. The parameter file is located at **./Utilities/TestParameters.sh**

    $./LaunchTestPipelineRemotely.sh -JenkinsUser "<Azure user account for ApiToken>" -ApiToken "<your access token>" -FtpUsername "<FTP user account>" -FtpPassword "<FTP user account password>" [-ImageSource "<Publisher Offer Sku Version>" | -CustomVHD "<path of vhd file>" | -CustomVHDURL "<URL of custom vhd file>"] -Kernel "[default|custom|linuxnext]" [-CustomKernelFile "<ONLY IF you set Kernel=custom>" | -CustomKernelURL "<ONLY IF you set Kernel=custom>"] -GitUrlForAutomation "https://github.com/LIS/LISAv2.git" -GitBranchForAutomation "master" [-TestByTestname "" | -TestByCategorisedTestname "" | -TestByCategory "" | -TestByTag ""] -Email "<Partner email for test result report>" -TestPipeline "<Partner pipeline name>" -LinuxUsername "<Linux guest OS user name>" -LinuxPassword "<Linux guest OS user password>" [-WaitForResult "yes"]

    $./LaunchTestPipelineRemotely.sh -ParametersFile "<parameter definition file>"

`‘Script name with populated parameters’`
 

    $./LaunchTestPipelineRemotely.sh -JenkinsUser "microsoft" -ApiToken "123451234512345dlkwekl2kfo" -FtpUsername "ftpuser" -FtpPassword "ftppassword!" [-ImageSource "linux-next_1.2" | -CustomVHD "/path/to/local/vhd/vhdx/vhd.xz" | -CustomVHDURL "http://downloadable/link/to/your/file.vhd/vhdx/vhd.xz"] -Kernel "default" -GitUrlForAutomation "https://github.com/LIS/LISAv2.git" -GitBranchForAutomation "master" -TestByTestname "Azure>>VERIFY-DEPLOYMENT-PROVISION>>eastasia,Azure>>VERIFY-HOSTNAME>>westeurope" -TestByCategorisedTestname "Azure>>Smoke>>default>>VERIFY-DEPLOYMENT-PROVISION>>northeurope,Azure>>Functional>>SRIOV>>VERIFY-SRIOV-LSPCI>>southcentralus" -TestByCategory "Azure>>Functional>>SRIOV>>eastus,Azure>>Community>>LTP>>westeurope" -TestByTag "Azure>>boot>>northcentralus,Azure>>wala>>westeurope,Azure>>gpu>>eastus" -Email "lisasupport@microsoft.com" -TestPipeline "Microsoft-Test-Execution-Pipeline" -LinuxUsername "linuxuser" -LinuxPassword "linuxpassword?"

    $./LaunchTestPipelineRemotely.sh -ParametersFile "TestParameters.sh"

## GlobalConfigurations.xml in XML folder

Pre-defined global configuration. We do not recommend making changes to this file.

## RegionAndStorageAccounts.xml in XML folder

It has pre-defined region information. We do not recommend making changes to this file.

## TestToRegionMapping.xml in XML folder

This XML file defines the regions per Category. It may require specific region only for available setup/resource. By default, 'global' has all regions.

## XML files in XML/TestCases folder

    This location has the list of XML files for test cases. Each XML file names after category 
    for each maintenance / sharing.
        1. BVT.xml: BVT (Build Validation Test) test cases
        2. CommunityTests.xml: Tests from Open Source Community.
        3. FunctionalTests-[FEATURE NAME].xml: Tests specific to a certain feature.
        4. FunctionalTests.xml: Miscellaneous feature tests for other areas.
        4. NestedVmTests.xml: Nested KVM and nested Hyper-V tests.
        4. Other.xml: If any does not fall into existing Category, add to here.
        5. PerformanceTests.xml: Performance test cases.
        7. SmokeTests.xml: It will run before BVT test runs.
        8. StressTests.xml: Network traffic and storage IO testing under heavy CPU and Memory stress.

    Here is the format inside of TestCases.xml file. TODO: Revise the definition, and required field or not.
    [Req] Required
    [Opt] Optional
        <testName></testName>: Represent unique Test Case name [Req]
        <testScript></testScript>: test script file name [Opt]
        <PowershellScript></PowershellScript>: Actual launch PS script file name. [Req]
        <files></files>: If test requires data files, add the file names here [Opt]
        <setupType></setupType>: The name represents VM definition in <Category name>TestsConfigurations xml file, 
            VMConfigurations folder. [Req]
        <Platform></Platform>: Supported platform names. Azure, HyperV, etc. [Req]
        <Category></Category>: Available Test Category [Req]
        <Area></Area>: Test Area [Req]
        <Tags></Tags>: Tag information seperated by comma [Opt]

## TestsConfigurations.xml in XML/VMConfigurations

Per Category, each XML file has VM name, Resource Group name, etc. We do not recommend to make change of the file.

## Add test case in Azure

    1. Design test case and its configuration.
    2. Create a new test case xml file under ./XML/TestCases folder. Or, update with new tags 
        in the existing xml file.
    3. Define testName, PowershellScript, setupType, Platform, Category, and Area as required. 
        Add optional tag if needed.
    4. Test design may have two ways;
        a. A single PowerShell script execution: A single PowerShell script imports builtin library 
            modules and posts the result. For example, 'BVT-VERIFY-DEPLOYMENT-PROVISION.ps1' shows 
            this script calls 'Deploy-VMs' function for its testing and collect the result
            by 'Check-KernelLogs'. 'Deploy-VMs' and 'Check-KernelLogs' are functions definded
            in ./Libraries/CommonFunctions.psm1 module. 
            You can add new module or update existing ones for further development.
        b. PowerShell script wraps multiple non-PowerShell script like Bash or Python scripts: 
            Like 'VERIFY-TEST-SCRIPT-IN-LINUX-GUEST.ps1', the PowerShell script wraps the multiple 
            Bash or Python script as a parameter of 'Run-LinuxCmd' function.
    5. Before PR review, we recommend you run script testing in cmdline/API mode. See above instruction.
    6. Current tags in the Repo: bvt, network, nested, hv_storvsc, stress, disk, dpdk,
        sriov, kvm, smb, storage, boot, pci_hyperv, core, wala, lsvmbus, synthetic, kvp,
        gpu, hv_netvsc, ltp, lis, fcopy, memory, backup, gen2vm. They are all lowercases.

## Coding Style

    1. Reuse existing module, consolidate similar modules before you add or extend new function or file.
    2. Remove duplicated methods or modules.
    3. Remove commented code snippets and personal information.
    4. Review file header comments.
    5. Enforce code convention.
    6. Clean coding in open source tools; PSScript-Analyzer, pep8, etc.
    7. Use tab for indentation.
    8. Test log clean up requires:
        a. Log should be readable to reflect what’s happening in the test execution.
        b. Remove noise. Determine if it would be error or warning.
        c. Exception only in the case of fatal errors.
    9. Recommended Bash & Python function name format - Function_Name(). Upper letter in each string connected
        with underscore character. PowerShell function name format remains Verb-Entity() format like Get-VMSize().
    10. Use the same terminology:
        1. PASS
        2. FAIL
        3. ABORTED (all upper cases)
    11. TestCase names in XML files are in all Capital.

## Use recommended distro name

    1. Short distro name in log, graph and script:
        a. CentOS
            CentOS Linux release 7.0.1406 (Core)
            CentOS Linux release 7.1.1503 (Core)
            CentOS Linux release 7.2.1511 (Core)
            CentOS Linux release 7.3.1611 (Core)
            CentOS Linux release 7.4.1708 (Core)
            CentOS Linux release 7.5.1804 (Core)
            CentOS release 6.5 (Final)
            CentOS release 6.6 (Final)
            CentOS release 6.7 (Final)
            CentOS release 6.8 (Final)
            CentOS release 6.9 (Final)
            CentOS release 6.10 (Final)
        b. ClearLinux
            Clear Linux OS for Intel Architecture 1
        c. Debian
            Debian GNU/Linux 7 (wheezy)
            Debian GNU/Linux 8 (jessie)
            Debian GNU/Linux 9 (stretch)
        d. OpenSUSE
            openSUSE Leap 42.3
        e. Oracle
            Oracle Linux Server 6.8
            Oracle Linux Server 6.9
            Oracle Linux Server 7.3
            Oracle Linux Server 7.4
        f. RHEL
            Red Hat Enterprise Linux Server release 6.7 (Santiago)
            Red Hat Enterprise Linux Server release 6.8 (Santiago)
            Red Hat Enterprise Linux Server release 6.9 (Santiago)
            Red Hat Enterprise Linux Server release 6.10 (Santiago)
            Red Hat Enterprise Linux Server release 7.2 (Maipo)
            Red Hat Enterprise Linux Server release 7.3 (Maipo)
            Red Hat Enterprise Linux Server release 7.4 (Maipo)
            Red Hat Enterprise Linux Server release 7.5 (Maipo)
        g. SLES
            SUSE Linux Enterprise Server 11 SP4
            SUSE Linux Enterprise Server 12 SP2
            SUSE Linux Enterprise Server 12 SP3
            SUSE Linux Enterprise Server 15
        h. Ubuntu
            Ubuntu 12.04.5 LTS, Precise Pangolin
            Ubuntu 14.04.5 LTS, Trusty Tahr
            Ubuntu 16.04.4 LTS (Xenial Xerus)
            Ubuntu 16.04.5 LTS (Xenial Xerus)
            Ubuntu 17.10 (Artful Aardvark)
            Ubuntu 18.04 LTS (Bionic Beaver)
            Ubuntu 18.04.1 LTS (Bionic Beaver)
        j. CoreOS
            CoreOS Linux (Stable)
            CoreOS Linux (Alpha)
            CoreOS Linux (Beta)
    2. Add version number, project name or use full name if space is sufficient.

## Support Contact

Contact LisaSupport@microsoft.com (Linux Integration Service Support), if you have technical issues.
