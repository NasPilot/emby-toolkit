# GitHub Actions Docker 构建配置指南

本文档说明如何配置 GitHub Actions 自动构建和推送 Docker 镜像到 Docker Hub。

## 前置要求

1. **Docker Hub 账户**: 确保你有 Docker Hub 账户 (NasPilot)
2. **GitHub 仓库**: 项目已 fork 到你的 GitHub 仓库 (NasPilot/emby-actor-processor)

## 配置步骤

### 1. 创建 Docker Hub 访问令牌

1. 登录 [Docker Hub](https://hub.docker.com/)
2. 点击右上角头像 → **Account Settings**
3. 选择 **Security** 标签页
4. 点击 **New Access Token**
5. 输入令牌名称（如：`github-actions`）
6. 选择权限：**Read, Write, Delete**
7. 点击 **Generate** 并**复制生成的令牌**（只显示一次）

### 2. 配置 GitHub Secrets

1. 进入你的 GitHub 仓库：`https://github.com/NasPilot/emby-actor-processor`
2. 点击 **Settings** 标签页
3. 在左侧菜单选择 **Secrets and variables** → **Actions**
4. 点击 **New repository secret** 添加以下密钥：

   **DOCKER_USERNAME**
   - Name: `DOCKER_USERNAME`
   - Secret: `NasPilot` (你的 Docker Hub 用户名)

   **DOCKER_PASSWORD**
   - Name: `DOCKER_PASSWORD`
   - Secret: `<刚才复制的访问令牌>`

### 3. 触发构建

GitHub Actions 会在以下情况自动触发：

- **推送到 main 分支**: 构建并推送 `latest` 标签
- **推送到 dev 分支**: 构建并推送 `dev` 标签
- **创建 Git 标签** (如 `v1.0.0`): 构建并推送版本标签
- **Pull Request**: 仅构建，不推送
- **手动触发**: 在 Actions 页面手动运行

### 4. 验证构建

1. 推送代码到仓库后，访问 **Actions** 标签页
2. 查看构建状态和日志
3. 构建成功后，检查 [Docker Hub](https://hub.docker.com/r/NasPilot/emby-actor-processor) 是否有新镜像

## 支持的平台

构建的 Docker 镜像支持以下平台：
- `linux/amd64` (x86_64)
- `linux/arm64` (ARM64)
- `linux/arm/v7` (ARM32)

## 镜像标签说明

- `latest`: 最新的 main 分支构建
- `dev`: 开发分支构建
- `v1.0.0`: 语义化版本标签
- `1.0`: 主要版本标签
- `1`: 大版本标签
- `pr-123`: Pull Request 构建（仅构建，不推送）

## 故障排除

### 构建失败

1. **权限错误**: 检查 Docker Hub 令牌权限
2. **认证失败**: 验证 GitHub Secrets 配置
3. **网络问题**: 重新运行 workflow

### 推送失败

1. **仓库不存在**: 确保 Docker Hub 仓库 `NasPilot/emby-actor-processor` 存在
2. **权限不足**: 检查访问令牌权限

### 手动创建 Docker Hub 仓库

如果仓库不存在，需要手动创建：

1. 登录 Docker Hub
2. 点击 **Create Repository**
3. 仓库名称：`emby-actor-processor`
4. 可见性：**Public** 或 **Private**
5. 点击 **Create**

## 本地测试

在推送前，可以本地测试构建：

```bash
# 构建镜像
./build.sh --test

# 或手动构建
docker build -t NasPilot/emby-actor-processor:test .

# 测试运行
docker run -d -p 5257:5257 -v ./test-data:/config NasPilot/emby-actor-processor:test
```

---

**注意**: 请妥善保管 Docker Hub 访问令牌，不要在代码中硬编码或公开分享。