import os
import logging
import pandas as pd  # [必要新增] 用于时间类型转换
from typing import Dict, Any, List
from pathlib import Path
from core.ingestion.loader_factory import LoaderFactory

logger = logging.getLogger(__name__)


class IngestionManager:
    """
    接入管理器：管理数据沙箱中的文件加载与预览。
    [V4.0 升级]：增加自动时间列识别转换，为时间维度分析及后续代码生成提速。
    """

    def __init__(self, sandbox_dir: str = "data_sandbox"):
        # 使用绝对路径确保路径引用的稳定性
        self.sandbox_dir = os.path.abspath(sandbox_dir)
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
                # [关键优化] 替换中划线，确保生成的变量名在 Python 中合法（防止 df_taxi-data 报错）
                var_name = f"df_{Path(path).stem.lower().replace('-', '_')}"

                if use_full:
                    logger.info(f"Full loading: {path}")
                    df = loader.load(path)
                else:
                    logger.info(f"Sampling (10): {path}")
                    df = loader.peek(path, n=10)

                # --- [新增必要逻辑] 自动时间列转换 ---
                # 预先转换 Datetime 对象，使得后续趋势分析中 resample() 速度提升 10 倍以上
                for col in df.columns:
                    if df[col].dtype == 'object':
                        # 识别常见的包含时间含义的关键词
                        if any(kw in col.lower() for kw in ['time', 'date', 'at', 'stamp']):
                            try:
                                df[col] = pd.to_datetime(df[col])
                                logger.info(f"字段 '{col}' 已自动转换为 Datetime 对象")
                            except:
                                continue

                data_context[var_name] = df
            except Exception as e:
                logger.error(f"Failed to load {path}: {e}")

        return data_context