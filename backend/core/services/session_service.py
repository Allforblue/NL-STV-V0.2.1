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
    支持从采样模式(快速响应)自动切换到全量模式(精准分析)。
    """

    def __init__(self):
        # 内存存储字典
        # Structure: { session_id: { "summaries": [...], "data_context": {...}, "history": [...] } }
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self.ingestion_manager = IngestionManager()

    def create_session(self, session_id: str, file_paths: List[str]) -> Dict[str, Any]:
        """
        创建新会话：
        1. 加载数据 (默认采样模式，保证上传接口秒开)
        2. 生成画像 (Profiling)
        3. 初始化状态
        """
        logger.info(f"正在初始化会话 {session_id}，处理文件: {file_paths}")

        # 1. 初始加载：使用采样模式 (Fast)
        data_context = self.ingestion_manager.load_all_to_context(file_paths, use_full=False)

        if not data_context:
            logger.warning(f"会话 {session_id} 未能加载任何有效数据。")

        # 2. 生成数据摘要 (Summaries)
        summaries = []
        for var_name, df in data_context.items():
            try:
                # [路径匹配逻辑] 根据 var_name 反向查找原始文件路径
                matched_path = "unknown"
                for p in file_paths:
                    fname_stem = Path(p).stem.lower()
                    if fname_stem in var_name:
                        matched_path = str(p)
                        break

                # 兜底逻辑
                if matched_path == "unknown" and file_paths:
                    matched_path = file_paths[0]

                # 调用 profiler 生成指纹信息
                fingerprint = get_dataset_fingerprint(df)

                # 构造标准的 summary 结构
                summary = {
                    "variable_name": var_name,
                    "file_info": {
                        "path": matched_path,
                        "rows": fingerprint["rows"],
                        "cols": fingerprint["cols"]
                    },
                    "basic_stats": fingerprint,
                    "semantic_analysis": {
                        "description": f"Loaded from {Path(matched_path).name}",
                        "semantic_tags": {}
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
            "file_paths": file_paths,  # [新增] 保存原始文件路径，方便后续重载
            "is_full_data": False,  # [新增] 标记当前是采样数据
            "last_workflow_state": None,
            "history": []
        }

        self._sessions[session_id] = session_state
        logger.info(f"✅ 会话 {session_id} 就绪 (采样模式)。包含变量: {list(data_context.keys())}")

        return session_state

    def ensure_full_data_context(self, session_id: str):
        """
        [新增] 确保当前会话的数据是全量的。
        如果是第一次进行分析，会触发全量加载（耗时操作）。
        """
        session = self.get_session(session_id)
        if not session:
            return

        # 如果已经是全量数据，直接返回
        if session.get("is_full_data", False):
            return

        logger.info(f">>> 正在将会话 {session_id} 切换为【全量数据模式】以保证分析准确性...")

        try:
            file_paths = session.get("file_paths", [])
            # 重新加载，这次 use_full=True
            full_context = self.ingestion_manager.load_all_to_context(file_paths, use_full=True)

            # 更新 Session 中的 data_context
            # 注意：summaries 不需要更新，因为基础统计特征（列名、类型）在全量和采样下通常是一致的，
            # 且行数差异不影响 Schema 理解，反而能节省 LLM Token。
            session["data_context"] = full_context
            session["is_full_data"] = True

            logger.info(f"✅ 全量数据加载完成。")
        except Exception as e:
            logger.error(f"切换全量数据失败: {e}")
            # 失败则保持原样，避免系统崩溃

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