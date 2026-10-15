#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static int write_start_time(const struct timespec *start_time)
{
    char timestamp[64];
    char timezone[8];
    struct tm local_now;

    if (localtime_r(&start_time->tv_sec, &local_now) == NULL ||
        strftime(timestamp, sizeof(timestamp), "%Y-%m-%dT%H:%M:%S",
                 &local_now) == 0 ||
        strftime(timezone, sizeof(timezone), "%z", &local_now) == 0) {
        return -1;
    }

    return fprintf(stdout, "Started: %s.%03ld%s\n", timestamp,
                   start_time->tv_nsec / 1000000L, timezone) < 0
               ? -1
               : fflush(stdout);
}

static int write_offset(const struct timespec *start_time)
{
    struct timespec now;
    time_t seconds;
    long nanoseconds;

    if (clock_gettime(CLOCK_MONOTONIC, &now) == -1) {
        return -1;
    }

    seconds = now.tv_sec - start_time->tv_sec;
    nanoseconds = now.tv_nsec - start_time->tv_nsec;
    if (nanoseconds < 0) {
        --seconds;
        nanoseconds += 1000000000L;
    }

    return fprintf(stdout, "[+%lld.%03lds] ", (long long)seconds,
                   nanoseconds / 1000000L) < 0
               ? -1
               : 0;
}

static int timestamp_output(int output_fd, const struct timespec *start_time)
{
    char buffer[4096];
    int at_line_start = 1;

    for (;;) {
        ssize_t bytes_read = read(output_fd, buffer, sizeof(buffer));
        ssize_t index;

        if (bytes_read == -1) {
            if (errno == EINTR) {
                continue;
            }
            perror("read");
            return -1;
        }
        if (bytes_read == 0) {
            break;
        }

        for (index = 0; index < bytes_read; ++index) {
            if (at_line_start) {
                if (write_offset(start_time) == -1) {
                    return -1;
                }
                at_line_start = 0;
            }
            if (fputc((unsigned char)buffer[index], stdout) == EOF) {
                return -1;
            }
            if (buffer[index] == '\n') {
                at_line_start = 1;
                if (fflush(stdout) == EOF) {
                    return -1;
                }
            }
        }
    }

    return fflush(stdout) == EOF ? -1 : 0;
}

int main(int argc, char *argv[])
{
    int output_pipe[2];
    int output_status;
    int wait_status;
    pid_t child_pid;
    struct timespec monotonic_start;
    struct timespec wall_clock_start;

    if (argc < 2) {
        fprintf(stderr, "Usage: %s PROGRAM [ARG ...]\n", argv[0]);
        return 2;
    }

    if (pipe(output_pipe) == -1) {
        perror("pipe");
        return 1;
    }
    if (clock_gettime(CLOCK_REALTIME, &wall_clock_start) == -1 ||
        clock_gettime(CLOCK_MONOTONIC, &monotonic_start) == -1 ||
        write_start_time(&wall_clock_start) == -1) {
        perror("start time");
        close(output_pipe[0]);
        close(output_pipe[1]);
        return 1;
    }

    child_pid = fork();
    if (child_pid == -1) {
        perror("fork");
        close(output_pipe[0]);
        close(output_pipe[1]);
        return 1;
    }

    if (child_pid == 0) {
        int exec_error;

        close(output_pipe[0]);
        if (dup2(output_pipe[1], STDOUT_FILENO) == -1 ||
            dup2(output_pipe[1], STDERR_FILENO) == -1) {
            perror("dup2");
            _exit(126);
        }
        close(output_pipe[1]);
        execvp(argv[1], &argv[1]);
        exec_error = errno;
        perror(argv[1]);
        _exit(exec_error == ENOENT ? 127 : 126);
    }

    close(output_pipe[1]);
    output_status = timestamp_output(output_pipe[0], &monotonic_start);
    close(output_pipe[0]);

    while (waitpid(child_pid, &wait_status, 0) == -1) {
        if (errno != EINTR) {
            perror("waitpid");
            return 1;
        }
    }

    if (output_status == -1) {
        perror("output");
        return 1;
    }
    if (WIFEXITED(wait_status)) {
        return WEXITSTATUS(wait_status);
    }
    if (WIFSIGNALED(wait_status)) {
        return 128 + WTERMSIG(wait_status);
    }

    return 1;
}
