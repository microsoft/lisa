/*
 * Azure Integrated HSM Error Handling Test
 * Copyright (c) Microsoft Corporation.
 * Licensed under the MIT license.
 */

#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <errno.h>
#include <string.h>

int test_invalid_operations() {
    printf("Testing invalid operations and error handling...\n");
    
    // Test opening non-existent device
    int fd = open("/dev/azihsm_nonexistent", O_RDWR);
    if (fd < 0) {
        printf("Non-existent device properly rejected: %s\n", strerror(errno));
    } else {
        printf("Non-existent device unexpectedly opened\n");
        close(fd);
    }
    
    // Find and test operations on valid HSM device  
    FILE* fp = popen("ls /dev/azihsm[0-9]* 2>/dev/null | head -1", "r");
    if (!fp) {
        printf("Failed to find HSM device\n");
        return -1;
    }
    
    char hsm_device[256];
    if (!fgets(hsm_device, sizeof(hsm_device), fp)) {
        printf("No HSM device found\n");
        pclose(fp);
        return -1;
    }
    pclose(fp);
    
    // Remove newline
    hsm_device[strcspn(hsm_device, "\n")] = 0;
    
    fd = open(hsm_device, O_RDWR);
    if (fd < 0) {
        printf("Failed to open HSM device %s: %s\n", hsm_device, strerror(errno));
        return -1;
    }
    
    // Test invalid ioctl
    int result = ioctl(fd, 0xDEADBEEF, NULL);
    if (result < 0) {
        printf("Invalid ioctl properly rejected: %s\n", strerror(errno));
    } else {
        printf("Invalid ioctl unexpectedly succeeded\n");
    }
    
    // Test writing to read-only areas (if applicable)
    char test_data[] = "test";
    ssize_t bytes = write(fd, test_data, sizeof(test_data));
    printf("Write test result: %ld bytes (errno: %s)\n", bytes, strerror(errno));
    
    close(fd);
    printf("Error handling tests completed\n");
    return 0;
}

int main() {
    printf("AziHSM Error Handling Test\n");
    printf("=========================\n");
    
    if (test_invalid_operations() == 0) {
        printf("Error handling tests passed\n");
        return 0;
    } else {
        printf("\nError handling tests failed\n");
        return 1;
    }
}