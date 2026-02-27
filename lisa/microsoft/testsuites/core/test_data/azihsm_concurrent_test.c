/*
 * Azure Integrated HSM Concurrent Access Test
 * Copyright (c) Microsoft Corporation.
 * Licensed under the MIT license.
 */

#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/wait.h>
#include <errno.h>
#include <string.h>

int child_test_process(int child_id, const char* device) {
    printf("Child %d: Testing %s\n", child_id, device);
    
    for (int i = 0; i < 5; i++) {
        int fd = open(device, O_RDWR);
        if (fd < 0) {
            printf("Child %d: Failed to open %s (attempt %d): %s\n", 
                   child_id, device, i+1, strerror(errno));
            usleep(100000); // 100ms
            continue;
        }
        
        printf("Child %d: Opened %s successfully (attempt %d)\n", child_id, device, i+1);
        usleep(200000); // Hold open for 200ms
        close(fd);
        usleep(100000); // 100ms between attempts
    }
    
    printf("Child %d: Completed tests\n", child_id);
    return 0;
}

int main() {
    printf("AziHSM Concurrent Access Test\n");
    printf("=============================\n");
    
    // Find HSM device
    FILE* fp = popen("ls /dev/azihsm[0-9]* 2>/dev/null | head -1", "r");
    if (!fp) {
        printf("Failed to find HSM device\n");
        return 1;
    }
    
    char test_device[256];
    if (!fgets(test_device, sizeof(test_device), fp)) {
        printf("No HSM device found\n");
        pclose(fp);
        return 1;
    }
    pclose(fp);
    
    // Remove newline
    test_device[strcspn(test_device, "\n")] = 0;
    
    // Check if device exists
    if (access(test_device, F_OK) != 0) {
        printf("Device %s not accessible\n", test_device);
        return 1;
    }
    
    printf("Testing concurrent access to: %s\n", test_device);
    
    // Fork multiple child processes
    int num_children = 3;
    pid_t children[num_children];
    
    printf("Starting %d concurrent test processes...\n", num_children);
    
    for (int i = 0; i < num_children; i++) {
        children[i] = fork();
        if (children[i] == 0) {
            // Child process
            exit(child_test_process(i + 1, test_device));
        } else if (children[i] < 0) {
            printf("❌ Failed to fork child %d\n", i + 1);
            return 1;
        }
    }
    
    // Wait for all children
    int failed = 0;
    for (int i = 0; i < num_children; i++) {
        int status;
        waitpid(children[i], &status, 0);
        if (WEXITSTATUS(status) != 0) {
            failed++;
        }
    }
    
    printf("\n📊 Concurrent test results: %d/%d processes succeeded\n", 
           num_children - failed, num_children);
    
    return failed == 0 ? 0 : 1;
}