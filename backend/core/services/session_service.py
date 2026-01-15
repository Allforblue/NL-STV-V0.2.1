import logging
from typing import Dict, Any, Optional, List
from pathlib import Path

# --- 引入必要的下层模块 ---
from core.ingestion.ingestion import IngestionManager
from core.profiler.basic_stats import get_dataset_fingerprint

logger = logging.getLogger(__name__)


class SessionManager:
    """
    会话管理器 (完整版)：
    负责会话的生命周期管理，并协调数据的初始加载与画像生成。
    """

    def __init__(self):
        # 内存存储字典
        # Structure: { session_id: { "summaries": [...], "data_context": {...}, "history": [...] } }
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self.ingestion_manager = IngestionManager()

    def create_session(self, session_id: str, file_paths: List[str]) -> Dict[str, Any]:
        """
        创建新会话：
        1. 加载数据 (Ingestion)
        2. 生成画像 (Profiling)
        3. 初始化状态
        """
        logger.info(f"正在初始化会话 {session_id}，处理文件: {file_paths}")

        # 1. 加载数据到内存 (Data Context)
        # 注意：这里我们默认加载采样数据用于快速分析，
        # 如果是全量计算需求，可以在 Workflow 执行阶段按需重新加载 Full Data
        data_context = self.ingestion_manager.load_all_to_context(file_paths, use_full=False)

        if not data_context:
            logger.warning(f"会话 {session_id} 未能加载任何有效数据。")

        # 2. 生成数据摘要 (Summaries)
        summaries = []
        for var_name, df in data_context.items():
            try:
                # 调用 profiler 生成指纹信息
                fingerprint = get_dataset_fingerprint(df)

                # 构造标准的 summary 结构
                # 注意：Semantic Tags (语义标签) 此时还是空的，
                # 它们稍后会由 SemanticAnalyzer 在 Workflow 或后台任务中填充。
                summary = {
                    "variable_name": var_name,
                    "file_info": {
                        "path": str(file_paths[0]),  # 简化处理，实际应匹配具体文件来源
                        "rows": fingerprint["rows"],
                        "cols": fingerprint["cols"]
                    },
                    "basic_stats": fingerprint,  # 包含 min/max/null 等统计
                    "semantic_analysis": {
                        "description": f"Loaded from {var_name}",
                        "semantic_tags": {}  # 待填充
                    }
                }
                summaries.append(summary)
            except Exception as e:
                logger.error(f"为变量 {var_name} 生成画像失败: {e}")

        # 3. 存入会话状态
        session_state = {
            "session_id": session_id,
            "data_context": data_context,
            "summaries": summaries,
            "last_workflow_state": None,  # 用于存储上一次的 Workflow 返回结果 (layout, code)
            "history": []  # 对话历史
        }

        self._sessions[session_id] = session_state
        logger.info(f"✅ 会话 {session_id} 就绪。包含变量: {list(data_context.keys())}")

        return session_state

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话对象"""
        return self._sessions.get(session_id)

    def update_session_metadata(self, session_id: str, metadata: Dict[str, Any]):
        """
        更新 Workflow 执行后的元数据 (如 last_code, last_layout)
        """
        if session_id in self._sessions:
            if "last_workflow_state" not in self._sessions[session_id]:
                self._sessions[session_id]["last_workflow_state"] = {}

            # 合并更新
            current_state = self._sessions[session_id]["last_workflow_state"] or {}
            current_state.update(metadata)
            self._sessions[session_id]["last_workflow_state"] = current_state

    def append_history(self, session_id: str, query: str, response: str):
        """记录对话历史"""
        if session_id in self._sessions:
            self._sessions[session_id]["history"].append({
                "query": query,
                "response": response
            })

    def delete_session(self, session_id: str):
        """清理会话"""
        if session_id in self._sessions:
            # 帮助 GC 回收
            self._sessions[session_id]["data_context"].clear()
            del self._sessions[session_id]
            logger.info(f"🗑️ 会话 {session_id} 已移除。")


# 单例模式
session_service = SessionManager()