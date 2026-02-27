# Azure HSM Driver Test Data

This directory contains C source files used by the Azure Integrated HSM driver test suite.

## Files

### `azihsm_userspace_test.c`
Basic userspace device access test program that:
- Discovers AzIHSM devices dynamically
- Tests device open/close operations
- Performs basic read operations
- Reports test results

### `azihsm_crypto_test.c` 
Crypto operations test program that:
- Tests AES operations through HSM device ioctl calls
- Tests control operations through HSM device
- Validates proper device communication for crypto operations

### `azihsm_concurrent_test.c`
Concurrent access test program that:
- Tests multiple processes accessing HSM device simultaneously
- Validates thread safety and resource management
- Uses fork() to create multiple test processes

### `azihsm_error_test.c`
Error handling validation program that:
- Tests invalid device access scenarios
- Validates proper error responses for invalid ioctl calls
- Tests edge cases and error conditions

## Building Manually

To compile and test manually:
```bash
gcc -o azihsm_userspace_test azihsm_userspace_test.c
gcc -o azihsm_crypto_test azihsm_crypto_test.c
gcc -o azihsm_concurrent_test azihsm_concurrent_test.c
gcc -o azihsm_error_test azihsm_error_test.c
```
