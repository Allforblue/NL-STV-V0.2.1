import json
import logging
from typing import Dict, Any, List
from pathlib import Path
from core.llm.AI_client import AIClient
from core.ingestion.loader_factory import LoaderFactory

logger = logging.getLogger(__name__)

class SemanticAnalyzer:
    """
    语义分析器 (V3 通用元数据版)：
    1. 自动识别任意数据集的业务概念映射（中英文对齐）。
    2. 分析维度基数 (Cardinality)，为图表选型提供决策依据。
    3. 识别跨表关联键，支撑通用的语义钻取。
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
            try:
                has_nulls = bool(df_preview[col].isnull().any())
            except:
                has_nulls = False

            try:
                # 获取样本值并去重，用于辅助 AI 判断业务含义
                raw_samples = df_preview[col].dropna().unique()[:3].tolist()
                samples = [str(x) for x in raw_samples]
            except:
                samples = []

            col_stats[col] = {
                "dtype": str(df_preview[col].dtype),
                "samples": samples,
                "has_nulls": has_nulls
            }

        return {
            "rows": row_count,
            "columns": col_stats,
            "filename": Path(file_path).name
        }

    def analyze(self, file_path: str) -> Dict[str, Any]:
        """主入口：从数据预览中提取通用业务元数据"""
        logger.info(f"Analyzing universal semantics for: {file_path}")

        # 1. 获取物理特征
        fingerprint = self._get_basic_fingerprint(file_path)

        # 2. 构建通用化 System Prompt
        system_prompt = """
        你是一位全能数据科学家。请对提供的任意数据集样例进行深度语义解析：

        1. 概念抽象化：不要受行业限制。观察原始列名及样本数据，推断其对应的【通用中文业务概念名称】。
        2. 字段分类：为每个字段打上语义标签：
           - ST_TIME: 时间/日期
           - ST_LAT/ST_LON/ST_GEO: 空间位置
           - BIZ_METRIC: 数值指标（可聚合，如金额、数量、得分）
           - BIZ_CAT: 分类维度（不可聚合，如类别、状态、名称）
           - ID_KEY: 唯一标识或关联外键
        3. 基数评估：推断该分类字段的【唯一值数量(Cardinality)】。
           - 若基数较小（<10），该字段非常适合作为饼图或过滤条件。
        """

        # 3. 定义严格的通用 JSON 输出结构
        user_prompt = f"""
        数据文件: {fingerprint['filename']}
        数据行数: {fingerprint['rows']}
        字段物理特征: {json.dumps(fingerprint['columns'], ensure_ascii=False)}

        请输出 JSON 格式，不要包含任何硬编码的行业假设：
        {{
          "dataset_domain": "识别出的行业领域（如：金融、交通、医疗等）",
          "description": "对该数据集内容的详细中文描述",
          "column_metadata": {{
            "原始列名": {{
              "concept_name": "对应的中文业务概念名称",
              "semantic_tag": "上述定义的标签",
              "cardinality": "估计唯一值数量（如：5, 100, High）",
              "description": "该字段的业务含义解释",
              "is_primary_dimension": true/false (是否是分析的核心维度)
            }}
          }},
          "recommended_analysis": ["建议的分析方向"],
          "potential_join_keys": ["可用于关联其他表的字段名"]
        }}
        """

        try:
            # 调用 AIClient 获取结构化输出
            ai_result = self.llm.query_json(prompt=user_prompt, system_prompt=system_prompt)

            # 整合最终结果
            final_result = {
                "file_info": {
                    "path": file_path,
                    "name": fingerprint['filename'],
                    "domain": ai_result.get("dataset_domain", "unknown")
                },
                "basic_stats": {
                    "rows": fingerprint['rows'],
                    "column_count": len(fingerprint['columns'])
                },
                "semantic_analysis": ai_result,
                "variable_name": f"df_{Path(file_path).stem.lower().replace('-', '_')}"
            }
            return final_result

        except Exception as e:
            logger.error(f"Universal semantic analysis failed: {e}")
            return {"error": str(e)}