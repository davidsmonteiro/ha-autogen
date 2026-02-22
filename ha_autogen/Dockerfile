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

# s6-overlay v3 service registration
COPY run.sh /etc/s6-overlay/s6-rc.d/ha_autogen/run
RUN chmod a+x /etc/s6-overlay/s6-rc.d/ha_autogen/run \
    && echo "longrun" > /etc/s6-overlay/s6-rc.d/ha_autogen/type \
    && mkdir -p /etc/s6-overlay/s6-rc.d/ha_autogen/dependencies.d \
    && touch /etc/s6-overlay/s6-rc.d/ha_autogen/dependencies.d/base \
    && mkdir -p /etc/s6-overlay/s6-rc.d/user/contents.d \
    && touch /etc/s6-overlay/s6-rc.d/user/contents.d/ha_autogen
