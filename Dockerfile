# Server image for aindy-apps-monolith — the app profile *consuming* the published
# aindy-runtime framework.
#
# This is deliberately NOT a combined runtime+apps image. It installs the runtime as
# a pinned PyPI dependency (see pyproject.toml: aindy-runtime>=1.5.3,<2.0) and adds
# the app-profile deployment inputs this repo owns: the plugin manifest
# (aindy_plugins.json), the app bootstrap package (apps/), and the app-owned Alembic
# tree. At startup the runtime discovers ./aindy_plugins.json -> apps.bootstrap, which
# registers the 16 domain apps into the runtime via the plugin ABI.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libpq + toolchain: aindy-runtime pins psycopg2 (source build) and may pull sdists.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the app package first (this resolves and installs the pinned aindy-runtime
# and the rest of the dependency tree from PyPI). Layer-cached on source-only changes.
COPY pyproject.toml README.md ./
COPY apps ./apps
RUN python -m pip install --upgrade pip \
 && python -m pip install .

# App-profile deployment inputs owned by this repo. The working directory must be the
# repo root so the runtime discovers aindy_plugins.json, and so Alembic finds alembic.ini
# (script_location = alembic/alembic).
COPY aindy_plugins.json alembic.ini ./
COPY alembic ./alembic
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000

# entrypoint applies migrations (runtime + app) then execs the CMD. The canonical
# documented app-profile entrypoint is `aindy-runtime-api`; we default to uvicorn on the
# runtime-provided ASGI app because it is provider-agnostic and binds 0.0.0.0 explicitly.
# Both fire apps.bootstrap via the lifespan when run from this repo root.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "AINDY.main:app", "--host", "0.0.0.0", "--port", "8000"]
