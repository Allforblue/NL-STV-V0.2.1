import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# 导入路由 (这些文件接下来需要完善)
from api import chat, data, session
from core.llm.AI_client import AIClient
from core.services.workflow import AnalysisWorkflow

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# --- 生命周期管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    在应用启动时初始化资源，在关闭时清理
    """
    logger.info("正在启动 NL-STV 后端服务...")

    # 1. 确保数据沙箱目录存在
    os.makedirs("core/data_sandbox", exist_ok=True)

    # 2. 初始化核心工作流并注入到 app 状态中
    # 这样在路由函数里可以通过 request.app.state.workflow 获取
    try:
        # 这里默认从环境变量读取 API Key，或者你在 config.yaml 中配置
        client = AIClient(model_name="deepseek-chat")
        app.state.workflow = AnalysisWorkflow(client)
        logger.info("✅ AnalysisWorkflow 串联成功")
    except Exception as e:
        logger.error(f"❌ 初始化核心工作流失败: {e}")

    yield

    logger.info("正在关闭 NL-STV 后端服务...")


# --- 创建 FastAPI 实例 ---
app = FastAPI(
    title="NL-STV Platform API",
    description="基于 LLM 驱动的多维时空数据智能分析与交互看板后端",
    version="2.1.0",
    lifespan=lifespan
)

# --- 配置跨域 (CORS) ---
# 允许 React 前端（通常是 http://localhost:5173）访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境建议指定具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 挂载 API 路由 ---
# 我们使用前缀 /api/v1 来规范接口
app.include_router(chat.router, prefix="/api/v1/chat", tags=["智能对话与看板"])
app.include_router(data.router, prefix="/api/v1/data", tags=["数据管理"])
app.include_router(session.router, prefix="/api/v1/session", tags=["会话管理"])


# --- 基础健康检查接口 ---
@app.get("/")
async def root():
    return {
        "status": "online",
        "message": "Welcome to NL-STV Platform API",
        "docs": "/docs"
    }


# --- 运行说明 ---
# 启动命令: uvicorn main:app --reload
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)