ARG BUILD_FROM
FROM ${BUILD_FROM:-python:3.12-alpine}

RUN apk add --no-cache \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    py3-pip

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY autogen/ ./autogen/
COPY frontend/ ./frontend/

# s6-overlay service (HA base image uses s6-overlay v3)
COPY run.sh /etc/services.d/ha_autogen/run
RUN chmod a+x /etc/services.d/ha_autogen/run
