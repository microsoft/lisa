# How to write extensions in LISA

- [Common](#common)
  - [Extend schema](#extend-schema)
- [Platform](#platform)
- [Feature](#feature)
- [Notifier](#notifier)
- [Tool](#tool)
- [Linux Distribution](#linux-distribution)
- [Hooks](#hooks)
  - [`get_environment_information`](#get_environment_information)

## Common

### Extend schema

Some components like Platform support to extend runbook schema.

The runbook uses [dataclass](https://docs.python.org/3/library/dataclasses.html) to define, [dataclass-json](https://github.com/lidatong/dataclasses-json/) to deserialize, and [marshmallow](https://marshmallow.readthedocs.io/en/3.0/api_reference.html) to validate the schema.

See more examples in [schema.py](../lisa/schema.py), if you need to extend runbook schema.

## Platform

## Feature

## Notifier

## Tool

## Linux Distribution

## Hooks

### `get_environment_information`
