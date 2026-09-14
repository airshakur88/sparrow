FROM python:3.14-alpine@sha256:05b2b8b732ecd268fee8727a369f936f022d1321b59befd13c30ede22769dcdc

WORKDIR /app
RUN apk upgrade --no-cache
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir \
    "anyio==4.14.2" \
    "certifi==2026.7.22" \
    "h11==0.16.0" \
    "httpcore==1.0.9" \
    "httpx==0.28.1" \
    "idna==3.19" \
    . \
    && python -m pip uninstall --yes pip setuptools wheel

RUN adduser -D -u 10001 sparrow
USER sparrow

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"
ENTRYPOINT ["sparrow"]
CMD ["start", "--host", "0.0.0.0", "--port", "8080", "--allow-lan", "--allow-no-auth"]
