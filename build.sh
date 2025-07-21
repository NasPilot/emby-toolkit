#!/bin/bash

# Emby Actor Processor Docker 构建脚本
# 用于构建和测试 Docker 镜像

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 默认配置
IMAGE_NAME="emby-actor-processor"
TAG="latest"
PLATFORM="linux/amd64,linux/arm64"
BUILD_ARGS=""
PUSH=false
TEST=false

# 显示帮助信息
show_help() {
    echo "Emby Actor Processor Docker 构建脚本"
    echo ""
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  -n, --name NAME        镜像名称 (默认: $IMAGE_NAME)"
    echo "  -t, --tag TAG          镜像标签 (默认: $TAG)"
    echo "  -p, --platform ARCH    目标平台 (默认: $PLATFORM)"
    echo "  --push                 构建后推送到仓库"
    echo "  --test                 构建后运行测试"
    echo "  --build-arg ARG        传递构建参数"
    echo "  -h, --help             显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0                                    # 基本构建"
    echo "  $0 --test                             # 构建并测试"
    echo "  $0 -n myrepo/emby-actor -t v1.0       # 自定义名称和标签"
    echo "  $0 --platform linux/amd64             # 指定单一平台"
    echo "  $0 --build-arg PUID=1026 --test       # 传递构建参数并测试"
}

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--name)
            IMAGE_NAME="$2"
            shift 2
            ;;
        -t|--tag)
            TAG="$2"
            shift 2
            ;;
        -p|--platform)
            PLATFORM="$2"
            shift 2
            ;;
        --push)
            PUSH=true
            shift
            ;;
        --test)
            TEST=true
            shift
            ;;
        --build-arg)
            BUILD_ARGS="$BUILD_ARGS --build-arg $2"
            shift 2
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

# 完整镜像名称
FULL_IMAGE_NAME="$IMAGE_NAME:$TAG"

echo -e "${BLUE}=== Emby Actor Processor Docker 构建 ===${NC}"
echo -e "镜像名称: ${GREEN}$FULL_IMAGE_NAME${NC}"
echo -e "目标平台: ${GREEN}$PLATFORM${NC}"
if [ -n "$BUILD_ARGS" ]; then
    echo -e "构建参数: ${GREEN}$BUILD_ARGS${NC}"
fi
echo -e "推送镜像: ${GREEN}$PUSH${NC}"
echo -e "运行测试: ${GREEN}$TEST${NC}"
echo ""

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}错误: Docker 未安装或不在 PATH 中${NC}"
    exit 1
fi

# 检查 entrypoint.sh 是否存在
if [ ! -f "entrypoint.sh" ]; then
    echo -e "${RED}错误: entrypoint.sh 文件不存在${NC}"
    exit 1
fi

# 确保 entrypoint.sh 有执行权限
chmod +x entrypoint.sh

# 构建镜像
echo -e "${YELLOW}开始构建 Docker 镜像...${NC}"
if [[ "$PLATFORM" == *","* ]]; then
    # 多平台构建
    echo -e "${BLUE}多平台构建: $PLATFORM${NC}"
    if [ "$PUSH" = true ]; then
        docker buildx build --platform "$PLATFORM" $BUILD_ARGS -t "$FULL_IMAGE_NAME" --push .
    else
        docker buildx build --platform "$PLATFORM" $BUILD_ARGS -t "$FULL_IMAGE_NAME" --load .
    fi
else
    # 单平台构建
    echo -e "${BLUE}单平台构建: $PLATFORM${NC}"
    docker build --platform "$PLATFORM" $BUILD_ARGS -t "$FULL_IMAGE_NAME" .
    
    if [ "$PUSH" = true ]; then
        echo -e "${YELLOW}推送镜像到仓库...${NC}"
        docker push "$FULL_IMAGE_NAME"
    fi
fi

echo -e "${GREEN}✓ 镜像构建完成: $FULL_IMAGE_NAME${NC}"

# 运行测试
if [ "$TEST" = true ]; then
    echo ""
    echo -e "${YELLOW}开始运行测试...${NC}"
    
    # 创建临时测试目录
    TEST_DIR="$(mktemp -d)"
    echo -e "测试数据目录: ${BLUE}$TEST_DIR${NC}"
    
    # 清理函数
    cleanup() {
        echo -e "${YELLOW}清理测试环境...${NC}"
        docker stop emby-actor-test 2>/dev/null || true
        docker rm emby-actor-test 2>/dev/null || true
        rm -rf "$TEST_DIR"
    }
    
    # 设置清理陷阱
    trap cleanup EXIT
    
    # 运行容器
    echo -e "${BLUE}启动测试容器...${NC}"
    docker run -d \
        --name emby-actor-test \
        -p 15257:5257 \
        -v "$TEST_DIR:/config" \
        -e PUID=1000 \
        -e PGID=100 \
        -e UMASK=022 \
        "$FULL_IMAGE_NAME"
    
    # 等待容器启动
    echo -e "${BLUE}等待容器启动...${NC}"
    sleep 10
    
    # 检查容器状态
    if docker ps | grep -q emby-actor-test; then
        echo -e "${GREEN}✓ 容器启动成功${NC}"
        
        # 检查日志
        echo -e "${BLUE}容器日志:${NC}"
        docker logs emby-actor-test
        
        # 检查健康状态
        echo -e "${BLUE}检查应用健康状态...${NC}"
        sleep 5
        
        if curl -f http://localhost:15257/ >/dev/null 2>&1; then
            echo -e "${GREEN}✓ 应用响应正常${NC}"
        else
            echo -e "${YELLOW}⚠ 应用可能还在启动中，请手动检查 http://localhost:15257/${NC}"
        fi
        
        # 检查配置文件
        if [ -f "$TEST_DIR/config.ini" ]; then
            echo -e "${GREEN}✓ 配置文件已创建${NC}"
            echo -e "配置文件权限: $(ls -la "$TEST_DIR/config.ini")"
        else
            echo -e "${YELLOW}⚠ 配置文件未找到${NC}"
        fi
        
        # 检查数据库文件
        if [ -f "$TEST_DIR/emby_actor_processor.sqlite" ]; then
            echo -e "${GREEN}✓ 数据库文件已创建${NC}"
            echo -e "数据库文件权限: $(ls -la "$TEST_DIR/emby_actor_processor.sqlite")"
        else
            echo -e "${YELLOW}⚠ 数据库文件未找到${NC}"
        fi
        
        echo ""
        echo -e "${GREEN}测试完成！${NC}"
        echo -e "访问地址: ${BLUE}http://localhost:15257/${NC}"
        echo -e "测试数据: ${BLUE}$TEST_DIR${NC}"
        echo ""
        echo -e "${YELLOW}按 Enter 键清理测试环境...${NC}"
        read
        
    else
        echo -e "${RED}✗ 容器启动失败${NC}"
        echo -e "${BLUE}容器日志:${NC}"
        docker logs emby-actor-test
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}=== 构建完成 ===${NC}"
echo -e "镜像: ${BLUE}$FULL_IMAGE_NAME${NC}"
echo -e "大小: ${BLUE}$(docker images --format 'table {{.Size}}' "$FULL_IMAGE_NAME" | tail -n 1)${NC}"
echo ""
echo "使用示例:"
echo -e "${BLUE}docker run -d -p 5257:5257 -v ./config:/config -e PUID=1000 -e PGID=100 $FULL_IMAGE_NAME${NC}"