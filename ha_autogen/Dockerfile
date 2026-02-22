ARG BUILD_FROM
FROM ${BUILD_FROM:-python:3.12-alpine}

RUN apk add --no-cache \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY autogen/ ./autogen/
COPY frontend/ ./frontend/
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
