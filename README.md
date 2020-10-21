# LISAv3 via pytest-lisa

[Pytest](https://docs.pytest.org/en/stable/) is an [incredibly
popular](https://docs.pytest.org/en/stable/talks.html) MIT licensed open source
Python testing framework. It has a thriving community and plugin framework, with
[over 750 plugins](https://plugincompat.herokuapp.com/). There is even a YAML
example of writing a Domain Specific Language
[DSL](https://docs.pytest.org/en/stable/example/nonpython.html#yaml-plugin) for
specifying tests. Instead of writing yet another test framework, LISAv3 could be
written as pytest-lisa, a [plugin for
Pytest](https://docs.pytest.org/en/stable/writing_plugins.html) which implements
our requirements. In fact, most of Pytest itself is implemented via [built-in
plugins](https://docs.pytest.org/en/stable/plugins.html), providing us with a
lot to leverage.

The [fundamental features](https://www.youtube.com/watch?v=CMuSn9cofbI) of
Pytest match our needs very well:

* Automatic test discovery, no boiler-plate test code
* Useful information when a test fails (assertions are introspected)
* Test parameterization
* Modular setup/teardown via fixtures
* Customizable (as detailed above)

So all the logic for discovering, running, skipping based on requirements, and
reporting the tests is already written and maintained by the greater open source
community, leaving us to focus on the hard and unique problem: creating an API
to launch the necessary nodes. It would also allow us the space to abstract the
installation of tools required by tests. In this way, LISAv3 could solve the
difficulties we have at hand without creating yet another unit test framework.

## Design

### pytest-mark

The [pytest-mark](https://docs.pytest.org/en/stable/mark.html) already provides
functionality for adding metadata to tests, where we specifically want:

* Owner
* Category
* Area
* Tags
* Priority

We could simply reuse this built-in plugin with minimal logic to enforce our
required metadata, with sane defaults (such as setting the area to the name of
the module), and to list statistics about our test coverage.

It also through pytest-mark that [skipping
functionality](https://docs.pytest.org/en/stable/skipping.html) exists, which we
would leverage for ensuring our environmental requirements are met.

Note that Pytest leverages Python’s docstrings for built-in documentation (and
can even run tests discovered in such strings, like doctest).

### Fixtures

Pytest supports [fixtures](https://docs.pytest.org/en/stable/fixture.html),
which are the primary way of setting up test requirements. They replace less
flexible alternatives like setup/teardown functions. It is through fixtures that
pytest-lisa would implement remote node setup/teardown. Our node fixture would
implement (with more as found to be required):

* Provision a node based on parameterized requirements
* Reboot the node if requested
* Run a command (perhaps asynchronously) on the node using SSH
* Download and upload files to the node (with retries and timeouts)

Our abstraction leverages
[Fabric](https://docs.fabfile.org/en/stable/index.html), which uses
[paramiko](https://docs.paramiko.org/en/stable/) underneath, directly to
implement the SSH commands. For deployment logic, it uses the [`az`
CLI](https://aka.ms/azureclidocs), wrapped by Fabric. For Hyper-V (and other
virtualization platforms), it could use
[libvirt](https://libvirt.org/python.html).

Other test specific requirements, such as installing software and daemons,
downloading files from remote storage, or checking the state of our Bash test
scripts, would similarly be implemented via fixtures and shared among tests.

### Test result output

Instead of writing our own test result output, we can leverage existing plugins.
For instance, there already exists
[pytest-azurepipelines](https://pypi.org/project/pytest-azurepipelines/) which
transforms results into the format consumed by ADO. It has over 90,000 downloads
a month. We don’t need to rewrite this.

## Alternatives considered

### Azure Python APIs instead of `az` CLI

We do not use the [Azure Python APIs](https://aka.ms/azsdk/python/all) directly
because they are more complicated (and less documented) than the `az` CLI. Given
Fabric (and its underlying Invoke library), the CLI becomes incredibly easy to
work with. The `az` CLI lead developer states that they have [feature
parity](https://stackoverflow.com/a/50005660/1028665) and that the CLI is more
straightforward to use. Considering our ease-of-maintenance requirement, this
seems the apt choice.

### pytest-xdist

With the [pytest-xdist plugin](https://github.com/pytest-dev/pytest-xdist) there
already exists support for running a folder of tests on an arbitrary remote host
via SSH.

The LISA tests could be written as Python code suitable for running on the
target test system, which means direct access to the system in the test code
itself (subprocesses are still available, without having to use SSH within the
test, but would become far less necessary), something that is not possible with
the current prototype. Where the pytest-xdist plugin copies the package of code
to the target node and runs it, the pytest-lisa plugin could instantiate that
node (boot the necessary image on a remote machine or launch a new Hyper-V or
Azure VM, etc.) for the tests. YAML playbooks (AKA “runbooks” in the current
prototype) could be interpreted by the pytest-lisa plugin to determine how to
create those nodes.

However, this is only one approach, and we may prefer to run the Python code on
the user’s machine, with pytest-lisa instead providing the previously mentioned
node fixtures, default marks, and requirements logic.

Note that pytest-dist can still be useful for locally running tests in parallel.

### Paramiko instead of Fabric

The Paramiko library is less complex (smaller library footprint) than Fabric, as
the latter wraps the former, but it is a bit more difficult to use, and doesn’t
support reading existing SSH config files, nor does it support “ProxyJump” which
we use heavily. Fabric instead provides a clean high-level interface for
existing shell commands, handling all the connection abstractions for us.

It looked a like this:

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

### Function per test instead of class

An option I explored to make an “executive summary” of the smoke test was to use
a class where each functionality was tested as individual function (meaning they
could fail independently without failing the whole smoke test), accompanied by a
class-scoped node fixture. This had its advantages, however, it was difficult to
parameterize and also overly verbose. We should instead keep each test as Pytest
intends: as a function. This allows the fixtures to be written in a simpler
manner (not rely on caching between functions) and allows parameterization using
the built-in decorator
[`@pytest.mark.parametrize`](https://docs.pytest.org/en/stable/parametrize.html).

### Tenacity _and_ pytest-rerunfailures

Due to an open
[bug](https://github.com/pytest-dev/pytest-rerunfailures/issues/51) this popular
Pytest plugin is incompatible with module/class/session fixtures. What this
means is given a class of tests with a class fixture (say a shared `Node`), if
the last test is marked as flaky and is rerun, the class fixture is unexpectedly
torn down and then the test is rerun. That is, the rerun happens too late, and
the test is then performed against a new `Node`. For this reason, to use this
plugin effectively tests would need to be contained to one function per test,
but as written above, that seems to be the best route.

However, this plugin is otherwise very useful for marking tests as flaky, and is
already integrated with pytest-html such that reruns are reported correctly in
the report.

For instances where particular parts of code are flaky and need to be rerun,
such as `ping`, we use the modern Python retry library,
[Tenacity](https://github.com/jd/tenacity), which has easy-to-use decorators to
retry functions (and context managers to use within functions), as well as good
wait and timeout support. The `ping()` function currently uses it with
exponential back-off to great effect.
