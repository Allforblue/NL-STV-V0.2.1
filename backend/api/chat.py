from fastapi import APIRouter, Request, HTTPException
from core.schemas.interaction import InteractionPayload
from core.schemas.dashboard import DashboardSchema
from core.services.session_service import session_manager

router = APIRouter()


@router.post("/interact", response_model=DashboardSchema)
async def handle_interaction(request: Request, payload: InteractionPayload):
    """
    接收多模态输入，执行 Workflow，返回看板 JSON。
    实现“从初步感知到深度溯源”的闭环。
    """
    workflow = request.app.state.workflow
    session_id = payload.session_id

    # 1. 获取 Session 数据
    state = session_manager.get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session 不存在，请先上传数据")

    try:
        # 2. 调用 Workflow (它会自动判断是 New Dashboard 还是 Drill-down)
        dashboard_json = await workflow.execute_step(
            payload=payload,
            data_summaries=state["summaries"],
            data_context=state["data_context"],
            last_session_state=state.get("last_workflow_state")
        )

        # 3. 更新 Session
        session_manager.update_session_state(session_id, "last_workflow_state", dashboard_json.metadata)

        return dashboard_json
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))