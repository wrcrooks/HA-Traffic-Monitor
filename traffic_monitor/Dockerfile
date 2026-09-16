ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.12-alpine3.24
FROM ${BUILD_FROM}

# Home Assistant base-python images already provide Python, s6-overlay and bashio.
WORKDIR /app

COPY app/requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY www /app/www
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
