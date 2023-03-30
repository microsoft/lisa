Introduction
============

Below test cases of LISA are selected to run in Azure Certification. This article explains the common error messages showing in the results of these cases, along with related solutions.

-  smoke_test
-  verify_no_pre_exist_users
-  verify_dns_name_resolution
-  validate_netvsc_reload

Test specifications
============

Please refer to `test spec <https://mslisa.readthedocs.io/en/main/run_test/test_spec.html>`__ for the case description and steps. You can also check the `source code <https://github.com/microsoft/lisa>`__ for more details.

Error description
============

smoke_test
^^^^^^^
- **cannot connect to TCP port: [xx.xx.xx.xx:22], error code: 10061, no panic found in serial log during bootup**
If you receive this error message, that means there is no kernel panic when the VM boot up. But it might have some network connectivity issue. Please double check the network related configurations. 


verify_no_pre_exist_users
^^^^^^^

verify_dns_name_resolution
^^^^^^^

validate_netvsc_reload
^^^^^^^
