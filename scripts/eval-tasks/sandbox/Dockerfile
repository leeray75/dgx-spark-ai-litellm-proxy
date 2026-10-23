# Test runner for scripts/eval-agentic-tasks.py. The model never gets a shell:
# this image only runs pytest on a copy of the task workspace, started with
# --network none, a read-only root, tmpfs work dirs and all capabilities dropped.
FROM python:3.12-slim
RUN pip install --no-cache-dir pytest==8.3.3 pytest-timeout==2.3.1 \
 && useradd -m -u 1000 runner
USER runner
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /work
