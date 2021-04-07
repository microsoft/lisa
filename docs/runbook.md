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
    - [strategy](#strategy)
  - [extension](#extension)
  - [variable](#variable)
    - [is_secret](#is_secret)
    - [file](#file)
    - [name](#name-1)
  - [value](#value)
  - [artifact](#artifact)
    - [name](#name-2)
    - [locations](#locations)
      - [type](#type)
      - [path](#path-1)
  - [notifier](#notifier)
    - [console](#console)
    - [html](#html)
  - [environment](#environment)
    - [name](#name-3)
    - [topology](#topology)
    - [nodes](#nodes)
    - [nodes_requirement](#nodes_requirement)
      - [type](#type-1)
  - [platform](#platform)
  - [testcase](#testcase)

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

Below section is to specify P0 and P1 test cases excluding case with name `hello`.

```yaml
testcase:
  - criteria:
      priority: [0, 1]
  - criteria:
      name: hello
    select_action: exclude
```

### Use variable and secrets

Below section is to specify the variable in name/value format. We can use this variable in other field in this format `$(location)`.

```yaml
variable:
  - name: location
    value: westus2
```

The value of variable passed from command line will override the value in runbook yaml file.

```bash
lisa -r sample.yml -v "location:eastus2"
```

Below section is to specify the path of yaml file which stores the secret values.

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

The variable values in its parent yaml file will be overrided by current yaml file. The relative path is always relative to current yaml file.

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

Below section is to specify path of extensions, the extensions are modules for test cases or extended features.

```yaml
extension:
  - name: extended_features
    path: ../../extensions
  - ../../lisa/testsuites/basic
```

## Reference

### name

### test_project

### test_pass

### tags

### parent

#### path

#### strategy

Not implemented

### extension

### variable

#### is_secret

#### file

#### name

### value

### artifact

#### name

#### locations

##### type

##### path


### notifier

#### console

#### html


### environment

#### name

#### topology

#### nodes

#### nodes_requirement

##### type

### platform

### testcase
