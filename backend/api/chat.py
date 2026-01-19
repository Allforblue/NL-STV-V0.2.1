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
        # 2. 确保全量数据
        session_service.ensure_full_data_context(session_id)
        # 重新获取最新的状态（包含全量 context 指针）
        state = session_service.get_session(session_id)

        # 3. [关键修改] 调用新版 Workflow
        # 移除了 last_session_state 参数，改由 workflow 内部通过 session_service 自动管理快照
        dashboard_json = await workflow.execute_step(
            payload=payload,
            data_summaries=state["summaries"],
            data_context=state["data_context"],
            session_service=session_service  # 传入实例用于存取快照
        )

        return dashboard_json

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")