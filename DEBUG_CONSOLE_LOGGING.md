# Debug Console Logging - What to Look For

## Summary of Changes

This branch adds comprehensive debug logging to diagnose why CH console logs are 0 bytes despite the kernel outputting to ttyS0.

### Key Changes:

1. **Console Logger (`console_logger.py`)**:
   - Added unbuffered mode (`buffering=0`) for immediate disk writes
   - Track bytes written by the logger
   - Added `get_stats()` method to expose logger state

2. **CH Platform (`ch_platform.py`)**:
   - Log full paths at attachment time (with resolved absolute paths)
   - Immediate size check after attachment (baseline = 0)
   - Wait 2s and check again to see if data is flowing
   - Compare logger's internal path vs context path at deletion
   - List all *console*.log files in directory
   - Report bytes written by logger vs file size

## What to Grep For in Logs

### 1. Attachment Phase (most important)

```bash
grep "\[DEBUG ATTACH\]" lisa.log
```

Look for this sequence:
```
[DEBUG ATTACH] VM: lisa-xxx-0
[DEBUG ATTACH] Console log path: /full/path/to/qemu-console.log
[DEBUG ATTACH] Resolved path: /full/path/to/qemu-console.log
[DEBUG ATTACH] Console logger attached successfully
[DEBUG ATTACH] File exists immediately after attach, size: 0 bytes (baseline)
[DEBUG ATTACH] Size after 2s: XXX bytes, logger reports XXX bytes written
```

**Key Questions:**
- **Does "attached successfully" appear?** If not, attachment failed
- **Does file exist immediately?** If not, path or permission issue
- **Is size still 0 after 2s?** If yes, VM not outputting to serial
- **Do file size and logger bytes_written match?** If not, buffering or flush issue

### 2. Deletion Phase

```bash
grep "\[DEBUG DELETE\]" lisa.log
```

Look for:
```
[DEBUG DELETE] VM: lisa-xxx-0
[DEBUG DELETE] Console log path from context: /path/to/qemu-console.log
[DEBUG DELETE] Resolved path: /path/to/qemu-console.log
[DEBUG DELETE] Logger stats: path=/path/to/qemu-console.log, bytes_written=XXX, completed=True
[DEBUG DELETE] File exists: True
[DEBUG DELETE] Source console log size: XXX bytes
[DEBUG DELETE] All console logs in directory:
[DEBUG DELETE]   - qemu-console.log: XXX bytes
```

**Key Questions:**
- **Does attachment path == deletion path?** If not, path changed during test run
- **Does logger's internal path == context path?** If not, logger wrote to wrong file
- **Are there multiple console log files?** Suggests path instability
- **Do file size and logger bytes_written match?** If logger wrote X bytes but file has 0, I/O issue

### 3. Path Mismatch Detection

```bash
grep "PATH MISMATCH" lisa.log
```

If this appears, **CRITICAL**: The logger wrote to one file but we're trying to copy from another.

### 4. Zero Byte Files

```bash
grep "EMPTY (0 bytes)" lisa.log
```

This will show:
```
Console log file is EMPTY (0 bytes). Logger reports XXX bytes written.
```

**Diagnosis:**
- **Logger reports 0 bytes:** VM never sent data to serial console (kernel cmdline issue)
- **Logger reports >0 bytes but file is 0:** Path mismatch or I/O issue

## Expected Outcomes

### Success Case:
```
[DEBUG ATTACH] Size after 2s: 1024 bytes, logger reports 1024 bytes written
... later ...
[DEBUG DELETE] Source console log size: 4096 bytes
[DEBUG DELETE] Logger stats: bytes_written=4096
```

### Path Mismatch Case:
```
[DEBUG ATTACH] Console log path: /path/A/qemu-console.log
[DEBUG DELETE] Console log path from context: /path/B/qemu-console.log
[DEBUG DELETE] PATH MISMATCH! Logger wrote to: /path/A, But we're trying to copy from: /path/B
```

### No Serial Output Case:
```
[DEBUG ATTACH] Size after 2s: 0 bytes, logger reports 0 bytes written
[DEBUG DELETE] Source console log size: 0 bytes
[DEBUG DELETE] Logger reports 0 bytes written.
```
**Fix**: Check kernel cmdline has `console=ttyS0,115200`

### Logger Not Receiving Data Case:
```
[DEBUG ATTACH] Size after 2s: 0 bytes, logger reports 0 bytes written
```
But you see in dmesg or virsh console that data IS being output.
**Fix**: Check libvirt stream connection, domain.openConsole() call

## Quick Diagnostic Commands

```bash
# Find all debug messages
grep -E "\[DEBUG (ATTACH|DELETE)\]" lisa.log

# Check for path mismatches
grep -i "mismatch\|differ" lisa.log

# Find bytes written stats
grep "bytes_written" lisa.log

# Check if files exist
grep "File exists:" lisa.log | grep -v "True"

# Find empty file warnings
grep "EMPTY" lisa.log
```

## Next Steps Based on Findings

1. **If paths don't match**: Fix path stability in node context
2. **If logger reports 0 bytes**: Fix kernel cmdline or serial port config
3. **If logger reports >0 but file is 0**: Fix path mismatch or check if logger closes file properly
4. **If size after 2s is 0**: VM boot issue or serial console not working
