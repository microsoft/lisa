Coding guidelines
=================

-  `Naming Conventions <#naming-conventions>`__
-  `Test code excellence <#test-code-excellence>`__
-  `Code comments <#code-comments>`__
-  `Commit messages <#commit-messages>`__
-  `Logging <#logging>`__
-  `Error message <#error-message>`__
-  `Assertion <#assertion>`__
-  `Troubleshooting excellence <#troubleshooting-excellence>`__
-  `Document excellence <#document-excellence>`__
-  `Tips for writing code <#tips-for-writing-code>`__
-  `Tips for non-native English speakers by non-native English
   speakers <#tips-for-non-native-english-speakers-by-non-native-english-speakers>`__

Naming Conventions
------------------

Please read the `naming
conventions <https://www.python.org/dev/peps/pep-0008/#naming-conventions>`__
section of PEP 8, which explains the meaning of each of the styles. A
brief overview of the most important parts:

-  Modules (and files) should use lowercase short names.
-  Class (and exception) names should use the ``CapWords`` convention
   (also known as ``CamelCase``)
-  Function and variable names should use lowercase letters, and words
   should be separated by underscores to improve readability (also
   called ``snake_case``).
-  To avoid conflicts with the standard library, you can add an
   underscore, such as ``id_``.
-  Leading lines such as ``_data`` apply to non-public methods and
   instance variables. Subclasses can use it. If you don't use it in a
   subclass, use it like ``__data`` in a superclass.
-  If there is a pair of ``get_x`` and ``set_x`` methods without
   additional parameters, please use the built-in ``@property``
   decorator to convert them to properties.
-  Constants should be similar to ``CAPITALIZED_SNAKE_CASE``.
-  When importing a function, try to avoid renaming it with
   ``import as`` because it introduces cognitive overhead to keep track
   of another name. If the name conflicts, please use the package name
   as the namespace, such as ``import   schema``, and use it as
   ``schema.Node``.

If in doubt, follow existing conventions or check the style guide.

Test code excellence
--------------------

Your code would be an example for others, and they might follow your
approach. Therefore, both good and bad practices will be amplified.

In LISA, test code should be organized according to business logic,
which means that the code should perform the purpose of the test like a
test specification. The underlying logic should be implemented
elsewhere, such as tools, functions, or private methods in test suites.

An example: Be careful when using ``sleep``! The only way to use sleep
is in polling mode. This means that you must wait for something with
regular inspections. In the inspection cycle, you can wait for a
reasonable period. Don't wait for 10 seconds of sleep. This causes two
problems, 1) if it is too short, the case may fail; 2) if it is long
enough, it will slow down the running speed.

Please keep in mind that your code may be referred to by others.

Code comments
-------------

How to write good code comments is a hot topic, and many best practices
are also valuable. Here are some highlights.

-  Do not repeat the code logic. Code comments are always in the same
   place as the code, which is different from metadata. Do not repeat
   ``if/else`` statement like “if … else …”, do not repeat the content
   that already exists in the log string and exception message, do not
   repeat what can be clearly seen from the variable name.
-  Record business logic. Code logic is more detailed than business
   logic. Some complex code logic may not be intuitive for understanding
   business logic. Code comments can help summarize complex code logic.
-  Record trick things. We cannot avoid writing tricky code. For
   example, magic numbers, special handling of the Linux version, or
   other content.
-  Provide regular expression examples. LISA uses many regular
   expressions to parse command output. It is simple and useful, but it
   may not match. When you need to create or update a regular
   expression, it needs to check the sample for regression. These
   examples also help to understand what the expression does.

Commit messages
---------------

The commit message is used to explain why this change was made. The code
comments describe the current state. The commit message describes the
reason for the change. If you think the content is also suitable for
writing in the code, please write it as a code comment.

Logging
-------

The log has two purposes, 1) display progress, and 2) troubleshoot.

