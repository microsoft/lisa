# LISA MCP server. Serves SSE on 0.0.0.0:8080, so it is reachable by anyone
# who can reach the port — LISA_MCP_API_KEY is mandatory and the server exits
# at startup without it. LISA_LOG_ROOT confines the log tools and is required
# before they will touch disk in SSE mode.
#
#   docker run -p 8080:8080 \
#     -e LISA_MCP_API_KEY=<shared secret> \
#     -e LISA_LOG_ROOT=/app/logs \
#     -e ALLOWED_HOSTS=<your-host>,localhost \
#     -v /var/log/lisa:/app/logs lisa-mcp
#
# Build context must be mcp/, not the repo root (see COPY below).
FROM python:3.12-slim

WORKDIR /app

# Install git (needed for repo clone) and curl (needed by the healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

# Clone the LISA repo
ARG LISA_BRANCH=main
RUN git clone --depth 1 --branch ${LISA_BRANCH} \
    https://github.com/microsoft/lisa.git /app/lisa

# Overlay local MCP source so unpushed changes are included in the image
COPY . /app/lisa/mcp

# Build args are exposed to RUN as environment variables, and pip reads
# PIP_INDEX_URL. Set it when public PyPI is unreachable, e.g.
#   --build-arg PIP_INDEX_URL=https://<your-mirror>/pypi/simple/
ARG PIP_INDEX_URL

# Install the MCP server package with SSE transport and Azure blob download
RUN pip install --no-cache-dir "/app/lisa/mcp[sse,azure]"

# Point the MCP server at the cloned repo
ENV LISA_REPO_ROOT=/app/lisa

# Drop privileges: run as a non-root user. /app must remain readable but
# writable areas (logs, downloads) are scoped to /home/mcp at runtime.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 mcp \
    && chown -R mcp:mcp /app
USER mcp

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s \
    CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["lisa-mcp"]
CMD ["--transport", "sse", "--port", "8080"]
