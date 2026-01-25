import logging
from typing import Dict, Any, List
from core.llm.AI_client import AIClient
from core.schemas.dashboard import InsightCard

logger = logging.getLogger(__name__)


class InsightExtractor:
    """
    智能洞察提取器：
    将 Executor 返回的原始统计数据转化为人类可读的业务解释。
    实现从“数据感知”到“决策支持”的跨越。
    """

    def __init__(self, llm_client: AIClient):
        self.llm = llm_client

    def generate_insights(
            self,
            query: str,
            execution_stats: Dict[str, Any],
            summaries: List[Dict[str, Any]]
    ) -> InsightCard:
        """
        根据执行统计结果生成深度业务洞察

        Args:
            query: 用户的原始问题
            execution_stats: Executor 捕获的中间计算摘要 (来自 global_insight_data)
            summaries: 数据语义背景 (SemanticAnalyzer 的输出)
        """

        # 1. 准备数据背景上下文
        # 提取语义标签，让 AI 知道数字代表的是“价格”、“经纬度”还是“时间轴”
        semantic_context = ""
        for s in summaries:
            var_name = s.get('variable_name')
            tags = s.get('semantic_analysis', {}).get('semantic_tags', {})
            semantic_context += f"变量 `{var_name}` 的字段含义: {tags}\n"

        # 2. 构建 Prompt
        system_prompt = f"""
        你是一位资深的商业数据分析专家。
        你的任务是根据提供的【数据统计摘要】和【语义上下文】，针对用户的【分析需求】生成深刻的业务洞察。

        === 数据语义背景 ===
        {semantic_context}

        === 写作准则 ===
        1. 事实驱动：只评论统计数据中存在的特征（均值、最大值、分布等）。
        2. 业务导向：不要只说“均值是10”，要说“该区域的平均通行成本较高，约为10元”或“该时段的业务量处于全天峰值”。
        3. 发现异常：特别关注统计数据中的极值、异常点或明显的突变。
        4. 时空深度结合：不仅描述“哪里多”，还要描述“什么时候多”。分析时间趋势（增长/下降）、周期性（早晚高峰）和空间聚集的重合情况。
        5. 简明扼要：结论要直接，帮助用户快速理解可视化结果背后的业务问题。
        """

        user_prompt = f"""
        用户的原始分析需求: "{query}"

        执行后的数据统计摘要 (JSON 格式):
        {execution_stats}

        请根据以上信息，生成一份 InsightCard 格式的分析报告：
        1. summary: 一句话核心结论。
        2. detail: 包含 2-3 个核心特征点的深度解释（结合时空分布与趋势变化）。
        3. tags: 提取 3 个关键词标签（如: '高峰拥堵', '显著增长', '空间聚集', '早晚高峰', '周期性波动'）。

        请直接输出 JSON 结果。
        """

        logger.info("Generating business insights from execution stats...")

        try:
            # 调用 AI 获取结构化结论
            ai_response = self.llm.query_json(
                prompt=user_prompt,
                system_prompt=system_prompt
            )

            # 封装为 Pydantic 模型返回
            return InsightCard(**ai_response)

        except Exception as e:
            logger.error(f"Insight generation failed: {e}")
            return InsightCard(
                summary="数据特征提取完成",
                detail=f"系统已生成可视化结果，但深度解释模块出现异常。原始数据特征包含: {list(execution_stats.keys())}",
                tags=["自动分析", "系统提示"]
            )