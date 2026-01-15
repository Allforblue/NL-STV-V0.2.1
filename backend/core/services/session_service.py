import logging
from typing import Dict, Any, Optional, List
from core.ingestion.ingestion import IngestionManager

logger = logging.getLogger(__name__)


class SessionManager:
    """
    会话管理器：
    负责在内存中维护每个用户的会话状态。
    存储内容包括：数据摘要 (Summaries)、真实的 DataFrame (Data Context)、以及历史代码快照。
    """

    def __init__(self):
        # 内存存储字典：{ session_id: { "summaries": [], "data_context": {}, "last_workflow_state": {} } }
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self.ingestion_manager = IngestionManager()

    def init_session(self, session_id: str, summaries: List[Dict[str, Any]]):
        """
        初始化会话：当用户上传并分析完数据后调用。
        它不仅存入摘要，还会根据路径真正将数据加载进内存。
        """
        logger.info(f"正在为会话 {session_id} 初始化数据上下文...")

        # 提取所有需要加载的文件路径
        file_paths = [s['file_info']['path'] for s in summaries]

        # 调用 IngestionManager 加载真实的 DataFrame 对象
        # 这里默认使用采样模式（False），如果需要全量可动态调整
        data_context = self.ingestion_manager.load_all_to_context(file_paths, use_full=False)

        self._sessions[session_id] = {
            "summaries": summaries,
            "data_context": data_context,
            "last_workflow_state": None,  # 初始时没有历史代码
            "history": []  # 对话历史
        }
        logger.info(f"✅ 会话 {session_id} 初始化完成，已加载 {len(data_context)} 个变量。")

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取会话完整状态"""
        return self._sessions.get(session_id)

    def update_session_state(self, session_id: str, key: str, value: Any):
        """更新会话中的特定状态（如更新 last_workflow_state）"""
        if session_id in self._sessions:
            self._sessions[session_id][key] = value
            # 如果更新的是工作流状态，同时也记录进对话历史
            if key == "last_workflow_state":
                self._sessions[session_id]["history"].append(value)

    def delete_session(self, session_id: str):
        """删除会话并释放内存"""
        if session_id in self._sessions:
            # 显式清理大的 DataFrame 对象
            self._sessions[session_id]["data_context"].clear()
            del self._sessions[session_id]
            logger.info(f"🗑️ 会idad {session_id} 已销毁，内存已释放。")


# 实例化单例对象供全局使用
session_manager = SessionManager()