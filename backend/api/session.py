from fastapi import APIRouter
# [修改] 导入单例对象
from core.services.session_service import session_service

router = APIRouter()


@router.get("/{session_id}/status")
async def get_session_status(session_id: str):
    """检查当前会话加载了哪些数据"""
    # [修改] 使用实例调用
    state = session_service.get_session(session_id)

    if not state:
        return {"active": False, "message": "Session not found"}

    # 提取文件名列表 (做一些防御性处理)
    file_names = []
    if "summaries" in state:
        for s in state["summaries"]:
            # 优先获取 filename，如果没有则尝试从 path 解析，最后用 variable_name 兜底
            info = s.get("file_info", {})
            name = info.get("name") or info.get("path") or s.get("variable_name", "unknown")
            file_names.append(name)

    return {
        "active": True,
        "session_id": session_id,
        "data_files": file_names,
        # 检查是否有历史 Workflow 状态，如果有说明已经进行过分析
        "has_history": state.get("last_workflow_state") is not None,
        "variable_count": len(state.get("data_context", {}))
    }


@router.delete("/{session_id}")
async def clear_session(session_id: str):
    """清理会话，释放内存中的 DataFrame"""
    # [修改] 使用实例调用
    session_service.delete_session(session_id)
    return {"status": "cleared", "session_id": session_id}