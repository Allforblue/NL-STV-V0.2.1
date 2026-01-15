from fastapi import APIRouter
from core.services.session_service import session_manager

router = APIRouter()

@router.get("/{session_id}/status")
async def get_session_status(session_id: str):
    """检查当前会话加载了哪些数据"""
    state = session_manager.get_session(session_id)
    if not state:
        return {"active": False}
    return {
        "active": True,
        "data_files": [s['file_info']['name'] for s in state['summaries']],
        "has_history": "last_workflow_state" in state
    }

@router.delete("/{session_id}")
async def clear_session(session_id: str):
    """清理会话，释放内存中的 DataFrame"""
    session_manager.delete_session(session_id)
    return {"status": "cleared"}