import os
import logging
from typing import Dict, Any, List
from pathlib import Path
from core.ingestion.loader_factory import LoaderFactory

logger = logging.getLogger(__name__)


class IngestionManager:
    """
    接入管理器：管理数据沙箱中的文件加载与预览。
    """

    def __init__(self, sandbox_dir: str = "data_sandbox"):
        self.sandbox_dir = sandbox_dir
        if not os.path.exists(self.sandbox_dir):
            os.makedirs(self.sandbox_dir)

    def load_all_to_context(self, file_paths: List[str], use_full: bool = False) -> Dict[str, Any]:
        """
        将多个文件加载到内存上下文中（data_context），供 Executor 使用。
        """
        data_context = {}
        for path in file_paths:
            try:
                loader = LoaderFactory.get_loader(path)
                var_name = f"df_{Path(path).stem.lower()}"

                if use_full:
                    logger.info(f"Full loading: {path}")
                    df = loader.load(path)
                else:
                    logger.info(f"Sampling (50k): {path}")
                    df = loader.peek(path, n=50000)

                data_context[var_name] = df
            except Exception as e:
                logger.error(f"Failed to load {path}: {e}")

        return data_context