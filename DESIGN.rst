Technical Specification Document
================================

This document outlines the technical specifications and design for
LISAv3 leveraging `Pytest <https://docs.pytest.org/en/stable/>`_ as
the test runner.

Please see `PR #1107 <https://github.com/microsoft/lisa/pull/1107>`_
for a working implementation and see the `documentation`_.

.. _documentation: https://microsoft.github.io/lisa/.

:Author: Andrew Schwartzmeyer (he/him) <andrew@schwartzmeyer.com>
:Version: 0.4

Why Pytest?
-----------

Pytest is an `incredibly popular
<https://docs.pytest.org/en/stable/talks.html>`_ MIT licensed open
source Python testing framework. It has a thriving community and
plugin framework, with over 750 `plugins
<https://plugincompat.herokuapp.com/>`_. Instead of writing (and
therefore maintaining) yet another test framework, we will do more
with less by reusing Pytest and existing plugins. This allows us to
focus on our unique problems: organizing and understanding our tests,
deploying necessary resources (such as Azure, Hyper-V, or bare metal
machines, collectively known as “targets”), and analyzing our results.

Most of Pytest itself is implemented via `built-in plugins
<https://docs.pytest.org/en/stable/plugins.html>`_, providing us with
many useful and well-documented examples. Furthermore, when others
were confronted with a problem similar to our own they also chose to
use Pytest.

`Labgrid`_ is an open source embedded board control library that
delegated the testing framework logic to Pytest in their `design
<https://labgrid.readthedocs.io/en/latest/design_decisions.html>`_,
and `U-Boot <https://github.com/u-boot/u-boot>`_, an embedded board
boot loader, similarly leveraged Pytest in their `tests
<https://github.com/u-boot/u-boot/tree/master/test/py>`_. KernelCI and
Avocado were also evaluated by the Labgrid developers at an `Embedded
Linux Conference <https://youtu.be/S0EJJM5bVUY>`_ and both ruled out
for reasons similar to our own before they settled on Pytest.

.. _Labgrid: https://github.com/labgrid-project/labgrid

The `fundamental features <https://youtu.be/CMuSn9cofbI>`_ of Pytest
match our needs very well:

- Automatic test discovery, no boiler-plate test code
- Useful information when a test fails (assertions are introspected)
- Test and fixture `parameterization`_
- Modular setup/teardown via `fixtures`_
- Incredibly customizable (as detailed above)

.. _parameterization: https://docs.pytest.org/en/stable/parametrize.html
.. _fixtures: https://docs.pytest.org/en/stable/fixture.html

All the logic for describing, discovering, running, skipping and
reporting results of the tests, as well as enabling and importing
users’ plugins is already written and maintained by the open source
community. This leaves us to focus on our hard and specific problems:
creating an abstraction to launch the necessary targets, organizing
and publishing our tests, and reporting test results upstream. Using
Pytest also allows us the space to abstract other commonalities in our
specific tests. In this way, LISAv3 could solve the difficulties we
have at hand without creating yet another test framework.

By leveraging such a popular framework we maximize the ease of
adoption for developers to write tests, as they are likely already
familiar with Pytest, and if not, have a wealth of examples and
`resources`_ from which to draw. The environment will be one of
instant familiarity, thus providing developers a running start.

.. _resources: https://docs.pytest.org/en/stable/example/index.html

Finally, by reducing the amount of code we maintain, we drastically
increase our chances of receiving pull requests instead of bug reports
from users. This is important because despite our best efforts it is
practically guaranteed that as adoption of LISAv3 increases, users
will want changes to be made, and we need to empower them to do so
themselves. Using Pytest gives us the best chances for users to
understand and extend the framework, plugins, etc. with ease.

What are we maintaining?
------------------------

We have three Pytest plugins, soon to be published on `PyPI
<https://pypi.org/>`_, supporting the framework:

- `pytest-target`_
- `pytest-lisa`_
- `pytest-playbook`_

We will also maintain our set of public “LISA” tests, but these are
decoupled from the plugins and packages.

The `pytest-target`_ plugin encapsulates all our logic for *how* and
*when* to deploy targets (local or cloud virtual machines, or bare
metal machines, and all the associated resources), run tests on the
specified targets, and delete the targets. This includes specifying
which features and resources each test needs and each given target
provides (such as number of cores, amount of RAM, and other hardware
like a GPU etc.), how to deploy and delete each target based on its
platform, and `parameterization`_ of the
:py:func:`~target.plugin.target` fixture based on YAML file input (the
“playbook”). In fact, some tests (like networking) require multiple
targets at once. This plugin will need to manage resources
intelligently, being able to optimize for both time and cost, and make
it easy for tests to request and use various resources.

The `pytest-lisa`_ plugin encapsulates all our logic for how to
organize and select tests, as well as our opinions on displaying test
results. This includes the user modes, test metadata and inventory,
test selection based on criteria against that metadata, required and
pre-configured upstream plugins, and result notifiers. It will
similarly support YAML file playbook input.

