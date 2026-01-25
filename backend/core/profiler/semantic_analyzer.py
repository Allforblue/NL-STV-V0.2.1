import json
import logging
from typing import Dict, Any, List
from pathlib import Path
from core.llm.AI_client import AIClient
from core.ingestion.loader_factory import LoaderFactory

logger = logging.getLogger(__name__)


class SemanticAnalyzer:
    """
    语义分析器 (V4 时空增强版)：
    1. 自动识别业务概念映射（中英文对齐）。
    2. [增强] 深度感知时间维度：识别时间范围、粒度和聚合建议。
    3. 分析维度基数，为时空看板规划提供依据。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    def _get_basic_fingerprint(self, file_path: str) -> Dict[str, Any]:
        """获取物理层面的指纹：包含对时间列的初步采样"""
        loader = LoaderFactory.get_loader(file_path)
        df_preview = loader.peek(file_path, n=10)  # 增加到10行，方便 AI 观察时间规律
        row_count = loader.count_rows(file_path)

        col_stats = {}
        for col in df_preview.columns:
            try:
                has_nulls = bool(df_preview[col].isnull().any())
            except:
                has_nulls = False

            try:
                # 采样并去重，特别保留可能的时间字符串
                raw_samples = df_preview[col].dropna().unique()[:5].tolist()
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
        """主入口：从数据中提取“时空双维度”业务元数据"""
        logger.info(f"Analyzing universal spatio-temporal semantics for: {file_path}")

        # 1. 获取物理特征
        fingerprint = self._get_basic_fingerprint(file_path)

        # 2. 构建包含时间感知逻辑的 System Prompt
        system_prompt = """
        你是一位资深时空数据专家。请对任意数据集样例进行深度语义解析：

        1. 概念抽象化：推断列对应的【通用中文业务概念名称】。
        2. 【核心】时间维度识别：针对标记为 ST_TIME 的字段，识别：
           - 精度：数据是秒级、分钟级、小时级还是天级？
           - 角色：它是下单时间、采集时间还是事件发生时间？
        3. 【核心】空间维度识别：识别经纬度(ST_LAT/LON)或地理对象(ST_GEO)。
        4. 字段分类标签：
           - ST_TIME: 时间戳
           - ST_LAT/ST_LON/ST_GEO: 地理信息
           - BIZ_METRIC: 数值指标
           - BIZ_CAT: 分类维度
        5. 基数评估：评估唯一值数量，辅助图表选型（<10适合饼图，10-30适合条形图）。
        """

        # 3. 定义包含 temporal_context 的 JSON 输出结构
        user_prompt = f"""
        数据文件: {fingerprint['filename']}
        数据行数: {fingerprint['rows']}
        字段特征预览: {json.dumps(fingerprint['columns'], ensure_ascii=False)}

        请输出 JSON 格式：
        {{
          "dataset_domain": "识别出的行业领域",
          "description": "数据集内容详细描述",
          "column_metadata": {{
            "原始列名": {{
              "concept_name": "中文概念名",
              "semantic_tag": "上述定义的标签",
              "cardinality": "唯一值数量预估",
              "time_granularity": "SECOND | MINUTE | HOUR | DAY | MONTH (仅时间字段)",
              "is_primary_dimension": true/false
            }}
          }},
          "temporal_context": {{
            "primary_time_col": "主时间轴列名",
            "time_span": "推断的时间范围描述 (如：2025年1月全月)",
            "suggested_resampling": "建议的聚合频率 (如：'1H', '1D', '1W')",
            "has_periodic_patterns": true/false (是否有明显的周期性特征)
          }},
          "recommended_analysis": ["包含空间和时间维度的分析建议"],
          "potential_join_keys": ["可用于关联的字段"]
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

            # 日志记录识别到的主时间轴
            p_time = ai_result.get("temporal_context", {}).get("primary_time_col")
            if p_time:
                logger.info(f"✅ 已识别主时间轴字段: {p_time}")

            return final_result

        except Exception as e:
            logger.error(f"Spatio-temporal analysis failed: {e}")
            return {"error": str(e)}