# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY prompts ./prompts
COPY code ./code

RUN uv venv /opt/venv && \
    . /opt/venv/bin/activate && \
    uv pip install .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --gid 10001 appuser && \
    useradd --uid 10001 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser pyproject.toml README.md ./
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser prompts ./prompts
COPY --chown=appuser:appuser code ./code
COPY --chown=appuser:appuser evaluation ./evaluation

USER appuser

EXPOSE 8000

ENTRYPOINT ["python", "-m", "deletion_audit.cli"]
CMD ["run", "--split", "full", "--output", "output.csv"]
