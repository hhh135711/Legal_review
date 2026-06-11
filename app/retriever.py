"""混合检索：BM25稀疏 + TF-IDF稠密近似 双路召回 → 加权融合(RRF) → 子块回溯父块 → 轻量重排。

生产环境为 BGE-M3 稠密/稀疏双向量 + Milvus + bge-reranker；
demo环境用等价的轻量实现保证零外部依赖、可现场跑通。
"""
import math
from collections import Counter, defaultdict
from typing import List

import jieba
from rank_bm25 import BM25Okapi

from .chunker import Chunk, build_chunks


def tokenize(text: str) -> List[str]:
    return [t for t in jieba.lcut(text) if t.strip() and t not in "，。；、：（）的了是"]


class HybridIndex:
    def __init__(self):
        self.parents: dict[int, Chunk] = {}
        self.children: List[Chunk] = []
        self._bm25: BM25Okapi | None = None
        self._child_tokens: List[List[str]] = []
        self._idf: dict[str, float] = {}

    # ---------- 构建 ----------
    def add_document(self, doc_name: str, text: str) -> dict:
        parents, children = build_chunks(doc_name, text)
        for p in parents:
            self.parents[p.chunk_id] = p
        self.children.extend(children)
        self._rebuild()
        return {"doc": doc_name, "parents": len(parents), "children": len(children)}

    def _rebuild(self):
        self._child_tokens = [tokenize(c.text) for c in self.children]
        self._bm25 = BM25Okapi(self._child_tokens)
        df = Counter()
        for toks in self._child_tokens:
            df.update(set(toks))
        n = len(self._child_tokens)
        self._idf = {t: math.log(1 + n / (1 + c)) for t, c in df.items()}

    # ---------- 双路召回 ----------
    def _sparse_route(self, query: str, topn: int) -> List[tuple[int, float]]:
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: -scores[i])[:topn]
        return [(i, scores[i]) for i in ranked]

    def _dense_route(self, query: str, topn: int) -> List[tuple[int, float]]:
        """TF-IDF余弦相似度，作为稠密向量通道的轻量等价。"""
        qv = Counter(tokenize(query))
        qvec = {t: f * self._idf.get(t, 0.1) for t, f in qv.items()}
        qnorm = math.sqrt(sum(v * v for v in qvec.values())) or 1.0
        sims = []
        for i, toks in enumerate(self._child_tokens):
            dv = Counter(toks)
            dvec = {t: f * self._idf.get(t, 0.1) for t, f in dv.items()}
            dot = sum(qvec[t] * dvec.get(t, 0) for t in qvec)
            dnorm = math.sqrt(sum(v * v for v in dvec.values())) or 1.0
            sims.append(dot / (qnorm * dnorm))
        ranked = sorted(range(len(sims)), key=lambda i: -sims[i])[:topn]
        return [(i, sims[i]) for i in ranked]

    # ---------- 融合 + 父块回溯 + 重排 ----------
    def search(self, query: str, topk: int = 3, recall_n: int = 10) -> dict:
        sparse = self._sparse_route(query, recall_n)
        dense = self._dense_route(query, recall_n)

        # Weighted RRF 融合
        fused: dict[int, float] = defaultdict(float)
        for rank, (idx, _) in enumerate(sparse):
            fused[idx] += 0.5 / (60 + rank)
        for rank, (idx, _) in enumerate(dense):
            fused[idx] += 0.5 / (60 + rank)

        # 子块 → 父块回溯（同父块取最高分）
        parent_scores: dict[int, float] = {}
        parent_hit_child: dict[int, int] = {}
        for idx, score in fused.items():
            pid = self.children[idx].parent_id
            if score > parent_scores.get(pid, -1):
                parent_scores[pid] = score
                parent_hit_child[pid] = idx

        # 轻量重排：查询词在父块中的覆盖率作为rerank信号
        qtoks = set(tokenize(query))
        results = []
        for pid, score in parent_scores.items():
            parent = self.parents[pid]
            cover = len(qtoks & set(tokenize(parent.text))) / (len(qtoks) or 1)
            results.append({
                "parent_id": pid,
                "doc": parent.doc_name,
                "text": parent.text,
                "hit_child": self.children[parent_hit_child[pid]].text,
                "score": round(0.6 * score * 100 + 0.4 * cover, 4),
            })
        results.sort(key=lambda r: -r["score"])
        return {
            "candidates": len(parent_scores),
            "sparse_hits": len(sparse),
            "dense_hits": len(dense),
            "results": results[:topk],
        }
