from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any,Union


class InteractionPayload(BaseModel):
    """
    多模态交互载荷：
    支持“自然语言指令”与“地图 UI 操作”协同驱动。
    """
    session_id: str = Field(..., description="用于维持对话上下文的会话ID")

    # 模态 1: 自然语言
    query: Optional[str] = Field(None, description="用户的文字指令，如 '分析这里的拥堵原因'")

    # 模态 2: 地图 UI 交互 (实现需求 2 的核心)
    bbox: Optional[List[float]] = Field(
        None,
        description="地图框选范围 [min_lon, min_lat, max_lon, max_lat]"
    )
    selected_ids: Optional[List[Union[str, int]]] = Field(
        None,
        description="地图上点击选中的特定实体 ID 列表"
    )

    # 交互控制
    force_new: bool = Field(
        False,
        description="是否强制重新规划看板，而非增量修改"
    )

    # 当前看板状态快照 (可选)
    current_dashboard_id: Optional[str] = None