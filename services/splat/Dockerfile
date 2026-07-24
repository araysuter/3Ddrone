ARG ODM_IMAGE=local-aerial-mapper/odm:3.6.0-gpu
FROM ${ODM_IMAGE}

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY services/splat/requirements.txt /tmp/splat-requirements.txt
RUN /code/venv/bin/pip install --no-cache-dir -r /tmp/splat-requirements.txt

# Spark's MIT-licensed compressor produces the web-ready SPZ derivative.
RUN git clone --branch v2.1.0 --depth 1 https://github.com/sparkjsdev/spark.git /opt/spark \
    && cd /opt/spark \
    && npm install

COPY services/splat/app.py /app/app.py
ENV PATH="/code/venv/bin:$PATH" \
    SPLAT_STATE_ROOT=/data/splat
WORKDIR /app
EXPOSE 8090
HEALTHCHECK --interval=20s --timeout=5s --retries=5 CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health')"
ENTRYPOINT []
CMD ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
