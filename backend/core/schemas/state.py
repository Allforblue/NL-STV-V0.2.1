from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from .dashboard import DashboardSchema


class SessionStateSnapshot(BaseModel):
    """
    会话状态快照模型：
    用于保存分析过程中的每一个“时间点”，支撑历史回溯功能。
    """
    # 1. 唯一标识
    snapshot_id: str = Field(..., description="快照唯一ID，通常由后端生成或使用时间戳")
    timestamp: datetime = Field(default_factory=datetime.now, description="快照创建时间")

    # 2. 触发上下文
    user_query: str = Field(..., description="触发该看板生成的用户原始指令")

    # 3. 核心逻辑备份
    # 保存生成该看板的完整 Python 代码。回溯时，如果不只是看图还要继续编辑，这份代码至关重要。
    code_snapshot: str = Field(..., description="生成该看板的 Python 代码快照")

    # 4. 看板数据备份
    # 直接嵌套 DashboardSchema，包含了当时的布局、图表配置以及执行后的真实数据(data_payload)
    layout_data: DashboardSchema = Field(..., description="当时的看板完整结构与数据负载")

    # 5. UI 表现元数据
    # 用于左侧历史对话列表显示的简短文字描述
    summary_text: Optional[str] = Field(None, description="用于历史列表展示的简短结论")

    class Config:
        # 允许从字典快速加载，并支持 JSON 序列化
        populate_by_name = True
        arbitrary_types_allowed = True


class SessionStateStore(BaseModel):
    """
    会话全状态存储：
    管理一个会话中所有的快照序列。
    """
    session_id: str
    # 按时间顺序排列的快照列表
    snapshots: List[SessionStateSnapshot] = Field(default_factory=list)
    # 当前激活的快照 ID
    current_snapshot_id: Optional[str] = None

    def get_snapshot(self, snapshot_id: str) -> Optional[SessionStateSnapshot]:
        """快速检索指定快照"""
        for ss in self.snapshots:
            if ss.snapshot_id == snapshot_id:
                return ss
        return None