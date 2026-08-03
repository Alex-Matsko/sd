FROM python:3.12-slim

WORKDIR /srv

# fonts-dejavu-core: reportlab's built-in Type1 fonts have no Cyrillic, so
# PDF reports (ТЗ р. 9) need a real TTF with Russian glyphs - otherwise every
# label renders as black boxes. ~1 MB, no browser or LaTeX toolchain.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 ca-certificates fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# MAX Bot API (platform-api2.max.ru, Этап 5) serves a certificate chain
# rooted at the Russian state CA (Минцифры), which isn't in the standard
# Mozilla/Debian trust store - without this, every outbound call from
# services/max_client.py fails TLS verification. The intermediate Sub CA is
# already sent by the server during the handshake; only the root is needed.
COPY certs/russian-trusted-root-ca.pem /usr/local/share/ca-certificates/russian-trusted-root-ca.crt
RUN update-ca-certificates

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Тестовые зависимости в боевой образ не попадают. Локально их ставит
# docker-compose.override.yml (см. README): раньше pytest доставлялся руками
# в запущенный контейнер и молча исчезал при каждой пересборке.
ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ]; then pip install --no-cache-dir -r requirements-dev.txt; fi

COPY . .

CMD ["sh", "-c", "alembic upgrade head && python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
