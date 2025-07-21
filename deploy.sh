#!/bin/bash

# Emby Actor Processor 一键部署脚本
# 支持自动检测系统类型并选择合适的部署配置

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 默认配置
IMAGE_NAME="NasPilot/emby-actor-processor:latest"
CONTAINER_NAME="emby-actor-processor"
PORT="5257"
DATA_DIR=""
SYSTEM_TYPE=""
FORCE_SYSTEM=""
PULL_IMAGE=true
START_CONTAINER=true

# 显示帮助信息
show_help() {
    echo "Emby Actor Processor 一键部署脚本"
    echo ""
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  -d, --data-dir DIR     数据目录路径 (默认: 自动选择)"
    echo "  -p, --port PORT        端口号 (默认: $PORT)"
    echo "  -s, --system TYPE      强制指定系统类型 (synology|generic)"
    echo "  --no-pull              不拉取最新镜像"
    echo "  --no-start             只准备环境，不启动容器"
    echo "  -h, --help             显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0                                    # 自动检测并部署"
    echo "  $0 -d /volume1/docker/emby-actor     # 指定数据目录"
    echo "  $0 -s synology                       # 强制使用群晖配置"
    echo "  $0 --no-pull --no-start              # 只准备环境"
}

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--data-dir)
            DATA_DIR="$2"
            shift 2
            ;;
        -p|--port)
            PORT="$2"
            shift 2
            ;;
        -s|--system)
            FORCE_SYSTEM="$2"
            shift 2
            ;;
        --no-pull)
            PULL_IMAGE=false
            shift
            ;;
        --no-start)
            START_CONTAINER=false
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo -e "${RED}错误: 未知选项 $1${NC}"
            show_help
            exit 1
            ;;
    esac
done

echo -e "${BLUE}=== Emby Actor Processor 一键部署 ===${NC}"
echo ""

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}错误: Docker 未安装或不在 PATH 中${NC}"
    echo "请先安装 Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

# 检查 Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo -e "${RED}错误: Docker Compose 未安装${NC}"
    echo "请先安装 Docker Compose"
    exit 1
fi

# 检测系统类型
detect_system() {
    if [ -n "$FORCE_SYSTEM" ]; then
        SYSTEM_TYPE="$FORCE_SYSTEM"
        echo -e "${YELLOW}强制指定系统类型: $SYSTEM_TYPE${NC}"
        return
    fi
    
    # 检测群晖系统
    if [ -f "/etc/synoinfo.conf" ] || [ -d "/volume1" ]; then
        SYSTEM_TYPE="synology"
        echo -e "${GREEN}检测到群晖 NAS 系统${NC}"
    else
        SYSTEM_TYPE="generic"
        echo -e "${GREEN}检测到通用 Linux 系统${NC}"
    fi
}

# 设置数据目录
setup_data_dir() {
    if [ -z "$DATA_DIR" ]; then
        if [ "$SYSTEM_TYPE" = "synology" ]; then
            DATA_DIR="/volume1/docker/emby-actor-processor"
        else
            DATA_DIR="$(pwd)/data"
        fi
    fi
    
    echo -e "${BLUE}数据目录: $DATA_DIR${NC}"
    
    # 创建数据目录
    if [ ! -d "$DATA_DIR" ]; then
        echo -e "${YELLOW}创建数据目录...${NC}"
        mkdir -p "$DATA_DIR"
    fi
    
    # 设置权限
    if [ "$SYSTEM_TYPE" = "synology" ]; then
        echo -e "${YELLOW}设置群晖权限...${NC}"
        sudo chown -R 1026:100 "$DATA_DIR" 2>/dev/null || {
            echo -e "${YELLOW}警告: 无法设置权限，请手动执行: sudo chown -R 1026:100 $DATA_DIR${NC}"
        }
    else
        echo -e "${YELLOW}设置通用权限...${NC}"
        sudo chown -R $USER:$USER "$DATA_DIR" 2>/dev/null || {
            echo -e "${YELLOW}警告: 无法设置权限，请确保当前用户对数据目录有读写权限${NC}"
        }
    fi
}

# 拉取镜像
pull_image() {
    if [ "$PULL_IMAGE" = true ]; then
        echo -e "${YELLOW}拉取最新镜像...${NC}"
        docker pull "$IMAGE_NAME"
        echo -e "${GREEN}✓ 镜像拉取完成${NC}"
    else
        echo -e "${YELLOW}跳过镜像拉取${NC}"
    fi
}

# 停止现有容器
stop_existing() {
    if docker ps -a --format "table {{.Names}}" | grep -q "^$CONTAINER_NAME$"; then
        echo -e "${YELLOW}停止并移除现有容器...${NC}"
        docker stop "$CONTAINER_NAME" 2>/dev/null || true
        docker rm "$CONTAINER_NAME" 2>/dev/null || true
        echo -e "${GREEN}✓ 现有容器已清理${NC}"
    fi
}

