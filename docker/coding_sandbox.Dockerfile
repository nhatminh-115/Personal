FROM python:3.12-slim

# Install pytest for sandboxed test execution
RUN pip install --no-cache-dir pytest

# Create non-root user matching default sandbox config 1000:1000
RUN groupadd -g 1000 sandboxgroup && \
    useradd -u 1000 -g sandboxgroup -m sandboxuser

WORKDIR /workspace
RUN chown sandboxuser:sandboxgroup /workspace

USER sandboxuser
