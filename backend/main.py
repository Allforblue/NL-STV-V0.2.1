import os
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# --- 导入核心模块 ---
# 确保你的 Python 环境能找到这些包 (在 backend 目录下运行)
from api import chat, data, session
from core.llm.AI_client import AIClient
from core.services.workflow import AnalysisWorkflow

# --- 配置 ---
# 【重要】请在这里填入你的 DeepSeek API Key，或者设置环境变量 DEEPSEEK_API_KEY
# API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- 路径配置 ---
# 获取 backend 目录的绝对路径，确保在任何地方启动都能找到 sandbox
BASE_DIR = Path(__file__).resolve().parent
SANDBOX_PATH = BASE_DIR / "core" / "data_sandbox"


# --- 生命周期管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    在应用启动时初始化资源，在关闭时清理
    """
    logger.info(">>> 正在启动 NL-STV 后端服务...")

    # 1. 确保数据沙箱目录存在 (使用绝对路径)
    if not SANDBOX_PATH.exists():
        SANDBOX_PATH.mkdir(parents=True, exist_ok=True)
        logger.info(f"已创建数据沙箱: {SANDBOX_PATH}")

    # 2. 初始化核心工作流并注入到 app 状态中
    try:
        # 检查 API Key
        # if not API_KEY or API_KEY.startswith("sk-xxx"):
        #     logger.warning(
        #         "⚠️  检测到可能无效的 API Key。请在 main.py 或环境变量中配置真实 Key，否则 LLM 功能将无法使用。")

        # 初始化 LLM 客户端
        client = AIClient(model_name="deepseek-chat")

        # 简单的连通性测试 (可选)
        if not client.is_alive():
            logger.warning("⚠️  无法连接到 DeepSeek API，请检查网络或 Key。")

        # 初始化工作流
        app.state.workflow = AnalysisWorkflow(client)
        logger.info("✅ 核心引擎 (AnalysisWorkflow) 挂载成功")

    except Exception as e:
        logger.error(f"❌ 初始化核心工作流失败: {e}")
        # 这里可以选择 raise e 强制停止启动，也可以仅记录日志
        raise e

    yield

    logger.info(">>> 正在关闭 NL-STV 后端服务...")


# --- 创建 FastAPI 实例 ---
app = FastAPI(
    title="NL-STV Platform API",
    description="基于 LLM 驱动的多维时空数据智能分析与交互看板后端",
    version="2.1.0",
    lifespan=lifespan
)

# --- 配置跨域 (CORS) ---
app.add_middleware(
    CORSMiddleware,
    # 允许所有源，生产环境建议改为 ["http://localhost:5173", "http://your-frontend-domain"]
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 挂载 API 路由 ---
# 对应 data.py, chat.py, session.py
app.include_router(chat.router, prefix="/api/v1/chat", tags=["智能对话与看板"])
app.include_router(data.router, prefix="/api/v1/data", tags=["数据管理"])
app.include_router(session.router, prefix="/api/v1/session", tags=["会话管理"])


# --- 基础健康检查接口 ---
@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "NL-STV Backend",
        "version": "2.1.0",
        "docs_url": "http://localhost:8000/docs"
    }


# --- 启动入口 ---
if __name__ == "__main__":
    import uvicorn

    # 确保 host="0.0.0.0" 以便局域网访问，reload=True 方便开发调试
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)