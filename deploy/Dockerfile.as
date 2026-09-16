# Third-party AS (B2BUA) — signalling only.
#
# The image installs the locked environment with uv and runs the AS as a non-root user.
# Nothing is built: the packages under src/ are put on PYTHONPATH.

FROM python:3.10-slim

# Build-time package index. The defaults are public PyPI, so CI and a normal checkout are
# unaffected; a network that cannot reach PyPI (or reaches it very slowly) overrides them
# for its own build, e.g.
#   PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
#   docker compose -f deploy/docker-compose.yml build
# pip reads PIP_INDEX_URL; uv does NOT — it reads UV_DEFAULT_INDEX, which defaults to
# PIP_INDEX_URL here. See docs/operations/deployment.md section 4.2.
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG UV_DEFAULT_INDEX=${PIP_INDEX_URL}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    UV_SYSTEM_PYTHON=1 \
    UV_VERSION=0.12.15 \
    UV_HTTP_TIMEOUT=180

RUN pip install --no-cache-dir uv==${UV_VERSION}

WORKDIR /app
RUN useradd --create-home --uid 10001 as

COPY pyproject.toml uv.lock ./
# `uv sync --frozen` installs exactly what uv.lock records: the wheel URLs in the lock point
# at files.pythonhosted.org and uv does NOT substitute the configured index for them
# (verified with uv 0.12.15 — a sync whose index was unreachable still downloaded those
# URLs). That is what the canonical public-PyPI build wants, so `--frozen` is kept whenever
# PIP_INDEX_URL is the public default, and a stale lock keeps failing the build as before.
#
# A mirror build must therefore let uv re-resolve against the index. That rewrites uv.lock
# *inside the image only*, against the unchanged version pins — verified as the same 50
# packages at the same versions, with only the registry URL changed. The committed uv.lock is
# never touched by a build and keeps referencing public PyPI, so CI and other machines are
# unaffected.
#
# The uv download cache is a build cache mount so a rebuild — and the other two images —
# reuse the distributions instead of downloading them again.
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "${PIP_INDEX_URL}" = "https://pypi.org/simple" ]; then \
        uv sync --frozen --no-install-project; \
    else \
        uv sync --no-install-project; \
    fi

COPY src/ ./src/
COPY config/ ./config/
COPY VERSION ./

# `uv sync` installs into the project environment /app/.venv, not into the system
# interpreter. Put that environment first on PATH so `python` in CMD is the interpreter that
# actually has sippy (and fastapi/uvicorn for the internal API) installed — without this the
# service fails at import with `ModuleNotFoundError: No module named 'sippy'` (found on the
# first run of the stack).
ENV PATH="/app/.venv/bin:${PATH}"

USER as
EXPOSE 5060/udp 8080/tcp

ENTRYPOINT []
CMD ["python", "-m", "as_app.main"]
