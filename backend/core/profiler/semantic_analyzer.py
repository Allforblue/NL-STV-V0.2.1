import json
import logging
from typing import Dict, Any, List
from pathlib import Path
from core.llm.AI_client import AIClient
from core.ingestion.loader_factory import LoaderFactory

logger = logging.getLogger(__name__)


class SemanticAnalyzer:
    """
    语义分析器 (V2 增强版)：
    1. 识别字段的地理/时间/指标属性。
    2. 为 DashboardPlanner 提供布局建议。
    3. 识别跨表关联键，支撑“语义钻取”。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    def _get_basic_fingerprint(self, file_path: str) -> Dict[str, Any]:
        """获取物理层面的指纹：行数、列名、数据类型、样本"""
        loader = LoaderFactory.get_loader(file_path)
        df_preview = loader.peek(file_path, n=5)  # 取样5行
        row_count = loader.count_rows(file_path)

        col_stats = {}
        for col in df_preview.columns:
            col_stats[col] = {
                "dtype": str(df_preview[col].dtype),
                "samples": df_preview[col].dropna().unique()[:3].tolist(),
                "has_nulls": df_preview[col].isnull().any()
            }

        return {
            "rows": row_count,
            "columns": col_stats,
            "filename": Path(file_path).name
        }

    def analyze(self, file_path: str) -> Dict[str, Any]:
        """主入口：从数据预览中提取语义标签"""
        logger.info(f"Analyzing semantics for: {file_path}")

        # 1. 获取物理特征
        fingerprint = self._get_basic_fingerprint(file_path)

        # 2. 构建 Prompt，引导 LLM 进行语义分类
        system_prompt = """
        你是一位时空数据专家。请根据提供的数据样例，为每个字段打上语义标签。
        可选标签：
        - ST_TIME: 时间戳/日期
        - ST_LAT/ST_LON: 经纬度坐标
        - ST_GEO: 几何对象 (WKT/WKB)
        - ST_LOC_ID: 位置 ID (如区域编码、路段ID)
        - BIZ_METRIC: 业务数值指标 (如流量、价格、速度)
        - BIZ_CAT: 业务分类字段 (如车型、天气、行政区名)
        - ID_KEY: 唯一标识符或外键
        """

        user_prompt = f"""
        数据文件: {fingerprint['filename']}
        行数预览: {fingerprint['rows']}
        字段样例: {json.dumps(fingerprint['columns'], ensure_ascii=False)}

        请输出 JSON 格式：
        {{
          "dataset_type": "TRAJECTORY | GEO_ZONE | LOOKUP_TABLE",
          "description": "一句话描述数据内容",
          "semantic_tags": {{ "字段名": "标签" }},
          "recommended_charts": ["应该用什么图表展示这个数据"],
          "potential_join_keys": ["哪些字段可能用于关联其他表"]
        }}
        """

        try:
            # 调用 AIClient 获取结构化输出
            ai_result = self.llm.query_json(prompt=user_prompt, system_prompt=system_prompt)

            # 整合结果
            final_result = {
                "file_info": {"path": file_path, "name": fingerprint['filename']},
                "basic_stats": {"rows": fingerprint['rows'], "column_count": len(fingerprint['columns'])},
                "semantic_analysis": ai_result,
                "variable_name": f"df_{Path(file_path).stem.lower()}"
            }
            return final_result

        except Exception as e:
            logger.error(f"Semantic analysis failed: {e}")
            return {"error": str(e)}