# Runbook Reference

- [How-to](#how-to)
  - [Configure Azure deployment](#configure-azure-deployment)
  - [Select and set test cases](#select-and-set-test-cases)
  - [Use variable and secrets](#use-variable-and-secrets)
  - [Use partial runbook](#use-partial-runbook)
  - [Use extensions](#use-extensions)
- [Reference](#reference)
  - [name](#name)
  - [test_project](#test_project)
  - [test_pass](#test_pass)
  - [tags](#tags)
  - [parent](#parent)
    - [path](#path)
  - [extension](#extension)
    - [name](#name-1)
    - [path](#path-1)
  - [variable](#variable)
    - [is_secret](#is_secret)
    - [file](#file)
    - [name](#name-2)
    - [value](#value)
  - [notifier](#notifier)
    - [console](#console)
      - [log_level](#log_level)
    - [html](#html)
      - [path](#path-2)
      - [auto_open](#auto_open)
  - [environment](#environment)
    - [environments](#environments)
      - [name](#name-3)
      - [topology](#topology)
      - [nodes](#nodes)
      - [nodes_requirement](#nodes_requirement)
        - [type](#type)
  - [platform](#platform)
  - [testcase](#testcase)
    - [criteria](#criteria)

## How-to

### Configure Azure deployment

Below section is for running cases on Azure platform, it specifies:

- admin_private_key_file: the private key file to access the Azure VM.
- subscription_id: Azure VM is created under this subscription.

```yaml
platform:
  - type: azure
    admin_private_key_file: $(admin_private_key_file)
    azure:
      subscription_id: $(subscription_id)
```

### Select and set test cases

Below section is to specify P0 and P1 test cases excluding case with name
`hello`.

```yaml
testcase:
  - criteria:
      priority: [0, 1]
  - criteria:
      name: hello
    select_action: exclude
```

### Use variable and secrets

Below section is to specify the variable in name/value format. We can use this
variable in other field in this format `$(location)`.

```yaml
variable:
  - name: location
    value: westus2
```

The value of variable passed from command line will override the value in
runbook yaml file.

```bash
lisa -r sample.yml -v "location:eastus2"
```

Below section is to specify the path of yaml file which stores the secret
values.

```yaml
variable:
  - file: secret.yml
```

Content of secret.yml.

```yaml
subscription_id:
  value: replace_your_subscription_id_here
  is_secret: true
  mask: guid
```

### Use partial runbook

Below three yaml files will be loaded in this sequence.

```
loading runbook sample.yml
|-- loading parent tier.yml
|   |-- loading parent t0.yml
```

The variable values in its parent yaml file will be overrided by current yaml
file. The relative path is always relative to current yaml file.

Part of sample.yml

```yaml
parent:
  - path: ./tier.yml
```

Part of tier.yml.

```yaml
parent:
  - path: ./t$(tier).yml
variable:
  - name: tier
    value: 0
```

Part of t0.yml.

```yaml
testcase:
  - criteria:
      priority: 0
```

### Use extensions

Below section is to specify path of extensions, the extensions are modules for
test cases or extended features.

```yaml
extension:
  - name: extended_features
    path: ../../extensions
  - ../../lisa/microsoft/testsuites/core
```

## Reference

### name

type: str, optional, default is "not_named"

Part of the test run name. This name will be used to group results and put it in
title of the html report, also the created resources's name contains this
specified str.

```yaml
name: Azure Default
```

### test_project

type: str, optional, default is empty

The project name of this test run. This name will be used to group test results
in html, it also shows up in notifier message.

```yaml
test_project: Azure Image Weekly Testing
```

### test_pass

type: str, optional, default is empty

The test pass name of this test run. This name combined with test project name
will be used to group test results in html report, it also shows up in notifier
message.

```yaml
test_pass: bvt testing
```

### tags

type: list of str, optional, default is empty

The tags of the test run. This name combined with test project name and test
pass name will be used to group test results in html report, it also shows up in
notifier message.

```yaml
tags:
  - test
  - bvt
```

### parent

type: list of path, optional, default is empty

Share the runbook for similar runs.

#### path

It can be absolute or relative path of current runbook.

### extension

type: list of path str or name/path pairs, optional, default: empty

The path and the name of the modules, we can also just specify the extension
path directly.

```yaml
extension:
  - name: ms
    path: ../../extensions
```

#### name

type: str, optional, default is empty

Each extension can be specified a name. With the name, one extension can
reference another one, using above example extension, in code we can reference
it like this way ms.submodule.

#### path

type: str, optional, default is empty

Path of extension, it can be absolute or relative path of current runbook file.

### variable

type: list of path str or name/value pairs, optional, default: empty

Used to support variables in other fields.

The values pass from command line has the highest priority, with below example,
any places use `${subscription_id}` will be replaced with value `subscription id
B`.

```bash
lisa -r ./microsoft/runbook/azure.yml -v "subscription_id:<subscription id A>"
```

```yaml
variable:
  - name: subscription_id
    value: subscription id B
```

The variables values in the runbook have higher priority than the same variables
defined in its parent runbook file. `${location}` will be replaced with value
`northeurope`.

```yaml
parent:
  - path: tier.yml
variable:
  - name: location
    value: northeurope
```

tier.yml

```yaml
variable:
  - name: location
    value: westus2
```

The later defined variables values in runbook have higher priority than the same
variables previous defined. `${location}` will be replaced with value
`northeurope`.

```yaml
variable:
  - name: location
    value: westus2
  - name: location
    value: northeurope
```

#### is_secret

type: boolean, optional, default is False.

When set to True, the value of this variable will be masked in log and other
output information.

Recommend to use secret file or env variable. It's not recommended to specify
secret value in runbook directly.

#### file

type: list of str, optional, default: empty

Specify path of other yml files which define variables.

#### name

type: str, optional, default is empty.

Variable name.

#### value

type: str, optional, default is empty

Value of the paired variable.

### notifier

Receive messages during the test run and output them somewhere.

#### console

One of notifier type. It outputs messages to the console and file log and
demonstrates how to implement notification procedures.

Example of console notifier:

```yaml
notifier:
  - type: console
    log_level: INFO
```

##### log_level

type: str, optional, default: DEBUG, values: DEBUG, INFO, WARNING...

Set log level of notification messages.

#### html

Output test results in html format. It can be used for local development or as
the body of an email.

##### path

type: str, optional, default: lisa.html

Specify the output file name and path.

##### auto_open

type: bool, optional, default: False

When set to True, the html will be opened in the browser after completion.
Useful in local run.

Example of html notifier:

```yaml
notifier:
  - type: html
    path: ./lisa.html
    auto_open: true
```

### environment

List of environments. For more information, refer [node and
environment](https://github.com/microsoft/lisa/blob/main/docs/concepts.md#node-and-environment).

#### environments

List of test run environment.

##### name

type: str, optional, default is empty

The name of the environment.

##### topology

type: str, optional, default is "subnet"

The topology of the environment, current only support value "subnet".

##### nodes

List of node, it can be a virtual machine on Azure or Hyper-V, bare metal or
others. For more information, refer [node and
environment](https://github.com/microsoft/lisa/blob/main/docs/concepts.md#node-and-environment).

##### nodes_requirement

List of testing required environments, by default node_count (default is 1),
core_count (default is 1), memory_mb (default is 512 MB), disk_count (default is
1), nic_count (default is 1), gpu_count (default is 0). The node can be created
once the node requirement is met.

###### type

type: str, optional, default value is "requirement", supported values are
"requirement", "remote", "local".

### platform

List of platform, default value is "ready", current support values are "ready",
"azure".

### testcase

type: list of str, optional, default: lisa

Criteria to select cases.

#### criteria

type: list of dictionary, optional, default is empty

Select test cases by area, category, name, priority or tags combined with select
action.

select_action can be "none", "include", "exclude", "forceInclude" and
"forceExclude", default value is "none".

```yaml
testcase:
  - criteria:
      priority: 0
    select_action: include
  - criteria:
      priority: 1
    select_action: exclude
```
