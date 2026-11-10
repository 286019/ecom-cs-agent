"""FastAPI 入口：页面、健康检查、SSE 对话接口。"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import sys
from logging.handlers import RotatingFileHandler

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import Agent
from .boundary import snapshot as boundary_snapshot
from .config import BASE_DIR, settings
from .knowledge import KnowledgeBase
from .rules import load_rules
from .session import store
from .mock_data import ORDERS

VERSION = "2.0.0"
ACTUAL_PORT = settings.port


def setup_logging() -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    if sys.stderr is not None:  # pythonw / 无控制台环境下跳过控制台输出
        root.addHandler(console)

    file_handler = RotatingFileHandler(
        settings.log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


setup_logging()
logger = logging.getLogger("ecom.main")

kb = KnowledgeBase(settings.knowledge_dir, settings)
agent = Agent(settings, kb)

app = FastAPI(title="电商客服 Agent", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/favicon.ico")
async def favicon() -> JSONResponse:
    return JSONResponse(status_code=204, content=None)


@app.get("/health")
async def health() -> dict:
    info = settings.public_info()
    rules = load_rules()
    return {
        "status": "ok",
        "version": VERSION,
        "port": ACTUAL_PORT,
        **info,
        "knowledge_chunks": len(kb.chunks),
        "retrieval": {
            "method": "vector" if kb._vectors is not None else "bm25",
            "method_label": rules["retrieval"]["vector"]["label"]
            if kb._vectors is not None
            else rules["retrieval"]["bm25"]["label"],
            "reason": kb.method_reason,
            "degraded": kb.degraded,
        },
        "boundary": boundary_snapshot(),
        "rules_version": rules.get("version"),
        "active_sessions": store.count(),
        "demo_orders": [
            {"order_id": o["order_id"], "status": o["status"], "phone_last4": o["phone_last4"]}
            for o in ORDERS.values()
        ],
        "tools": [
            "query_order",
            "query_logistics",
            "query_product",
            "create_refund",
            "query_after_sale",
            "handoff_to_human",
        ],
    }


@app.post("/api/chat")
async def chat(request: Request, payload: ChatRequest) -> StreamingResponse:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    session = store.get_or_create(payload.session_id)
    logger.info("收到消息 session=%s mode=%s", session.session_id, settings.mode)

    async def event_stream():
        info = settings.public_info()
        yield sse({"type": "meta", "session_id": session.session_id, **info})
        try:
            async for event in agent.chat(session, message):
                if await request.is_disconnected():
                    logger.info("客户端已断开 session=%s", session.session_id)
                    return
                yield sse(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # 兜底：任何异常都返回可读信息，避免前端卡住
            logger.exception("对话处理异常 session=%s", session.session_id)
            yield sse({"type": "error", "content": f"服务处理异常：{exc}"})
        finally:
            yield sse({"type": "done", "session_id": session.session_id})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/session/{session_id}")
async def get_session(session_id: str) -> dict:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session.snapshot()


@app.delete("/api/session/{session_id}")
async def reset_session(session_id: str) -> dict:
    return {"reset": store.reset(session_id)}


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def pick_port(preferred: int) -> int:
    for candidate in [preferred, *range(preferred + 1, preferred + 11)]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            # Windows 下 SO_REUSEADDR 会允许 0.0.0.0 与已占用的 127.0.0.1 重复绑定，
            # 导致端口探测失效，这里改用独占绑定。
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((settings.host, candidate))
                return candidate
            except OSError:
                continue
    raise RuntimeError(f"{preferred}-{preferred + 10} 端口均被占用，请修改 .env 中的 PORT")


def run() -> None:
    global ACTUAL_PORT
    ACTUAL_PORT = pick_port(settings.port)
    # 监听 0.0.0.0 时对外展示可直接点击的本机地址
    display_host = "127.0.0.1" if settings.host in ("0.0.0.0", "::") else settings.host
    url = f"http://{display_host}:{ACTUAL_PORT}"
    try:
        (settings.log_dir / "server_url.txt").write_text(url, encoding="utf-8")
    except OSError as exc:  # 文件可能被杀毒软件短暂锁定，不影响服务启动
        logger.warning("写入 server_url.txt 失败：%s", exc)

    logger.info("=" * 56)
    logger.info("电商客服 Agent 启动中：%s", url)
    logger.info("运行模式：%s（%s / %s）", settings.mode_label, settings.provider_label, settings.model or "local-rules")
    logger.info("知识库：%d 个片段", len(kb.chunks))
    logger.info("=" * 56)

    uvicorn.run(app, host=settings.host, port=ACTUAL_PORT, log_level="info", log_config=None)


if __name__ == "__main__":
    run()