The `pytest-playbook`_ plugin encapsulates the shared common
functionality of registering component schemata (e.g. platform and
target parameters from `pytest-target`_ and selection criteria from
`pytest-lisa`_). It uses the `schema`_ library.

.. _schema: https://pypi.org/project/schema/

We have striven to keep `pytest-lisa`_ and `pytest-target`_ from
depending on each other in order to keep their scope well-defined.
They both depend on `pytest-playbook`_, and the “LISA” project depends
on them both, but they are independent plugins.

In the “LISA” repository of tests we may also maintain additional
`fixtures`_ for our tests’ unique requirements. Similarly, we and
others may have private test repositories which build upon the above
by defining new platform support and internal service integrations.
The built-in plugin discovery of Pytest (via ``conftest.py`` files)
enables us to satisfy one of our requirements to “support plugins to
orchestrate the test environment.”

pytest-target
-------------

How are targets provided and accessed?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

First we need to define “target” as an instance of a
system-under-test. That is, given some environment requirements, such
an Azure image (URN) and size (SKU), a target would be a virtual
machine deployed by `pytest-target`_ with SSH access provided to the
requesting test. A target could optionally be pre-deployed and simply
connected. Some tests may request multiple targets as well.

Pytest uses `fixtures`_, which are the primary way of setting up test
requirements. They replace less flexible alternatives like
setup/teardown functions. It is through fixtures that we implement
remote target setup/teardown. Our :py:func:`~target.plugin.target`
fixture returns a :py:class:`~target.target.Target` instance, which
currently provides:

- Remote shell access via SSH using `Fabric`_
- Data including hostname / IP address
- Cross-platform ping functionality with exponential back-off
- Uploading of local files to arbitrary remote destinations
- Downloading of remote file contents into local string variable
- Asynchronous remote command execution with promises

.. _Fabric: https://www.fabfile.org/

The :py:class:`~target.azure.AzureCLI` subclass additionally provides:

- An example of a working platform implementation
- Automatic provisioning of a parameterized Azure VM
- Allowing ICMP ping via Azure firewall rules
- Azure platform forced reboot by API
- Downloading boot diagnostics (serial console log)

The :py:class:`~target.target.SSH` subclass is a simple implementation
which only connects to a given host.

The :py:class:`~target.target.Target` class leverages `Fabric`_ which
is a popular high-level Python library for executing shell commands on
remote systems over SSH. Underneath the covers Fabric uses
`Paramiko`_, the most popular low-level Python SSH library. Fabric
does the heavy lifting of safely connecting and disconnecting from the
node, executing the shell command (synchronously or asynchronously),
reporting the exit status, gathering the ``stdout`` and ``stderr``,
providing ``stdin`` (or interactive auto-responses, similar to
``expect``), uploading and downloading files, and much more. In fact,
these APIs are all available and implemented for the local machine by
the underlying `Invoke`_ library, which is essentially a Python
``subprocess`` wrapper with “a powerful and clean feature set.”

.. _Paramiko: https://docs.paramiko.org/en/stable/
.. _Invoke: https://www.pyinvoke.org/

Other test specific requirements, such as installing software and
daemons, downloading files from remote storage, or checking the state
of our Bash test scripts, would similarly be implemented by methods on
:py:class:`~target.target.Target`, its subclasses, or via additional
fixtures and thus shared among tests.

What’s the :py:class:`~target.target.Target` class?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In version 0.1 of this design document we detailed a planned refactor
of what was then called the ``Node`` class. This has since been
executed with just a few modifications (one being the rename to
:py:class:`~target.target.Target`, as ``Node`` was found to be an
overloaded term in the context of data centers). This class and its
subclasses are decoupled from Pytest, and are used via fixtures. Its
interface looks like this:

.. code:: python

   from abc import ABC, abstractmethod
   from schema import Schema
   import fabric

   class Target(ABC):

       group: str
       params: Dict[str, str]
       features: List[str]
       data: Dict[Any, Any]
       number: int
       locked: bool
       name: str
       host: str
       conn: fabric.Connection  # Provides run, sudo, get, put etc.

       def __init__(...):
           ...
           self.params = self.get_schema().validate(params)
           self.name = f"{self.group}-{self.number}"
           self.host = self.deploy()
           self.conn = fabric.Connection(self.host, ...)

       @classmethod
       @abstractmethod
       def schema(cls) -> Mapping[Any, Any]:
           """Must return a mapping for expected instance parameters."""
           ...

       @classmethod
       def defaults(cls) -> Mapping[Any, Any]:
           """Can return a mapping for default parameters."""
           ...

       @abstractmethod
       def deploy(self) -> str:
           """Must deploy the target resources and return the hostname."""
           ...

       @abstractmethod
       def delete(self) -> None:
           """Must delete the target's resources."""
           ...

This class allows us to answer the next question.

How are new platforms supported?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Platform support is implemented by subclassing
:py:class:`~target.target.Target` and implementing the abstract
methods in the above interface:

