FROM docker.io/alpine:3.18

RUN apk add --no-cache \
      python3 py3-pip py3-setuptools py3-wheel \
      #py3-pillow \
      py3-aiohttp \
      py3-magic \
      py3-ruamel.yaml \
      py3-commonmark \
      #py3-prometheus-client \
      py3-paho-mqtt \
      # proxy support
      py3-aiohttp-socks \
      py3-pysocks \
      # Other dependencies
      ca-certificates \
      su-exec \
      ffmpeg \
      # encryption
      py3-olm \
      py3-cffi \
      py3-pycryptodome \
      py3-unpaddedbase64 \
      py3-future \
      bash \
      curl \
      jq \
      yq \
  # Temporarily install pillow from edge repo to get up-to-date version
  && apk add --no-cache py3-pillow --repository=https://dl-cdn.alpinelinux.org/alpine/edge/community

COPY requirements.txt /opt/mautrix-instagram/requirements.txt
COPY optional-requirements.txt /opt/mautrix-instagram/optional-requirements.txt
WORKDIR /opt/mautrix-instagram
RUN apk add --virtual .build-deps python3-dev libffi-dev build-base \
 && pip3 install --no-cache-dir -r requirements.txt -r optional-requirements.txt \
 && apk del .build-deps

COPY . /opt/mautrix-instagram
RUN apk add git && pip3 install --no-cache-dir .[all] && apk del git \
  # This doesn't make the image smaller, but it's needed so that the `version` command works properly
  && cp mautrix_instagram/example-config.yaml . && rm -rf mautrix_instagram .git build

ENV UID=1337 GID=1337
VOLUME /data

CMD ["/opt/mautrix-instagram/docker-run.sh"]
