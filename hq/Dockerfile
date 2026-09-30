# Tico HQ, the collector behind the anonymous usage count. Its own image, apart from the Tico server's.
#   docker build -t tico-hq hq/      (docker compose -f hq/compose.yaml up -d --build does this)
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e
FROM ${PYTHON_IMAGE}
RUN groupadd --gid 10005 hq && useradd --uid 10005 --gid hq --home-dir /data --no-create-home --shell /usr/sbin/nologin hq \
    && install -d -m 0700 -o hq -g hq /data
WORKDIR /srv
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements.txt
COPY . /srv/hq
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HQ_DB=/data/hq.db
USER 10005:10005
EXPOSE 8770
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8770/healthz', timeout=4)"
CMD ["python", "-m", "hq"]
