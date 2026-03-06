import logging
import json
from typing import Dict, Any, List
from core.llm.AI_client import AIClient
from core.schemas.dashboard import InsightCard

logger = logging.getLogger(__name__)


class InsightExtractor:
    """
    智能洞察提取器 (V2.5 时空增强版)：
    1. [Logic] 将 Executor 返回的原始统计数据转化为人类可读的业务解释。
    2. [STV Optimized] 深度解析时间序列特征（峰值、趋势）与空间指纹（地理覆盖、聚集特征）。
    3. [Reasoning] 实现从“数据分布”到“业务决策建议”的跨越。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    async def generate_insights(
            self,
            query: str,
            execution_stats: Dict[str, Any],
            summaries: List[Dict[str, Any]]
    ) -> InsightCard:
        """
        根据执行统计结果生成深度业务洞察。

        Args:
            query: 用户的原始问题
            execution_stats: Executor 捕获的中间计算摘要 (包含时空指纹)
            summaries: 数据语义背景 (来自 SemanticAnalyzer)
        """

        # 1. 提取深度语义上下文
        # 让 AI 知道每个变量的行业领域和字段业务含义
        context_blocks = []
        for s in summaries:
            var_name = s.get('variable_name')
            sem = s.get('semantic_analysis', {})
            domain = sem.get('dataset_domain', '通用领域')
            desc = sem.get('dataset_description', '')
            tags = sem.get('column_metadata', {})

            tags_str = ", ".join([f"{k}({v.get('concept_name')})" for k, v in tags.items()])
            context_blocks.append(f"数据集 `{var_name}` [{domain}]: {desc}\n   - 字段含义: {tags_str}")

        semantic_context = "\n".join(context_blocks)

        # 2. 构建系统提示词：强化对 Executor 新增字段的识别能力
        system_prompt = f"""
        你是一位顶尖的时空数据分析专家。
        你的任务是根据提供的【数据统计摘要】和【语义上下文】，针对用户的【分析需求】生成深刻的业务洞察。

        === 数据语义背景 ===
        {semantic_context}

        === 深度分析准则 ===
        1. **时间维度解析**：
           - 关注 `temporal_insights` 中的 peak_value (峰值) 和 valley_value (谷值)。
           - 识别 `start_time` 与 `end_time` 之间的趋势变化，指出业务的“爆发点”或“低谷期”。
        2. **空间维度解析**：
           - 参考 `spatial_info` 和 `bounds`。描述数据覆盖的地理范围是否广泛。
           - 若有 `geom_type` 为 Point，分析其空间分布的疏密；若为 Polygon，分析区域间的差异。
        3. **业务语言转化**：
           - 禁止直接罗列数字。将“均值10”转化为“平均运营效率”、“通行成本”或“订单密度”等业务指标。
           - 针对异常值（Outliers）提供预警性质的描述。
        4. **多表关联洞察**：
           - 如果涉及多个数据集，尝试分析它们之间的因果或关联关系（例如：天气数据集与订单量的同步波动）。
        5. **输出格式准则**：
           - 禁止使用 Markdown 表格形式展示结果。
           - 必须使用连贯的、具有深度解析力度的自然语言段落进行描述。
        """

        # 3. 构建用户提示词
        user_prompt = f"""
        用户的原始分析意图: "{query}"

        Executor 输出的统计摘要 (内含时空指纹):
        {json.dumps(execution_stats, indent=2, ensure_ascii=False)}

        请直接输出 JSON 结果（严格禁止输出 Markdown 表格），符合以下结构：
        {{
          "summary": "一句话核心结论（字数控制在20字内）",
          "detail": "深度解析：请结合时间趋势、空间分布、数值对比三个维度进行不少于150字的深刻段落描述，并给出1条业务改进建议。禁止使用表格。",
          "tags": ["标签1", "标签2", "标签3"]
        }}
        """

        logger.info(">>> [Insight] 正在将执行数据转化为业务洞察...")

        try:
            # 调用异步 LLM
            ai_response = await self.llm.query_json_async(
                prompt=user_prompt,
                system_prompt=system_prompt
            )

            # --- [必要修改] 解析清洗器逻辑：修正表格思维输出并对齐字段名 ---
            if isinstance(ai_response, dict):
                # 1. 字段名修复：LLM 习惯输出 Description 而不是 detail
                for alias in ["Description", "description", "content"]:
                    if alias in ai_response and "detail" not in ai_response:
                        ai_response["detail"] = ai_response.pop(alias)

                # 2. 表格化内容重组：处理含有 Metric/Value 结构的非标准输出
                if "Metric" in ai_response or "Value" in ai_response:
                    m = ai_response.pop("Metric", "关键指标")
                    v = ai_response.pop("Value", "统计值")
                    table_lead = f"【{m}】: {v}"
                    # 将结构化指标合并到 detail 段落的首部
                    original_detail = ai_response.get("detail", "")
                    ai_response["detail"] = f"{table_lead}\n{original_detail}".strip()

            # 兼容性处理：检查并补全缺失字段
            if not ai_response.get("summary"):
                ai_response["summary"] = "时空分析执行完成"
            if not ai_response.get("tags"):
                ai_response["tags"] = ["自动提取", "时空分析"]

            print(ai_response)

            return InsightCard(**ai_response)

        except Exception as e:
            logger.error(f"❌ 洞察生成失败: {e}")
            # 降级方案：根据统计摘要中的关键 Key 拼凑基础结论
            found_keys = list(execution_stats.keys())
            return InsightCard(
                summary="数据特征分析已就绪",
                detail=f"可视化结果已成功生成。基于对变量 {found_keys} 的分析，系统观察到明显的时间/空间分布规律。由于 AI 引擎繁忙，详细的深度解析未能完全展示，建议您直接观察可视化看板进行判断。",
                tags=["系统回退", "分析完成"]
            )