# 生成 Docker Compose 配置
generate_compose() {
    local compose_file="docker-compose.deploy.yml"
    
    if [ "$SYSTEM_TYPE" = "synology" ]; then
        echo -e "${YELLOW}生成群晖专用配置...${NC}"
        cat > "$compose_file" << EOF
# Docker Compose 配置文件 - 群晖系统专用 (自动生成)
version: '3.8'

services:
  emby-actor-processor:
    image: $IMAGE_NAME
    container_name: $CONTAINER_NAME
    
    # 群晖系统权限配置
    environment:
      - PUID=1026             # 群晖默认管理员 UID
      - PGID=100              # 群晖 users 组 GID
      - UMASK=022             # 权限掩码
      - TZ=Asia/Shanghai       # 时区
      - AUTH_USERNAME=admin    # Web 界面登录用户名
    
    # 网络模式配置
    network_mode: bridge
    
    # 端口映射
    ports:
      - "$PORT:5257"
    
    # 数据卷挂载
    volumes:
      - "$DATA_DIR:/config"
    
    # 重启策略
    restart: unless-stopped
    
    # 健康检查
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5257/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
EOF
    else
        echo -e "${YELLOW}生成通用系统配置...${NC}"
        cat > "$compose_file" << EOF
# Docker Compose 配置文件 - 通用版本 (自动生成)
version: '3.8'

services:
  emby-actor-processor:
    image: $IMAGE_NAME
    container_name: $CONTAINER_NAME
    
    # 环境变量配置
    environment:
      - PUID=$(id -u)          # 当前用户的 UID
      - PGID=$(id -g)          # 当前用户的 GID
      - UMASK=022              # 权限掩码
      - TZ=Asia/Shanghai        # 时区
      - AUTH_USERNAME=admin     # Web 界面登录用户名
    
    # 网络模式配置
    network_mode: bridge
    
    # 端口映射
    ports:
      - "$PORT:5257"
    
    # 数据卷挂载
    volumes:
      - "$DATA_DIR:/config"
    
    # 重启策略
    restart: unless-stopped
    
    # 健康检查
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5257/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
EOF
    fi
    
    echo -e "${GREEN}✓ 配置文件已生成: $compose_file${NC}"
}

# 启动容器
start_container() {
    if [ "$START_CONTAINER" = true ]; then
        echo -e "${YELLOW}启动容器...${NC}"
        
        # 使用 docker-compose 或 docker compose
        if command -v docker-compose &> /dev/null; then
            docker-compose -f docker-compose.deploy.yml up -d
        else
            docker compose -f docker-compose.deploy.yml up -d
        fi
        
        echo -e "${GREEN}✓ 容器启动完成${NC}"
        
        # 等待服务启动
        echo -e "${YELLOW}等待服务启动...${NC}"
        sleep 10
        
        # 检查服务状态
        if curl -f "http://localhost:$PORT/" >/dev/null 2>&1; then
            echo -e "${GREEN}✓ 服务启动成功！${NC}"
            echo -e "${BLUE}访问地址: http://localhost:$PORT${NC}"
            echo -e "${BLUE}默认用户名: admin${NC}"
            echo -e "${YELLOW}首次登录密码请查看容器日志获取${NC}"
        else
            echo -e "${YELLOW}⚠ 服务可能还在启动中，请稍后访问 http://localhost:$PORT${NC}"
        fi
    else
        echo -e "${YELLOW}跳过容器启动${NC}"
        echo -e "${BLUE}手动启动命令: docker-compose -f docker-compose.deploy.yml up -d${NC}"
    fi
}

# 显示日志
show_logs() {
    echo ""
    echo -e "${BLUE}=== 容器日志 ===${NC}"
    docker logs "$CONTAINER_NAME" --tail 20
}

# 主执行流程
main() {
    detect_system
    setup_data_dir
    pull_image
    stop_existing
    generate_compose
    start_container
    
    if [ "$START_CONTAINER" = true ]; then
        show_logs
    fi
    
    echo ""
    echo -e "${GREEN}=== 部署完成 ===${NC}"
    echo -e "系统类型: ${BLUE}$SYSTEM_TYPE${NC}"
    echo -e "数据目录: ${BLUE}$DATA_DIR${NC}"
    echo -e "访问端口: ${BLUE}$PORT${NC}"
    echo ""
    echo -e "${YELLOW}常用命令:${NC}"
    echo -e "  查看日志: ${BLUE}docker logs $CONTAINER_NAME${NC}"
    echo -e "  停止服务: ${BLUE}docker stop $CONTAINER_NAME${NC}"
    echo -e "  重启服务: ${BLUE}docker restart $CONTAINER_NAME${NC}"
    echo -e "  更新服务: ${BLUE}$0 --no-start && docker-compose -f docker-compose.deploy.yml up -d${NC}"
}

# 错误处理
trap 'echo -e "${RED}部署过程中发生错误，请检查上述输出${NC}"' ERR

# 执行主程序
main