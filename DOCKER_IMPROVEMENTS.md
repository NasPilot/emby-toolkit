# Docker 容器权限问题修复说明

## 问题描述

原始的 Docker 配置在群晖 NAS 系统下存在严重的权限问题：

1. **用户 ID 不匹配**：容器内使用 UID=1000，但群晖默认管理员用户为 UID=1026
2. **文件所有权错误**：生成的配置文件和数据库文件所有者为不存在的用户
3. **权限设置固化**：无法在运行时动态调整用户权限
4. **群晖兼容性差**：需要设置 Everyone 写入权限才能正常使用

## 解决方案

### 1. 动态用户管理

**改进前：**
```dockerfile
# 固定的用户创建
RUN useradd -m -u 1000 -g 100 myuser
USER myuser
```

**改进后：**
```dockerfile
# 支持运行时调整的用户创建
ARG PUID=1000
ARG PGID=100
RUN groupadd -g $PGID appuser || true
RUN useradd -m -u $PUID -g $PGID -s /bin/bash appuser || true
```

### 2. 启动脚本权限处理

新增 `entrypoint.sh` 脚本，在容器启动时：

- 根据环境变量动态调整用户 UID/GID
- 自动设置目录权限
- 支持 UMASK 配置
- 使用 `gosu` 安全地切换用户

### 3. 配置目录标准化

**改进前：**
- 数据存储在 `/app/local_data`
- 路径不符合容器最佳实践

**改进后：**
- 统一使用 `/config` 作为数据目录
- 符合 LinuxServer.io 标准
- 更好的数据持久化管理

### 4. 群晖专用配置

创建 `docker-compose.synology.yml`，专门针对群晖系统优化：

```yaml
services:
  emby-actor-processor:
    environment:
      - PUID=1026    # 群晖默认管理员 UID
      - PGID=100     # 群晖 users 组 GID
      - UMASK=022    # 适合的权限掩码
```

## 技术改进详情

### 1. Dockerfile 优化

- **添加 gosu 工具**：安全的用户切换，避免 PID 1 问题
- **参数化用户创建**：支持构建时和运行时用户配置
- **移除固定权限设置**：改为运行时动态设置

### 2. 启动脚本功能

`entrypoint.sh` 提供以下功能：

- **用户 ID 检查和修改**：自动调整到指定的 PUID/PGID
- **目录权限修复**：确保 `/config` 和 `/app` 目录权限正确
- **环境变量设置**：自动设置 `APP_DATA_DIR=/config`
- **详细日志输出**：便于调试权限问题
- **错误处理**：优雅处理用户/组 ID 冲突

### 3. 构建和部署工具

- **build.sh**：自动化构建脚本，支持多平台构建和测试
- **SYNOLOGY_SETUP.md**：详细的群晖部署指南
- **.dockerignore 优化**：排除不必要的文件，减小镜像体积

## 使用方法

### 标准部署

```bash
docker run -d \
  --name emby-actor-processor \
  -p 5257:5257 \
  -v ./config:/config \
  -e PUID=1000 \
  -e PGID=100 \
  -e UMASK=022 \
  emby-actor-processor:latest
```

### 群晖部署

```bash
# 创建数据目录
sudo mkdir -p /volume1/docker/emby-actor-processor
sudo chown 1026:100 /volume1/docker/emby-actor-processor

# 启动容器
docker run -d \
  --name emby-actor-processor \
  -p 5257:5257 \
  -v /volume1/docker/emby-actor-processor:/config \
  -e PUID=1026 \
  -e PGID=100 \
  -e UMASK=022 \
  emby-actor-processor:latest
```

## 验证方法

### 1. 检查容器日志

```bash
docker logs emby-actor-processor
```

应该看到类似输出：
```
=== Emby Actor Processor 容器启动 ===
PUID: 1026
PGID: 100
UMASK: 022
更新用户/组 ID: 1000:100 -> 1026:100
启动应用程序...
```

### 2. 检查文件权限

```bash
# 群晖系统中检查
ls -la /volume1/docker/emby-actor-processor/
```

文件所有者应该是 `1026:100`。

### 3. 功能测试

- 访问 Web 界面：`http://your-nas-ip:5257`
- 修改配置并保存
- 检查配置文件是否正确更新

## 兼容性

### 支持的系统

- ✅ 群晖 DSM 6.x/7.x
- ✅ 标准 Linux 发行版
- ✅ Docker Desktop (Windows/macOS)
- ✅ Unraid
- ✅ TrueNAS

### 支持的架构

- ✅ linux/amd64
- ✅ linux/arm64
- ✅ linux/arm/v7

## 迁移指南

### 从旧版本升级

1. **停止旧容器**：
   ```bash
   docker stop emby-actor-processor
   docker rm emby-actor-processor
   ```

2. **备份数据**：
   ```bash
   cp -r /path/to/old/local_data /path/to/backup
   ```

3. **创建新的配置目录**：
   ```bash
   mkdir -p /path/to/new/config
   cp /path/to/old/local_data/* /path/to/new/config/
   ```

4. **修复权限**（群晖）：
   ```bash
   sudo chown -R 1026:100 /path/to/new/config
   ```

5. **启动新容器**：
   使用新的配置启动容器。

## 故障排除

### 常见问题

1. **容器无法启动**
   - 检查数据目录是否存在
   - 确认 PUID/PGID 设置正确
   - 查看容器日志获取详细错误信息

2. **配置无法保存**
   - 检查目录权限
   - 确认 UMASK 设置
   - 验证用户 ID 映射

3. **数据库访问错误**
   - 检查 SQLite 文件权限
   - 确认目录可写
   - 重启容器重新初始化

### 调试命令

```bash
# 进入容器检查
docker exec -it emby-actor-processor bash

# 检查用户信息
id appuser

# 检查目录权限
ls -la /config

# 检查进程
ps aux
```

## 总结

通过这些改进，emby-actor-processor 现在：

- ✅ 完全兼容群晖 NAS 系统
- ✅ 支持动态用户权限配置
- ✅ 遵循容器最佳实践
- ✅ 提供详细的部署文档
- ✅ 包含自动化构建和测试工具

不再需要设置 Everyone 写入权限，文件所有权也会正确匹配系统用户，大大提升了安全性和易用性。