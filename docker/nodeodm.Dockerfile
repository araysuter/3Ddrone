ARG ODM_IMAGE=local-aerial-mapper/odm:3.6.0-gpu
FROM ${ODM_IMAGE}

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm unzip p7zip-full \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /code/SuperBuild/install/bin/untwine /usr/local/bin/untwine \
    && ln -sf /code/SuperBuild/install/bin/entwine /usr/local/bin/entwine \
    && ln -sf /code/SuperBuild/install/bin/pdal /usr/local/bin/pdal

WORKDIR /var/www
COPY vendor/nodeodm/package*.json ./
RUN npm install --omit=dev
COPY vendor/nodeodm/ ./
RUN mkdir -p data tmp logs \
    && useradd --create-home --shell /bin/bash odm \
    && chown -R odm:odm /var/www /code

USER odm
EXPOSE 3000
HEALTHCHECK --interval=20s --timeout=5s --retries=8 CMD node -e "require('http').get('http://127.0.0.1:3000/info',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"
ENTRYPOINT ["/usr/bin/node", "/var/www/index.js"]
