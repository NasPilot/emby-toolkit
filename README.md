# Emby Actor Processor (Emby 演员管理工具)

[![GitHub stars](https://img.shields.io/github/stars/NasPilot/emby-actor-processor.svg?style=social&label=Star)](https://github.com/NasPilot/emby-actor-processor)
[![GitHub license](https://img.shields.io/github/license/NasPilot/emby-actor-processor.svg)](https://github.com/NasPilot/emby-actor-processor/blob/main/LICENSE)
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

**⚡ 想要立即开始？** 查看我们的 [快速开始指南](QUICK_START.md)，几分钟内完成部署！

### 先决条件

*   已安装 Docker 和 Docker Compose (推荐)。
*   一个 Emby 服务器。
*   TMDb API Key (v3 Auth)。

### Docker 部署 (推荐)

这是最简单和推荐的部署方式。我们提供了多种部署选项：

#### 🚀 一键部署脚本 (最简单)

我们提供了智能一键部署脚本，可以自动检测系统类型并选择合适的配置：

```bash
# 下载项目
git clone https://github.com/NasPilot/emby-actor-processor.git
cd emby-actor-processor

# 一键部署
./deploy.sh
```

**脚本功能：**
- 自动检测系统类型（通用 Linux 或群晖 NAS）
- 自动创建数据目录并设置正确权限
- 拉取最新镜像并启动容器
- 提供详细的部署状态和访问信息

**高级选项：**
```bash
./deploy.sh -h                    # 查看帮助
./deploy.sh -d /custom/path       # 指定数据目录
./deploy.sh -s synology           # 强制使用群晖配置
./deploy.sh --no-pull --no-start  # 只准备环境，不启动
```

#### 📋 手动 Docker Compose 部署

如果需要更多控制，可以使用预配置的 Docker Compose 文件：

- **`docker-compose.yml`** - 通用版本，适用于大多数 Linux 系统
- **`docker-compose.synology.yml`** - 群晖专用版本，解决权限问题

#### 通用部署（推荐）

适用于 Ubuntu、CentOS、Debian 等标准 Linux 系统。

1.  **准备数据目录**：
    ```bash
    mkdir -p ./data
    # 确保目录权限正确
    sudo chown -R $USER:$USER ./data
    ```

2.  **使用标准配置文件**：
    ```bash
    # 下载或使用项目中的 docker-compose.yml
    docker-compose up -d
    ```

3.  **自定义配置**：
    根据需要修改 `docker-compose.yml` 中的以下配置：
    - `PUID` 和 `PGID`：使用 `id` 命令查看你的用户 ID
    - `volumes`：调整数据目录路径
    - `TZ`：设置你的时区

#### 群晖 NAS 部署

群晖系统用户请使用专用配置文件：

```bash
# 使用群晖专用配置
docker-compose -f docker-compose.synology.yml up -d
```

详细的群晖部署说明请参考：[群晖部署指南](SYNOLOGY_SETUP.md)

#### 手动 Docker 命令部署

如果不使用 Docker Compose，也可以直接使用 docker run 命令：

**通用系统：**
```bash
docker run -d \
  --name emby-actor-processor \
  -p 5257:5257 \
  -v ./data:/config \
  -e PUID=1000 \
  -e PGID=1000 \
  -e UMASK=022 \
  -e TZ=Asia/Shanghai \
  -e AUTH_USERNAME=admin \
  --restart unless-stopped \
  NasPilot/emby-actor-processor:latest
```

**群晖系统：**
```bash
docker run -d \
  --name emby-actor-processor \
  -p 5257:5257 \
  -v /volume1/docker/emby-actor-processor:/config \
  -e PUID=1026 \
  -e PGID=100 \
  -e UMASK=022 \
  -e TZ=Asia/Shanghai \
  -e AUTH_USERNAME=admin \
  --restart unless-stopped \
  NasPilot/emby-actor-processor:latest
```

#### 环境变量说明

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| PUID | 1000 | 用户 ID（群晖系统建议设置为 1026）|
| PGID | 1000 | 组 ID（群晖系统建议设置为 100）|
| UMASK | 022 | 文件权限掩码 |
| TZ | Asia/Shanghai | 时区设置 |
| AUTH_USERNAME | admin | Web 界面登录用户名 |
| APP_DATA_DIR | /config | 数据目录（已在镜像中预设）|

#### 网络模式配置

两个 compose 文件都支持灵活的网络模式配置：

- **bridge 模式**（默认推荐）：使用端口映射，更安全，避免端口冲突
- **host 模式**：直接使用宿主机网络，性能更好但可能有端口冲突

修改 `network_mode` 参数即可切换：
```yaml
# Bridge 模式（推荐）
network_mode: bridge
ports:
  - "5257:5257"

# Host 模式（高性能）
network_mode: host
# 注意：host 模式下不需要 ports 配置
```

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

