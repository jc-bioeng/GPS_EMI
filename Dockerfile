FROM python:3.14.7-slim-bookworm AS builder
WORKDIR /build
COPY pyproject.toml ./
COPY src/ ./src/
RUN python -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.14.7-slim-bookworm
ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GPS_EMI_STATE_DIR=/data/state
WORKDIR /app
COPY requirements-runtime.txt ./
RUN python -m pip install --no-cache-dir -r requirements-runtime.txt \
    && groupadd --gid 10001 gps-emi \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /app --shell /usr/sbin/nologin gps-emi \
    && mkdir /data && chown 10001:10001 /data && chmod 700 /data
COPY --from=builder /wheels/ /tmp/wheels/
RUN python -m pip install --no-cache-dir --no-deps /tmp/wheels/*.whl \
    && rm -rf /tmp/wheels
USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import json, urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3); assert r.status == 200 and json.load(r) == {'status':'ok'}"]
CMD ["python", "-m", "gps_emi.whatsapp.server", "--host", "0.0.0.0", "--port", "8000"]
