# 群晖 NAS 系统部署指南

本指南专门针对群晖 NAS 系统用户，解决容器权限问题，确保 emby-actor-processor 能够正常运行。

## 🚀 一键部署 (推荐)

最简单的部署方式是使用我们提供的一键部署脚本：

```bash
# SSH 登录到群晖系统
ssh admin@your-synology-ip

# 下载项目
git clone https://github.com/NasPilot/emby-actor-processor.git
cd emby-actor-processor

# 一键部署（脚本会自动检测群晖系统）
./deploy.sh
```

脚本会自动：
- 检测群晖系统并使用专用配置
- 创建 `/volume1/docker/emby-actor-processor` 数据目录
- 设置正确的权限 (1026:100)
- 拉取最新镜像并启动容器

如果需要自定义数据目录：
```bash
./deploy.sh -d /volume2/docker/emby-actor-processor
```

---

## 📋 手动部署

如果您需要更多控制或一键部署脚本无法满足需求，可以参考以下手动部署方法。

### 问题背景

原始的 Docker 配置在群晖系统下存在以下权限问题：
- 容器内创建的文件所有者是 UID=1000，但群晖系统中不存在此用户
- 群晖默认管理员用户的 UID=1026，与容器内用户不匹配
- 导致容器无法对挂载目录进行写入操作

## 解决方案

新的 Docker 配置通过以下方式解决权限问题：
1. 使用 `gosu` 工具以指定用户身份运行应用
2. 启动脚本动态调整容器内用户的 UID/GID
3. 运行时设置正确的目录权限
4. 支持 UMASK 配置

## 部署步骤

### 1. 准备数据目录

首先，在群晖系统中创建数据目录：

```bash
# SSH 登录到群晖系统，然后执行：
sudo mkdir -p /volume1/docker/emby-actor-processor
sudo chown 1026:100 /volume1/docker/emby-actor-processor
sudo chmod 755 /volume1/docker/emby-actor-processor
```

### 2. 使用 Docker Compose（推荐）

将 `docker-compose.synology.yml` 文件上传到群晖系统，然后：

```bash
# 进入包含 docker-compose.synology.yml 的目录
cd /path/to/your/compose/file

# 启动容器
docker-compose -f docker-compose.synology.yml up -d
```

### 3. 使用 Docker 命令行

如果不使用 Docker Compose，可以直接使用 docker run 命令：

```bash
docker run -d \
  --name emby-actor-processor \
  -p 5257:5257 \
  -e PUID=1026 \
  -e PGID=100 \
  -e UMASK=022 \
  -e TZ=Asia/Shanghai \
  -e AUTH_USERNAME=admin \
  -v /volume1/docker/emby-actor-processor:/config \
  --restart unless-stopped \
  NasPilot/emby-actor-processor:latest
```

### 4. 使用群晖 Docker 图形界面

1. 打开群晖的 Docker 套件
2. 在「映像」中搜索或导入 emby-actor-processor 镜像
3. 创建容器时设置以下参数：

**环境变量：**
- `PUID=1026`
- `PGID=100`
- `UMASK=022`
- `TZ=Asia/Shanghai`
- `AUTH_USERNAME=admin`

**网络设置：**
- 网络模式：bridge（推荐）或 host
- 端口映射：5257:5257（仅 bridge 模式需要）

**存储空间：**
- 装载路径：`/volume1/docker/emby-actor-processor`
- 装载点：`/config`

## 环境变量说明

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| PUID | 1000 | 用户 ID，群晖建议设置为 1026 |
| PGID | 100 | 组 ID，群晖建议设置为 100 |
| UMASK | 022 | 文件权限掩码 |
| TZ | UTC | 时区设置 |
| AUTH_USERNAME | admin | Web 界面登录用户名 |

## 网络模式配置

### Bridge 模式（推荐）

**特点：**
- 容器使用独立的网络命名空间
- 通过端口映射访问服务
- 更好的网络隔离和安全性
- 避免端口冲突

**配置方法：**
```yaml
network_mode: bridge
ports:
  - "5257:5257"
```

### Host 模式

**特点：**
- 容器直接使用宿主机网络
- 更好的网络性能
- 可能存在端口冲突风险
- 适合对网络性能要求较高的场景

**配置方法：**
```yaml
network_mode: host
# 注意：host 模式下不需要端口映射
```

**使用建议：**
- 一般情况下推荐使用 bridge 模式
- 如果遇到网络性能问题，可以尝试 host 模式
- 使用 host 模式前请确保端口 5257 未被占用

## 权限验证

容器启动后，可以通过以下方式验证权限设置是否正确：

1. 查看容器日志：
```bash
docker logs emby-actor-processor
```

应该看到类似输出：
```
Starting with PUID=1026, PGID=100, UMASK=022
Updating user/group IDs to PUID=1026, PGID=100
Starting application as user appuser (1026:100)
```

2. 检查配置文件权限：
```bash
# 在群晖系统中检查
ls -la /volume1/docker/emby-actor-processor/
```

应该看到文件所有者为 1026:100。

## 故障排除

### 问题 1：容器无法启动

**可能原因：**
- 数据目录不存在或权限不正确

**解决方法：**
```bash
sudo mkdir -p /volume1/docker/emby-actor-processor
sudo chown 1026:100 /volume1/docker/emby-actor-processor
sudo chmod 755 /volume1/docker/emby-actor-processor
```

### 问题 2：配置文件无法保存

**可能原因：**
- PUID/PGID 设置不正确
- 目录权限问题

**解决方法：**
1. 确认环境变量设置正确
2. 重新设置目录权限
3. 重启容器

### 问题 3：数据库文件权限错误

**可能原因：**
- 旧的数据库文件权限不正确

**解决方法：**
```bash
# 修复现有文件权限
sudo chown -R 1026:100 /volume1/docker/emby-actor-processor/
sudo find /volume1/docker/emby-actor-processor/ -type f -exec chmod 644 {} \;
sudo find /volume1/docker/emby-actor-processor/ -type d -exec chmod 755 {} \;
```

## 升级注意事项

从旧版本升级时：

1. 停止旧容器
2. 备份数据目录
3. 修复文件权限（如上所示）
4. 使用新的配置启动容器

## 安全建议

1. 不要使用 root 用户运行容器
2. 定期备份配置文件和数据库
3. 限制容器的网络访问权限
4. 定期更新镜像版本

## 技术细节

新的 Dockerfile 主要改进：

1. **动态用户管理：** 启动脚本会根据环境变量动态调整容器内用户的 UID/GID
2. **权限修复：** 自动设置 /config 目录的正确权限
3. **gosu 工具：** 使用 gosu 而不是 su 来切换用户，避免信号处理问题
4. **UMASK 支持：** 支持设置文件创建权限掩码

这些改进确保了容器在群晖系统中的兼容性和稳定性。