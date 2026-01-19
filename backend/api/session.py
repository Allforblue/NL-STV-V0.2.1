from fastapi import APIRouter, HTTPException
from core.services.session_service import session_service

router = APIRouter()


@router.get("/{session_id}/status")
async def get_session_status(session_id: str):
    """获取会话实时状态"""
    state = session_service.get_session(session_id)
    if not state:
        return {"active": False}

    store = state.get("state_store")
    return {
        "active": True,
        "session_id": session_id,
        "is_full_data": state.get("is_full_data", False),
        "snapshot_count": len(store.snapshots) if store else 0,
        "current_snapshot_id": store.current_snapshot_id if store else None
    }


@router.get("/{session_id}/history")
async def get_session_history(session_id: str):
    """
    [新增] 获取历史快照列表
    用于驱动原型图左侧的“历史对话区域”
    """
    history = session_service.get_history_list(session_id)
    if not history and not session_service.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_id,
        "history": history  # 包含 snapshot_id, query, time, summary
    }


@router.delete("/{session_id}")
async def clear_session(session_id: str):
    session_service.delete_session(session_id)
    return {"status": "cleared", "session_id": session_id}