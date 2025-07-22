# Emby Actor Processor (Emby 演员管理工具)

[![GitHub stars](https://img.shields.io/github/stars/hbq0405/emby-actor-processor.svg?style=social&label=Star)](https://github.com/hbq0405/emby-actor-processor)
[![GitHub license](https://img.shields.io/github/license/hbq0405/emby-actor-processor.svg)](https://github.com/hbq0405/emby-actor-processor/blob/main/LICENSE)
<!-- 你可以添加更多的徽章，例如构建状态、Docker Hub 拉取次数等 -->

一个用于处理和增强 Emby 媒体库中演员信息的工具，包括但不限于演员名称翻译、信息补全（从豆瓣、TMDb等）、以及演员映射管理。
2.6.4之后版本不再支持非神医Pro用户！！！
## ✨ 功能特性

*   **演员信息处理**：自动翻译演员名、角色名、从豆瓣数据源获取中文角色名。
*   **外部数据源集成**：从豆瓣获取更补充的演员信息，通过TMDB比对（如TMDBID、IMDBID充实演员映射表）。
*   **演员映射管理**：允许用户手动或自动同步 Emby 演员与外部数据源演员的映射关系，还可以直接导入别人分享的演员映射表。
*   **处理质量评估**：程序综合各方面因素自动对处理后的演员信息进行打分，低于阈值（自行设置）的分数会列入待复核列表，方便用户手动重新处理，特别是外语影视，机翻的效果很尬的。
*   **定时任务**：支持定时全量扫描媒体库和同步人物映射表。
*   **Docker 支持**：易于通过 Docker 部署和运行。
*   **实时处理新片**：自动处理Emby新入库资源，需配置webhook:http://ip:5257/webhook/emby 请求内容类型：application/json 勾选：【新媒体已添加】和【按剧集和专辑对通知进行分组】。
*   **自动追剧**：神医Pro用户覆盖缓存无法更新剧集简介的问题可以通过自动追剧来更新简介


## 🚀 快速开始

### 先决条件

*   已安装 Docker 和 Docker Compose (推荐)。
*   一个 Emby 服务器。
*   TMDb API Key (v3 Auth)。

### Docker 部署 (推荐)

这是最简单和推荐的部署方式。

1.  **准备持久化数据目录**：
    在你的服务器上（例如 NAS）创建一个目录，用于存放应用的配置文件和数据库。例如：
    ```bash
    mkdir -p /path/app_data/emby_actor_processor/config
    ```
    请将 `/path/app_data/emby_actor_processor/config` 替换为你实际的路径。

2.  **使用 `docker-compose.yml` (推荐)**：
    创建一个 `docker-compose.yml` 文件，内容如下：

    ```yaml
    version: '3'

    services:
      emby-actor-processor:
        image: hbq0405/emby-actor-processor:latest 
        container_name: emby-actor-processor
        network_mode: bridge
        ports:
          - "5257:5257"              # 将容器的 5257 端口映射到宿主机的 5257 端口 (左边可以改成你希望的宿主机端口)
        volumes:
          - /path/config:/config     # 将宿主机的数据目录挂载到容器的 /config 目录
          - /path/tmdb:/tmdb         # 映射神医本地TMDB目录，必须配置
        environment:
          - TZ=Asia/Shanghai         # 设置容器时区
          - AUTH_USERNAME=admin      # 用户名可任意设置，密码在程序首次运行会生成随机密码打印在日志中
          - PUID=0                   # 设置为您的用户ID，建议与宿主机用户ID保持一致
          - PGID=0                   # 设置为您的组ID，建议与宿主机组ID保持一致
          - UMASK=000                # 设置文件权限掩码，建议022
        restart: unless-stopped
    ```
    然后在 `docker-compose.yml` 文件所在的目录下运行：
    ```bash
    docker-compose up -d
    ```

3.  **或者使用 `docker run` 命令**：
    ```bash
    docker run -d \
      --name emby-actor-processor \
      --network bridge \
      -p 5257:5257 \
      -v /path/config:/config \
      -v /path/tmdb:/tmdb \
      -e TZ="Asia/Shanghai" \
      -e AUTH_USERNAME="admin" \
      -e PUID=0 \
      -e PGID=0 \
      -e UMASK=000 \
      --restart unless-stopped \
      hbq0405/emby-actor-processor:latest
    ```
    同样，请替换占位符。

4.  **首次配置**：
    *   通过容器启动日志查找随机生成的密码
    *   容器启动后，通过浏览器访问 `http://<你的服务器IP>:5257`。
    *   进入各个设置页面（Emby配置、通用设置），填写必要的 API Key 和服务器信息。
    *   **点击保存。** 这会在你挂载的 `/config` 目录下（即宿主机的 `/path/to/your/app_data/emby_actor_processor_config` 目录）创建 `config.ini` 文件和 `emby_actor_processor.sqlite` 数据库文件。


## ⚙️ 配置项说明

应用的主要配置通过 Web UI 进行，并保存在 `config.ini` 文件中。关键配置项包括：

*   **Emby 配置**:
    *   Emby 服务器 URL
    *   Emby API Key
    *   Emby 用户 ID 
    *   要处理的媒体库
*   **通用设置**:
    *   基础设置

## 🔒 用户权限管理

本应用采用了创建专用的非root用户权限管理机制，确保容器内的应用以非root用户运行，同时保持对挂载卷的正确访问权限。

### 环境变量说明

*   **PUID**：用户ID，建议设置为宿主机上拥有媒体文件访问权限的用户ID
*   **PGID**：组ID，建议设置为宿主机上拥有媒体文件访问权限的组ID
*   **UMASK**：文件权限掩码，控制新创建文件的权限，建议022表示新文件权限为755(目录)和644(文件)
*   **APP_DATA_DIR**：应用数据目录，已在镜像中默认设置为`/config`，无需在运行时重复指定

### 工作原理

1. 容器内创建了一个固定UID/GID为918的`embyactor`用户
2. 启动时，entrypoint.sh脚本会根据环境变量PUID和PGID动态修改`embyactor`用户的UID和GID
3. 应用以`embyactor`用户身份运行，而不是root用户
4. 所有挂载的卷和应用目录的所有权会被更改为`embyactor`用户

### 权限问题排查

如果遇到权限问题，请尝试以下步骤：

1. 确认PUID和PGID设置正确，可以通过在宿主机上运行`id`命令查看当前用户的UID和GID
2. 检查挂载目录的权限，确保指定的PUID/PGID用户有权访问
3. 如果使用NAS或特殊文件系统，可能需要调整UMASK值，例如使用000以允许最大权限
    *   翻译设置
    *   本地数据源路径 (神医Pro版本地TMDB目录)
*   **定时任务配置**:
    *   是否启用定时全量扫描及 CRON 表达式
    *   是否强制重处理所有项目 (定时任务)
    *   是否启用定时同步人物映射表及 CRON 表达式
    *   定时刷新追剧列表剧集简介
*   **手动处理**:
    *   一键翻译
    *   手动编辑演员、角色名
    *   手动添加剧集为追更剧

## 🛠️ 任务中心


*   **全量媒体库扫描**: 扫描并处理所有选定媒体库中的项目。
    *   可选择是否“强制重新处理所有项目”。
*   **同步Emby人物映射表**: 从 Emby 服务器拉取所有人物信息，并更新到本地的 `person_identity_map` 数据库表中。
    *   可选择是否“强制重新处理此项目”。
*   **停止当前任务**: 尝试停止当前正在后台运行的任务。

## 📝 日志

*   应用日志默认会输出到任务中心，同时会在配置目录生成日志文件。
*   可以在任务中心查看历史日志，通过搜索定位完整处理过程。

