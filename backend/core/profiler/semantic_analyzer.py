import json
import logging
import re  # [新增优化] 用于处理大模型返回的 markdown 格式字符串
from typing import Dict, Any, List, Optional
from pathlib import Path
from core.llm.AI_client import AIClient

logger = logging.getLogger(__name__)


class SemanticAnalyzer:
    """
    语义分析器 (V4 时空增强版)：
    1. 自动识别业务概念映射（中英文对齐）。
    2. 深度感知时空维度：识别时间粒度、空间类型和聚合建议。
    3. 为交互映射和关系映射提供基础语义标签 (Tags)。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    async def analyze(self, file_path: str, fingerprint: Dict[str, Any]) -> Dict[str, Any]:
        """
        主入口：结合物理指纹，提取深度业务语义。

        Args:
            file_path: 文件路径
            fingerprint: 由 basic_stats.get_dataset_fingerprint 生成的物理元数据
        """
        logger.info(f">>> 正在进行深度时空语义分析: {Path(file_path).name}")

        # 1. 整理上下文信息，让 LLM 更有把握
        # [修改优化] 显式提取列名列表，防止 LLM 在深层 JSON 中迷失导致幻觉 (如 LocationID vs PULocationID)
        col_stats = fingerprint.get("column_stats", {})
        col_names = list(col_stats.keys())

        context_summary = {
            "filename": Path(file_path).name,
            "total_rows": fingerprint.get("rows"),
            "column_names_list": col_names,  # <--- 显式注入列名清单，作为最重要的提示
            "is_geospatial": fingerprint.get("is_geospatial", False),
            "columns": col_stats
        }

        # 2. 构建 System Prompt
        #[修改点 1] 增加主时间轴决策规则，解决多时间字段（如上下车）时的选择幻觉
        system_prompt = """
        你是一位资深时空数据专家。请根据提供的数据统计信息进行深度语义解析。

        你的核心任务是识别字段的【语义标签 (Semantic Tags)】：
        - ST_TIME: 时间戳或日期。
        - ST_LAT / ST_LON: 纬度/经度数值。
        - ST_GEO: 地理几何对象 (WKT, GeoJSON, H3Index 等)。
        - ST_LOC_ID: 空间区域 ID (如：区划代码、网格 ID、站点 ID)。
        - BIZ_METRIC: 关键业务指标 (如：金额、速度、温度)。
        - BIZ_CAT: 分类维度 (如：订单状态、车辆类型)。
        - ID_KEY: 唯一标识符。

        请注意时间维度的识别：
        - 如果发现时间字段，必须推断其时间粒度 (SECOND/MINUTE/HOUR/DAY)。
        - 结合 min/max 值推断其覆盖的真实时间范围。
        - 【主时间决策规则】：当存在多个时间维度（如行程数据的上车/下车时间，开始/结束时间）时，请务必优先选择代表事件发生起点的字段（如 pickup_datetime, start_time）作为主时间轴 (primary_time_col)。
        """

        # 3. 构建 User Prompt
        # [修改点 2] 在 JSON 模板中增加注释，明确区分底层记录粒度与宏观聚合粒度；强调 primary_time_col 必须是单一字段
        user_prompt = f"""
        待分析的数据特征:
        {json.dumps(context_summary, indent=2, ensure_ascii=False)}

        请输出 JSON 格式结果：
        {{
          "dataset_domain": "数据集所属领域 (如：智慧交通、环境监测)",
          "dataset_description": "一句话描述该数据集",
          "column_metadata": {{
            "原始列名": {{
              "concept_name": "业务概念中文名",
              "semantic_tag": "ST_TIME | ST_LAT | ST_LON | ST_GEO | ST_LOC_ID | BIZ_METRIC | BIZ_CAT | ID_KEY",
              "description": "字段业务含义",
              "time_granularity": "SECOND | MINUTE | HOUR | DAY | NONE (注：指底层数据的物理记录精度)",
              "is_primary_key": true/false
            }}
          }},
          "temporal_context": {{
            "primary_time_col": "主时间轴字段名 (注：务必只输出单一首选字段名，如无则为null)",
            "time_span": "描述时间跨度 (如：2023年夏季)",
            "suggested_resampling": "建议的聚合频率 (如：'1H', '1D'，注：指宏观业务分析建议)",
            "has_periodic_patterns": true/false
          }},
          "spatial_context": {{
            "spatial_type": "POINT | POLYGON | GRID | NONE",
            "coordinate_system": "WGS84 | GCJ02 | Unknown",
            "analysis_level": "区划级 | 街道级 | 坐标级"
          }},
          "recommended_analysis": ["结合时空维度的分析建议1", "建议2"]
        }}
        """

        try:
            # 4. 调用 AI 异步接口
            ai_result_raw = await self.llm.query_json_async(prompt=user_prompt, system_prompt=system_prompt)

            # [新增优化 1]：增加对 Markdown 格式 JSON 的剥离容错机制
            if isinstance(ai_result_raw, str):
                # 剔除可能包含的 ```json 和 ``` 标签
                cleaned_str = re.sub(r'^```(?:json)?\s*|\s*```$', '', ai_result_raw.strip(), flags=re.MULTILINE)
                try:
                    ai_result = json.loads(cleaned_str)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON 解析失败，LLM 原始输出:\n{ai_result_raw}")
                    raise e
            else:
                # 如果底层 Client 已经把 JSON load 成了字典，则直接使用
                ai_result = ai_result_raw

            # [新增优化 2]：双保险 Fallback 逻辑，防止 LLM 在 temporal_context 中遗漏主时间
            temporal_context = ai_result.get("temporal_context", {})
            p_time = temporal_context.get("primary_time_col")

            # 检查 p_time 是否为空或大模型擅自填写的 "null", "none" 字符串
            if not p_time or str(p_time).strip().lower() in["null", "none", ""]:
                logger.warning("⚠️ AI 未能在 temporal_context 中明确输出主时间维度，启动 Fallback 扫描逻辑...")
                column_metadata = ai_result.get("column_metadata", {})
                for col_name, meta in column_metadata.items():
                    if isinstance(meta, dict) and meta.get("semantic_tag") == "ST_TIME":
                        p_time = col_name
                        # 强行修复 temporal_context
                        if "temporal_context" not in ai_result:
                            ai_result["temporal_context"] = {}
                        ai_result["temporal_context"]["primary_time_col"] = p_time
                        logger.info(f"🔧 Fallback 成功: 自动将字段[{p_time}] 兜底设为主时间维度 (primary_time_col)。")
                        break

            # 5. 整合最终结果
            final_result = {
                "variable_name": f"df_{Path(file_path).stem.lower().replace('-', '_')}",
                "file_info": {
                    "path": file_path,
                    "name": Path(file_path).name,
                    "domain": ai_result.get("dataset_domain")
                },
                "column_stats": fingerprint.get("column_stats"),  # 保留物理统计
                "is_geospatial": fingerprint.get("is_geospatial"),
                "semantic_analysis": ai_result,  # 存放 AI 生成的语义
            }

            # 记录关键发现
            if p_time:
                logger.info(f"✅ 识别到主时间维度: {p_time} ({ai_result.get('temporal_context', {}).get('time_span', '未提供时间跨度')})")
            else:
                logger.error("❌ 数据集中未能识别出任何有效的时间维度！")

            return final_result

        except Exception as e:
            logger.error(f"语义分析过程中出错: {e}")
            # 返回一个基础的降级结果，保证流程不中断
            return {
                "variable_name": f"df_{Path(file_path).stem.lower().replace('-', '_')}",
                "error": str(e),
                "semantic_analysis": {"column_metadata": {}}
            }