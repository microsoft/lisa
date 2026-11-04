# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

FROM ubuntu:24.04

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    --no-install-recommends \
    binutils build-essential ca-certificates cmake curl git \
    gcc-mingw-w64-x86-64-win32 \
    libarchive-tools libssl-dev pkg-config sudo unzip zip zstd \
    && rm -rf /var/lib/apt/lists/*

ARG HOST_UID
ARG HOST_GID
RUN if getent passwd ubuntu > /dev/null; then userdel ubuntu; fi \
    && groupadd --non-unique --gid "$HOST_GID" openvmm \
    && useradd --non-unique --uid "$HOST_UID" --gid openvmm \
        --create-home --shell /bin/bash openvmm \
    && printf 'openvmm ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/openvmm \
    && chmod 0440 /etc/sudoers.d/openvmm

USER openvmm
ENV HOME=/home/openvmm
ENV PATH=/home/openvmm/.cargo/bin:$PATH
ENV OPENSSL_NO_VENDOR=1
ENV RUST_BACKTRACE=full
ENV RUST_LOG=info

RUN curl --fail --silent --show-error --connect-timeout 30 --max-time 120 \
        --retry 3 --retry-all-errors --retry-max-time 300 \
        https://sh.rustup.rs -o /tmp/rustup-init.sh \
    && for attempt in 1 2 3; do \
        if sh /tmp/rustup-init.sh -y --profile minimal --component rust-src \
            --target x86_64-unknown-linux-musl,x86_64-pc-windows-gnu; then \
            rm /tmp/rustup-init.sh; exit 0; \
        fi; \
        if [ "$attempt" -eq 3 ]; then \
            echo "Rust bootstrap failed after 3 attempts" >&2; exit 1; \
        fi; \
        echo "Rust bootstrap attempt $attempt failed; retrying in 10 seconds" >&2; \
        sleep 10; \
    done
