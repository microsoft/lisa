# command line reference

- [common arguments](#common-arguments)
  - [-r, --runbook](#-r---runbook)
  - [-d, --debug](#-d---debug)
  - [-h, --help](#-h---help)
  - [-v, --variable](#-v---variable)
- [run](#run)
- [check](#check)
- [list](#list)

## common arguments

### -r, --runbook

Specify the path of [runbook](runbook.md). It can be an absolute path or a relative path. In most usages, this parameter is required.

```sh
lisa -r ./microsoft/runbook/azure.yml
```

### -d, --debug

Set the log level output by the console to DEBUG level. By default, the console displays logs with INFO and higher levels. The log file will contain the DEBUG level and is not affected by this setting.

```sh
lisa -d
```

### -h, --help

Show help message.

```sh
lisa -h
```

### -v, --variable

Define one or more variables in the format of `name:value`, which will overwrite the value in the YAML file. It can support secret values in the format of `s:name:value`.

```sh
lisa -r ./microsoft/runbook/azure.yml -v location:westus2 -v "gallery_image:Canonical UbuntuServer 18.04-LTS Latest"
```

## run

Run is the default operation. The `run` is optional.

```sh
lisa run -r ./microsoft/runbook/azure.ym
```

## check

Check whether the specified YAML file and variables are valid.

```sh
lisa check -r ./microsoft/runbook/azure.ym
```

## list

Output information of this run.

- The `-t` or `--type` specifies the information type. It supports `case`.

  ```sh
  lisa list-r ./microsoft/runbook/local.yml -v tier:0 -t case
  ```

- When using `-a` or `--all`, it will ignore test case selection, and display all test cases.

  ```sh
  lisa list -r ./microsoft/runbook/local.yml -v tier:0 -t case -a
  ```
