# Contributing Guidelines

This document describes the existing developer tooling we have in place (and what to
expect of it), as well as our design and development philosophy.

## Naming Conventions

Naming conventions are not automatically enforced, so please read the [naming
conventions](https://www.python.org/dev/peps/pep-0008/#naming-conventions)
section of PEP 8, which describes what each of the different styles means. A
short summary of the most important parts:

* Modules (and hence files) should have short, all-lowercase names.
* Class (and exception) names should normally use the `CapWords` convention
  (also known as `CamelCase`).
* Function and variable names should be lowercase, with words separated by
  underscores as necessary to improve readability (also known as `snake_case`).
* To avoid collisions with the standard library, an underscore can be appended,
  such as `id_`.
* Always use `self` for the first argument to instance methods.
* Always use `cls` for the first argument to class methods.
* Use one leading underscore only for non-public methods and instance variables,
  such as `_data`. Do not activate name mangling with `__` unless necessary.
* If there is a pair of `get_x` and `set_x` methods, they should instead be a
  proper property, which is easy to do with the built-in `@property` decorator.
* Constants should be `CAPITALIZED_SNAKE_CASE`.
* When importing a function, try to avoid renaming it with `import as` because
  it introduces cognitive overhead to track yet another name.
* When deriving another module’s class (such as `unittest.TestCase`), reuse the
  class name to avoid confusion, such as `LisaTestCase`, instead of introducing
  a different connotation like `TestSuite`.

When in doubt, adhere to existing conventions, or check the style guide.

## Automated Tooling

If you have ran pytest-lisa already, then you have installed and used the `poetry`
tool. [Poetry][] is a [PEP 518][] compliant and cross-platform build system
which handles our Python dependencies and environment.

This project’s dependencies are found in the [`pyproject.toml`](pyproject.toml)
file. This is similar to but more powerful than the familiar `requirements.txt`.
With [PEP 518][] and [PEP 621][].

[Poetry]: https://python-poetry.org/docs/
[PEP 518]: https://www.python.org/dev/peps/pep-0518/
[PEP 621]: https://www.python.org/dev/peps/pep-0621/

### Metadata

The first section, `tool.poetry`, defines the project’s metadata (name, version,
description, authors, and license) which will be embedded in the final built
package.

The chosen version follows [Semantic Versioning][], with the [Python specific
pre-release versioning suffix][pre-release] ‘.dev1’. Since this is “pytest-lisa” it
seemed appropriate to set our version to ‘3.0.0.dev1’, that is, “the first
development release of pytest-lisa.”

[Semantic Versioning]: https://semver.org/
[pre-release]: https://packaging.python.org/guides/distributing-packages-using-setuptools/#choosing-a-versioning-scheme

### Package Dependencies

The next section, `tool.poetry.dependencies`, is where `poetry add
<package_name>` records our required packages.

Poetry automatically creates and manages [isolated
environments](https://python-poetry.org/docs/managing-environments/).

From the documentation:

> Poetry will first check if it’s currently running inside a virtual
> environment. If it is, it will use it directly without creating a new one. But
> if it’s not, it will use one that it has already created or create a brand new
> one for you.

On Linux, your initial run of `poetry install` will cause Poetry to
automatically setup a new [virtualenv][] using [pyenv][]. If you are developing
on Windows, you will want to setup your own, perhaps using [Conda][].

[virtualenv]: https://docs.python-guide.org/dev/virtualenvs/
[pyenv]: https://github.com/pyenv/pyenv
[Conda]: https://docs.conda.io/en/latest/

* python: We pinned Python to version 3.8 so everyone uses the same version.

### Developer Dependencies

Similar to the previous section, `tool.poetry.dev-dependencies` is where `poetry
add --dev <package_name>` records our _developer_ packages. These are not
necessary for LISAv3 to execute, but are used by developers to automatically
adhere to our coding standards.

* [Black](https://github.com/psf/black), the opinionated code formatter which
  settles all debates as to how our Python files should be formatted. It follows
  [PEP 8](https://www.python.org/dev/peps/pep-0008/), the official Python style
  guide, and where ambiguous makes the decision for us.

* [Flake8](https://flake8.pycqa.org/en/latest/) (and integrations), the semantic
  analyzer, used to coordinate most of the other tools.

* [isort](https://timothycrosley.github.io/isort/), the `import` sorter, which
  automatically splits imports into the expected, alphabetized sections.

* [mypy](http://mypy-lang.org/), the static type checker, which coupled with
  type annotations allows us to avoid the pitfalls of Python being a dynamically
  typed language.

* [python-language-server](https://github.com/palantir/python-language-server)
  (and integrations), the de facto LSP server. While Microsoft is developing
  their own LSP servers, they do not integrate with the existing ecosystem of
  tools, and their latest tool, Pyright, simply does not support
  `pyproject.toml`. Since pyls is used far more widely, and supports every
  editor, we use it.

* [rope](https://github.com/python-rope/rope), to provide completions and
  renaming support to pyls.

With these packages installed and a correctly setup editor (see the readme and
feel free to reach out to us), your code should automatically follow all the
standards which we could automate.

The final sections, `tool.black`, `tool.isort`, `build-system`, and the
`.flake8` file (Flake8 does not yet support `pyproject.toml`) configure the
tools per their recommendations.

## Type Annotations

We are using [mypy][] to enforce static type checking of our Python code. This
may surprise you as Python is not a statically typed language. While dynamic
typing can be useful, for a complex tool such as LISA it is more likely to
introduce bugs that are found only at runtime (which the user experiences as a
crash). For more information on why we (and others) do this, see [Dropbox’s
journey to type checking 4 million lines of Python][dropbox]. [PEP 484][] and
[PEP 526][] (among others) introduced and defined [type hints][] for the Python
language. You can probably figuring out the syntax based on the surrounding
code, but you can also see this [Intro to Using Python Type Hints][intro] and
mypy’s [cheat sheet][].

[mypy]: http://mypy-lang.org/
[dropbox]: https://dropbox.tech/application/our-journey-to-type-checking-4-million-lines-of-python
[PEP 484]: https://www.python.org/dev/peps/pep-0484/
[PEP 526]: https://www.python.org/dev/peps/pep-0526/
[type hints]: https://docs.python.org/3/library/typing.html
[intro]: https://kishstats.com/python/2019/01/07/python-type-hinting.html
[cheat sheet]: https://mypy.readthedocs.io/en/latest/cheat_sheet_py3.html

## Runbook schema

Some plugins like Platform need follow this section to extend runbook schema. Runbook is the configurations of LISA runs. Every LISA run need a runbook.

The runbook uses [dataclass](https://docs.python.org/3/library/dataclasses.html) to define, [dataclass-json](https://github.com/lidatong/dataclasses-json/) to deserialize, and [marshmallow](https://marshmallow.readthedocs.io/en/3.0/api_reference.html) to validate the schema.

See more examples in [schema.py](lisa/schema.py), if you need to extend runbook schema.

## Committing Guidelines

A best practice when using [Git](https://git-scm.com/book/en/v2) is to create a
series of independent and well-documented commits. Each commit should “do one
thing” and do it correctly. If a mistake is made (you need to fix a bug or
adjust formatting), you should amend it (or use an [interactive
rebase](https://thoughtbot.com/blog/git-interactive-rebase-squash-amend-rewriting-history)
to edit it). If you’re using Emacs, the [Magit](https://magit.vc/) package makes
all of this easy. Some of the reasons for making each commit polished is that it
aids immensely in future debugging. It lets us use tools like [`git
bisect`](https://git-scm.com/docs/git-bisect) to automatically find bugs, and
understand why prior code was written. Although some of it has gone out of date,
see this otherwise great essay on [Git best
practices](http://sethrobertson.github.io/GitBestPractices/). For how Git works,
read [Git from the Bottom
Up](https://jwiegley.github.io/git-from-the-bottom-up/).

For writing your commit messages, see this modification of [Tim Pope’s
example](https://tbaggery.com/2008/04/19/a-note-about-git-commit-messages.html):

> Capitalized, short (72 chars or less) summary
>
> More detailed explanatory text, if necessary. Wrap it to about 72
> characters or so. In some contexts, the first line is treated as the
> subject of an email and the rest of the text as the body. The blank line
> separating the summary from the body is critical (unless you omit the
> body entirely); tools like rebase can get confused if you run the two
> together.
>
> Write your commit message in the imperative: “Fix bug” and not “Fixed
> bug” or “Fixes bug.” This convention matches up with commit messages
> generated by commands like git merge and git revert.
>
> Further paragraphs come after blank lines.
>
> * Bullet points are okay, too
>
> * Typically a hyphen or asterisk is used for the bullet, followed by a
>   single space, with blank lines in between, but conventions vary here
>
> * Use a hanging indent

You should also feel free to use Markdown in the commit messages, as our project
is hosted on GitHub which renders it (and Markdown is human readable).

## Design Patterns

The most important goal we are attempting to accomplish with LISAv3 is for it to
be “simple, clean, and with a low maintenance cost.”

We should use caution when using Object Oriented Design, because when it is used
without critical analysis, it creates unmaintainable code. A great talk on this
subject is [Stop Writing Classes](https://www.youtube.com/watch?v=o9pEzgHorH0),
by Jack Diederich. As he says, “classes are great but they are also overused.”

This [Python Design Patterns](https://python-patterns.guide/) is a fantastic
collection of material for writing maintainable Python code. It specifically
details many of the common “Object Oriented” patterns from the Gang of Four book
(which, in fact, were patterns geared toward languages like C++, and no longer
apply to modern languages like Python), what lessons can be learned from them,
and how to apply them (or their modern alternatives) today. It also serves as an
easy-to-read guide to the Gang of Four book itself, as its principles still
serve us well today.

Every time a developer chooses to use a design pattern, that person needs to
reason through and document why it was chosen, and what alternatives were
considered. We will recreate the problems with LISAv2 unless we take our time to
carefully create a well-designed and maintainable framework.

Several popular patterns that actually _do not_ work well in Python are:

* [The Abstract Factory Pattern](https://python-patterns.guide/gang-of-four/abstract-factory/)
* [The Factory Method Pattern](https://python-patterns.guide/gang-of-four/factory-method/)
* [The Prototype Pattern](https://python-patterns.guide/gang-of-four/prototype/)
* [The Singleton Pattern](https://python-patterns.guide/gang-of-four/singleton/)

Conversely, patterns that are a natural fit to Python include:

* [The Composite Pattern](https://python-patterns.guide/gang-of-four/composite/)
* [The Iterator Pattern](https://python-patterns.guide/gang-of-four/iterator/)
  (caution: it is actually better to implement these with `yield`!)

Finally, a high-level guide to all things Python is [The Hitchhiker’s Guide to
Python](https://docs.python-guide.org/). It covers just about everything in the
Python world. If you make it through even some of these guides, you will be well
on your way to being a “Pythonista” (a Python developer) writing “Pythonic”
(canonically correct Python) code left and right.

### Async IO

With Python 3.4, the Async IO pattern found in languages such as C# and Go is
available through the keywords `async` and `await`, along with the Python module
`asyncio`. Please read [Async IO in Python: A Complete
Walkthrough](https://realpython.com/async-io-python/) to understand at a high
level how asynchronous programming works. As of Python 3.7, One major “gotcha”
is that `asyncio.run(...)` should be used [exactly once in
`main`](https://docs.python.org/3/library/asyncio-task.html), it starts the
event loop. Everything else should be a coroutine or task which the event loop
schedules.

## Future Sections

Just a collection of reminders for the author to expand on later.

* [unittest](https://docs.python.org/3/library/unittest.html)
* [doctest](https://docs.python.org/3/library/doctest.html)
* [subprocess](https://pymotw.com/3/subprocess/index.html)
* [GitHub Actions](https://github.com/LIS/LISAv2/actions)
* [ShellCheck](https://www.shellcheck.net/)
* [Governance](https://opensource.guide/leadership-and-governance/)
* [Maintenance Cost](https://web.archive.org/web/20120313070806/http://users.jyu.fi/~koskinen/smcosts.htm)
* Parallelism and multi-plexing
* Versioned inputs and outputs