- :py:meth:`~target.target.Target.schema`: Define the schema for the platform’s parameters
- :py:meth:`~target.target.Target.defaults`: Define defaults for those parameters
- :py:meth:`~target.target.Target.deploy`: Create an instance resource
- :py:meth:`~target.target.Target.delete`: Delete the instance and its resources

Internally we use the ``__subclasses__`` attribute of
:py:class:`~target.target.Target` to automatically gather all the
available platforms and their parameter schemata from users’ own
``conftest.py`` files and other plugins. This enables the
:py:func:`~target.plugin.target` fixture to dynamically instantiate a
target from the gathered requirements and parameters.

For example, the :py:class:`~target.azure.AzureCLI` subclass defines
its required parameters using the `schema`_ library like this:

.. code:: python

   from schema import Optional, Schema
   from target import Target

   class AzureCLI(Target):
       ...
       @classmethod
       def schema(cls) -> Dict[Any, Any]:
           return {
               "image": str,
               Optional("sku"): str,
               Optional("location"): str,
           }

Simply through defining this subclass the user can now specify a set
of parameterized YAML targets in a playbook like this:

.. code:: yaml

   platforms:
     AzureCLI:
       sku: Standard_DS2_v2

   targets:
     - name: Debian
       platform: AzureCLI
       image: Debian:debian-10:10:latest

     - name: Ubuntu
       platform: AzureCLI
       image: Canonical:UbuntuServer:18.04-LTS:latest


These targets are then used to parameterize the
:py:func:`~target.plugin.target` fixture in the
:py:func:`~target.plugin.pytest_generate_tests` hook (see below for
more details).

This demonstrated how we can have platforms define their own schema
and register that schema automatically. The ``platforms`` key allows a
playbook to override the defaults in the platform implementation,
which are then eclipsed for each named target in the ``targets`` key.
This is accomplished through internal details in `pytest-target`_’s
hook implementation :py:func:`~target.plugin.pytest_playbook_schema`
using the `pytest-playbook`_ plugin, but for the users, it just works.

How do we interact with Azure?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For :py:class:`~target.azure.AzureCLI`, we use the `Azure CLI`_ to
deploy a virtual machine. For Hyper-V (and other virtualization
platforms), we would like to use `libvirt`_, and for embedded / bare
metal environments we are evaluating `Labgrid`_.

.. _Azure CLI: https://aka.ms/azureclidocs
.. _libvirt: https://libvirt.org/python.html

If possible, we do not want to use the `Azure Python APIs
<https://aka.ms/azsdk/python/all>`_ directly because they are more
complicated (and less documented) than the `Azure CLI`_. With
`Invoke`_ (as discussed above), ``az`` becomes incredibly easy to work
with. The Azure CLI lead developer states that they have `feature
parity <https://stackoverflow.com/a/50005660/1028665>`_ and that the
CLI is more straightforward to use. Considering our
ease-of-maintenance requirement, this seems the apt choice, especially
since the Azure CLI supports deploying resources with `ARM templates
<https://docs.microsoft.com/en-us/azure/azure-resource-manager/templates/deploy-cli>`_.

If it later becomes necessary to use the Python APIs directly, that
is, of course, still doable (and we can reuse existing code doing it).
This implementation can coexist as simply another class, ``AzureAPI``.

On the topic of “servicing” the `Azure CLI`_, its developers state
that “at command level, packages only upgrading the PATCH version
guarantee backward compatibility.” The tool is also intended to be
used in scripts, so servicing would amount to documenting the tested
version and having the Azure class check that it’s compatible before
using it (or warning and then trying its best).

How are requirements examined?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The :py:attr:`~target.target.TargetData.features` attribute is
currently a list of strings and (combined with the
:py:attr:`~target.target.TargetData.params` dictionary) is used to
demonstrate how we can test if an existing target instance
(representing a deployed machine) met a test’s requirements. It should
be updated with a ``Requirements`` class that represents all physical
attributes of the target. The :py:mod:`target.plugin` module defines a
``@pytest.mark.target`` `pytest-mark`_ which takes the features list
but should instead take instances of this ``Requirements`` class. Two
``Requirements`` should be comparable to determine if one set meets
(or exceeds) the other set. Existing code that does this can be reused
for this.

.. _pytest-mark: https://docs.pytest.org/en/stable/mark.html

How do we share common tasks?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Common tasks for targets like rebooting and pinging should be
implemented on the :py:class:`~target.target.Target` class, and
platform-specific tasks on the respective subclass.

Methods available from :py:attr:`~target.target.Target.conn` include
``run()`` and ``sudo()`` which are used to easily run arbitrary
commands, and ``get()`` and ``put()`` to download and upload arbitrary
files.

The :py:meth:`~target.target.Target.cat` method wraps ``get()`` and
returns the file as data in a string. This makes test code like this
possible:

.. code:: python

   assert target.cat("state.txt") == "TestCompleted"

A ``reboot()`` method should be added that first tries to use
``sudo("reboot", timeout=5)`` (with a short timeout to avoid a hung SSH
session). It should retry with an exponential back-off to see if the
machine has rebooted by checking either ``uptime`` or the existence of a
file created before the reboot. This is to avoid having to ``sleep()``
and just guess the amount of time it takes to reboot.

