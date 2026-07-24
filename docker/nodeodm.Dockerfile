ARG ODM_IMAGE=local-aerial-mapper/odm:3.6.0-gpu
FROM ${ODM_IMAGE}

ARG MAPPER_UID=1000
ARG MAPPER_GID=1000

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm unzip p7zip-full \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /code/SuperBuild/install/bin/untwine /usr/local/bin/untwine \
    && ln -sf /code/SuperBuild/install/bin/entwine /usr/local/bin/entwine \
    && ln -sf /code/SuperBuild/install/bin/pdal /usr/local/bin/pdal

WORKDIR /var/www
COPY vendor/nodeodm/package*.json ./
RUN npm ci --omit=dev
COPY vendor/nodeodm/ ./
COPY docker/nodeodm-config.json /var/www/local-mapper-config.json
RUN set -eux; \
    if ! getent group "${MAPPER_GID}" >/dev/null; then \
        groupadd --gid "${MAPPER_GID}" "mapper${MAPPER_GID}"; \
    fi; \
    if ! getent passwd "${MAPPER_UID}" >/dev/null; then \
        useradd \
            --uid "${MAPPER_UID}" \
            --gid "${MAPPER_GID}" \
            --home-dir /var/www/home \
            --no-create-home \
            --shell /bin/bash \
            "mapper${MAPPER_UID}"; \
    fi; \
    install -d -m 0770 \
        -o "${MAPPER_UID}" \
        -g "${MAPPER_GID}" \
        /var/www/data \
        /var/www/tmp \
        /var/www/logs \
        /var/www/home

ENV HOME=/var/www/home
USER ${MAPPER_UID}:${MAPPER_GID}
EXPOSE 3000
HEALTHCHECK --interval=20s --timeout=5s --retries=8 CMD node -e "const token=encodeURIComponent(process.env.NODEODM_TOKEN||'');require('http').get('http://127.0.0.1:3000/info?token='+token,r=>{let raw='';r.on('data',c=>raw+=c);r.on('end',()=>{try{const body=JSON.parse(raw);process.exit(r.statusCode===200&&body.version&&!body.error?0:1)}catch{process.exit(1)}})}).on('error',()=>process.exit(1))"
ENTRYPOINT ["/usr/bin/node", "/var/www/index.js"]
