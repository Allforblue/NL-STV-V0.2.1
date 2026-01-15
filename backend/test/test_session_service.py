import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from typing import Dict, Any

from core.services.session_service import SessionManager


class TestSessionManager:

    @pytest.fixture
    def mock_ingestion(self):
        """
        Mock IngestionManager。
        注意：必须在 SessionManager 初始化前生效。
        """
        # Patch 目标必须指向 session_service 文件里导入的那个类
        with patch("core.services.session_service.IngestionManager") as mock_cls:
            instance = mock_cls.return_value
            # 模拟 load_all_to_context 返回的数据
            df = pd.DataFrame({"col1": [1, 2, 3], "col2": ["a", "b", "c"]})
            instance.load_all_to_context.return_value = {"df_test": df}
            yield instance

    @pytest.fixture
    def mock_profiler(self):
        """Mock basic_stats"""
        with patch("core.services.session_service.get_dataset_fingerprint") as mock_func:
            mock_func.return_value = {
                "rows": 3,
                "cols": 2,
                "column_stats": {"col1": {"dtype": "int64"}}
            }
            yield mock_func

    @pytest.fixture
    def manager(self, mock_ingestion, mock_profiler):
        """
        【关键修改】
        这里将 mock_ingestion 和 mock_profiler 作为参数传入。
        这迫使 Pytest 先运行 Mock Fixtures (进入 patch 上下文)，
        然后再执行 SessionManager() 的实例化。
        这样 SessionManager 内部 new IngestionManager() 时，拿到的就是 Mock 对象了。
        """
        return SessionManager()

    def test_create_session_flow(self, manager, mock_ingestion, mock_profiler):
        """核心测试：验证 create_session 是否串联了 Ingestion 和 Profiler"""
        session_id = "test_user_001"
        file_paths = ["/tmp/data.csv"]

        # 执行创建
        session = manager.create_session(session_id, file_paths)

        # 1. 验证 Ingestion 被调用 (这次应该成功了)
        mock_ingestion.load_all_to_context.assert_called_once_with(file_paths, use_full=False)

        # 2. 验证 Profiler 被调用
        mock_profiler.assert_called_once()

        # 3. 验证 Session 结构是否完整
        assert session["session_id"] == session_id
        assert "df_test" in session["data_context"]
        assert len(session["summaries"]) == 1

        # 验证 summary 内容
        summary = session["summaries"][0]
        assert summary["variable_name"] == "df_test"
        assert summary["basic_stats"]["rows"] == 3

    def test_session_isolation(self, manager, mock_ingestion):
        """测试：不同用户的会话应该隔离"""
        manager.create_session("user_A", ["file_A"])
        manager.create_session("user_B", ["file_B"])

        sess_a = manager.get_session("user_A")
        sess_b = manager.get_session("user_B")

        assert sess_a is not sess_b
        assert sess_a["session_id"] == "user_A"
        assert sess_b["session_id"] == "user_B"

    def test_update_metadata(self, manager, mock_ingestion):
        """测试：Workflow 执行后更新状态"""
        sid = "user_X"
        manager.create_session(sid, [])

        new_state = {"last_code": "print('updated')"}
        manager.update_session_metadata(sid, new_state)

        sess = manager.get_session(sid)
        assert sess["last_workflow_state"]["last_code"] == "print('updated')"

    def test_delete_session(self, manager):
        """测试：删除会话"""
        # 为了测试删除，我们需要先手动塞一个进去，或者调用 create_session
        manager._sessions["temp"] = {"data_context": {}}

        manager.delete_session("temp")
        assert manager.get_session("temp") is None