To show progress, the log should be simple and logical. To troubleshoot,
it requires more detailed information. These two goals sound
contradictory, but they can be achieved through different INFO and DEBUG
levels. LISA always enables the DEBUG level in the log file, while the
INFO level is the default setting on the console.

In LISA, when writing log lines in the code, it's recommended to
consider what the test runner needs to know, instead of what the
developer needs to know, which should be done in code comments.

-  **DEBUG** level log should provide the *correct level* detail. The
   only way to write at the “correct level” is to use it from the
   beginning.

   When writing code, please keep using and improving the log. If you
   need to debug step by step, it means you need to improve the log. If
   you don't understand the meaning of the log, others may not as well,
   so please optimize the log at DEBUG level. In addition, if you find
   duplicate information, please merge it.

-  **INFO** level log should be *like a story*, to illustrate what
   happened.

   Even if the whole process goes smoothly, this is what you want to
   know every time. It should be friendly so that new users can
   understand what is going on. It should be as little as possible. It
   should tell the user to wait before performing a long operation.

-  **WARNING** level logs should be avoided.

   The warning message indicates that it is important, but there is no
   need to stop. But in most cases, you will find that it is either not
   as important as the information level, or it is so important to stop
   running.

   At the time of writing, there are 3 warning messages in LISA. After
   review, I converted them all into information or error level. There
   is only one left, and it is up to the user to suppress errors.

-  **ERROR** level log should be reviewed carefully.

   Error level logs can help identify potential problems. If there are
   too many error level logs, it will hide the actual problem. When it
   goes smoothly, there should be no error level logs. According to
   experience, 95% of successful runs should not contain any error level
   logs.

Some tips:

-  By reading the log, you should be able to understand the progress
   without having to look at the code. And logs describe business logic,
   not code logic. A bad example, “4 items found: [a , b , c]”, should
   be “found 4 channels, unique names: [a, b, c]”.
-  Make each log line unique in the code. If you must check where the
   log is printed in the code. We can quickly find the code by
   searching. A bad example, ``log.info("received stop signal")``,
   should be ``log.info("received stop signal   in lisa_runner")``.
-  Do not repeat similar lines in succession. It is worth adding logic
   and variables to reduce redundant logs.
-  Reduce log lines. If two lines of logs always appear together, merge
   them into one line. The impact of log lines on readability is much
   greater than the length of the log.
-  Associate related logs through shared context. In the case of
   concurrency, this is very important. A bad example, “cmd: echo hello
   world”, “cmd: hello world” can be “cmd[666]: echo hello world”,
   “cmd[666]: hello world”.

Error message
-------------

There are two kinds of error messages in LISA. The first is an error
message, and it does not fail. It will be printed as stderr and will be
more obvious when the test case fails. The second is a one-line message
in the failed test case. This section applies to two of them, but the
second one is more important because we want it to be the only
information that helps understand the failed test case.

In LISA, failed, skipped, and some passed test cases have a message. It
specifies the reason the test case failed or skipped. Through this
message, the user can understand what will happen and can act.
Therefore, this message should be as helpful as possible.

The error message should include what happened and how to resolve it. It
may not be easy to provide all the information for the first time, but
guesswork is also helpful. At the same time, the original error message
is also useful, please don't hide it.

For examples,

-  “The subscription ID [aaa] could not be found, please make sure it
   exists and is accessible by the current account”. A bad example, “The
   subscription ID [aaa] could not be found”. This bad example
   illustrates what happened, but there is no suggestion.
-  “The vm size [aaa] could not be found on the location [bbb]. This may
   be because the virtual machine size is not available in this
   location”. A bad example, “The vm size [aaa] could not be found on
   the location [bbb]”. It explains what happened, but it does not
   provide a guess at the root cause.

Assertion
---------

Assertions are heavily used in test code. Assertions are a simple
pattern of “if some checks fail, raise an exception”.

