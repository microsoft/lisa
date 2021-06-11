# Understand test results

## Understand log messages

The log meesages display progress, and provide information for troubleshooting
at a range of levels. In LISA, there are four levels of log messages shown as
following, ranking from the least to the most severe.

- **DEBUG** level log messages provide operational details for step-by-step
  debugging.

  The DEBUG messages are information mainly for developers to see what is going
  on inside programs, typically of interest only when diagnosing problems.

- **INFO** level log messages illustrate what happened.

  Even if the whole process goes smoothly, this is what you want to know every
  time. You can know what is going on through this level of messages. You will
  be notified of such INFO log messages to wait before performing a long
  operation. They work as confirmations that everything is working as expected.

- **WARNING** level log messages signify operations that should be avoided.

  The WARNING log messages indicate that there are important, but not fatal
  unexpectations happening while running. However, in most cases, it is more
  likely to find only INFO level log messages which are important to know, or
  ERROR level log messages that terminates the program.

- **ERROR** level log messages should be reviewed carefully.

  Error level logs messages are more serious than WARNING and they usually mean
  that some functions are not able to run. Though, according to exprience, 95%
  of successful runs should not contain any error level log messages.
  nevertheless, in the remaining 5% runs, they can help identify potential
  problems.

## Troubleshoot failure

Test failures are common. You can turn to the information below for a better
understanding:

1. Catch the one-line message that throws an exception and trace back.

2. Read all log messages on console in the failed run. 

3. Find extra log messages that are saved into test result files. 
