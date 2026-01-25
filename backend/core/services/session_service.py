import logging
import uuid
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime

# --- 引入必要的模型与下层模块 ---
from core.ingestion.ingestion import IngestionManager
from core.profiler.basic_stats import get_dataset_fingerprint
from core.schemas.state import SessionStateSnapshot, SessionStateStore
from core.schemas.dashboard import DashboardSchema

logger = logging.getLogger(__name__)


class SessionManager:
    """
    增强型会话管理器：
    1. 管理大规模时空数据的采样与全量加载。
    2. [关键升级] 管理看板状态快照序列，支持历史回溯。
    """

    def __init__(self):
        # 内存存储结构: { session_id: { "store": SessionStateStore, "data_context": {...}, ... } }
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self.ingestion_manager = IngestionManager()

    def create_session(self, session_id: str, file_paths: List[str]) -> Dict[str, Any]:
        """创建新会话并初始化画像"""
        logger.info(f">>> 初始化高交互会话 {session_id}...")

        # 1. 初始加载：采样模式
        data_context = self.ingestion_manager.load_all_to_context(file_paths, use_full=False)

        # 2. 生成基础画像 (Summaries)
        summaries = []
        for var_name, df in data_context.items():
            try:
                matched_path = next((p for p in file_paths if Path(p).stem.lower() in var_name), file_paths[0])
                fingerprint = get_dataset_fingerprint(df)

                summaries.append({
                    "variable_name": var_name,
                    "file_info": {"path": str(matched_path), "rows": fingerprint["rows"]},
                    "basic_stats": fingerprint,
                    "semantic_analysis": {"description": f"数据源: {Path(matched_path).name}", "semantic_tags": {}}
                })
            except Exception as e:
                logger.error(f"画像生成失败: {e}")

        # 3. 初始化快照存储库
        state_store = SessionStateStore(session_id=session_id)

        session_state = {
            "session_id": session_id,
            "data_context": data_context,
            "summaries": summaries,
            "file_paths": file_paths,
            "is_full_data": False,
            "state_store": state_store,  # [关键新增] 快照存储
            "last_workflow_state": None
        }

        self._sessions[session_id] = session_state
        return session_state

    # --- 快照管理核心逻辑 (支撑历史回溯) ---

    def save_snapshot(
            self,
            session_id: str,
            query: str,
            code: str,
            layout_data: DashboardSchema,
            summary: str = ""
    ) -> str:
        """
        保存当前看板状态为快照。
        """
        session = self.get_session(session_id)
        if not session: return ""

        snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"

        # 创建快照对象
        new_snapshot = SessionStateSnapshot(
            snapshot_id=snapshot_id,
            timestamp=datetime.now(),
            user_query=query,
            code_snapshot=code,
            layout_data=layout_data,
            summary_text=summary or f"分析: {query[:15]}..."
        )

        # 存入序列
        store: SessionStateStore = session["state_store"]
        store.snapshots.append(new_snapshot)
        store.current_snapshot_id = snapshot_id

        logger.info(f"✅ 快照已存档: {snapshot_id} (Session: {session_id})")
        return snapshot_id

    def get_snapshot(self, session_id: str, snapshot_id: str) -> Optional[SessionStateSnapshot]:
        """获取特定历史快照"""
        session = self.get_session(session_id)
        if session:
            return session["state_store"].get_snapshot(snapshot_id)
        return None

    def get_history_list(self, session_id: str) -> List[Dict[str, Any]]:
        """
        获取历史记录摘要列表，供前端左侧边栏渲染。
        """
        session = self.get_session(session_id)
        if not session: return []

        return [
            {
                "snapshot_id": s.snapshot_id,
                "query": s.user_query,
                "time": s.timestamp.strftime("%H:%M:%S"),
                "summary": s.summary_text
            }
            for s in session["state_store"].snapshots
        ]

    # --- 数据一致性维护 ---

    def ensure_full_data_context(self, session_id: str):
        """切换至全量数据模式"""
        session = self.get_session(session_id)
        if not session or session.get("is_full_data"): return

        logger.info(f">>> 切换会话 {session_id} 至全量数据模式...")
        try:
            full_context = self.ingestion_manager.load_all_to_context(session["file_paths"], use_full=True)
            session["data_context"] = full_context
            session["is_full_data"] = True
        except Exception as e:
            logger.error(f"全量加载失败: {e}")

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._sessions.get(session_id)

    def delete_session(self, session_id: str):
        if session_id in self._sessions:
            self._sessions[session_id]["data_context"].clear()
            del self._sessions[session_id]
            logger.info(f"🗑️ 会话 {session_id} 已移除。")

    def update_session_metadata(self, session_id: str, metadata: Dict[str, Any]):
        """
        更新会话的最新的执行元数据（如 last_code, last_layout）
        以便下一轮交互能基于当前状态进行 VizEditor 修改。
        """
        session = self.get_session(session_id)
        if session:
            # 将最新的看板元数据同步到 session 的顶层状态中
            session["last_workflow_state"] = metadata
            logger.info(f"💾 会话元数据已同步: {session_id}")


# 单例
session_service = SessionManager()