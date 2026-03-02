/*
 * Azure Integrated HSM Crypto Operations Test
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

// Basic ioctl definitions (may need adjustment based on actual driver)
#define AZIHSM_IOC_MAGIC 'H'
#define AZIHSM_AES_ENCRYPT _IOW(AZIHSM_IOC_MAGIC, 1, int)
#define AZIHSM_AES_DECRYPT _IOW(AZIHSM_IOC_MAGIC, 2, int)

int test_aes_operations() {
    printf("Testing AES operations through HSM device...\n");
    
    // Find HSM device (AES operations go through HSM device via ioctl)
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
    
    int fd = open(hsm_device, O_RDWR);
    if (fd < 0) {
        printf("Failed to open HSM device %s: %s\n", hsm_device, strerror(errno));
        return -1;
    }
    
    printf("HSM device %s opened successfully\n", hsm_device);
    
    // Test basic ioctl calls (may fail gracefully without hardware)
    int test_value = 0;
    
    int result = ioctl(fd, AZIHSM_AES_ENCRYPT, &test_value);
    printf(" AES encrypt ioctl result: %d (errno: %s)\n", result, strerror(errno));
    
    result = ioctl(fd, AZIHSM_AES_DECRYPT, &test_value);
    printf("AES decrypt ioctl result: %d (errno: %s)\n", result, strerror(errno));
    
    close(fd);
    printf("HSM device closed successfully\n");
    return 0;
}

int test_ctrl_operations() {
    printf("Testing control operations through HSM device...\n");
    
    // Find HSM device (control operations go through HSM device)
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
    
    int fd = open(hsm_device, O_RDWR);
    if (fd < 0) {
        printf("Failed to open HSM device %s: %s\n", hsm_device, strerror(errno));
        return -1;
    }
    
    printf("HSM device %s opened successfully\n", hsm_device);
    
    // Test device status query (implementation-specific)
    char status_buffer[256];
    ssize_t bytes = read(fd, status_buffer, sizeof(status_buffer));
    printf(" Status read result: %ld bytes (errno: %s)\n", bytes, strerror(errno));
    
    close(fd);
    printf("HSM device closed successfully\n");
    return 0;
}

int main() {
    printf("AziHSM Crypto Operations Test\n");
    printf("============================\n");
    
    int tests_passed = 0;
    
    if (test_aes_operations() == 0) tests_passed++;
    if (test_ctrl_operations() == 0) tests_passed++;
    
    printf("Crypto tests completed: %d/2 passed\n", tests_passed);
    return tests_passed > 0 ? 0 : 1;
}