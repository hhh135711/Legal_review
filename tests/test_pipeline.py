"""核心链路自动化测试。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app, pipeline
from app.chunker import build_chunks, split_children
from app.strategy import choose_strategy

client = TestClient(app)


# ---------- 切块 ----------
def test_parent_child_linkage():
    parents, children = build_chunks("t.txt", "第一条 测试条款。" * 100)
    assert parents and children
    pids = {p.chunk_id for p in parents}
    assert all(c.parent_id in pids for c in children)


def test_child_size_limit():
    for c in split_children("条款内容。" * 200):
        assert len(c) <= 160


# ---------- 策略路由 ----------
def test_strategy_decompose():
    r = choose_strategy("对赌协议的回购利率上限是多少，以及业绩补偿有没有封顶要求")
    assert r["strategy"] == "decompose" and len(r["sub_queries"]) >= 2


def test_strategy_fallback_on_error(monkeypatch):
    import app.strategy as s
    monkeypatch.setattr(s.re, "split", lambda *a, **k: 1 / 0)
    r = s.choose_strategy("哪些和以及同时的复合问题触发拆分逻辑分支")
    assert r["strategy"] == "direct"  # 异常必须回退兜底


# ---------- 三层拦截 ----------
def test_faq_hit_bypasses_llm():
    r = client.post("/api/query", json={"query": "竞业限制期限最长多久"}).json()
    assert r["route"] == "faq"
    assert "24个月" in r["answer"]


def test_cache_hit_on_repeat():
    q = {"query": "供应商破产源代码拿不到怎么办"}
    first = client.post("/api/query", json=q).json()
    second = client.post("/api/query", json=q).json()
    assert second["route"] == "cache"
    assert second["latency_ms"] <= first["latency_ms"]


def test_rag_returns_citations():
    r = client.post("/api/query", json={"query": "创始人个人回购有什么历史风险案例"}).json()
    assert r["route"] in ("rag", "cache")
    assert r["citations"], "RAG答案必须携带溯源引用"
    assert all("doc" in c and "full_text" in c for c in r["citations"])


def test_empty_query_rejected():
    assert client.post("/api/query", json={"query": "  "}).status_code == 400


# ---------- 文档上传 ----------
def test_upload_txt_and_search():
    content = "测试制度文件。第一条 演示专用条款：现场上传文档零延迟入库检索。".encode()
    r = client.post("/api/upload", files={"file": ("现场上传.txt", content)})
    assert r.status_code == 200 and r.json()["children"] >= 1


def test_upload_unsupported_format():
    r = client.post("/api/upload", files={"file": ("x.exe", b"MZ\x00\x00")})
    assert r.status_code == 422


# ---------- 健康检查 ----------
def test_health():
    r = client.get("/health").json()
    assert r["status"] == "ok"