The :py:meth:`~target.target.Target.restart` method should “power
cycle” the machine using the platform’s API, and thus is in abstract
method as each platform needs to implement it differently.

Other tools and shared logic should be implemented as necessary. A major
area of concern is the automatic and package-manager agnostic
installation of necessary tools, much of which has been implemented
previously and can be reused.

How are targets requested and managed?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In version 0.3 of this design document we detailed how we used a
session-scoped ``pool()`` fixture to manage targets across an entire
test session. This has since been replaced with an enhanced disk-based
`cache`_, accessed through a context manager with an atomic file lock:

.. _cache: https://docs.pytest.org/en/stable/cache.html

.. code:: python

   from filelock import FileLock

   @contextmanager
   def target_pool(config: Config) -> Generator[Dict[str, Any], None, None]:
       """Exclusive access to the cached targets pool."""
       assert config.cache is not None
       lock = Path(config.cache.makedir("target")) / "pool.lock"
       with FileLock(str(lock)):
           pool = config.cache.get("target/pool", {})
           yield pool
           config.cache.set("target/pool", pool)

Note that the cross-session `cache`_ is provided by Pytest, and very
easy to work with. The key maps to a file path, and the data stored
and read is JSON. So our targets are serializable: internally the
`data class`_ :py:attr:`~target.target.TargetData` implements the
methods :py:meth:`~target.target.TargetData.to_json` and
:py:meth:`~target.target.TargetData.from_json`, and the
:py:func:`~target.plugin.target` fixture creates new instances of
:py:class:`~target.target.Target` for the requesting test from either
a “fit” cached target (and so locks it) or deploys a new target.

.. _data class: https://docs.python.org/3/library/dataclasses.html

.. code:: python

   @pytest.fixture
   def target(request: SubRequest) -> Iterator[Target]:
       ...
       with target_pool(request.config) as pool:
           for name, json in pool.items():
               if fits(TargetData(**json)):
                   t = Target.from_json(json)
                   t.locked = True
                   pool[t.name] = t.to_json()
           # Or...
           cls = Target.get_platform(params["platform"])
           t = cls(group, params, features, {}, i)
           pool[t.name] = t.to_json()

Because all access to the cache (and so the target pool) is within the
scope of the context manager, the access is locked in such a way that
this works with multiple Pytest processes, as used by `pytest-xdist`_
and as necessary for parallel CPU-bound tasks (like testing multiple
targets) given Python’s `Global Interpreter Lock`_. Platform
implementations can save arbitrary JSON-serializable data to the
class’s :py:attr:`~target.target.TargetData.data` attribute and it
will be returned when recreated from the cache.

.. _Global Interpreter Lock: https://wiki.python.org/moin/GlobalInterpreterLock

While currently an unordered dictionary, to support optimal scheduling
we will likely want to use a priority queue, where the priority of a
target represents its cost (whether in terms of time or money),
allowing us to provide either the fastest or the cheapest target to
each request. By using the `pytest_collection_modifyitems`_ hook to
sort (and so group) the tests by their requirements, the tests would
efficiently reuse targets. Except for the most recently used target,
targets not in use (unlocked) should be deallocated.

.. _pytest_collection_modifyitems: https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_collection_modifyitems

With the ``--keep-targets`` CLI flag the targets won’t be deleted at
the end of a run, and without it they will be automatically deleted.
Regardless, they will always be cached to disk when they are created
so that the CLI flag ``--delete-targets`` can delete *all* allocated
targets, even after a test session is interrupted.

The fixture is indirectly parameterized during setup with the
:py:func:`~target.plugin.pytest_generate_tests` hook. Test and fixture
`parameterization`_ is a huge feature of Pytest. When we parameterize
the :py:func:`~target.plugin.target` fixture for multiple targets
(e.g. “Ubuntu” and “Debian”), Pytest automatically creates a set of
tests for each target. So ``test_smoke`` turns into
``test_smoke[Ubuntu]`` and ``test_smoke[Debian]``. This allows us to
run a collection of tests against multiple targets with ease. These
targets are defined in a YAML file (thanks to `pytest-playbook`_) and
validated against the parameters collected from the previously
described platform subclasses.

Finally, once the :py:func:`~target.plugin.target` fixture has
returned a working and sanity-checked environment to the requesting
test, the test is capable of examining any and all attributes of the
:py:class:`~target.target.Target` and quickly marking itself as
skipped, expected to fail, or failed before executing the body of the
test. Our static type checking enables developers to ensure that the
platform they requested supports all methods and fields they use by
annotating the test’s ``target`` parameter with the expected platform
type (or types). Ensuring the effectiveness of this type checking will
require us to carefully update our platform implementations, and not
rely on arbitrary objects of data. (For example, add an
``internal_address`` field to ``AzureCLI``, don’t just look up
``data["internal_address"]``.)

pytest-lisa
-----------

How are tests described?
~~~~~~~~~~~~~~~~~~~~~~~~

