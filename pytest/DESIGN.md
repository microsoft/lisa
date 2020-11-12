# LISAv3 Technical Specification Document

This document outlines the technical specifications for LISAv3. We are
evaluating the feasibility of leveraging
[Pytest](https://docs.pytest.org/en/stable/) as our test runner.

Please see [PR #1065](https://github.com/LIS/LISAv2/pull/1065) for a working,
proof-of-concept prototype.

Authored by Andrew Schwartzmeyer (he/him), version 0.2.0.

## Why Pytest?

Pytest is an [incredibly popular](https://docs.pytest.org/en/stable/talks.html)
MIT licensed open source Python testing framework. It has a thriving community
and plugin framework, with over 750
[plugins](https://plugincompat.herokuapp.com/). Instead of writing (and
therefore maintaining) yet another test framework, we would do more with less by
reusing Pytest and existing plugins. This will allow us to focus on our unique
problems: organizing and understanding our tests, deploying necessary resources
(such as Azure, Hyper-V, or bare metal machines, collectively known as
“targets”), and analyzing our results.

In fact, most of Pytest itself is implemented via [built-in
plugins](https://docs.pytest.org/en/stable/plugins.html), providing us with many
useful and well-documented examples. Furthermore, when others were confronted
with a problem similar to our own they also chose to use Pytest.
[Labgrid](https://github.com/labgrid-project/labgrid) is an open source embedded
board control library that delegated the testing framework logic to Pytest in
their [design](https://labgrid.readthedocs.io/en/latest/design_decisions.html),
and [U-Boot](https://github.com/u-boot/u-boot), an embedded board boot loader,
similarly leveraged Pytest in their
[tests](https://github.com/u-boot/u-boot/tree/master/test/py). KernelCI and
Avocado were also evaluated by the Labgrid developers at an [Embedded Linux
Conference](https://youtu.be/S0EJJM5bVUY) and both ruled out for reasons similar
to our own before they settled on Pytest.

The [fundamental features](https://youtu.be/CMuSn9cofbI) of Pytest match our
needs very well:

* Automatic test discovery, no boiler-plate test code
* Useful information when a test fails (assertions are introspected)
* Test and fixture parameterization
* Modular setup/teardown via fixtures
* Incredibly customizable (as detailed above)

So all the logic for describing, discovering, running, skipping and reporting
results of the tests, as well as enabling and importing users’ plugins is
already written and maintained by the open source community. This leaves us to
focus on our hard and specific problems: creating an abstraction to launch the
necessary targets, organizing and publishing our tests, and reporting test
results upstream. Using Pytest would also allow us the space to abstract other
commonalities in our specific tests. In this way, LISAv3 could solve the
difficulties we have at hand without creating yet another test framework.

Finally, by leveraging such a popular framework and reducing the amount of code
we need to maintain, we drastically increase our chances of receiving pull
requests instead of bug reports from users. This is important because despite
our best efforts it is practically guaranteed that as adoption of LISAv3
increases, users will want changes to be made, and we need to empower them to do
so themselves.

## What are we maintaining?

The current proof-of-concept implementation uses the top-level `conftest.py`
file to define our “plugin” functionality. This works, but it is not ideal. I
believe that we will want to publish two open source Pytest plugins as packages
on [PyPI](https://pypi.org/), the Python Package Index: `pytest-target` and
`pytest-lisa`. We will also maintain our set of public “LISA” tests, but these
should simply install and use our plugins.

The `pytest-target` plugin should encapsulate all our logic for _how_ and _when_
to deploy targets (local or cloud virtual machines, or bare metal machines, and
all the associated resources), run tests on the specified targets, and delete
the targets. This includes specifying which features and resources each test
needs and each given target provides (such as number of cores, amount of RAM,
and other hardware like a GPU etc.), how to deploy and delete each target based
on its platform, and parameterization of the `target` fixture based on CLI or
YAML file input. In fact, some tests (like networking) will require multiple
targets at once. This plugin will need to manage resources intelligently, being
able to optimize for both time and cost, and make it easy for tests to request
and use various resources.

The `pytest-lisa` plugin should encapsulate all our logic for how to organize
and select tests, as well as our opinions on displaying test results. This
includes the user modes, test metadata and inventory, test selection based on
criteria against that metadata, required and pre-configured upstream plugins,
and result notifiers. It will similarly support both CLI and YAML file input.

We should strive to keep these plugins from depending on each other in order to
keep their scope well-defined. In the “LISA” repository of tests we will depend
on the two plugins and maintain additional fixtures for our tests’ unique
requirements. Similarly, we and others may have private test repositories which
build upon the above by defining new platform support and internal service
integrations.

## pytest-target

### How are targets provided and accessed?

First we need to define “target” as an instance of a system-under-test. That is,
given some environment requirements, such an Azure image (URN) and size (SKU), a
target would be a virtual machine deployed by `pytest-target` with SSH access
provided to the requesting test. A target could optionally be pre-deployed and
simply connected. Some tests may request multiple targets as well.

Pytest uses [fixtures](https://docs.pytest.org/en/stable/fixture.html), which
are the primary way of setting up test requirements. They replace less flexible
alternatives like setup/teardown functions. It is through fixtures that we
implement remote target setup/teardown. Our `target` fixture returns a `Target`
instance, which currently provides:

* Remote shell access via SSH
* Data including hostname / IP address
* Cross-platform ping functionality with exponential back-off
* Uploading of local files to arbitrary remote destinations
* Downloading of remote file contents into local string variable
* Asynchronous remote command execution with promises

The `Azure(Target)` subclass additionally provides:

* Automatic provisioning of an Azure VM given URN and SKU
* Allowing ICMP ping via Azure firewall rules
* Azure platform forced reboot by API
* Downloading boot diagnostics (serial console log) from platform

The prototype demonstrates how easy it is to quickly implement these features.
As we need more features, they can be readily added and shared among tests.

The `Target` class leverages [Fabric](https://www.fabfile.org/) which is a
popular high-level Python library for executing shell commands on remote systems
over SSH. Underneath the covers Fabric uses
[paramiko](https://docs.paramiko.org/en/stable/), the most popular low-level
Python SSH library. Fabric does the heavy lifting of safely connecting and
disconnecting from the node, executing the shell command (synchronously or
asynchronously), reporting the exit status, gathering the stdout and stderr,
providing stdin (or interactive auto-responses, similar to `expect`), uploading
and downloading files, and much more. In fact, these APIs are all available and
implemented for the local machine by the underlying
[Inovke](https://www.pyinvoke.org/) library, which is essentially a Python
`subprocess` wrapper with “a powerful and clean feature set.”

Other test specific requirements, such as installing software and daemons,
downloading files from remote storage, or checking the state of our Bash test
scripts, would similarly be implemented by methods on the `Target` class or via
additional fixtures and thus shared among tests.

### How do we interact with Azure?

For Azure, we currently use the [Azure CLI](https://aka.ms/azureclidocs) to
deploy a virtual machine. For Hyper-V (and other virtualization platforms), we
would like to use [libvirt](https://libvirt.org/python.html), and for embedded
environments we are evaluating
[labgrid](https://github.com/labgrid-project/labgrid).

If possible, we do not want to use the [Azure Python
APIs](https://aka.ms/azsdk/python/all) directly because they are more
complicated (and less documented) than the [Azure
CLI](https://aka.ms/azureclidocs). With Invoke (as discussed above), `az`
becomes incredibly easy to work with. The Azure CLI lead developer states that
they have [feature parity](https://stackoverflow.com/a/50005660/1028665) and
that the CLI is more straightforward to use. Considering our ease-of-maintenance
requirement, this seems the apt choice. If it later becomes necessary to use the
Python APIs directly, that is, of course, still doable.

### What’s the `Target` class?

In version 0.1 of this design document we detailed a planned refactor of what
was then called the `Node` class. This has since been executed with just a few
modifications (one being the rename to `Target`, as `Node` was found to be an
overloaded term in the context of data centers). This class and its subclasses
are decoupled from Pytest, and are used via fixtures. It looks like this:

```python
from abc import ABC, abstractmethod
from schema import Schema
import fabric

class Target(ABC):
    parameters: Mapping[str, str]
    features: Set[str]
    name: str
    host: str
    conn: fabric.Connection  # Provides run, sudo, get, put etc.

    def __init__(...):
        ...
        self.host = self.deploy()
        self.conn = fabric.Connection(self.host)

    @classmethod
    @property
    @abstractmethod
    def schema(cls) -> Schema:
        """Must return the parameters schema for setup."""
        ...

    @abstractmethod
    def deploy(self) -> str:
        """Must deploy the target resources and return hostname."""
        ...

    @abstractmethod
    def delete(self) -> None:
        """Must delete the target resources."""
        ...

    @classmethod
    def local(...) -> Result:
        """Runs a local shell command."""
        ...
```

#### How are platforms implemented?

Platform support is implemented by subclassing `Target` and defining the
`schema` property, `deploy` method, `delete` method, and any platform-specific
methods. Using the `__subclasses__` attribute of `Target` the available
platforms and their parameter schemata are automatically gathered from users’
own `conftest.py` files and other plugins. This enables the `target` fixture to
dynamically instantiate a target from the gathered requirements and parameters.

#### How are requirements examined?

The `features` attribute is currently a set of strings and (combined with the
parameters dictionary) was used to demonstrate how we can test if an existing
target instance (representing a deployed machine) met a test’s requirements. It
should be updated with a `Requirements` class that represents all physical
attributes of the target, and a `requires` Pytest mark should be added which
takes instances of this class. Two `Requirements` should be comparable to
determine if one set meets (or exceeds) the other set.

#### How do we share common tasks?

Common tasks for targets like rebooting and pinging should be implemented on the
`Target` class, and platform-specific tasks on the respective subclass.

Methods available from `Connection` include `run()` and `sudo()` which are used
to easily run arbitrary commands, and `get()` and `put()` to download and upload
arbitrary files.

The `cat()` method wraps `get()` and returns the file as data in a string. This
makes test code like this possible:

```python
assert target.conn.cat("state.txt") == "TestCompleted"
```

A `reboot()` method should be added that first tries to use `sudo("reboot",
timeout=5)` (with a short timeout to avoid a hung SSH session). It should retry
with an exponential back-off to see if the machine has rebooted by checking
either `uptime` or the existence of a file created before the reboot. This is to
avoid having to `sleep()` and just guess the amount of time it takes to reboot.

A `restart()` method should “power cycle” the machine using the platform’s API,
and thus is in abstract method.

Other tools and shared logic should be implemented as necessary. A major area of
concern is the automatic and package-manager agnostic installation of necessary
tools, much of which has been implemented previously and can be integrated.

### How are targets requested and managed?

We implement a pair of Pytest fixtures to provide targets. The first is the
`pool` fixture, which looks like:

```python
@pytest.fixture(scope="session")
def pool(request: SubRequest) -> Iterator[List[Target]]:
    """This fixture tracks all deployed target resources."""
    targets: List[Target] = []
    yield targets
    for t in targets:
        t.delete()
```

The `pool` fixture is setup once at the beginning of the test session, at which
point the `targets` list is then provided as input to every instance of the
`target` fixture. While currently a list, to support optimal scheduling we will
likely want to use a priority queue, where the priority of a target represents
its cost (whether in terms of time or money), allowing us to provide either the
fastest or the cheapest target to each request. Targets not in use will be
deallocated, and all targets will be automatically deleted after the tests are
finished (unless the user requested otherwise, in which case they’ll be cached).

Note that cross-session [caching](https://docs.pytest.org/en/stable/cache.html)
is provided by Pytest, and very easy to work with. An early prototype
implemented a `--keep-vms` flag successfully, and this will be implemented again
with the updated design.

The second is the `target` fixture, which looks like:

```python
@pytest.fixture
def target(pool: List[Target], request: SubRequest) -> Iterator[Target]:
    """This fixture provides a connected target for each test."""
    platform: Type[Target] = playbook.PLATFORMS[request.param["platform"]]
    parameters: Dict[str, Any] = request.param["parameters"]
    marker = request.node.get_closest_marker("lisa")
    features = set(marker.kwargs["features"])

    # TODO: If `t` is not already in use, deallocate the previous target.
    for t in pool:
        if isinstance(t, platform) and t.parameters == parameters and t.features >= features:
            yield t
            break
    else:
        t = platform(parameters, features)
        pool.append(t)
        yield t
    t.connection.close()
```

This is obviously still an early implementation, but it is viable. By using the
[pytest_collection_modifyitems][] hook to sort (and so group) the tests by their
requirements, the tests would efficiently reuse targets. This fixture is
indirectly parameterized during setup with the [pytest_generate_tests][] hook.
Test and fixture [parameterization][] is a huge feature of Pytest. When we
parameterize the `target` fixture for multiple targets (e.g. “Ubuntu” and
“Debian”), Pytest automatically creates a set of tests for each target. So
`test_smoke` turns into `test_smoke[Ubuntu]` and `test_smoke[Debian]`. This
allows us to run a collection of tests against multiple targets with ease. These
targets are defined in a YAML file and validated against the parameters
collected from the previously described platform subclasses.

### How are tests executed in parallel?

While our original list of goals stated that we want to run tests “in parallel”
we were not specific about what was meant, and the topic of parallelism and
concurrency is understandably complex. We certainly don’t mean running two tests
at once on the same target, as this would undoubtedly lead to flaky tests.

Assuming that we care about a set of tests passing on a particular image and
size combination, but not necessarily on a particular deployed instance, then we
can run tests concurrently by deploying multiple “identical” targets and
splitting the tests across them. The tests would still run in isolation on each
target. This sounds hard, but actually it’s practically free with Pytest via
[pytest-xdist][].

The default `pytest-xdist` implementation simply takes the list of tests and
runs them in a round-robin fashion with the desired number of executors. We’ve
talked at length about being able to schedule groups of tests to run in
particular executors and using particular targets. While there are many paths
open to us, this plugin actually provides a hook, `pytest_xdist_make_scheduler`
that exists specifically to “implement custom tests distribution logic.”

## pytest-lisa

### What are the user modes?

Because Pytest is incredibly customizable, we want to provide a few sets of
reasonable default configurations for some common scenarios. We will add a flag
like `--lisa-mode=[dev,debug,ci,demo]` to change the default options and output
of Pytest. Doing so is readily supported by Pytest via the [pytest_addoption][]
and [pytest_configure][] hooks. We call these the provided “user modes.”

* The dev(eloper) mode is intended for use by test developers while writing a
  new test. It is verbose, caches the deployed VMs between runs, and generates a
  digestible [HTML](https://pypi.org/project/pytest-html/) report.

* The debug mode is like dev mode but with all possible information shown, and
  will open the Python debugger automatically on failures (which is provided by
  Pytest with the `--pdb` flag).

* The CI mode will be fairly quiet on the console, showing all test results, but
  putting the full info output into the generated report file (HTML for sharing
  with humans and
  [JUnit](https://docs.pytest.org/en/stable/_modules/_pytest/junitxml.html) for
  the associated CI environment, which presents as native test results).

* The demo mode will show the “executive summary” (a lot like CI, but finely
  tuned for demos). For example, what `make smoke` currently shows.

### How are tests described?

The built-in [pytest-mark](https://docs.pytest.org/en/stable/mark.html) plugin
already provides functionality for adding metadata to tests, where we
specifically want:

* Platform: used to skip tests inapplicable to the current system-under-test
* Category: our high-level test organization
* Area: feature being tested
* Priority: self-explanatory
* Tags: optional additional metadata for test organization

We simply reuse this with minimal logic to enforce our required metadata, with
sane defaults (perhaps setting the area to the name of the module), and to list
statistics about our test coverage. This is already included in the prototype.
It looks like this:

```python
import pytest

@pytest.mark.lisa(platform="Azure", category="Functional", priority=0, area="LIS_DEPLOY")
def test_lis_driver_version(target: Azure) -> None:
    """Checks that the installed drivers have the correct version."""
    ...
```

This is a functional example, which takes zero implementation. With this simple
decorator, all test [collection hooks][] can introspect the metadata, enforce
required parameters and set defaults, select tests based on arbitrary criteria,
and list test coverage statistics.

Note that Pytest leverages Python’s docstrings for built-in documentation (and
can even run tests discovered in such strings, like doctest). Hence we do not
have a separate field for the test’s documentation.

Being just Python code, this decorator need not be `@pytest.mark.lisa(...)` but
can trivially be provided as simply `@LISA(...)`. In fact, we provide this in
`lisa.py` with:

```python
LISA = pytest.mark.lisa

@LISA(...)
def test_something(...)
```

Currently we validate the parameters given to this mark during test collection,
by using the following code, which leverages the [schema][] library:

```python
from schema import Optional, Or, Schema

lisa_schema = Schema(
    {
        "platform": str,
        "category": Or("Functional", "Performance", "Stress", "Community", "Longhaul"),
        "area": str,
        "priority": Or(0, 1, 2, 3),
        Optional("tags", default=list): [str],
    },
)

def validate(mark: Mark) -> None:
    """Validate each test's LISA parameters."""
    assert not mark.args, "LISA marker cannot have positional arguments!"
    mark.kwargs.update(lisa_schema.validate(mark.kwargs))
```

In the future we could change `LISA` to be a function with these keyword
arguments so that IDE auto-completion is enabled. However, this is not mandatory
to move forward, and parameter validation is enabled succinctly with the above.

This mark also does need to be repeated for each test, as marks can be scoped to
a module, and so one line could describe defaults for every test in a file, with
individual tests overriding parameters as needed.

In the current implementation, we also take a `features: List[str]` argument
that is used to prove the concept deploying (or reusing) a target based on the
test’s required and the target’s available sets of features. However, as we move
forward we should define a separate `requires` mark that takes well-defined
classes describing the minimal required resources for a test. This will be part
of the refactor into the two Pytest plugins mentioned above.

Furthermore, we have a prototype
[generator](https://github.com/LIS/LISAv2/tree/pytest/generator) which parses
LISAv2 XML test descriptions and generates stubs with this mark filled in
correctly.

### How are tests selected?

Pytest already allows a user to specify which exact tests to run:

* Listing folders on the CLI (see below on where tests should live)
* Specifying a name expression on the CLI (e.g. `-k smoke and xdp`)
* Specifying a mark expression on the CLI (e.g. `-m functional and not slow`)

We can also implement any other mechanism via the
[pytest_collection_modifyitems][] hook. The proof-of-concept supports gathering
selection criteria from a YAML file:

```yaml
criteria:
  # Select all Priority 0 tests.
  - priority: 0
  # Run tests with 'smoke' in the name twice.
  - name: smoke
    times: 2
  # Exclude all tests in Area "xdp"
  - area: xdp
    exclude: true
```

This criteria is validated against the following [schema][]:

```python
from schema import Schema, Optional

criteria_schema = Schema(
    {
        # TODO: Validate that these strings are valid regular
        # expressions if we change our matching logic.
        Optional("name", default=None): str,
        Optional("area", default=None): str,
        Optional("category", default=None): str,
        Optional("priority", default=None): int,
        Optional("tags", default=list): [str],
        Optional("times", default=1): int,
        Optional("exclude", default=False): bool,
    }
)
```

The test collection is then modified using the Pytest hook,
[pytest_collection_modifyitems][]:

```python
def pytest_collection_modifyitems(
    session: Session, config: Config, items: List[Item]
) -> None:
    included: List[Item] = []
    excluded: List[Item] = []

    def select(item: Item, times: int, exclude: bool) -> None:
        if exclude:
            excluded.append(item)
        else:
            for _ in range(times - included.count(item)):
                included.append(item)

    for c in criteria: # Where `criteria` is from the schema.
        for item in items:
            marker = item.get_closest_marker("lisa")
            if not marker:
                # Not all tests will have the LISA marker, such as
                # static analysis tests.
                continue
            i = marker.kwargs
            if any(
                [
                    c["name"] and c["name"] in item.name,
                    c["area"] and c["area"].casefold() == i["area"].casefold(),
                    c["category"]
                    and c["category"].casefold() == i["category"].casefold(),
                    c["priority"] and c["priority"] == i["priority"],
                    c["tags"] and set(c["tags"]) <= set(i["tags"]),
                ]
            ):
                select(item, c["times"], c["exclude"])
    items[:] = [i for i in included if i not in excluded]
```

Because this is simply a Python list, we can also sort the tests according to
our needs, such as by priority. If the `python-targets` plugin has already
sorted by requirements, that’s just fine, Python’s `sorted()` built-in is
guaranteed to be stable (meaning we can sort in multiple passes).

### How are results reported?

Parsing the results of a large test suite can be difficult. Fortunately, because
Pytest is a testing framework, there already exists support for generating
excellent reports. For developers, the
[HTML](https://pypi.org/project/pytest-html/) report is easy to read: it is
self-contained, holds all the results and logs, and each test can be expanded
and collapsed. Tests which were rerun are recorded separately. For CI pipelines,
Pytest has integrated
[JUnit](https://docs.pytest.org/en/stable/_modules/_pytest/junitxml.html) XML
test report support. This is the standard method of reporting results to CI
servers like Jenkins and are natively parsed into the CI system’s built-in test
display page. Finally, Azure DevOps pipelines are even supported with a
community plugin
[pytest-azurepipelines](https://pypi.org/project/pytest-azurepipelines/) which
enhances the standard JUnit report for ADO.

However, we also have internal requirements to report test results throughout
the test life cycle to a database to be consumed by other tools. In this sense,
LISAv3 (the composition of our published plugins, tests, and fixtures) is simply
a producer. Our repository’s `conftest.py` can implement the necessary logic
using Pytest’s ample [test running hooks][]. In particular, the hook
[pytest_runtest_makereport][] is called for each of the setup, call and teardown
phases of a test. As such it can used for precisely this purpose.

### How are tests timed out?

The [pytest-timeout](https://pypi.org/project/pytest-timeout/) plugin provides
integrated timeouts via `@pytest.mark.timeout(<N seconds>)`, a configuration
file option, environment variable, and CLI flag. The Fabric library provides
timeouts in both the configuration and per-command usage. These are already used
to satisfaction in the prototype.

### How are tests organized?

That is, what does a folder of tests map to: a platform, feature, or owner?

In my opinion it is likely to be both. Tests which are common to a platform and
written by our team are probably best placed in a folder like `tests/azure`
whereas tests for a particular scenario which limits their image and SKU
applicability should be in a folder like `tests/acc`. It’s going to depend on
how often the tests are run together.

Because Pytest can run tests and `conftest.py` files from arbitrary folders,
maintaining sets of tests and plugins separately from the base LISA repository
is easy. Custom repositories with new tests, plugins, fixtures,
platform-specific support, etc. can simply be cloned anywhere, and provided on
the command-line to Pytest.

Test authors should keep tests which share requirements and are otherwise
similar to a single module (Python file). Not only is this well-organized, but
because marks can be applied at the module level, setting all the tests to be
skipped or expected to fail (with the built-in `skip` and `xfail` Pytest marks)
becomes even easier.

An open question is if we really want to bring every test from LISAv2 directly
over, or if we should carefully analyze our tests to craft a new set of
high-level scenarios. An interesting result of reorganizing and rewriting the
tests would be the ability to have test layers, where the result of a high-level
test dictates if the tests below it should be skipped. If it passes, it implies
the tests underneath it would pass, and so skips them; but if it fails, the next
test below it runs and so on until a passing layer is found.

### How will we port LISAv2 tests?

Given the above, we still must decide if we want to put the engineering effort
into porting _every_ LISAv2 test. However, the prototype started by porting the
`LIS-DRIVER-VERSION-CHECK` test, proving that tests which exclusively use Bash
scripts are trivially portable. Unfortunately, most tests use an associated
PowerShell script which is tightly coupled to the LISAv2 framework.

We believe that it is _possible_ to port these tests without untoward
modifications. We would need to write a mock library that implements (or stubs
where appropriate) LISAv2 framework functionality such as
`Provision-VMsForLisa`, `Copy-RemoteFiles`, `Run-LinuxCmd`, etc., and provides
both the expected “global” objects and the test function parameters `AllVmData`
and `CurrentTestData`.

This work needs to be done regardless of the approach we take with our framework
(leveraging Pytest or writing our own), and it is not inconsequential work. It
needs to be thoroughly planned and executed, and is certainly a ways off.

### How are tests and functions retried?

Testing remote targets is inherently flaky, so we take a two-pronged approach to
dealing with the flakiness.

The [pytest-rerunfailures](https://pypi.org/project/pytest-rerunfailures/)
plugin will be used to easily mark a test itself as flaky. It has the nice
feature of recording each rerun in the produced report. It looks like this:

```python
@pytest.mark.flaky(reruns=5)
def test_something_flaky(...):
    """This fails most of the time."""
    ...
```

> Note that there is an open
> [bug](https://github.com/pytest-dev/pytest-rerunfailures/issues/51) in this
> plugin which can cause issues with fixtures using scopes other than “function”
> but it can be worked around.

The [Tenacity](https://tenacity.readthedocs.io/en/latest/) library should be
used to retry flaky functions that are not tests, such as downloading boot
diagnostics or pinging a node. As the modern Python retry library it has
easy-to-use decorators to retry functions (and context managers to use within
functions), as well as excellent wait and timeout support. It looks like this:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

class Node:
    ...
    @retry(reraise=True, wait=wait_exponential(), stop=stop_after_attempt(3))
    def ping(self, **kwargs):
        """Ping the node from the local system in a cross-platform manner."""
        flag = "-c 1" if platform.system() == "Linux" else "-n 1"
        return self.local(f"ping {flag} {self.host}", **kwargs)
    ...
```

We can additionally list a test twice when modifying the items collection, as
implemented in the criteria proof-of-concept. However, given the above
abilities, this may not be desired.

## What Else?

There’s still a lot more to think about and design. A non-exhaustive list of
future topics (some touched on above):

* Tests inventory (generating statistics from metadata)
* ARM template support (with Azure CLI)
* Servicing Azure CLI (how stable is their API?)
* libvirt driver support (gives us Hyper-V and more)
* Duration reporting (built-in)
* Self-documentation (via Pydoc)
* Environment class design
* Feature requests (NICs in particular)
* Selection and targets YAML schema
* Secret management
* External results reporting (database and emails)
* Embedded systems / bare metal support
* Managing Python `logging` records
* Managing shell command stdout/stderr

## What alternatives were tried?

These are notes from things tried that did not work out, and why.

### Writing Another Framework

I believe the above set of technical specifications clearly describes how we can
leverage Pytest for our needs. Furthermore, the existing prototype proves this
is a viable option. Therefore I do not think we should consider writing and
maintaining a _new_ Python testing framework. We should avoid falling for “not
invented here” syndrome. The alternative prototype which does implement a new
framework required over five thousand lines of code, the Pytest-based prototype
used less than two hundred, or less than three percent. We do not want to take
on the maintenance cost of yet another framework, the maintenance cost of LISAv2
already caused this mess in the first place. I think the work of prototyping
said new framework was valuable, as it provided insight into the eventual
technical design of LISAv3.

### Using Remote Capabilities of `pytest-xdist`

With the [pytest-xdist][] plugin there already exists support for running a
folder of tests on an arbitrary remote host via SSH.

The LISA tests could be written as Python code suitable for running on the
target test system, which means direct access to the system in the test code
itself (subprocesses are still available, without having to use SSH within the
test, but would become far less necessary), something that is not possible with
any current prototype. Where the `pytest-xdist` plugin copies the package of code
to the target node and runs it, the pytest-lisa plugin could instantiate that
node (boot the necessary image on a remote machine or launch a new Hyper-V or
Azure VM, etc.) for the tests.

However, this use of pytest-dist requires full Python support on the target
machines, and drastically changes how developers write tests. Furthermore, it
would not support running local commands against the remote node (like ping) or
running the test across a reboot of the node. Thus we do not want to use this
functionality of `pytest-xdist`. That said, `pytest-xdist` will still be useful
for running tests concurrently, as described above.

### Using Paramiko Instead of Fabric

The Paramiko library is less complex (smaller library footprint) than Fabric, as
the latter wraps the former, but it is a bit more difficult to use, and doesn’t
support reading existing SSH config files, nor does it support “ProxyJump” which
we use heavily. Fabric instead provides a clean high-level interface for
existing shell commands, handling all the connection abstractions for us.

Using Paramiko looked like this:

```python
from pathlib import Path
from typing import List

from paramiko import SSHClient

import pytest

@pytest.fixture
def node() -> SSHClient:
    with SSHClient() as client:
        client.load_system_host_keys()
        client.connect(hostname="...")
        yield client


def test_lis_version(node: SSHClient) -> None:
    with node.open_sftp() as sftp:
        for f in ["utils.sh", "LIS-VERSION-CHECK.sh"]:
            sftp.put(LINUX_SCRIPTS / f, f)
        _, stdout, stderr = node.exec_command("./LIS-VERSION-CHECK.sh")
        sftp.get("state.txt", "state.txt")
    with Path("state.txt").open as f:
        assert f.readline() == "TestCompleted"
```

It is more verbose than necessary when compared to Fabric.

### StringIO

For `Node.cat()` it would seem we could use `StringIO` like so:

```python
from io import StringIO

with StringIO() as result:
    node.get("state.txt", result)
    assert result.getvalue().strip() == "TestCompleted"
```

However, the data returned by Paramiko is in bytes, which in Python 3 are not
equivalent to strings, hence the existing implementation which uses `BytesIO`
and decodes the bytes to a string.

[pytest-xdist]: https://github.com/pytest-dev/pytest-xdist
[collection hooks]: https://docs.pytest.org/en/latest/reference.html#collection-hooks
[parameterization]: https://docs.pytest.org/en/stable/parametrize.html
[pytest_addoption]: https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_addoption
[pytest_collection_modifyitems]: https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_collection_modifyitems
[pytest_configure]: https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_configure
[pytest_generate_tests]: https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_generate_tests
[pytest_runtest_makereport]: https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_runtest_makereport
[schema]: https://pypi.org/project/schema/
[test running hooks]: https://docs.pytest.org/en/latest/reference.html#test-running-runtest-hooks
