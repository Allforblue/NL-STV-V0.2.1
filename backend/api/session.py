import logging
import os
import shutil
from datetime import datetime
from fastapi import APIRouter, HTTPException
from core.services.session_service import session_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{session_id}/status")
async def get_session_status(session_id: str):
    """获取会话实时状态，增加时空特征标识"""
    state = session_service.get_session(session_id)
    if not state:
        return {"active": False}

    store = state.get("state_store")
    summaries = state.get("summaries", [])

    return {
        "active": True,
        "session_id": session_id,
        "is_full_data": state.get("is_full_data", False),
        "has_geospatial": any(s.get("is_geospatial", False) for s in summaries),
        "snapshot_count": len(store.snapshots) if store else 0,
        "current_snapshot_id": store.current_snapshot_id if store else None,
        "last_updated": datetime.now().isoformat() if not store.snapshots else store.snapshots[-1].timestamp.isoformat()
    }


@router.get("/{session_id}/history")
async def get_session_history(session_id: str):
    """
    获取历史快照列表
    用于驱动原型图左侧的“历史对话区域”
    """
    history = session_service.get_history_list(session_id)
    if not history and not session_service.get_session(session_id):
        logger.warning(f"Attempted to access non-existent session history: {session_id}")
        raise HTTPException(status_code=404, detail="会话不存在")

    return {
        "session_id": session_id,
        "history": history  # 包含 snapshot_id, query, time, summary
    }


@router.get("/{session_id}/metadata")
async def get_session_metadata(session_id: str):
    """
    [增强] 获取会话元数据（时空范围 + 字段指纹）
    用于前端初始化时间轴范围、地图中心点以及过滤器组件。
    """
    state = session_service.get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    metadata = {
        "session_id": session_id,
        "temporal_context": [],  # 时间维度特征
        "spatial_context": [],  # [新增] 空间维度特征（Bounds, CRS）
        "variables": []  # 变量清单
    }

    for summary in state.get("summaries", []):
        var_name = summary.get("variable_name")
        is_geo = summary.get("is_geospatial", False)

        # 1. 基础变量信息
        var_info = {
            "name": var_name,
            "rows": summary.get("file_info", {}).get("rows_total", 0),
            "type": "spatial" if is_geo else "tabular"
        }
        metadata["variables"].append(var_info)

        # 2. 提取时间特征 (来自 SemanticAnalyzer)
        sem = summary.get("semantic_analysis", {})
        temp_ctx = sem.get("temporal_context", {})
        if temp_ctx and temp_ctx.get("primary_time_col"):
            metadata["temporal_context"].append({
                "variable": var_name,
                "column": temp_ctx.get("primary_time_col"),
                "span": temp_ctx.get("time_span"),
                "granularity": temp_ctx.get("time_granularity"),
                "suggested_resampling": temp_ctx.get("suggested_resampling")
            })

        # 3. [新增] 提取空间特征 (来自 BasicStats)
        if is_geo:
            stats = summary.get("basic_stats", {})
            col_stats = stats.get("column_stats", {})

            # 寻找包含 bounds 的几何列
            for col, info in col_stats.items():
                if info.get("dtype") == "geometry" and info.get("bounds"):
                    metadata["spatial_context"].append({
                        "variable": var_name,
                        "crs": summary.get("crs", "EPSG:4326"),
                        "bounds": info.get("bounds"),  # [minx, miny, maxx, maxy]
                        "geom_type": info.get("geom_type")
                    })
                    break

    return metadata


@router.delete("/{session_id}")
async def clear_session(session_id: str):
    """彻底清理会话及其沙箱缓存"""

    # 1. 清理内存/数据库中的会话状态
    session_service.delete_session(session_id)

    # 2. 定义沙箱根目录 (建议放到配置文件中，这里暂沿用硬编码)
    sandbox_root = "core/data_sandbox"

    # 3. 安全性处理：防止路径遍历攻击 (如 session_id 为 "../../etc")
    # os.path.basename 确保只取文件名部分，过滤掉路径分隔符
    safe_session_id = os.path.basename(session_id)
    if safe_session_id != session_id:
        logger.warning(f"Potential path traversal attempt with session_id: {session_id}")
        # 如果检测到恶意路径，可以根据策略决定是否继续，这里选择仅处理安全ID

    session_sandbox = os.path.join(sandbox_root, safe_session_id)

    # 4. 执行文件系统删除
    if os.path.exists(session_sandbox) and os.path.isdir(session_sandbox):
        try:
            # rmtree 会递归删除文件夹及其所有内容
            shutil.rmtree(session_sandbox)
            logger.info(f"Sandbox directory deleted: {session_sandbox}")
        except Exception as e:
            # 即使文件删除失败，也记录日志，但不阻断 API 返回
            logger.error(f"Failed to delete sandbox directory {session_sandbox}: {str(e)}")
            # 可选：如果文件残留不可接受，可以在这里 raise HTTPException
    else:
        logger.info(f"Sandbox directory not found (already clean): {session_sandbox}")

    logger.info(f"Session {session_id} has been explicitly cleared via API.")
    return {"status": "cleared", "session_id": session_id}