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

Specify the path of [runbook](runbook.md). It can be an absolute path or a
relative path. This parameter is required in every run other than run with -h.

```sh
lisa -r ./microsoft/runbook/azure.yml
```

### -d, --debug

By default, the console will display INFO or higher level logs, but will not
display DEBUG level logs. This option enables the console to output DEBUG level
logs. Note the log file will not be affected by this setting and will always
contain the DEBUG level messages.

```sh
lisa -d
```

### -h, --help

Show help messages.

```sh
lisa -h
```

### -v, --variable

Define one or more variables in the format of `name:value`, which will overwrite
the value in the YAML file. It can support secret values in the format of
`s:name:value`.

```sh
lisa -r ./microsoft/runbook/azure.yml -v location:westus2 -v "gallery_image:Canonical UbuntuServer 18.04-LTS Latest"
```

## run

An optional command since it is the default operation. The following two lines
perform the same operation.

```sh
lisa run -r ./microsoft/runbook/azure.yml
lisa -r ./microsoft/runbook/azure.yml
```

## check

Check whether the specified YAML file and variables are valid.

```sh
lisa check -r ./microsoft/runbook/azure.yml
```

## list

Output information of this run.

- `-t` or `--type` specifies the information type. It supports `case`.

  ```sh
  lisa list -r ./microsoft/runbook/local.yml -v tier:0 -t case
  ```

- With `-a` or `--all`, it will ignore test case selection, and display all test
  cases.

  ```sh
  lisa list -r ./microsoft/runbook/local.yml -v tier:0 -t case -a
  ```
