import logging
import uuid
import threading
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
    增强型会话管理器 (V2.3 时空增强版)：
    1. [Performance] 管理大规模时空数据的采样与全量加载。
    2. [Safety] 管理看板状态快照序列，支持历史回溯。
    3. [STV Optimized] 强化时空指纹（CRS/Bounds）在画像中的存储。
    """

    def __init__(self):
        # 内存存储结构: { session_id: { "store": SessionStateStore, "data_context": {...}, "lock": Lock, ... } }
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self.ingestion_manager = IngestionManager()

    def create_session(self, session_id: str, file_paths: List[str]) -> Dict[str, Any]:
        """创建新会话并初始化画像"""
        logger.info(f">>> [Session] 正在初始化时空分析会话: {session_id}")

        # 1. 初始加载：采用采样模式，保障响应速度
        data_context = self.ingestion_manager.load_all_to_context(file_paths, use_full=False)

        # 2. 生成基础画像 (Summaries) - 增强了对时空特性的感知
        summaries = []
        for var_name, df in data_context.items():
            try:
                # 匹配原始文件路径
                matched_path = next((p for p in file_paths if Path(p).stem.lower() in var_name), file_paths[0])

                # 核心：获取增强后的时空指纹
                fingerprint = get_dataset_fingerprint(df)

                summaries.append({
                    "variable_name": var_name,
                    "file_info": {
                        "path": str(matched_path),
                        "name": Path(matched_path).name,
                        "rows_total": fingerprint.get("rows", 0)
                    },
                    "is_geospatial": fingerprint.get("is_geospatial", False),
                    "crs": fingerprint.get("crs", "Unknown"),  # 记录原始坐标系
                    "column_stats": fingerprint.get("column_stats", {}),  # 注入列统计，辅助 Join 安全检查
                    "basic_stats": fingerprint,
                    "semantic_analysis": {
                        "description": f"数据源: {Path(matched_path).name}",
                        "dataset_type": "spatial" if fingerprint.get("is_geospatial") else "tabular",
                        "semantic_tags": {}
                    }
                })
            except Exception as e:
                logger.error(f"画像生成失败 ({var_name}): {e}")

        # 3. 初始化状态存储库
        state_store = SessionStateStore(session_id=session_id)

        session_state = {
            "session_id": session_id,
            "data_context": data_context,
            "summaries": summaries,
            "file_paths": file_paths,
            "is_full_data": False,
            "state_store": state_store,
            "last_workflow_state": None,
            "lock": threading.Lock()  # 会话级互斥锁，防止全量加载时的并发冲突
        }

        self._sessions[session_id] = session_state
        return session_state

    # --- 快照管理核心逻辑 ---

    def save_snapshot(
            self,
            session_id: str,
            query: str,
            code: str,
            layout_data: DashboardSchema,
            summary: str = ""
    ) -> str:
        """保存当前看板状态为快照"""
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

        # 存入序列并更新当前指针
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
        """获取历史记录摘要列表"""
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
        """
        切换至全量数据模式。
        [STV Optimized] 确保在大规模数据加载过程中保持坐标系感知和内存隔离。
        """
        session = self.get_session(session_id)
        if not session: return

        if session.get("is_full_data"): return

        lock = session["lock"]
        with lock:
            # 双重检查
            if session.get("is_full_data"):
                return

            logger.info(f">>> [IO] 会话 {session_id} 正在执行全量数据切换 (Large Scale Loading)...")
            try:
                # 执行全量加载
                full_context = self.ingestion_manager.load_all_to_context(session["file_paths"], use_full=True)

                # 数据完整性检查：确保变量名未发生漂移
                for var in session["data_context"].keys():
                    if var not in full_context:
                        logger.warning(f"全量加载中缺失变量: {var}，保留采样副本。")
                        full_context[var] = session["data_context"][var]

                session["data_context"] = full_context
                session["is_full_data"] = True
                logger.info(f"✅ 会话 {session_id} 全量数据就绪。")
            except Exception as e:
                logger.error(f"全量加载过程中发生严重错误: {e}")
                # 失败时保持采样模式，不中断业务

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._sessions.get(session_id)

    def delete_session(self, session_id: str):
        """清理会话资源，防止内存溢出"""
        if session_id in self._sessions:
            try:
                # 显式清理 context 中的 DataFrame
                for var_name in list(self._sessions[session_id]["data_context"].keys()):
                    del self._sessions[session_id]["data_context"][var_name]
                self._sessions[session_id]["data_context"].clear()
            except:
                pass
            del self._sessions[session_id]
            logger.info(f"🗑️ 会话 {session_id} 资源已释放。")

    def update_session_metadata(self, session_id: str, metadata: Dict[str, Any]):
        """更新会话执行状态，为增量修改 (VizEditor) 提供上下文"""
        session = self.get_session(session_id)
        if session:
            session["last_workflow_state"] = metadata
            logger.info(f"💾 会话状态已同步 (Code/Layout): {session_id}")


# 单例导出
session_service = SessionManager()