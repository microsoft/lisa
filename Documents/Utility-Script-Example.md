#Example Usages
## Get-LisaV2Statistics.ps1
PS /Utilities> ./Get-LISAv2Statistics.ps1
```Powershell
TestCase                                                      Platform        Category            Area                                     Tags
-----------------------------------------------------------------------------------------------------------------------------------------------
STRESSTEST-VERIFY-RESTART-MAX-SRIOV-NICS                         Azure          Stress          stress                stress,boot,network,sriov
STRESSTEST-RELOAD-LIS-MODULES                              Azure,HyperV         Stress          stress                                   stress
STRESSTEST-SYSBENCH                                             HyperV          Stress          stress                                   stress
STRESSTEST-CHANGE-MTU-RELOAD-NETVSC                             HyperV          Stress          stress                                   stress
STRESSTEST-BOOT-VM-LARGE-MEMORY                                 HyperV          Stress          stress                                   stress
STRESSTEST-EventId-18602-Regression                             HyperV          Stress          stress                                   stress
...

===== Test Cases Number per platform =====

Azure only: 91
Hyper-V only: 82
Both platforms: 33
...

===== Tag Details =====

Name                           Value
----                           -----
nested                         15
core                           24
...
```
## Get-AzureVMs.ps1
```Powershell
PS /Utilities> ./Get-AzureVMs.ps1 -Tags "User" -IncludeAge
10/19/2018 16:33:10 : [INFO ] Collecting VM age from disk details for 2 machines.

VMRegion       VMName                      ResourceGroupName           VMSize          BuildURL BuildUser TestName                    CreationDate RGAge VMAge                           
--------       ------                      -----------------           ------          -------- --------- --------                    ------------ ----- -----                           
eastus         ICA-RG-SingleVM-RS17-SJHG   ICA-RG-SINGLEVM             Standard_E4s_v3 NA       User                                                        52                           
southcentralus ICA-RG-SingleVM-PERSISTANT  ICA-RG-SINGLEVM             Standard_DS1_v2 NA       User      VERIFY-DEPLOYMENT-PROVISION                       52


#In this case, we load the Secrets file from $env:Azure_Secrets_File
PS /Utilities> ./Get-AzureVMs.ps1 -Region Eastus -UseSecretsFile

VMRegion VMName                      ResourceGroupName                                      VMSize           BuildURL BuildUser TestName CreationDate RGAge
-------- ------                      -----------------                                      ------           -------- --------- -------- ------------ -----
eastus   user--b104-jenkins-1        USER-B104-JENKINS-ONEVM                                Standard_DS2_v2  ...      User      Run        10.10.2018    22            
eastus   user-eastus-bsd104-jenkins  USER-EASTUS-BSD104-JENKINS-DEPLOY1VM                   Standard_DS2_v2  ...      User                                  
eastus   user--b122-jenkins-1        USER-B122-JENKINS-ONEVM                                Standard_DS2_v3  ...      User      Run        10.10.2018    22            
eastus   user-eastus-bsd122-jenkins  USER-EASTUS-BSD122-JENKINS-DEPLOY1VM                   Standard_DS2_v3  ...      User                                  

 
PS /Utilities> ./Get-AzureVMs.ps1 -Region Eastus -VMSize Standard_DS2_v2

VMRegion VMName                      ResourceGroupName                                       VMSize          BuildURL BuildUser TestName CreationDate RGAge
-------- ------                      -----------------                                       ------          -------- --------- -------- ------------ -----
eastus   user--b104-jenkins-1        USER-B104-JENKINS-ONEVM                                Standard_DS2_v2  ...      User      Run        10.10.2018    22            
eastus   user-eastus-bsd104-jenkins  USER-EASTUS-BSD104-JENKINS-DEPLOY1VM                   Standard_DS2_v2  ...      User                                  


PS /Utilities> ./Get-AzureVMs.ps1 -AzureSecretsFile c:\MySecrets.xml                   
VMName    TestName         BuildURL                                         ResourceGroup          VMRegion   VMAge BuildUser                      VMSize
------    --------         --------                                         -------------          --------   ----- ---------                      ------
vm001                                                                       MYRESOURCeGROUP        westeurope    23 User Account                   Standard_DS15_v3
client-vm VERIFY-DEP       https://someurl.com/job/id/console               MYRESOURCEGROUP        westeurope     1 User Account                   Standard_DS15_v2
vm017                                                                       MYOtherRESOURCeGROUP   eastus2      103 User Account                   Standard_DS15_v2
...

PS /> ./Utilities/Get-VMs.ps1 -filterScriptBlock {$_.VMSize -eq 'Standard_DS15_v3'}
VMName    TestName         BuildURL                                         ResourceGroup          VMRegion   VMAge BuildUser                      VMSize
------    --------         --------                                         -------------          --------   ----- ---------                      ------
vm001                                                                       MYRESOURCeGROUP        westeurope    23 User Account                   Standard_DS15_v3

```
## Support Contact

Contact LisaSupport@microsoft.com (Linux Integration Service Support), if you have technical issues.