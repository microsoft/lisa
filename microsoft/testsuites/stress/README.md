# TLB Stress Test Suite

This directory contains the TLB (Translation Lookaside Buffer) stress testing suite for the LISA framework.

## Overview

The TLB stress test suite is designed to create intensive TLB pressure to reveal performance degradation under heavy virtual memory operations. This is crucial for validating virtual memory subsystem performance and detecting regressions.

## Files

### Test Suites
- **`tlb_stress_suite.py`** - Main TLB stress test suite with three test methods
- **`stress_ng_suite.py`** - General stress-ng test suite (TLB tests moved to dedicated suite)

### Configuration Files
- **`tlb_stress_job.yaml`** - Stress-ng job file for TLB stress testing using built-in stressors

### Validation Tools
- **`validate_tlb_stress.sh`** - Validation script for testing TLB program compilation and execution

## Test Methods

### TlbStressTestSuite

#### 1. `tlb_flush_stress_test`
- **Purpose**: Comprehensive TLB stress test combining stress-ng --vm with custom TLB flush program
- **Duration**: 120 seconds
- **Configuration**: 4 threads, 1000 pages per thread
- **Requirements**: 2+ CPU cores, 2GB+ RAM

#### 2. `tlb_stress_job_test`
- **Purpose**: TLB stress using stress-ng job file with multiple VM-related stressors
- **Duration**: 120 seconds
- **Components**: VM, mmap, mremap, mprotect, madvise, mlock stressors
- **Requirements**: 2+ CPU cores, 2GB+ RAM

#### 3. `tlb_flush_quick_test`
- **Purpose**: Lightweight TLB test for quick validation and CI/CD
- **Duration**: 30 seconds
- **Configuration**: 2 threads, 500 pages per thread
- **Requirements**: 1+ CPU core, 1GB+ RAM

## TLB Stress Methodology

The TLB stress tests use a three-phase approach to create intensive TLB pressure:

1. **Map Phase**: Allocate virtual memory pages using `mmap()`
2. **Access Phase**: Perform random read/write operations to populate TLB entries
3. **Unmap Phase**: Force TLB flushes using `munmap()` calls

This cycle is repeated continuously with multiple threads to maximize TLB cache misses and reveal performance degradation under TLB pressure.

## Usage Examples

### Running TLB Tests

```bash
# Run comprehensive TLB stress test
lisa run --runbook your_runbook.yml --test_case tlb_flush_stress_test

# Run quick validation test
lisa run --runbook your_runbook.yml --test_case tlb_flush_quick_test

# Run stress-ng job file approach
lisa run --runbook your_runbook.yml --test_case tlb_stress_job_test
```

### Custom Configuration

The TLB tests can be customized by modifying the configuration parameters in the test methods:

- `test_duration`: Test duration in seconds
- `tlb_threads`: Number of TLB flush threads per node
- `tlb_pages`: Number of pages per thread for mapping/unmapping

## Integration with Stress-ng

The TLB stress tests leverage the existing stress-ng tool integration in LISA:

- **Parallel execution**: Runs stress-ng --vm stressors alongside custom TLB programs
- **Automatic deployment**: Compiles and deploys TLB program to test nodes
- **Comprehensive monitoring**: Tracks both stress-ng and TLB program execution
- **Built-in stressors**: Uses stress-ng's VM, memory mapping, and protection stressors

## Performance Analysis

The TLB stress tests provide detailed performance metrics:

- **Cycles completed**: Number of map/access/unmap cycles
- **Pages processed**: Total pages mapped and unmapped
- **Memory throughput**: GB/s of memory processing
- **Timing statistics**: Per-thread and overall execution times

These metrics help identify performance degradation under TLB pressure and validate virtual memory subsystem efficiency.

## Architecture Support

The TLB stress tests are designed to work across different CPU architectures:

- **x86-64**: Standard page sizes and TLB behavior
- **ARM64**: ARM-specific TLB characteristics
- **Multi-architecture**: Automatic adaptation to platform page sizes

## Best Practices

1. **Memory Requirements**: Ensure adequate memory for the configured page count
2. **CPU Resources**: Use sufficient CPU cores for multi-threaded stress testing
3. **Duration**: Allow adequate test duration for meaningful TLB analysis (minimum 30 seconds)
4. **Monitoring**: Review both TLB program output and stress-ng metrics for complete analysis

## Troubleshooting

### Common Issues

1. **Compilation Failures**: Ensure gcc and pthread development libraries are available
2. **Memory Allocation**: Reduce page count if system runs out of memory
3. **Timeout Issues**: Increase test timeout for slower systems or larger configurations

### Debug Options

- Set verbose logging in LISA for detailed execution traces
- Review individual node outputs for TLB program statistics
- Check stress-ng YAML output for comprehensive metrics