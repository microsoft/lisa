// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.
//
// Test program for SCHED_CORE (Core Scheduling) prctl interface.
// Creates a core scheduling group and verifies a valid cookie is assigned.

#include <stdio.h>
#include <sys/prctl.h>
#include <errno.h>
#include <string.h>

#ifndef PR_SCHED_CORE
#define PR_SCHED_CORE           62
#define PR_SCHED_CORE_GET       0
#define PR_SCHED_CORE_CREATE    1
#define PR_SCHED_CORE_SCOPE_THREAD 0
#endif

int main(void) {
    unsigned long cookie = 0;
    int ret;

    ret = prctl(PR_SCHED_CORE, PR_SCHED_CORE_CREATE,
                0, PR_SCHED_CORE_SCOPE_THREAD, 0);
    if (ret != 0) {
        fprintf(stderr, "CREATE failed: %s\n", strerror(errno));
        return 1;
    }

    ret = prctl(PR_SCHED_CORE, PR_SCHED_CORE_GET,
                0, PR_SCHED_CORE_SCOPE_THREAD, &cookie);
    if (ret != 0) {
        fprintf(stderr, "GET failed: %s\n", strerror(errno));
        return 1;
    }

    if (cookie == 0) {
        fprintf(stderr, "Cookie is 0 after CREATE\n");
        return 1;
    }

    printf("SCHED_CORE OK: cookie=0x%lx\n", cookie);
    return 0;
}
