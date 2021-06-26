# Concepts

- [Test suite and test case](#test-suite-and-test-case)
- [Node and Environment](#node-and-environment)
- [Platform](#platform)
- [Tools and Scripts](#tools-and-scripts)
- [Feature](#feature)
- [Runbook](#runbook)
- [Combinator](#combinator)
  - [Grid combinator](#grid-combinator)
  - [Batch combinator](#batch-combinator)
- [Transformer](#transformer)
- [Requirement and Capability](#requirement-and-capability)

## Test suite and test case

A test suite contains one or more test cases that focus on certain functions or
tested domains. A test case is the smallest unit that runs and generates test
results.

The test cases in the same test suite have the same overall description and
setting/clearing method. Each test case describes its own steps and sets the
appropriate priority.

Test suites and test cases have their metadata. The metadata includes the
description, priority, test requirement, and other information.

## Node and Environment

The node is the system under test. Usually it's a virtual machine in a
virtualization platform, but it can also be a physical computer. LISA can be
further customized to support other types of nodes as well.

The environment includes one or more nodes and how they are connected. For
example, certain Hyper-V tests need to be run on two hosts. This type of
information is not within the scope of the node and is described at the
environmental level.

## Platform

The platform provides a test environment, such as Azure, Hyper-V or WSL. The
platform will call its API to measure test requirements, deploy the environment
and delete the used environment.

In most cases, after the environment is deployed, it has nothing to do with the
source platform. In this way, tests from different platforms can be run in a
consistent manner.

## Tools and Scripts

The tools are runnable commands in a node. The scripts are considered tools. The
only difference is that the tool can be installed in many ways, but the script
can only be uploaded to a node.

In different Linux distributions, tools may have different installation methods,
commands, or command-line parameters. The LISA tool provides a simple test
interface to focus on verifying logic and does not need to deal with the
diversity of distributions.

A collection of tools are provided on each node. After one tool is initialized,
it will be added to the collection, and will be available during the lifetime of
the node.

## Feature

The feature is like a tool, except it supports operations outside the node, for
example, get serial logs of nodes, add disks, etc.

Note that there are test cases that require certain features to run. To run such
test cases, the platform must support the required features.

## Runbook

The runbook contains all the configurations of LISA operation. It keeps you from
lengthy command-line commands and makes it easy to adjust configurations.

The previous version of LISA is powerful and supports many scenarios. However,
the trade-off there is increased complexity of the command-line parameters, and
it relies on a secret file to work. The current version of LISA provides a
consistent way to manage configuration and maximize customization capabilities
through a runbook.

One runbook can refer to other runbooks so that test case selection, platform
configuration and other options can be separated. It helps reduce redundancy.

The runbook supports custom variables, and these variables can be provided in
the runbook, command line or environment variables. Variables are only used in
the runbook and are resolved to actual values before the start of the test.

The configuration of the runbook can be extended to certain components. For
example, when defining a notifier, you can define its configuration structure
together. The corresponding configuration will be loaded into the notifier with
the same schema. The extended configuration also supports variables.

## Combinator

The combinator helps to run large-scale test cases with different variables,
such as running multiple images with different VM sizes or other variables.
There are two kinds of combinators provided: grid combinator and batch
combinator. You can also write your own combinator.

### Grid combinator

A [grid combinator](../../lisa/combinators/grid_combinator.py) selects all the
combination of provided images and variables. For example, if you are to run 10
images with 3 different VM sizes ([`img1`, `vm1`], [`img1`, `vm2`], [`img1`,
`vm3`], [`img2`, `vm1`], etc.), the grid combinator saves you from expanding
that combination out manually in complete form and would automatically give all
$10\times3=30$ combinations.

### Batch combinator

A [batch combinator](../../lisa/combinators/batch_combinator.py) instead runs a
batch of specified combinations. For example, maybe we only want `img1` to run
with `vm1` but we want `img2` to run with `vm1`, `vm2` and `vm3`, you can give
the batch combinator such specification and all tests would run as you expect.

## Transformer

The transformers generate variables from other variables, and multiple
transformers can run one by one to achieve complex transformation. For example,
the first transformer can build Linux kernel and another one can save the VM to
a VHD. The two transformers can be reused in other workflows.

## Requirement and Capability

A test case may have certain requirements for the test environment. For example,
it may need two nodes, four CPU cores, serial logging, a certain Linux
distribution or other requirements. When writing test cases, other requirements
of the test cases in addition to the default ones should be defined explicitly.

The platform provides environments with different capability. The capabilities
of environments are loaded from the platform's API.

If the capability of an environment meets the requirements of a test case, the
test case can be run on this environment.

The figure below shows a test case that requires at least one core, 2G memory
and three network interface cards (NIC). The Azure VM Standard_DS2_v2 in the
middle meets the first two requirements, as it has two cores and 7G memory; but
because it can only have two NICs at most, it fails the test requirements and
thus the test case will be performed on another VM. Standard_DS3_v2 supports up
to four NICs and it meets all three requirements, so it will run the test cases.

![requirements to capability](img/req_cap.png)