The built-in `pytest-mark`_ plugin already provides functionality for
adding metadata to tests, where we specifically want (and describe
using `schema`_ :py:data:`~lisa.lisa_schema`):

- Platform: used to skip tests inapplicable to the current
  system-under-test
- Category: our high-level test organization
- Area: feature being tested
- Priority: self-explanatory
- Tags: optional additional metadata for test organization
- Features: a set of required features (like “GPU”)
- Reuse: a boolean to indicate if a target is reusable after the test
- Count: number of targets the test needs

We simply reuse this with minimal logic to enforce our required
metadata, with sane defaults , and to list statistics about our test
coverage. It looks like this:

.. code:: python

   from lisa import LISA

   @LISA(platform="Azure", category="Functional", area="deploy", priority=0)
   def test_smoke(target: AzureCLI, caplog: LogCaptureFixture) -> None:
       """Check that an Azure Linux VM can be deployed and is responsive.

This is a functional example. With this simple decorator, all test
`collection hooks`_ can introspect the metadata, enforce required
parameters and set defaults, select tests based on arbitrary criteria,
and list test coverage statistics (test inventory). We validate the
metadata in :py:func:`lisa.pytest_collection_modifyitems`.

.. _collection hooks: https://docs.pytest.org/en/latest/reference.html#collection-hooks

Note that Pytest leverages Python’s docstrings for built-in
documentation (and can even run tests discovered in such strings, like
doctest). Hence we do not have a separate field for the test’s
documentation. By following the best practice of using docstrings for
our modules, classes, and functions, we can automatically to generate
full `documentation`_ for each plugin and test (which you are likely
currently reading).

This mark also does need to be repeated for each test, as marks can be
scoped to a module, and so one line could describe defaults for every
test in a file, with individual tests overriding parameters as needed.

In the current implementation, we take a ``features: List[str]``
argument that is used to prove the concept deploying (or reusing) a
target based on the test’s required and the target’s available sets of
features, and it is passed to ``@pytest.mark.target``. See `How are
requirements examined?`_ for more. Coupled with the test’s requested
:py:func:`~target.plugin.target` fixture being parameterized (see
discussion in `pytest-target`_) this demonstrates at least one way we
can satisfy our “test run planner/scheduler” requirement.

Furthermore, we have a prototype `generator
<https://github.com/LIS/LISAv2/tree/pytest/generator>`_ which parses
LISAv2 XML test descriptions and generates stubs with this mark filled
in correctly.

How are tests selected?
~~~~~~~~~~~~~~~~~~~~~~~

Pytest already allows a user to specify which exact tests to run:

- Listing folders on the CLI (see below on where tests should live)
- Specifying a name expression on the CLI (e.g. ``-k smoke and xdp``)
- Specifying a mark expression on the CLI (e.g. ``-m functional and
  not slow``)

We can also implement any other mechanism via the
`pytest_collection_modifyitems`_ hook. The existing implementation in :py:mod:`lisa`
supports gathering selection criteria from a YAML file:

.. code-block:: yaml

   criteria:
     # Select all Priority 0 tests.
     - priority: 0
     # Run tests with 'smoke' in the name twice.
     - name: smoke
       times: 2
     # Exclude all tests in Area "xdp"
     - area: xdp
       exclude: true

This criteria is validated against following `schema`_ defined in
:py:func:`lisa.pytest_playbook_schema`.

The test collection is then modified using the Pytest hook in
:py:func:`lisa.pytest_collection_modifyitems`. Because this is simply
a Python list, we can also sort the tests according to our needs, such
as by priority. If the `pytest-target`_ plugin has already sorted by
requirements, that’s just fine, Python’s ``sorted()`` built-in is
guaranteed to be stable (meaning we can sort in multiple passes).

Together, the CLI support and YAML playbook satisfy one of our “test
entrance” requirements. We also generate our own binary called
``lisa`` which simply delegates to Pytest.

How are results reported?
~~~~~~~~~~~~~~~~~~~~~~~~~

Parsing the results of a large test suite can be difficult.
Fortunately, because Pytest is a testing framework, there already
exists support for generating excellent reports. For developers, the
`HTML report`_ is easy to read: it is self-contained, holds all the
results and logs, and each test can be expanded and collapsed. Tests
which were rerun are recorded separately. For CI pipelines, Pytest has
integrated `JUnit
<https://docs.pytest.org/en/stable/_modules/_pytest/junitxml.html>`_
XML test report support. This is the standard method of reporting
results to CI servers like Jenkins and are natively parsed into the CI
system’s built-in test display page. Finally, Azure DevOps pipelines
are even supported with a community plugin `pytest-azurepipelines
<https://pypi.org/project/pytest-azurepipelines/>`_ which enhances the
standard JUnit report for ADO.

.. _HTML report: https://pypi.org/project/pytest-html/

One of our requirements is to support the lookup of previous tests’
execution metrics, such as recorded performance metrics and duration,
so that performance tests can check regressions. This is the perfect
example of carrying a small fixture which provides access to our
internal database and is dynamically added to our tests when run
internally, and the tests can lookup and record whatever they need
through the fixture.

However, we also have internal requirements to report test results
throughout the test life cycle to a database (the “result manager” and
“progress tracker”) to be consumed by other tools. In this sense,
LISAv3 (the composition of our published plugins, tests, and fixtures)
is simply a producer, and the consumers can parse the test results,
send emails, archive the collected logs, update a GUI display of test
progress, etc. Our repository’s ``conftest.py`` can implement the
necessary logic using Pytest’s ample `test running hooks
<https://docs.pytest.org/en/latest/reference.html#test-running-runtest-hooks>`_.
In particular, the hook `pytest_runtest_makereport
<https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_runtest_makereport>`_
is called for each of the setup, call and teardown phases of a test.
As such it can used for precisely this purpose.

How is setup, run, and cleanup handled?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Pytest strives to require minimal boiler-plate code. Thus the classic
“xunit-style” of defining a class with setup and teardown functions in
addition to test functions is not recommended (nor necessary).
Generally Pytest expects `fixtures`_ to be used for dependency
injection (which is what setup/teardown functions usually do). For
users that really want the classic style, it is nonetheless fully
`supported <https://docs.pytest.org/en/stable/xunit_setup.html>`_ and
documented (and can be applied at the module, class, and method
scopes). Thus our “test runner” requirement is satisfied.

How are tests timed out?
~~~~~~~~~~~~~~~~~~~~~~~~

The `pytest-timeout <https://pypi.org/project/pytest-timeout/>`_
plugin provides integrated timeouts via ``@pytest.mark.timeout(<N
seconds>)``, a configuration file option, environment variable, and
CLI flag. The Fabric library provides timeouts in both the
configuration and per-command usage. These are already used to
satisfaction in the prototype. Additionally, Pytest has built-in
support for measuring the duration of each fixture’s setup and
teardown and each test (it’s simply the ``--durations`` and
``--durations-min`` flags).

How are tests organized?
~~~~~~~~~~~~~~~~~~~~~~~~

That is, what does a folder of tests map to: a platform, feature, or
owner?

In the author’s opinion it is likely to be both. Tests which are
common to a platform and written by our team are probably best placed
in a folder like ``tests/azure`` whereas tests for a particular
scenario which limits their image and SKU applicability should be in a
folder like ``tests/acc``. It’s going to depend on how often the tests
are run together.

Because Pytest can run tests and ``conftest.py`` files from arbitrary
folders, maintaining sets of tests and plugins separately from the
base LISA repository is easy. Custom repositories with new tests,
plugins, fixtures, platform-specific support, etc. can simply be
cloned anywhere, and provided on the command-line to Pytest.

Test authors should keep tests which share requirements and are
otherwise similar to a single module (Python file). Not only is this
well-organized, but because marks can be applied at the module level,
setting all the tests to be skipped or expected to fail (with the
built-in ``skip`` and ``xfail`` Pytest marks) becomes even easier.

An open question is if we really want to bring every test from LISAv2
directly over, or if we should carefully analyze our tests to craft a
new set of high-level scenarios. An interesting result of reorganizing
and rewriting the tests would be the ability to have test layers,
where the result of a high-level test dictates if the tests below it
should be skipped. If it passes, it implies the tests underneath it
would pass, and so skips them; but if it fails, the next test below it
runs and so on until a passing layer is found.

How will we port LISAv2 tests?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Given the above, we still must decide if we want to put the
engineering effort into porting *every* LISAv2 test. However, the
prototype started by porting the ``LIS-DRIVER-VERSION-CHECK`` test,
proving that tests which exclusively use Bash scripts are trivially
portable. Unfortunately, most tests use an associated PowerShell
script which is tightly coupled to the LISAv2 framework.

We believe that it is *possible* to port these tests without untoward
modifications. We would need to write a mock library that implements
(or stubs where appropriate) LISAv2 framework functionality such as
``Provision-VMsForLisa``, ``Copy-RemoteFiles``, ``Run-LinuxCmd``,
etc., and provides both the expected “global” objects and the test
function parameters ``AllVmData`` and ``CurrentTestData``. But it
wouldn’t be great.

This work needs to be done regardless of the approach we take with our
framework (leveraging Pytest or writing our own), and it is not
inconsequential work. It needs to be thoroughly planned and executed,
and is certainly a ways off. The author’s personal opinion is that we
won’t want to port most LISAv2 tests, and instead create a new set of
well-documented, comprehensive, layered tests that cover our current
needs, instead of bringing along all these historical tests.

How are tests and functions retried?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Testing remote targets is inherently flaky, so we take a two-pronged
approach to dealing with the flakiness.

The `pytest-rerunfailures`_ plugin can be used to easily mark a test
itself as flaky. It has the nice feature of recording each rerun in
the produced report. It looks like this:

.. _pytest-rerunfailures: https://pypi.org/project/pytest-rerunfailures/

.. code:: python

   @pytest.mark.flaky(reruns=5)
   def test_something_flaky(...):
       """This fails most of the time."""
       ...

Note that there is an open `bug
<https://github.com/pytest-dev/pytest-rerunfailures/issues/51>`_ in
this plugin which can cause issues with fixtures using scopes other
than “function” but it can be worked around (and we mostly use
“function” scope anyway).

The `Tenacity`_ library is used to retry flaky functions that are not
tests, such as downloading boot diagnostics or pinging a node. As the
“modern Python retry library” it has easy-to-use decorators to retry
functions (and context managers to use within functions), as well as
excellent wait and timeout support. The
:py:meth:`~target.target.Target.ping` method looks like this:

.. _Tenacity: https://tenacity.readthedocs.io/en/latest/

.. code:: python

   from tenacity import retry, stop_after_attempt, wait_exponential

   class Target:
       ...
       @retry(reraise=True, wait=wait_exponential(), stop=stop_after_attempt(3))
       def ping(self, **kwargs: Any) -> Result:
           """Ping the node from the local system in a cross-platform manner."""
           flag = "-c 1" if platform.system() == "Linux" else "-n 1"
           return self.local(f"ping {flag} {self.host}", **kwargs)

We can additionally list a test twice when modifying the items
collection, as implemented in the criteria proof-of-concept. However,
given the above abilities, this may not be desired.

How are tests executed in parallel?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

While our original list of goals stated that we want to run tests “in
parallel” we were not specific about what was meant, and the topic of
parallelism and concurrency is understandably complex. We certainly
don’t mean running two tests at once on the same target, as this would
undoubtedly lead to flaky tests.

Assuming that we care about a set of tests passing on a particular
image and size combination, but not necessarily on a particular
deployed instance, then we can run tests concurrently by deploying
multiple “identical” targets and splitting the tests across them. The
tests would still run in isolation on each target. This sounds hard,
but actually it’s practically free with Pytest via `pytest-xdist`_.

.. _pytest-xdist: https://github.com/pytest-dev/pytest-xdist

The default `pytest-xdist`_ implementation simply takes the list of
tests and runs them in a round-robin fashion with the desired number
of executors. We’ve talked at length about being able to schedule
groups of tests to run in particular executors and using particular
targets. While there are many paths open to us, this plugin actually
provides a hook, `pytest_xdist_make_scheduler
<https://github.com/pytest-dev/pytest-xdist/blob/master/OVERVIEW.md>`_
that exists specifically to “implement custom tests distribution
logic.” We used this to create the :py:class:`~lisa.LISAScheduling`
custom scheduler.

Figuring out the requirements of our test scheduler and designing the
best algorithm will require further discussion and design review. For
the purposes of moving forward, we are not blocked, as the eventual
implementation can be dropped in-place with minimal effort.

What are the user modes?
~~~~~~~~~~~~~~~~~~~~~~~~

Because Pytest is incredibly `customizable`_, we may want to provide a
few sets of reasonable default configurations for some common
scenarios. We should add a flag like
``--lisa-mode=[dev,debug,ci,demo]`` to change the default options and
output of Pytest. Doing so is readily supported by Pytest via the
`pytest_addoption`_ and `pytest_configure`_ hooks. We call these the
provided “user modes.” Note that by “output” we mean not just logging
(because that implies the Python ``logger`` module, which Pytest
allows full control over) but also commands’ ``stdout`` and ``stderr``
as well as Pytest-provided information.

As the current implementation stands, we just have sane defaults in
our repository’s ``pytest.ini``, and users who install and use our
plugins or tests can edit their own ``pytests.ini``

.. _customizable: https://docs.pytest.org/en/stable/customize.html
.. _pytest_addoption: https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_addoption
.. _pytest_configure: https://docs.pytest.org/en/latest/reference.html#pytest.hookspec.pytest_configure

- The dev(eloper) mode is intended for use by test developers while
  writing a new test. It is verbose, caches the deployed VMs between
  runs, and generates a digestible `HTML report`_ report.

- The debug mode is like dev mode but with all possible information
  shown, and will open the Python debugger automatically on failures
  (which is provided by Pytest with the ``--pdb`` flag).

- The CI mode will be fairly quiet on the console, showing all test
  results, but putting the full info output into the generated report
  file (HTML for sharing with humans and `JUnit
  <https://docs.pytest.org/en/stable/_modules/_pytest/junitxml.html>`_
  for the associated CI environment, which presents as native test
  results).

- The demo mode will show the “executive summary” (a lot like CI, but
  finely tuned for demos).

pytest-playbook
---------------

This plugin is simple, but exciting. The module :py:mod:`playbook`
defines a hook :py:meth:`playbook.Hooks.pytest_playbook_schema` which
other plugins (as discussed above) can use to add schemata to the
final playbook. In :py:meth:`playbook.pytest_configure`, all the
schemata are gathered and then the file given by ``--playbook=<FILE>``
is read, validated, and made available at :py:data:`playbook.data`. It
uses the `PyYAML <https://pyyaml.org/wiki/PyYAMLDocumentation>`_
library, but can be extended to support other formats. Also “YAML
Schema” section in :doc:`contributing guidelines <CONTRIBUTING>` on
how to generate the `JSON Schema <https://json-schema.org/>`_ for use
with editors or for manual review.

This is leveraging Pytest’s existing parameterization technology to
achieve one of our “test entrance” goals of requesting environments
with a YAML playbook, and one of our “test parameter validation” goals
of validating platforms before executing tests so that we can fail
fast if a target has insufficient information to be setup. Parsing the
same parameters from a CLI can also be implemented.

What does the “flow” of Pytest look like?
-----------------------------------------

This is best described in Pythonic pseudo-code, where the context
manager encapsulates each scope and the for loop encapsulates
processing:

.. code:: python

   pool_fixture: a session-scoped context manager
   target_fixture: a function-scoped context manager
   items: a collection of tests
   targets: a collection of targets
   criteria: a collection of test selection criteria

   def pytest_addoption(parser):
       """Add CLI options etc."""
       parser.addoption("--playbook", type=Path)

   pytest_addoption(parser) # Pytest fills in parser.

   def pytest_configure(config):
       """Setup the run's configuration."""
       targets = playbook.get_targets()
       criteria = playbook.get_criteria()

   pytest_configure(config) # Pytest fills in config.

   # pytest_generate_tests(metafunc) does this:
   for test_metafunc in metafuncs:
       for target in targets:
           # items is tests * targets in size
           items.append(test_metafunc[target])

   # pytest_collection_modifyitems(session, config, items) does this:
   for test in items:
       validate(test)
       include_or_exclude(test, criteria)

   # finally, each executor/session does this:
   session_items = items.split() # based on scheduler algorithm
   with pool_fixture as pool:
       # the fixture has setup a pool to track the deployed targets
       for test_function in session_items:
           with target_fixture as target:
               # the fixture has found or deployed an appropriate target
               test_function(target)

