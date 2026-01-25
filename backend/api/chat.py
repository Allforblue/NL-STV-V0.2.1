import traceback
from fastapi import APIRouter, Request, HTTPException
from core.schemas.interaction import InteractionPayload
from core.schemas.dashboard import DashboardSchema
from core.services.session_service import session_service

router = APIRouter()

@router.post("/interact", response_model=DashboardSchema)
async def handle_interaction(request: Request, payload: InteractionPayload):
    """
    接收多模态输入（NLP/UI/Backtrack），执行 Workflow，返回看板 JSON。
    """
    workflow = request.app.state.workflow
    session_id = payload.session_id

    # 1. 基础检查
    state = session_service.get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session 不存在，请重新上传数据")

    try:
        # 2. 调用新版 Workflow
        # 全量数据的加载时机现已移动至 workflow 内部，以优化语义分析阶段的响应速度
        dashboard_json = await workflow.execute_step(
            payload=payload,
            data_summaries=state["summaries"],
            data_context=state["data_context"],
            session_service=session_service  # 传入实例用于存取快照及按需触发全量加载
        )

        return dashboard_json

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")