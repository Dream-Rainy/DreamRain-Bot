#!/bin/bash
set -e

# 默认使用环境变量中的 UID/GID
USER_ID=${UID:-1000}
GROUP_ID=${GID:-1001}

echo "Starting container with UID=${USER_ID}, GID=${GROUP_ID}"

# 确保 bind-mount 文件对非 root 用户可读（Docker Desktop on Windows 已知问题）
# bind mount 的文件在容器内常显示为 root:root，chown 无效，只能用 chmod
echo "Ensuring bind-mounted files are readable by non-root user..."
chmod -R o+r /app/src /app/bot.py 2>/dev/null || true
chmod -R o+r /app/.env.prod 2>/dev/null || true
# 数据目录需要写权限
chmod -R o+rw /app/data 2>/dev/null || true

for dir in /app/src /app/config /app/data /app/logs; do
    if [ -d "$dir" ]; then
        # 只 chown 顶层目录，不递归
        chown "$USER_ID:$GROUP_ID" "$dir" 2>/dev/null || \
            echo "  [info] $dir is bind-mounted (this is expected)"
    fi
done

if [ -d "/app/data" ] && [ "$(find /app/data -maxdepth 0 -user root 2>/dev/null)" ]; then
    echo "Fixing /app/data permissions..."
    chown -R "$USER_ID:$GROUP_ID" /app/data 2>/dev/null || true
fi

echo "Switching to user appuser (${USER_ID}:${GROUP_ID})..."

# 使用 gosu 切换到目标用户并执行命令
exec gosu ${USER_ID}:${GROUP_ID} "$@"
