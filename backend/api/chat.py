import traceback
import logging
from fastapi import APIRouter, Request, HTTPException
from core.schemas.interaction import InteractionPayload, InteractionTriggerType
from core.schemas.dashboard import DashboardSchema
from core.services.session_service import session_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/interact", response_model=DashboardSchema)
async def handle_interaction(request: Request, payload: InteractionPayload):
    """
    接收多模态输入（NLP/UI/Backtrack），执行 Workflow，返回看板 JSON。
    """
    workflow = request.app.state.workflow
    session_id = payload.session_id

    # 1. 基础状态检查
    state = session_service.get_session(session_id)
    if not state:
        logger.warning(f"Session {session_id} not found during interaction.")
        raise HTTPException(status_code=404, detail="会话不存在或已过期，请重新上传数据文件")

    # 2. 时空数据严谨性前置检查 (STV 增强)
    if payload.trigger_type == InteractionTriggerType.UI_ACTION and payload.bbox:
        if len(payload.bbox) == 4:
            # 确保 bbox 坐标不包含 None 或非法值
            if any(coord is None for coord in payload.bbox):
                logger.error(f"Invalid BBox received: {payload.bbox}")
                payload.bbox = None  # 降级处理，防止后续 .cx 过滤报错
        else:
            payload.bbox = None

    try:
        logger.info(f">>> [API] 收到交互请求 | 触发源: {payload.trigger_type} | 会话: {session_id}")

        # 3. 执行核心 Workflow
        # 该过程包含：语义画像同步、交互映射、代码生成/编辑、沙箱安全执行、洞察提取
        dashboard_json = await workflow.execute_step(
            payload=payload,
            data_summaries=state["summaries"],
            data_context=state["data_context"],
            session_service=session_service
        )

        # 4. 响应状态检查
        if not dashboard_json or not dashboard_json.components:
            logger.error("Workflow returned an empty dashboard.")
            raise ValueError("分析结果为空，请尝试更换描述或重新选择区域")

        logger.info(f"✅ [API] 交互处理成功 | 会话: {session_id} | 快照: {dashboard_json.metadata.get('snapshot_id')}")
        return dashboard_json

    except ValueError as ve:
        # 业务逻辑层面的错误（如 LLM 生成代码不可用）
        logger.error(f"业务逻辑错误: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))

    except Exception as e:
        # 系统级严重错误
        error_trace = traceback.format_exc()
        logger.error(f"Workflow 致命错误:\n{error_trace}")

        # 针对超大规模数据可能导致的超时或内存问题提供更明确的提示
        detail_msg = "时空计算引擎处理超时或内存溢出，请尝试缩小数据范围" if "MemoryError" in error_trace else f"分析失败: {str(e)}"
        raise HTTPException(status_code=500, detail=detail_msg)