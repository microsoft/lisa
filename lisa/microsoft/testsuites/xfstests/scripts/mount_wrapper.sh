#!/bin/bash
# Rewrite xfstests remounts to use the configured mount helper and server source.
set -u

# Skip this wrapper while resolving the real mount and umount commands.
resolve_underlying_command() {
    local command_name=$1 candidate path_entry resolved_path
    local wrapper_path
    wrapper_path=$(readlink -f "$0")
    while IFS= read -r path_entry; do
        [ -n "$path_entry" ] || path_entry=.
        candidate="$path_entry/$command_name"
        if [ -x "$candidate" ]; then
            resolved_path=$(readlink -f "$candidate")
            if [ "$resolved_path" != "$wrapper_path" ]; then
                echo "$resolved_path"
                return 0
            fi
        fi
    done < <(printf '%s' "$PATH" | tr ':' '\n')
    return 1
}

real_mount=$(resolve_underlying_command mount)
real_umount=$(resolve_underlying_command umount)
if [ -z "$real_mount" ] || [ -z "$real_umount" ]; then
    echo "Azure mount wrapper could not find mount or umount in PATH." >&2
    exit 127
fi

if [ "$#" -eq 0 ]; then
    exec "$real_mount"
fi

helper_fstype="${AZ_HELPER_FSTYPE:-}"
base_fstype="${AZ_BASE_FSTYPE:-${FSTYP:-}}"

mount_args=("$@")
expected_source=""
server_source=""
mountpoint="${mount_args[${#mount_args[@]} - 1]}"

# Replace the helper's loopback source with the server source for remounting.
for index in "${!mount_args[@]}"; do
    if [ -n "${AZ_TEST_DEV:-}" ] && \
        [ "${mount_args[$index]}" = "${TEST_DEV:-}" ]; then
        expected_source="${TEST_DEV:-}"
        server_source="$AZ_TEST_DEV"
        mount_args[index]="$AZ_TEST_DEV"
    elif [ -n "${AZ_SCRATCH_DEV:-}" ] && \
        [ "${mount_args[$index]}" = "${SCRATCH_DEV:-}" ]; then
        expected_source="${SCRATCH_DEV:-}"
        server_source="$AZ_SCRATCH_DEV"
        mount_args[index]="$AZ_SCRATCH_DEV"
    fi
done

# Route the server source through the configured mount helper.
if [ -n "$server_source" ] && [ -n "$helper_fstype" ]; then
    for index in "${!mount_args[@]}"; do
        if [ "${mount_args[$index]}" = "-t" ] && \
            [ "${mount_args[$((index + 1))]:-}" = "$base_fstype" ]; then
            mount_args[index + 1]="$helper_fstype"
        fi
    done
fi

"$real_mount" "${mount_args[@]}"
mount_result=$?
if [ "$mount_result" -ne 0 ] || [ -z "$server_source" ]; then
    exit "$mount_result"
fi

# Fail if the helper reports a source different from the xfstests config.
# findmnt lists stacked mounts oldest first, so use the last source.
mounted_source=$(findmnt -rn -o SOURCE --target "$mountpoint" | tail -1)
if [ -n "$mounted_source" ] && [ "$mounted_source" = "$expected_source" ]; then
    exit 0
fi

"$real_umount" "$mountpoint"
echo "${helper_fstype:-mount helper} changed the source of $mountpoint." >&2
echo "Expected [$expected_source], found [${mounted_source:-none}]." >&2
echo "Use an in-shell mount hook so xfstests can refresh its device variable." >&2
exit 1
