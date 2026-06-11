"""衡鉴 LexiCheck — 企业法务可溯源依据检索系统 API入口。"""
import time
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .pipeline import LegalRAGPipeline
from .parser import parse_any, UnsupportedFormat

app = FastAPI(title="衡鉴 LexiCheck", version="1.0.0")
START_TIME = time.time()
pipeline = LegalRAGPipeline()

try:  # Prometheus指标暴露（/metrics）
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app)
except ImportError:
    pass

STATIC = Path(__file__).resolve().parent.parent / "static"


class QueryIn(BaseModel):
    query: str


@app.post("/api/query")
def query(body: QueryIn):
    q = body.query.strip()
    if not q:
        raise HTTPException(400, "问题不能为空")
    return pipeline.query(q)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "文件超过10MB限制")
    try:
        text, channel = parse_any(file.filename, data)
    except UnsupportedFormat as e:
        raise HTTPException(422, str(e))
    stat = pipeline.add_document(file.filename, text)
    return {"filename": file.filename, "channel": channel, "chars": len(text), **stat}


@app.get("/api/metrics/business")
def business_metrics():
    return pipeline.metrics.snapshot()


@app.get("/api/corpus")
def corpus():
    return {"docs": pipeline.docs, "faq_count": len(pipeline.faq),
            "parents": len(pipeline.index.parents), "children": len(pipeline.index.children)}


@app.get("/health")
def health():
    return {"status": "ok", "uptime_s": round(time.time() - START_TIME, 1),
            "components": {"index": "up", "cache": "up", "faq": "up", "pipeline": "up"}}


@app.get("/")
def root():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