What Else?
----------

There’s still a lot more to think about and design. A non-exhaustive
list of future topics (some touched on above):

- Terminology table
- Tests inventory (generating statistics from metadata)
- Environment / multiple targets class design
- Feature/requirement requests (NICs in particular)
- Custom test scheduler algorithm
- Secret management

What alternatives were tried?
-----------------------------

These are notes from things tried that did not work out, and why.

Writing Another Framework
~~~~~~~~~~~~~~~~~~~~~~~~~

The author believes the above set of technical specifications clearly
describes how we can leverage Pytest for our needs. Furthermore, the
existing implementation proves this is a viable option. Therefore he
does not think we should write and maintain a *new* Python testing
framework. We should avoid falling for “not invented here” syndrome.
The alternative prototype which implements a whole new testing
framework required over five thousand lines of code, and the
Pytest-based prototype used less than two hundred (now barely six
hundred as a full fledged implementation with three separate Pytest
plugins, even after extensive feature additions and refactors), or
less than three percent.

We do not want to take on the maintenance cost of yet another
framework, the maintenance cost of LISAv2 already caused this mess in
the first place. The work of prototyping said new framework was
valuable, as it provided insight into the eventual technical design of
LISAv3, as laid out in this document.

Using Remote Capabilities of ``pytest-xdist``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

