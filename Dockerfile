FROM python:3.13-slim

# System deps: curl for OpenTable client's _curl_fetch() Cloudflare bypass,
# plus shared libraries required by Playwright's Chromium (Resy auth fallback).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libnss3 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 \
        libdrm2 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
        libpango-1.0-0 libcairo2 libasound2t64 libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . 2>/dev/null || true

# Copy source code
COPY . .
RUN pip install --no-cache-dir -e .

# Install Playwright Chromium browser
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.playwright-browsers
RUN playwright install chromium

# Create non-root user (security best practice for internet-facing containers)
RUN useradd --create-home --shell /bin/bash mcpuser \
    && chown -R mcpuser:mcpuser /app
USER mcpuser

# Default env vars for remote hosting
ENV MCP_TRANSPORT=streamable-http
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["python", "-m", "src"]
