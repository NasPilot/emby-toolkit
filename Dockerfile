# --- 阶段 1: 构建前端 ---
FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY emby-actor-ui/package.json emby-actor-ui/package-lock.json* ./emby-actor-ui/
WORKDIR /app/emby-actor-ui
RUN npm install --no-fund
COPY emby-actor-ui/ ./

# ✨✨✨ 在 install 之前增加清理缓存的步骤 ✨✨✨
RUN npm cache clean --force

# 使用 --verbose 参数获取更详细的日志，方便排错
RUN npm install --no-fund --verbose

COPY emby-actor-ui/ ./
RUN npm run build

# --- 阶段 2: 构建最终的生产镜像 ---
FROM python:3.11-slim

# 设置环境变量
ENV LANG="C.UTF-8" \
    TZ="Asia/Shanghai" \
    HOME="/embyactor" \
    CONFIG_DIR="/config" \
    APP_DATA_DIR="/config" \
    TERM="xterm" \
    PUID=0 \
    PGID=0 \
    UMASK=000

WORKDIR /app

# 安装必要的系统依赖和 Node.js
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y \
        nodejs \
        gettext-base \
        locales \
        procps \
        gosu \
        bash \
        wget \
        curl \
        dumb-init && \
    apt-get clean && \
    rm -rf \
        /tmp/* \
        /var/lib/apt/lists/* \
        /var/tmp/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝后端源码
COPY web_app.py .
COPY core_processor.py .
COPY douban.py .
COPY tmdb_handler.py .
COPY emby_handler.py .
COPY utils.py .
COPY logger_setup.py .
COPY constants.py .
COPY web_parser.py .  
COPY ai_translator.py . 
COPY watchlist_processor.py .
COPY actor_sync_handler.py .
COPY actor_utils.py .

COPY templates/ ./templates/ 

# 从前端构建阶段拷贝编译好的静态文件
COPY --from=frontend-build /app/emby-actor-ui/dist/. /app/static/

# 复制入口点脚本
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 创建用户和组
RUN mkdir -p ${HOME} && \
    groupadd -r embyactor -g 918 && \
    useradd -r embyactor -g embyactor -d ${HOME} -s /bin/bash -u 918

# 声明 /config 目录为数据卷
VOLUME [ "${CONFIG_DIR}" ]

EXPOSE 5257

# 设置容器入口点
ENTRYPOINT [ "/entrypoint.sh" ]