import uuid
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
    snapshot_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="快照唯一ID"
    )
    # [新增] 父快照 ID，用于构建分析路径树 (Undo/Redo 或 Branching)
    parent_snapshot_id: Optional[str] = None

    timestamp: datetime = Field(default_factory=datetime.now, description="快照创建时间")

    # 2. 触发上下文
    user_query: str = Field(..., description="触发该看板生成的用户原始指令")

    # [新增] 意图分类：如 "REGENERATE" (重做), "MODIFY" (修改), "EXPLORE" (钻取)
    # 帮助后端判断是该保留还是覆盖旧代码
    intent: Optional[str] = None

    # 3. 核心逻辑备份
    # 保存生成该看板的完整 Python 代码。回溯时，如果不只是看图还要继续编辑，这份代码至关重要。
    code_snapshot: str = Field(..., description="生成该看板的 Python 代码快照")

    # 4. 看板数据备份
    # 包含了当时的布局、图表配置以及执行后的真实数据(data_payload)
    layout_data: DashboardSchema = Field(..., description="当时的看板完整结构与数据负载")

    # 5. UI 表现元数据
    # 用于左侧历史对话列表显示的简短文字描述
    summary_text: Optional[str] = Field(None, description="用于历史列表展示的简短结论")

    # [新增] 执行耗时：用于性能监控
    execution_time_ms: Optional[float] = None

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True


class SessionStateStore(BaseModel):
    """
    会话全状态存储：
    管理一个会话中所有的快照序列。
    """
    session_id: str
    user_id: Optional[str] = None

    # 按时间顺序或逻辑顺序排列的快照列表
    snapshots: List[SessionStateSnapshot] = Field(default_factory=list)

    # 当前激活的快照 ID
    current_snapshot_id: Optional[str] = None

    # [新增] 会话元数据：如关联的数据文件路径列表
    active_files: List[str] = Field(default_factory=list)

    def get_snapshot(self, snapshot_id: str) -> Optional[SessionStateSnapshot]:
        """快速检索指定快照"""
        for ss in self.snapshots:
            if ss.snapshot_id == snapshot_id:
                return ss
        return None

    def get_latest(self) -> Optional[SessionStateSnapshot]:
        """获取最近一次生成的快照"""
        if not self.snapshots:
            return None
        return self.snapshots[-1]

    def add_snapshot(self, snapshot: SessionStateSnapshot):
        """添加新快照并更新当前指针"""
        self.snapshots.append(snapshot)
        self.current_snapshot_id = snapshot.snapshot_id

    def rollback(self, target_snapshot_id: str) -> bool:
        """回滚到指定状态"""
        snapshot = self.get_snapshot(target_snapshot_id)
        if snapshot:
            self.current_snapshot_id = target_snapshot_id
            return True
        return False