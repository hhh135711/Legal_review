"""自动评估管道：在标注评估集上计算 Recall@K 与 MRR，对比 纯稀疏 / 纯稠密 / 混合检索。

用法: python -m scripts.eval
输出: 控制台报告 + static/eval_report.json (供测试报告页渲染)
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.pipeline import LegalRAGPipeline  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = Path(__file__).resolve().parent.parent / "static" / "eval_report.json"


def evaluate(index, eval_set, mode: str, k: int = 3):
    hits, rr = 0, 0.0
    for item in eval_set:
        if mode == "hybrid":
            results = index.search(item["q"], topk=k)["results"]
        elif mode == "sparse":
            idxs = index._sparse_route(item["q"], k)
            results = [{"doc": index.children[i].doc_name} for i, _ in idxs]
        else:  # dense
            idxs = index._dense_route(item["q"], k)
            results = [{"doc": index.children[i].doc_name} for i, _ in idxs]
        docs = [r["doc"] for r in results]
        if item["doc"] in docs:
            hits += 1
            rr += 1.0 / (docs.index(item["doc"]) + 1)
    n = len(eval_set)
    return {"recall_at_3": round(hits / n * 100, 1), "mrr": round(rr / n, 3)}


def main():
    eval_set = json.loads((DATA / "eval_set.json").read_text(encoding="utf-8"))
    pipe = LegalRAGPipeline()
    t0 = time.time()
    report = {
        "eval_size": len(eval_set),
        "modes": {m: evaluate(pipe.index, eval_set, m) for m in ("sparse", "dense", "hybrid")},
        "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_s": 0,
    }
    report["duration_s"] = round(time.time() - t0, 2)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"评估集规模: {len(eval_set)} 条标注问答")
    print(f"{'检索模式':<12}{'Recall@3':>10}{'MRR':>8}")
    for m, r in report["modes"].items():
        print(f"{m:<14}{r['recall_at_3']:>8}%{r['mrr']:>8}")
    print(f"\n报告已写入 {OUT}")


if __name__ == "__main__":
    main()
