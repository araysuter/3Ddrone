ARG ODM_IMAGE=local-aerial-mapper/odm:3.6.0-gpu
ARG GSPLAT_COMMIT=4d3a3b69db4de0326f983ccf7b7b255271a17b01
ARG SPARK_COMMIT=f22236f95fdd8078f0c12e3aab479523d401daf6

# Nerfstudio 1.1.5's gsplat backend needs a CUDA compiler. Keep this toolchain
# separate from ODM's CUDA 12.9 runtime so the already-built ODM image remains
# untouched while PyTorch and gsplat use a matching, pinned CUDA 12.4 stack.
FROM nvidia/cuda:12.4.1-devel-ubuntu22.04 AS splat-cuda

FROM ${ODM_IMAGE}

ARG GSPLAT_COMMIT
ARG SPARK_COMMIT

USER root
COPY --from=splat-cuda /usr/local/cuda-12.4 /usr/local/cuda-12.4

ENV CUDA_HOME=/usr/local/cuda-12.4 \
    TORCH_CUDA_ARCH_LIST=8.6 \
    TORCH_HOME=/opt/torch-cache \
    MAX_JOBS=2 \
    PATH="/opt/splat-venv/bin:/usr/local/cuda-12.4/bin:/code/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        curl \
        git \
        ninja-build \
        nodejs \
        npm \
        python3-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY services/splat/requirements.txt /tmp/splat-requirements.txt
RUN /usr/bin/python3 -m venv /opt/splat-venv \
    && /opt/splat-venv/bin/pip install --no-cache-dir --upgrade \
        pip==26.1.2 \
        "setuptools<70.0.0" \
        wheel \
    && /opt/splat-venv/bin/pip install --no-cache-dir \
        torch==2.4.1+cu124 \
        torchvision==0.19.1+cu124 \
        --index-url https://download.pytorch.org/whl/cu124 \
    && /opt/splat-venv/bin/pip install --no-cache-dir --no-build-isolation \
        "git+https://github.com/nerfstudio-project/gsplat.git@${GSPLAT_COMMIT}" \
    && /opt/splat-venv/bin/pip install --no-cache-dir -r /tmp/splat-requirements.txt \
    && /opt/splat-venv/bin/python -c \
        "import gsplat, nerfstudio, torch; assert torch.__version__.startswith('2.4.1'); assert torch.version.cuda == '12.4'; print('splat stack', torch.__version__, torch.version.cuda)"

# Splatfacto constructs the LPIPS metric at startup. Torchmetrics otherwise
# downloads AlexNet weights on the first job, but the worker intentionally runs
# on an internal Docker network. Preload and retain the hash-verified weights in
# the image so training is deterministic and requires no runtime DNS/network.
RUN mkdir -p "${TORCH_HOME}" \
    && /opt/splat-venv/bin/python -c \
        "from torchmetrics.image.lpip import LearnedPerceptualImagePatchSimilarity; LearnedPerceptualImagePatchSimilarity(normalize=True); print('LPIPS cache ready')" \
    && find "${TORCH_HOME}/hub/checkpoints" -type f -name 'alexnet-*.pth' -size +1M -print -quit | grep -q . \
    && chmod -R a+rX "${TORCH_HOME}"

# Spark's MIT-licensed compressor produces the web-ready SPZ derivative. Its
# repository package.json contains development-only file dependencies generated
# by the Rust/WASM build, so a repository-level `npm install` cannot work from
# the release tag. Install only the two dependencies used by the committed
# JavaScript distribution and verify that the compressor can load.
RUN git clone --branch v2.1.0 --depth 1 https://github.com/sparkjsdev/spark.git /opt/spark \
    && test "$(git -C /opt/spark rev-parse HEAD)" = "${SPARK_COMMIT}" \
    && npm install \
        --prefix /opt/spark-runtime \
        --ignore-scripts \
        --no-audit \
        --no-fund \
        --package-lock=false \
        fflate@0.8.2 \
        three@0.180.0 \
    && ln -s /opt/spark-runtime/node_modules /opt/spark/node_modules \
    && node /opt/spark/scripts/compress-to-spz.js --help >/dev/null

COPY services/splat/app.py /app/app.py
ENV PATH="/opt/splat-venv/bin:/usr/local/cuda-12.4/bin:/code/venv/bin:$PATH" \
    SPLAT_STATE_ROOT=/data/splat
WORKDIR /app
EXPOSE 8090
HEALTHCHECK --interval=20s --timeout=5s --retries=5 CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health')"
ENTRYPOINT []
CMD ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
