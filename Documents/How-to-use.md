# Title: Partner Jenkins Pipeline Operation Instruction

`Updated: Tuesday, May 29, 2018`

## Objective

    This document instructs for partners to create customized menu of Jenkins pipeline and run either/both Microsoft-provided tests or/and customized test cases in Jenkins. This instruction has 2 major parts; creating menu from xml files and executing tests.

## Prepare a VHD for tests.

    1. Start PowerShell with the Run As Administrator option.
    2. In powershell, Goto Automation Folder.
    3. Run following command.
        .\AzureAutomationManager.ps1 -xmlConfigFile .\Azure_ICA_all.xml -cycleName autosetup -Distro YourDistroName -runtests

        This command will install "Minimum Required Packages" and will capture the VHD which can be used to run further tests like, Network tests & VNET tests.

        List of minimum packages in VHD
            iperf
            mysql
            gcc
            bind
            bind-utils
            bind9
            python
            python-argparse
            python-crypto
            python-paramiko
            libstdc++6
            psmisc
            nfs-utils
            nfs-common
            tcpdump

    4.Once you get the prepared VHD Name, create a new element "Distro" in XML file and give prepared VHD name in Distro element.

## Develop tests in GitHub

`Source: https://github.com/LIS/LISAv2`

    1. XML folder: it has pre-defined global configuration and account information. It also has Region information in xml files. This folder also has two sub folders; TestCases and VMConfigurations. VMConfigurations has the list of xml files for each test case. TestCases folder has the list of xml files for each test category. The master branch is owned by Microsoft, and actively manage the PR in LISAv2. New test case development and/or new menu development must be approved by Microsoft.
    2. TestScripts folder has the number of test scripts defined in TestCases, and separated by OS type.
    3. Tools folder has binary files required for test execution.
    4. This repo will provide Microsoft-provided test cases as well as Partner-developed test cases.
        a. Microsoft will share the test development plan and its log with partners. If this is the case, you can skip the next paragraph to ‘Verify a published image on Azure’.
        b. Partners’ developed test cases should be followed below steps.
            i. Sync up the local master branch from remote master branch in the GitHub project, if new work branch is in the LISAv2. Otherwise, you can folk the LISAv2 repo to your own GitHub account.
            ii. Branch out for work and pull down to your local system.
            iii. Once change is ready to review, create a PR from LISAv2 in your account to LIS account. Or, new working branch to master in LISAv2 repo.
            iv. Add ‘LisaSupport@microsoft.com’ to ‘Reviewers’.
            v. Once it is approved, then you can merge the PR to master branch.
            vi. In this case, you will need to rebuild menu by ‘<Partner name>-Refresh-Test-Selection-Menus’

## Verify a published image on Azure

`UI I Instructions`

        1. Sign in to Jenkins page with the assigned user name & password
        2. Browse to '<Partner name>-Refresh-Test-Selection-Menu', if you would like to apply new menu or test cases before test execution.
        3. Click 'Build with Parameters' in left panel menu
            a. Enter git repo ULR and branch name for menu xml file. Recommend keeping the default Repo URL and branch name.
            b. Click 'Build' button.
            c. Click the rotation icon of running job and verify 'SUCCESS' inside 'Console Output'. You have new menu/test cases in Jenkins.
        4. Browse to '<Partner name>-Launch-Tests' and submit the job for test execution.
        5. Click 'Build with Parameters' in left panel menu
            a. Select 'ImageSource' or navigate to 'CustomVHD'. If you have external source URL, you can enter it in 'CustomVHDURL' text box.
            b. Leave 'Kernel' unless you would like to change to customized kernel code or linux-next.
            c. Next, there are 3 options regarding how to select test cases; TestName, Category and Tag.
                i. Supported platform: Azure, etc.
                ii. Available Category: BVT, Community, Functional, Performance, Smoke.
                iii. Available Tags: boot, bvt, disk, ext4, gpu, hv_netvsc, etc.
        6. Enter the email address for report notification.

`API/cmdline Instruction`

    A single script executes the test launch/execute with pre-defined parameters.
        TODO: TBD
`‘Script name and its parameters’`
    $TriggerTestPipelineRemotely 'parameters'
    Example,
        TODO: TBD
`‘Script name’ ‘parameters’`

## GlobalConfigurations.xml in XML folder

    Pre-defined global configuration. Do not recommend to make change in the file.

## RegionAndStorageAccounts.xml in XML folder

    It has pre-defined region information. Do not recommend to make change of this file.

## TestToRegionMapping.xml in XML folder

    This XML file defines the regions per Category. It may require specific region only for available setup/resource. By default, 'global' has all regions.

## XML files in XML/TestCases folder

    This location has the list of XML files for test cases. Each XML file names after category for each maintenance / sharing. 
        1. BVT.xml: BVT (Build Validation Test) test cases
        2. CommunityTests.xml: Tests from Open Source Community.
        3. FunctionalTests.xml: Feature tests for SR-IOV, GPU, DPDK, etc.
        4. Other.xml: If any does not fall into existing Category, add to here.
        5. PerformanceTests.xml: Performance test cases
        6. RegressionTests.xml: Add any tests for regression cycle. 
        7. SmokeTests.xml: It will run before BVT test runs.
        8. StressTests.xml: Under development. Network traffic and stroage IO testing under heavy CPU and Memory stress.

    Here is the format inside of TestCases.xml file. TODO: Revise the definition, and required field or not.
        <testName></testName>: Represent unique Test Case name
        <testScript></testScript>
        <PowershellScript></PowershellScript>: Actual PS script file name.
        <files></files>
        <setupType></setupType>: The name represents VM's size and its definition in TestsConfigurations.xml file, VMConfigurations folder.
        <TestType></TestType>
        <TestFeature></TestFeature>
        <Platform></Platform>: Supported platform names. Azure, HyperV, etc.
        <Category></Category>: Available Test Category
        <Area></Area>: Test Area
        <Tags></Tags>: Tag information seperated by comma
        <TestID></TestID>: Unique Test ID used in Jenkins.

## TestsConfigurations.xml in XML/VMConfigurations

    Per Category, each XML file has VM name, Resource Group name, etc. Do not recommend to make change of the file.

## Support Contact

    Contact LisaSupport@microsoft.com (Linux Integration Service Support), when you have technical issues.
