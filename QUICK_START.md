# 🚀 快速开始指南

这是 Emby Actor Processor 的快速部署指南，让您在几分钟内完成部署。

## 📋 系统要求

- Docker 和 Docker Compose
- Git（用于下载项目）
- 网络连接（用于拉取镜像）

## ⚡ 一键部署

### 1. 下载项目

```bash
git clone https://github.com/NasPilot/emby-actor-processor.git
cd emby-actor-processor
```

### 2. 运行部署脚本

```bash
# 自动检测系统并部署
./deploy.sh
```

脚本会自动：
- ✅ 检测您的系统类型（通用 Linux 或群晖 NAS）
- ✅ 创建数据目录并设置正确权限
- ✅ 拉取最新的 Docker 镜像
- ✅ 启动容器服务
- ✅ 显示访问信息

### 3. 访问服务

部署完成后，访问：`http://您的服务器IP:5257`

- **默认用户名**：`admin`
- **默认密码**：查看容器日志获取随机生成的密码

```bash
# 查看容器日志获取密码
docker logs emby-actor-processor
```

## 🔧 高级选项

### 自定义数据目录

```bash
./deploy.sh -d /path/to/your/data
```

### 自定义端口

```bash
./deploy.sh -p 8080
```

### 强制指定系统类型

```bash
# 强制使用群晖配置
./deploy.sh -s synology

# 强制使用通用配置
./deploy.sh -s generic
```

### 只准备环境不启动

```bash
./deploy.sh --no-start
# 然后手动启动
docker-compose -f docker-compose.deploy.yml up -d
```

## 📱 常用管理命令

```bash
# 查看服务状态
docker ps

# 查看日志
docker logs emby-actor-processor

# 停止服务
docker stop emby-actor-processor

# 重启服务
docker restart emby-actor-processor

# 更新到最新版本
./deploy.sh --no-start
docker-compose -f docker-compose.deploy.yml up -d
```

## 🆘 故障排除

### 权限问题

如果遇到权限问题，手动设置数据目录权限：

```bash
# 通用 Linux 系统
sudo chown -R $USER:$USER ./data

# 群晖系统
sudo chown -R 1026:100 /volume1/docker/emby-actor-processor
```

### 端口冲突

如果 5257 端口被占用：

```bash
./deploy.sh -p 8080  # 使用其他端口
```

### 网络问题

如果无法拉取镜像：

```bash
./deploy.sh --no-pull  # 跳过镜像拉取
```

## 📚 更多信息

- [完整部署文档](README.md)
- [群晖专用指南](SYNOLOGY_SETUP.md)
- [Docker 改进说明](DOCKER_IMPROVEMENTS.md)

## 🎯 下一步

1. 访问 Web 界面：`http://您的IP:5257`
2. 配置 Emby 服务器连接
3. 设置 TMDb API Key
4. 开始处理您的媒体库！

---

**需要帮助？** 请查看 [GitHub Issues](https://github.com/NasPilot/emby-actor-processor/issues) 或提交新的问题。