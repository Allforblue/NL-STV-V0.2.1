import traceback
from fastapi import APIRouter, Request, HTTPException
from core.schemas.interaction import InteractionPayload
from core.schemas.dashboard import DashboardSchema
# 导入单例对象 session_service
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

    # 1. 基础检查：Session 是否存在
    if not session_service.get_session(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' 不存在，请先上传数据")

    try:
        # 2. [关键修改] 确保数据是全量的
        # 如果当前是采样模式，这里会触发全量加载（第一次分析时可能需要几秒钟）
        # 如果已经是全量模式，这步会直接跳过，耗时为0
        session_service.ensure_full_data_context(session_id)

        # 3. 获取最新的 Session 数据
        # 注意：必须在 ensure_full_data_context 之后获取，确保拿到的是 full_context
        state = session_service.get_session(session_id)

        # 4. 调用 Workflow
        # workflow 内部会自动处理语义增强(Lazy Loading)和 New/Edit 模式判断
        dashboard_json = await workflow.execute_step(
            payload=payload,
            data_summaries=state["summaries"],
            data_context=state["data_context"],  # 此时这里是全量数据
            last_session_state=state.get("last_workflow_state")
        )

        # 5. 更新 Session 状态
        # 保存生成的代码和布局，供下一次“语义钻取”使用
        session_service.update_session_metadata(session_id, dashboard_json.metadata)

        # 6. 记录对话历史
        session_service.append_history(
            session_id,
            query=payload.query,
            response=f"Generated dashboard: {dashboard_json.title}"
        )

        return dashboard_json

    except Exception as e:
        # 打印详细堆栈方便后端调试
        traceback.print_exc()
        # 返回 500 错误给前端
        raise HTTPException(status_code=500, detail=f"Workflow Execution Error: {str(e)}")