from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union
from enum import Enum


class InteractionTriggerType(str, Enum):
    """交互触发源类型"""
    NATURAL_LANGUAGE = "nl"  # 底部对话框输入的文字指令
    UI_ACTION = "ui"  # 地图上的框选(bbox)、点选(click)等 UI 行为
    BACKTRACK = "backtrack"  # 点击左侧历史对话区域进行回溯


class InteractionPayload(BaseModel):
    """
    增强版多模态交互载荷：
    支持“自然语言指令”、“地图/图表 UI 操作”以及“历史回溯”协同驱动。
    """
    session_id: str = Field(..., description="用于维持对话上下文的会话ID")

    # [关键新增] 标识本次交互的性质：是说话、是点图、还是点历史？
    trigger_type: InteractionTriggerType = Field(
        default=InteractionTriggerType.NATURAL_LANGUAGE,
        description="交互触发来源类型"
    )

    # 模态 1: 自然语言 (对应原型图底部的对话框)
    query: Optional[str] = Field(None, description="用户的文字指令，如 '分析这里的拥堵原因'")

    # 模态 2: UI 交互 (实现中间大地图与右侧图表的联动)
    active_component_id: Optional[str] = Field(
        None,
        description="触发交互的源组件ID，例如 'main_map' 或 'right_pie_1'"
    )
    bbox: Optional[List[float]] = Field(
        None,
        description="地图框选范围 [min_lon, min_lat, max_lon, max_lat]"
    )
    selected_ids: Optional[List[Union[str, int]]] = Field(
        None,
        description="地图上点击选中的特定实体 ID 列表"
    )

    # 模态 3: 历史回溯 (实现原型图左侧历史区域的需求)
    target_snapshot_id: Optional[str] = Field(
        None,
        description="回溯的目标快照ID。当点击历史记录时，后端直接返回对应的状态快照"
    )

    # 交互控制
    force_new: bool = Field(
        False,
        description="是否强制重新规划看板（即忽略现有布局，重新开始生成）"
    )

    # 当前上下文
    current_dashboard_id: Optional[str] = Field(None, description="当前页面正在显示的看板ID")