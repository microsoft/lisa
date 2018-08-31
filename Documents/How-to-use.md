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
                i. Supported platform: Azure, etc.
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
        3. FunctionalTests.xml: Feature tests for SR-IOV, GPU, DPDK, etc.
        4. Other.xml: If any does not fall into existing Category, add to here.
        5. PerformanceTests.xml: Performance test cases
        6. RegressionTests.xml: Add any tests for regression cycle.
        7. SmokeTests.xml: It will run before BVT test runs.
        8. StressTests.xml: Under development. Network traffic and stroage IO testing 
        under heavy CPU and Memory stress.

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
            this script calls 'DeployVMs' function for its testing and collect the result 
            by 'CheckKernelLogs'. 'DeployVMs' and 'CheckKernelLogs' are functions definded 
            in ./Libraries/CommonFunctions.psm1 module. 
            You can add new module or update existing ones for further development.
        b. PowerShell script wraps multiple non-PowerShell script like Bash or Python scripts: 
            Like 'VERIFY-TEST-SCRIPT-IN-LINUX-GUEST.ps1', the PowerShell script wraps the multiple 
            Bash or Python script as a parameter of 'RunLinuxCmd' function.
    5. Before PR review, we recommend you run script testing in cmdline/API mode. See above instruction.

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
    9. Recommended function name format - Function_Name(). Upper letter in each string connected with underscore character.

## Support Contact

Contact LisaSupport@microsoft.com (Linux Integration Service Support), if you have technical issues.
