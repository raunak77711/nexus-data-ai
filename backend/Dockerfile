# Pinned to the minor version and the Debian release, not just `python:3.12`.
# A bare major.minor tag is re-pointed upstream whenever a patch or a new base
# distro ships, so a build that worked last month can fail today for reasons
# nothing in this repo explains. Pinning to a digest (python:3.12-slim@sha256:...)
# is stricter still and is what a production build should do; minor+distro is
# the level that stays legible in a submission.
FROM python:3.12-slim-bookworm

# Slim omits a compiler. pandas, numpy and scikit-learn all publish manylinux
# wheels for this Python and platform, so nothing needs to build from source and
# no toolchain is installed -- which keeps the image small and its attack
# surface correspondingly narrow. If a future dependency has no wheel, this is
# the line that will need build-essential added, and it should be a deliberate
# decision rather than a precaution taken in advance.

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Requirements are copied and installed BEFORE the source. Docker caches each
# layer against the files it read, so with this ordering an edit to core/ or
# backend/ reuses the cached dependency layer, and only a change to
# requirements.txt triggers a reinstall. Copying everything first would
# reinstall pandas on every edit.
COPY requirements.txt .

# streamlit is stripped out of the API image: app.py is a dev harness that runs
# on the host, and shipping a 40MB dependency the container never imports is
# dead weight in every pull.
RUN grep -v '^streamlit==' requirements.txt > requirements.api.txt \
    && pip install -r requirements.api.txt

COPY core/ ./core/
COPY backend/ ./backend/
COPY scripts/ ./scripts/

# Runs as a non-root user. The bind mounts in docker-compose.yml need this uid
# to be able to write samples/, which is why the directory is created and
# chowned here rather than left to the mount.
RUN mkdir -p /app/samples \
    && useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# The compose file overrides this to add --reload and the sample generator.
# The default is the production-shaped command, so `docker run` on this image
# alone does something sensible.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
