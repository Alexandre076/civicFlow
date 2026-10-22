FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.10 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 1000 app
WORKDIR /app
RUN chown app:app /app
USER app

COPY --chown=app:app . .
RUN uv sync --locked

EXPOSE 8000
CMD [".venv/bin/uvicorn", "civicflow.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--no-access-log"]
