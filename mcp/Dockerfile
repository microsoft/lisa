FROM python:3.12-slim

WORKDIR /app

# Install git (needed for repo clone)
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Clone the LISA repo
ARG LISA_BRANCH=main
RUN git clone --depth 1 --branch ${LISA_BRANCH} \
    https://github.com/microsoft/lisa.git /app/lisa

# Overlay local MCP source so unpushed changes are included in the image
COPY . /app/lisa/mcp

# Install the MCP server package (with Azure blob download support)
RUN pip install --no-cache-dir "/app/lisa/mcp[azure]"

# Point the MCP server at the cloned repo
ENV LISA_REPO_ROOT=/app/lisa

# Drop privileges: run as a non-root user. /app must remain readable but
# writable areas (logs, downloads) are scoped to /home/mcp at runtime.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 mcp \
    && chown -R mcp:mcp /app
USER mcp

EXPOSE 8080

ENTRYPOINT ["lisa-mcp"]
CMD ["--transport", "sse", "--port", "8080"]
