import traceback
from fastapi import APIRouter, Request, HTTPException
from core.schemas.interaction import InteractionPayload
from core.schemas.dashboard import DashboardSchema
# [修改] 导入单例对象 session_service，而不是类
from core.services.session_service import session_service

router = APIRouter()


@router.post("/interact", response_model=DashboardSchema)
async def handle_interaction(request: Request, payload: InteractionPayload):
    """
    接收多模态输入，执行 Workflow，返回看板 JSON。
    实现“从初步感知到深度溯源”的闭环。
    """
    # 确保 main.py 中已经将 workflow 挂载到了 app.state
    workflow = request.app.state.workflow
    session_id = payload.session_id

    # 1. 获取 Session 数据
    # [修改] 使用实例调用 get_session
    state = session_service.get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' 不存在，请先上传数据")

    try:
        # 2. 调用 Workflow
        # workflow 内部会自动处理语义增强(Lazy Loading)和 New/Edit 模式判断
        dashboard_json = await workflow.execute_step(
            payload=payload,
            data_summaries=state["summaries"],
            data_context=state["data_context"],
            last_session_state=state.get("last_workflow_state")
        )

        # 3. 更新 Session 状态
        # [修改] 调用 update_session_metadata，传入 dashboard_json.metadata (包含 last_code, last_layout)
        session_service.update_session_metadata(session_id, dashboard_json.metadata)

        # [可选] 记录对话历史
        session_service.append_history(
            session_id,
            query=payload.query,
            response=f"Generated dashboard: {dashboard_json.title}"
        )

        return dashboard_json

    except Exception as e:
        # 打印详细堆栈方便后端调试
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Workflow Execution Error: {str(e)}")