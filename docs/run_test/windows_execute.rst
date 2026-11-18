Direct command execution on Windows
===================================

``WindowsExecute.verify_node_execute_on_windows`` is a small, read-only example
of using ``node.execute()`` on Windows. It verifies:

* A native executable (``whoami.exe``) runs and returns the current identity.
* Explicitly invoking ``powershell.exe`` returns the Windows platform identifier.
* ``shell=True`` uses the Windows command shell for redirection, separate
  stdout/stderr, and a nonzero exit code.

``node.execute()`` does not translate Linux commands into Windows commands.
Invoke PowerShell explicitly for cmdlets instead of assuming the default shell
is PowerShell. ``expected_exit_code=7`` in the last command deliberately checks
exit-code propagation; it does not ignore failures.
``no_error_log=True`` avoids logging the deliberately generated stderr as an
unexpected error; the case still asserts its contents and the exit code.
The PowerShell expression in this example has no spaces and needs no surrounding
quotes, avoiding differences in argument quoting between local and remote nodes.

Add this selection to a Windows runbook:

.. code-block:: yaml

   import_builtin_tests: true
   testcase:
     - criteria:
         name: ^verify_node_execute_on_windows$

This case intentionally bypasses Tools to exercise the execution API. For normal
functional cases, prefer existing Tools and keep reusable OS-specific commands
in their Windows implementations.
