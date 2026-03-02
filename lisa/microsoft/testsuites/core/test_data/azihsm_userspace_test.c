/*
 * Azure Integrated HSM Userspace Device Test
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

int test_device_open_close(const char* device_path) {
    printf("Testing device: %s\n", device_path);
    
    int fd = open(device_path, O_RDWR);
    if (fd < 0) {
        printf("Failed to open %s: %s\n", device_path, strerror(errno));
        return -1;
    }
    
    printf("Successfully opened %s (fd=%d)\n", device_path, fd);
    
    // Test basic read (may fail gracefully)
    char buffer[64];
    ssize_t result = read(fd, buffer, sizeof(buffer));
    printf("Read test result: %ld (errno: %s)\n", result, strerror(errno));
    
    close(fd);
    printf("Device closed successfully\n");
    return 0;
}

int main() {
    printf("AziHSM Userspace Device Test\n");
    printf("============================\n");
    
    // Find actual device names (they have numeric suffixes)
    system("ls /dev/azihsm[0-9]* /dev/azihsm-mgmt[0-9]* 2>/dev/null > /tmp/azihsm_devices.txt || true");
    
    FILE* fp = fopen("/tmp/azihsm_devices.txt", "r");
    if (!fp) {
        printf("No AziHSM devices found\n");
        return 1;
    }
    
    char device_path[256];
    int passed = 0;
    int total = 0;
    
    while (fgets(device_path, sizeof(device_path), fp)) {
        // Remove newline
        device_path[strcspn(device_path, "\n")] = 0;
        
        if (strlen(device_path) > 0) {
            total++;
            if (test_device_open_close(device_path) == 0) {
                passed++;
            }
        }
    }
    
    fclose(fp);
    system("rm -f /tmp/azihsm_devices.txt");
    
    printf("\nResults: %d/%d devices tested successfully\n", passed, total);
    return (passed > 0) ? 0 : 1;
}