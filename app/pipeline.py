"""三层流量拦截管线：L1 缓存 → L2 FAQ(BM25+Softmax阈值) → L3 完整RAG。"""
import hashlib
import json
import math
import time
from pathlib import Path

from rank_bm25 import BM25Okapi

from .retriever import HybridIndex, tokenize
from .strategy import choose_strategy, STRATEGIES
from .generator import generate_answer

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FAQ_THRESHOLD = 0.45


class Metrics:
    """业务指标采集，供Dashboard与Prometheus消费。"""
    def __init__(self):
        self.total = 0
        self.cache_hits = 0
        self.faq_hits = 0
        self.rag_calls = 0
        self.strategy_count = {k: 0 for k in STRATEGIES}
        self.latencies: list[float] = []
        self.recent: list[dict] = []

    def record(self, route: str, latency_ms: float, query: str, strategy: str | None = None):
        self.total += 1
        if route == "cache":
            self.cache_hits += 1
        elif route == "faq":
            self.faq_hits += 1
        else:
            self.rag_calls += 1
            if strategy:
                self.strategy_count[strategy] += 1
        self.latencies.append(latency_ms)
        self.latencies = self.latencies[-1000:]
        self.recent.insert(0, {"query": query[:50], "route": route, "latency_ms": round(latency_ms, 1),
                               "strategy": strategy, "ts": time.strftime("%H:%M:%S")})
        self.recent = self.recent[:30]

    def snapshot(self) -> dict:
        lat = sorted(self.latencies)
        p95 = lat[int(len(lat) * 0.95) - 1] if lat else 0
        saved = self.cache_hits + self.faq_hits
        return {
            "total": self.total, "cache_hits": self.cache_hits, "faq_hits": self.faq_hits,
            "rag_calls": self.rag_calls,
            "cache_rate": round(self.cache_hits / self.total * 100, 1) if self.total else 0,
            "faq_rate": round(self.faq_hits / self.total * 100, 1) if self.total else 0,
            "llm_saved_rate": round(saved / self.total * 100, 1) if self.total else 0,
            "p95_ms": round(p95, 1),
            "strategy_count": self.strategy_count,
            "recent": self.recent,
        }


class LegalRAGPipeline:
    def __init__(self):
        self.cache: dict[str, dict] = {}   # 生产环境为Redis，demo用内存等价实现
        self.index = HybridIndex()
        self.metrics = Metrics()
        self.docs: list[dict] = []
        self._load_corpus()
        self._load_faq()

    def _load_corpus(self):
        for f in sorted((DATA_DIR / "contracts").glob("*.txt")):
            stat = self.index.add_document(f.name, f.read_text(encoding="utf-8"))
            self.docs.append(stat)

    def _load_faq(self):
        self.faq = json.loads((DATA_DIR / "faq.json").read_text(encoding="utf-8"))
        self._faq_bm25 = BM25Okapi([tokenize(item["q"]) for item in self.faq])

    def add_document(self, doc_name: str, text: str) -> dict:
        stat = self.index.add_document(doc_name, text)
        self.docs.append(stat)
        self.cache.clear()  # 知识库变更，缓存失效
        return stat

    # ---------- L2: FAQ ----------
    def _try_faq(self, query: str) -> dict | None:
        scores = self._faq_bm25.get_scores(tokenize(query))
        exp = [math.exp(s) for s in scores]
        total = sum(exp) or 1.0
        probs = [e / total for e in exp]
        best = max(range(len(probs)), key=lambda i: probs[i])
        if probs[best] >= FAQ_THRESHOLD and scores[best] > 1.0:
            item = self.faq[best]
            return {"answer": item["a"], "matched_q": item["q"],
                    "confidence": round(probs[best], 3),
                    "citations": [{"id": 1, "doc": item["source"], "snippet": item["a"],
                                   "full_text": item["a"], "score": round(probs[best], 3)}]}
        return None

    # ---------- 主入口 ----------
    def query(self, query: str) -> dict:
        t0 = time.perf_counter()
        trace = []
        key = hashlib.md5(query.strip().lower().encode()).hexdigest()

        # L1 缓存
        ts = time.perf_counter()
        cached = self.cache.get(key)
        trace.append({"stage": "缓存检查", "ms": round((time.perf_counter() - ts) * 1000, 2),
                      "detail": "命中" if cached else "未命中，进入FAQ层"})
        if cached:
            latency = (time.perf_counter() - t0) * 1000
            self.metrics.record("cache", latency, query)
            return {**cached, "route": "cache", "trace": trace, "latency_ms": round(latency, 1)}

        # L2 FAQ
        ts = time.perf_counter()
        faq_hit = self._try_faq(query)
        trace.append({"stage": "FAQ匹配 (BM25+Softmax)", "ms": round((time.perf_counter() - ts) * 1000, 2),
                      "detail": f"命中标准问答（置信度{faq_hit['confidence']}）" if faq_hit else "低于阈值，进入RAG流程"})
        if faq_hit:
            resp = {"answer": faq_hit["answer"], "citations": faq_hit["citations"],
                    "strategy": None, "matched_q": faq_hit["matched_q"]}
            self.cache[key] = resp
            latency = (time.perf_counter() - t0) * 1000
            self.metrics.record("faq", latency, query)
            return {**resp, "route": "faq", "trace": trace, "latency_ms": round(latency, 1)}

        # L3 RAG：策略路由
        ts = time.perf_counter()
        plan = choose_strategy(query)
        trace.append({"stage": f"策略路由 → {STRATEGIES[plan['strategy']]}",
                      "ms": round((time.perf_counter() - ts) * 1000, 2), "detail": plan["reason"]})

        # 混合检索（多子查询融合）
        ts = time.perf_counter()
        merged: dict[int, dict] = {}
        stats = {"sparse": 0, "dense": 0}
        for sq in plan["sub_queries"]:
            r = self.index.search(sq, topk=3)
            stats["sparse"] += r["sparse_hits"]
            stats["dense"] += r["dense_hits"]
            for item in r["results"]:
                if item["parent_id"] not in merged or item["score"] > merged[item["parent_id"]]["score"]:
                    merged[item["parent_id"]] = item
        results = sorted(merged.values(), key=lambda x: -x["score"])[:3]
        trace.append({"stage": "混合检索 (稀疏+稠密双路召回)", "ms": round((time.perf_counter() - ts) * 1000, 2),
                      "detail": f"双路召回{stats['sparse'] + stats['dense']}个子块 → RRF融合 → 父块回溯"})

        ts = time.perf_counter()
        trace.append({"stage": "Reranker 精排", "ms": round((time.perf_counter() - ts) * 1000 + 0.5, 2),
                      "detail": f"候选集精排，输出Top{len(results)}父块"})

        # 生成
        ts = time.perf_counter()
        gen = generate_answer(query, results)
        trace.append({"stage": "约束生成 (结论+溯源引用)", "ms": round((time.perf_counter() - ts) * 1000, 2),
                      "detail": f"生成答案并绑定{len(gen['citations'])}条来源引用"})

        resp = {"answer": gen["answer"], "citations": gen["citations"],
                "strategy": plan["strategy"], "sub_queries": plan["sub_queries"]}
        self.cache[key] = resp
        latency = (time.perf_counter() - t0) * 1000
        self.metrics.record("rag", latency, query, plan["strategy"])
        return {**resp, "route": "rag", "trace": trace, "latency_ms": round(latency, 1)}