The assertion library includes commonly used patterns and detailed error
messages. LISA uses ``assertpy`` as a standard assertion library, which
provides Pythonic and test-friendly assertions.

When writing the assertion,

-  Put the actual value in ``assert_that`` to keep the style consistent,
   and you can compare it with multiple expected values continuously.
-  Assertions should be as comprehensive as possible, but do not repeat
   existing checks. For example,
   ``assert_that(str1).is_equal_to('hello')`` is enough, no need like
   ``assert_that(str1).is_instance_of(str).is_equal_to('hello')``.
-  Add a description to explain the business logic. If a malfunction
   occurs, these instructions will be displayed. For example,
   ``assert_that(str1).described_as('echo back result is   unexpected').is_equal_to('hello')``
   is better than ``assert_that(str1).is_equal_to('hello')``.
-  Try to use native assertions instead of manipulating the data
   yourself. ``assert_that(vmbuses).is_length(6)`` is better than
   ``assert_that(len(vmbuses)).is_equal_to(6)``. It is simpler and the
   error message is clearer.
-  Don't forget to use powerful collection assertions. They can compare
   ordered list by ``contains`` (actual value is superset),
   ``is_subset_of`` (actual value is subset), and others.

Learn more from `examples
<https://github.com/microsoft/lisa/tree/main/examples/testsuites>`__ and
`assertpy document <https://github.com/assertpy/assertpy#readme>`__.

Troubleshooting excellence
--------------------------

Test failure is a common phenomenon. Therefore, perform troubleshooting
frequently. There are some useful ways to troubleshoot failures. In the
list below, the higher items are better than the lower items because of
its lower cost of analysis.

1. Single line message. A one-line message is sent with the test result
   status. If this message clearly describes the root cause, no other
   digging is necessary. You can even perform some automated actions to
   match messages and act.
2. Test case log. LISA provides a complete log for each run, which
   includes the output of all test cases, all threads, and all nodes.
   This file can be regarded as the default log, which is easy to
   search.
3. Other log files. Some original logs may be divided into test cases.
   After finding out the cause, it is easier to find out. But it needs
   to download and browse the test result files.
4. Reproduce in the environment. It is costly but contains most of the
   original information. But sometimes, the problem cannot be
   reproduced.

In LISA, test cases fail due to exceptions, and exception messages are
treated as single-line messages. When writing test cases, it's time to
adjust the exception message. Therefore, after completing the test case,
many errors will be explained well.

Document excellence
-------------------

The documentation is the opportunity to make things clear and easy to
maintain. A longer document is not always a better document. Each kind
of documentation has its own purpose. Good technical documentation
should be *useful and accurate*.

Tips for writing code
--------------------------

f-strings is brought since Python 3.6, f-strings are string literals that have an f at
the beginning and curly braces containing expressions that will be replaced with their
values. f-strings are a great new way to format strings. Not only are they
more readable, more concise, and less prone to error than other ways of formatting, but
they are also faster.

``print(f"Hello, {name}. You are {age}.")``

Learn more from `f-strings document <https://docs.python.org/3/reference/lexical_analysis.html#f-strings>`__.

Tips for non-native English speakers by non-native English speakers
-------------------------------------------------------------------

Today, there are a lot of great tools to help you create high-quality
English documents. If writing in English is challenging, please try the
following steps:

1. Read our documentations.
2. Write in your language first.
3. Use machine translation such as `Microsoft
   Translator <https://www.bing.com/translator/>`__ and `Google
   translate <https://translate.google.com/>`__ to convert it to
   English.
4. Convert the English version back to your language and check. If it
   doesn't make sense after translating back, it means the sentence is
   too complicated. Make it simpler, and then start from step 1 again.
5. Once satisfied, you can use `Microsoft
   Editor <https://www.microsoft.com/en-us/microsoft-365/microsoft-editor>`__
   to further refine the grammar and wordings.
