ARG BUILD_FROM
FROM ${BUILD_FROM}

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

COPY rootfs /
