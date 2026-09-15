# Third-party AS (B2BUA) — signalling only.
#
# The image installs the locked environment with uv and runs the AS as a non-root user.
# Nothing is built: the packages under src/ are put on PYTHONPATH.

FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    UV_SYSTEM_PYTHON=1 \
    UV_VERSION=0.12.15

RUN pip install --no-cache-dir uv==${UV_VERSION}

WORKDIR /app
RUN useradd --create-home --uid 10001 as

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY src/ ./src/
COPY config/ ./config/
COPY VERSION ./

USER as
EXPOSE 5060/udp 8080/tcp

ENTRYPOINT []
CMD ["python", "-m", "as_app.main"]
