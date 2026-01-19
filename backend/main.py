import os
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# --- 核心模块导入 ---
from api import chat, data, session
from core.llm.AI_client import AIClient
from core.services.workflow import AnalysisWorkflow
# [建议新增] 导入以确保启动时日志能记录 session 系统状态
from core.services.session_service import session_service

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- 路径配置 ---
BASE_DIR = Path(__file__).resolve().parent
SANDBOX_PATH = BASE_DIR / "core" / "data_sandbox"


# --- 生命周期管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    在应用启动时初始化资源，在关闭时清理
    """
    logger.info(">>> [NL-STV V2.1] 正在启动高交互时空数据分析后端...")

    # 1. 确保数据沙箱目录存在
    if not SANDBOX_PATH.exists():
        SANDBOX_PATH.mkdir(parents=True, exist_ok=True)
        logger.info(f"已创建数据沙箱: {SANDBOX_PATH}")

    # 2. 初始化核心工作流
    try:
        # 初始化 LLM 客户端
        client = AIClient(model_name="deepseek-chat")

        # 连通性检查
        if not client.is_alive():
            logger.error("❌ 无法连接到 DeepSeek API，请检查网络或 API Key！")
        else:
            logger.info("✅ DeepSeek API 连接成功")

        # [核心] 初始化新版 AnalysisWorkflow 并挂载
        # 现在的 Workflow 内部已经集成了 InteractionMapper 和新版 Planner
        app.state.workflow = AnalysisWorkflow(client)
        logger.info("✅ 高交互分析引擎 (AnalysisWorkflow V2) 挂载成功")

    except Exception as e:
        logger.error(f"❌ 初始化核心工作流失败: {e}")
        import traceback
        traceback.print_exc()
        raise e

    yield

    # 3. 停止时的清理 (如有必要可清理内存 Session)
    logger.info(">>> 正在关闭 NL-STV 后端服务，执行内存清理...")


# --- 创建 FastAPI 实例 ---
app = FastAPI(
    title="NL-STV Platform API",
    description="LLM 驱动的高交互时空分析平台后端 - 支持快照回溯与多图联动",
    version="2.1.0",
    lifespan=lifespan
)

# --- 配置跨域 (CORS) ---
# 时空数据展示常涉及大量地理坐标 JSON，确保 CORS 允许必要的头信息
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 挂载 API 路由 ---
app.include_router(chat.router, prefix="/api/v1/chat", tags=["智能对话与看板"])
app.include_router(data.router, prefix="/api/v1/data", tags=["数据管理"])
app.include_router(session.router, prefix="/api/v1/session", tags=["会话管理"])


# --- 基础健康检查接口 ---
@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "NL-STV Backend (High-Interaction)",
        "version": "2.1.0",
        "features": ["Snapshot Backtrack", "UI Interaction Mapping", "Template-driven Layout"]
    }


if __name__ == "__main__":
    import uvicorn

    # reload=True 适合开发环境。正式部署建议关闭。
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)