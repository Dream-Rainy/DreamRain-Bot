FROM astral/uv:python3.12-bookworm-slim AS builder
WORKDIR /build
ENV UV_PROJECT_ENVIRONMENT=/build/.venv \
    UV_DEFAULT_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple" \
    UV_COMPILE_BYTECODE=1 \
    UV_CACHE_DIR=/build/.cache/uv \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8
COPY pyproject.toml uv.lock* ./
RUN uv sync --locked --no-dev && \
    uvx pip-licenses \
        --python /build/.venv/bin/python \
        --format=json \
        --with-urls \
        --with-authors \
        --with-description \
        --output-file /build/DEPENDENCY_LICENSES.json

FROM astral/uv:python3.12-bookworm-slim

RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y ffmpeg libsm6 libxext6 freeglut3-dev tini fontconfig wget ca-certificates \
    # 安装 CJK 字体
    fonts-noto-cjk fonts-noto-cjk-extra fonts-wqy-zenhei fonts-wqy-microhei fonts-noto-color-emoji \
    # 安装语言包
    locales && \
    # 配置 UTF-8 locale
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    echo "C.UTF-8 UTF-8" >> /etc/locale.gen && \
    locale-gen && \
    # 安装 gosu
    set -eux; \
    apt-get install -y gosu && \
    # 验证 gosu 安装
    gosu nobody true && \
    # 更新字体缓存
    fc-cache -fv && \
    # 清理
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
COPY --from=builder --chown=${UID}:${GID} /build/.venv /app/.venv

RUN mkdir -p /app/config /app/data /app/logs /app/.cache && \
    chown -R ${UID}:${GID} /app/config /app/data /app/logs /app/.cache

COPY --chown=${UID}:${GID} src /app/src
COPY --chown=${UID}:${GID} bot.py /app/bot.py
COPY --chown=${UID}:${GID} LICENSE README.md THIRD_PARTY_NOTICES.md REUSE.toml /usr/share/doc/dreamrain-bot/
COPY --from=builder --chown=${UID}:${GID} /build/DEPENDENCY_LICENSES.json /usr/share/doc/dreamrain-bot/DEPENDENCY_LICENSES.json

# 复制并设置入口脚本
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && \
    chown ${UID}:${GID} /app/entrypoint.sh

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "print('healthy')" || exit 1

EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
CMD ["uv", "run", "bot.py"]
