# 衡鉴 LexiCheck — 企业法务可溯源依据检索系统

> 让每一条法务结论，都能被信任、被验证、被采纳。

## 快速启动（本地）

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0
# 打开 http://localhost:8000
```

页面入口：
| 页面 | 地址 |
|---|---|
| 依据检索工作台 | `/` |
| 运维监控中心 | `/static/dashboard.html` |
| 质量保障报告 | `/static/tests.html` |
| 项目展示（替代PPT） | `/static/presentation.html` |

## 架构

```
Query → L1缓存(Redis) → L2 FAQ(BM25+Softmax阈值,零幻觉) → L3 RAG
                                                      ├ 策略路由(直接/HyDE/拆分/回溯,异常兜底)
                                                      ├ 混合检索(稀疏+稠密双路→RRF融合→父子回溯→精排)
                                                      └ 约束生成(结论+溯源引用)
离线: 多格式解析(txt/docx/pdf/扫描件OCR) → 父子切块(1200/300) → 向量化 → 入库
```

## 测试 / 评估 / 压测

```bash
python -m pytest tests -v        # 11个用例
python -m scripts.eval           # Recall@3 / MRR 对比报告
locust -f locustfile.py --host http://localhost:8000   # 压力测试
```

## 部署（腾讯云 Linux）

```bash
docker compose up -d --build
# 80: 主系统 | 9090: Prometheus | 3000: Grafana(匿名只读)
```

CI/CD：GitHub Actions 三阶段流水线（单测 → 效果回归门禁 Recall@3≥90% → 镜像构建），见 `.github/workflows/ci.yml`。

## 说明

Demo环境为保证零外部依赖做了等价降级：BGE-M3→TF-IDF稠密近似、Milvus→内存索引、Redis→进程内缓存、LLM生成→抽取式生成（天然零幻觉）、OCR→通道占位。架构与生产一致，组件可无缝替换。
