#!/bin/bash
set -e

# 设置环境变量默认值
PUID=${PUID:-1000}
PGID=${PGID:-100}
UMASK=${UMASK:-022}

echo "=== Emby Actor Processor 容器启动 ==="
echo "PUID: $PUID"
echo "PGID: $PGID"
echo "UMASK: $UMASK"
echo "时区: ${TZ:-UTC}"
echo "========================================"

# 确保 /config 目录存在
if [ ! -d "/config" ]; then
    echo "创建 /config 目录..."
    mkdir -p /config
fi

# 设置 umask
echo "设置 umask 为 $UMASK"
umask $UMASK

# 检查是否需要修改用户和组的 ID
CURRENT_UID=$(id -u appuser)
CURRENT_GID=$(id -g appuser)

if [ "$PUID" != "$CURRENT_UID" ] || [ "$PGID" != "$CURRENT_GID" ]; then
    echo "更新用户/组 ID: $CURRENT_UID:$CURRENT_GID -> $PUID:$PGID"
    
    # 修改组 ID
    if [ "$PGID" != "$CURRENT_GID" ]; then
        echo "修改组 ID 为 $PGID"
        groupmod -g $PGID appuser 2>/dev/null || {
            echo "警告: 无法修改组 ID，可能已存在相同 GID 的组"
        }
    fi
    
    # 修改用户 ID
    if [ "$PUID" != "$CURRENT_UID" ]; then
        echo "修改用户 ID 为 $PUID"
        usermod -u $PUID appuser 2>/dev/null || {
            echo "警告: 无法修改用户 ID，可能已存在相同 UID 的用户"
        }
    fi
else
    echo "用户/组 ID 已正确设置: $PUID:$PGID"
fi

# 设置目录权限
echo "设置 /config 目录权限..."
chown -R $PUID:$PGID /config
chmod -R 755 /config

echo "设置 /app 目录权限..."
chown -R $PUID:$PGID /app

# 设置 APP_DATA_DIR 环境变量
export APP_DATA_DIR=/config
echo "设置 APP_DATA_DIR=/config"

# 显示最终的用户信息
echo "========================================"
echo "最终用户信息:"
echo "用户: $(id appuser)"
echo "工作目录: $(pwd)"
echo "APP_DATA_DIR: $APP_DATA_DIR"
echo "========================================"

# 检查关键文件权限
if [ -f "/config/config.ini" ]; then
    echo "配置文件权限: $(ls -la /config/config.ini)"
fi

if [ -f "/config/emby_actor_processor.sqlite" ]; then
    echo "数据库文件权限: $(ls -la /config/emby_actor_processor.sqlite)"
fi

echo "启动应用程序..."
echo "========================================"

# 使用 gosu 以指定用户身份运行应用
exec gosu appuser python web_app.py