#!/usr/bin/env bash
# GitOps 拉取式自动部署守护进程
# 每30秒检查GitHub远端，发现新提交自动 pull + 重建容器（同ArgoCD的pull模型）
#
# 启动: nohup bash deploy/autodeploy.sh > /tmp/autodeploy.log 2>&1 &
# 停止: pkill -f autodeploy.sh

set -u
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BRANCH="main"
INTERVAL=30

cd "$REPO_DIR"
echo "[autodeploy] 守护启动 · 仓库 $REPO_DIR · 分支 $BRANCH · 间隔 ${INTERVAL}s"

while true; do
    git fetch origin "$BRANCH" --quiet 2>/dev/null || { echo "[autodeploy] $(date +%T) fetch失败，跳过本轮"; sleep "$INTERVAL"; continue; }
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse "origin/$BRANCH")
    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "[autodeploy] $(date +%T) 检测到新提交 ${REMOTE:0:7}，开始部署"
        git pull --ff-only origin "$BRANCH"
        if docker compose up -d --build 2>&1; then
            echo "[autodeploy] $(date +%T) ✓ 部署完成 → ${REMOTE:0:7}: $(git log -1 --pretty=%s)"
            # 部署后健康检查，失败自动回滚到上一版本
            sleep 8
            if ! curl -sf http://localhost/health > /dev/null; then
                echo "[autodeploy] $(date +%T) ✗ 健康检查失败，回滚到 ${LOCAL:0:7}"
                git reset --hard "$LOCAL"
                docker compose up -d --build
            fi
        else
            echo "[autodeploy] $(date +%T) ✗ 构建失败，保持当前版本运行"
        fi
    fi
    sleep "$INTERVAL"
done
