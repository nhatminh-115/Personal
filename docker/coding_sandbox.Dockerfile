FROM python:3.12-slim

# Keep the sandbox test runner aligned with requirements-dev.lock.
RUN pip install --no-cache-dir pytest==9.1.1

# Create non-root user matching default sandbox config 1000:1000
RUN groupadd -g 1000 sandboxgroup && \
    useradd -u 1000 -g sandboxgroup -m sandboxuser

WORKDIR /workspace
RUN chown sandboxuser:sandboxgroup /workspace

USER sandboxuser