With the `pytest-xdist <https://github.com/pytest-dev/pytest-xdist>`_
plugin there already exists support for running a folder of tests on an
arbitrary remote host via SSH.

The LISA tests could be written as Python code suitable for running on
the target test system, which means direct access to the system in the
test code itself (subprocesses are still available, without having to
use SSH within the test, but would become far less necessary), something
that is not possible with any current prototype. Where the
``pytest-xdist`` plugin copies the package of code to the target node
and runs it, the pytest-lisa plugin could instantiate that node (boot
the necessary image on a remote machine or launch a new Hyper-V or Azure
VM, etc.) for the tests.

However, this use of pytest-dist requires full Python support on the
target machines, and drastically changes how developers write tests.
Furthermore, it would not support running local commands against the
remote node (like ping) or running the test across a reboot of the node.
Thus we do not want to use this functionality of ``pytest-xdist``. That
said, ``pytest-xdist`` will still be useful for running tests
concurrently, as described above.

Using Paramiko Instead of Fabric
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Paramiko library is less complex (smaller library footprint) than
Fabric, as the latter wraps the former, but it is a bit more difficult
to use, and doesn’t support reading existing SSH config files, nor does
it support “ProxyJump” which we use heavily. Fabric instead provides a
clean high-level interface for existing shell commands, handling all the
connection abstractions for us.

Using Paramiko looked like this:

.. code:: python

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

It is more verbose than necessary when compared to Fabric.

StringIO
~~~~~~~~

For ``Node.cat()`` it would seem we could use ``StringIO`` like so:

.. code:: python

   from io import StringIO

   with StringIO() as result:
       node.get("state.txt", result)
       assert result.getvalue().strip() == "TestCompleted"

However, the data returned by Paramiko is in bytes, which in Python 3
are not equivalent to strings, hence the existing implementation which
uses ``BytesIO`` and decodes the bytes to a string.
