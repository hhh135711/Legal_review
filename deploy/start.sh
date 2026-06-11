#!/usr/bin/env bash
# 衡鉴 LexiCheck 一键启动：容器全家桶 + GitOps自动部署守护 + Locust压测台
# 用法: bash deploy/start.sh
set -u
cd "$(cd "$(dirname "$0")/.." && pwd)"

echo "[1/5] 同步最新代码..."
git pull --ff-only || echo "  (pull失败，使用本地版本继续)"

echo "[2/5] 启动容器: app + prometheus + grafana ..."
docker compose up -d --build
docker compose ps

echo "[3/5] 启动GitOps自动部署守护..."
pkill -f autodeploy.sh 2>/dev/null
nohup bash deploy/autodeploy.sh > /tmp/autodeploy.log 2>&1 &
echo "  日志: tail -f /tmp/autodeploy.log"

echo "[4/5] 启动Locust压测台(8089)..."
pkill -9 -f locust 2>/dev/null
sleep 1
command -v locust >/dev/null || pip install -q locust
nohup locust -f locustfile.py --host http://localhost --web-port 8089 > /tmp/locust.log 2>&1 &

echo "[5/5] 健康检查 + 预热流量..."
for i in $(seq 1 20); do
  curl -sf http://localhost/health > /dev/null && break
  sleep 2
done
for i in $(seq 1 15); do
  curl -s -X POST http://localhost/api/query -H 'Content-Type: application/json' \
    -d '{"query":"竞业限制期限最长多久"}' > /dev/null
done

echo ""
echo "===================== 启动完成 ====================="
echo "  主系统      : 端口 80   (/, /static/dashboard.html, /static/tests.html, /static/presentation.html)"
echo "  Grafana     : 端口 3000 (Dashboards → 衡鉴 LexiCheck 系统监控)"
echo "  Prometheus  : 端口 9090"
echo "  Locust压测  : 端口 8089"
echo "  自动部署    : tail -f /tmp/autodeploy.log"
curl -s http://localhost/health && echo ""
