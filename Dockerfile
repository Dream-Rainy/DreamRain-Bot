# syntax=docker/dockerfile:1.7

FROM astral/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_DEFAULT_INDEX="https://pypi.org/simple" \
    UV_COMPILE_BYTECODE=1 \
    UV_CACHE_DIR=/app/.cache/uv \
    CARGO_HOME=/usr/local/cargo \
    RUSTUP_HOME=/usr/local/rustup \
    PATH="/usr/local/cargo/bin:$PATH" \
    DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    UV_HTTP_TIMEOUT=120 \
    UV_LINK_MODE=copy

RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends build-essential curl ca-certificates pkg-config libssl-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
        sh -s -- -y --profile minimal --default-toolchain 1.85.0 && \
    rustc --version && \
    cargo --version

COPY pyproject.toml uv.lock* ./
COPY src/submodule/arcade-helper ./src/submodule/arcade-helper
RUN --mount=type=cache,target=/app/.cache/uv \
    uv sync --locked --no-dev && \
    uvx pip-licenses \
        --python /app/.venv/bin/python \
        --format=json \
        --with-urls \
        --with-authors \
        --with-description \
        --output-file /app/DEPENDENCY_LICENSES.json

FROM scratch AS dependency-licenses
COPY --from=builder /app/DEPENDENCY_LICENSES.json /DEPENDENCY_LICENSES.json

FROM astral/uv:python3.12-bookworm-slim

RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
        fontconfig \
        fonts-noto-cjk \
        fonts-noto-cjk-extra \
        fonts-noto-color-emoji \
        fonts-wqy-microhei \
        fonts-wqy-zenhei \
        freeglut3-dev \
        gosu \
        libsm6 \
        libxext6 \
        locales \
        tini \
        wget && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    echo "C.UTF-8 UTF-8" >> /etc/locale.gen && \
    locale-gen && \
    gosu nobody true && \
    command -v fc-cache && \
    fc-cache -fv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# 使用 ARG 让 UID/GID 可配置
ARG UID=1000
ARG GID=1001
ARG IMAGE_SOURCE=""
ARG VCS_REF=""

LABEL org.opencontainers.image.source="${IMAGE_SOURCE}" \
      org.opencontainers.image.description="DreamRain-Bot NoneBot2 container image" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV UID=${UID} \
    GID=${GID} \
    TZ=Asia/Shanghai \
    DEBIAN_FRONTEND=noninteractive \
    UV_COMPILE_BYTECODE=1 \
    UV_CACHE_DIR=/app/.cache/uv \
    PATH="/app/.venv/bin:$PATH" \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=utf-8

# 创建用户和组
RUN groupadd -g ${GID} appuser && \
    useradd -m -u ${UID} -g ${GID} -s /bin/bash appuser

WORKDIR /app

# 复制文件
COPY --from=builder --chown=${UID}:${GID} /app/.venv /app/.venv

RUN mkdir -p /app/config /app/data /app/logs /app/.cache && \
    chown -R ${UID}:${GID} /app/config /app/data /app/logs /app/.cache

COPY --chown=${UID}:${GID} src /app/src
COPY --chown=${UID}:${GID} scripts /app/scripts
COPY --chown=${UID}:${GID} bot.py /app/bot.py
COPY --chown=${UID}:${GID} LICENSE README.md THIRD_PARTY_NOTICES.md REUSE.toml /usr/share/doc/dreamrain-bot/
COPY --from=builder --chown=${UID}:${GID} /app/DEPENDENCY_LICENSES.json /usr/share/doc/dreamrain-bot/DEPENDENCY_LICENSES.json

# 复制并设置入口脚本
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && \
    chown ${UID}:${GID} /app/entrypoint.sh

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "print('healthy')" || exit 1

EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
CMD ["uv", "run", "bot.py"]
