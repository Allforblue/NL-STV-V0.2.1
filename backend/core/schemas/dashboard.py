from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union
from enum import Enum


# --- 基础枚举 ---

class ComponentType(str, Enum):
    MAP = "map"  # Deck.gl 地图组件
    CHART = "chart"  # ECharts 统计图表
    KPI = "kpi"  # 关键指标卡片
    INSIGHT = "insight"  # AI 文本深度洞察
    TABLE = "table"  # 数据表格预览


class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    SCATTER = "scatter"
    PIE = "pie"
    HEATMAP = "heatmap"


# --- 细分配置 ---

class MapLayerConfig(BaseModel):
    """地图图层配置，对应前端 Deck.gl 的图层参数"""
    layer_id: str
    layer_type: str = Field(..., description="例如: HexagonLayer, ScatterplotLayer, ArcLayer")
    data_api: str = Field(..., description="获取该图层数据的后端路由")
    color_range: Optional[List[str]] = None
    opacity: float = 0.8
    visible: bool = True
    params: Dict[str, Any] = Field(default_factory=dict, description="其他特定图层参数，如 radius, get_elevation 等")


class ChartConfig(BaseModel):
    """图表配置，对应前端 ECharts 的参数"""
    chart_type: ChartType
    x_axis: Optional[str] = None
    y_axis: Optional[List[str]] = None
    series_name: str
    unit: Optional[str] = None
    stack: bool = False


class InsightCard(BaseModel):
    """AI 生成的文本洞察"""
    summary: str = Field(..., description="简短的业务结论")
    detail: str = Field(..., description="详细的深度解释")
    tags: List[str] = Field(default_factory=list, description="标签，如: '异常点', '趋势上升', '空间聚集'")


class LayoutConfig(BaseModel):
    """看板布局配置 (Grid Layout)"""
    x: int
    y: int
    w: int
    h: int


# --- 核心组件定义 ---

class DashboardComponent(BaseModel):
    """通用看板组件容器"""
    id: str = Field(..., description="组件唯一ID，用于联动")
    title: str
    type: ComponentType
    layout: LayoutConfig

    # [关键修改] 允许 Dict (Plotly), List (DataFrame records), str (Text)
    data_payload: Optional[Union[Dict[str, Any], List[Any], str]] = None

    map_config: Optional[List[MapLayerConfig]] = None
    chart_config: Optional[ChartConfig] = None
    insight_config: Optional[InsightCard] = None

    interactions: List[str] = Field(
        default_factory=list,
        description="该组件支持的交互行为列表"
    )


# --- 根协议 ---

class DashboardSchema(BaseModel):
    """
    完整的看板协议
    llm 将根据数据分析结果生成此结构的 JSON
    """
    dashboard_id: str
    title: str
    description: Optional[str] = None

    # 地图初始视口状态
    initial_view_state: Dict[str, Any] = Field(
        default={"longitude": 121.47, "latitude": 31.23, "zoom": 11},
        description="地图中心点、缩放等级等"
    )

    # 组件列表
    components: List[DashboardComponent]

    # 全局上下文与元数据
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="存储当前查询的变量名、过滤条件等上下文"
    )


class InteractionPayload(BaseModel):
    """
    前端传回后端的交互载荷 (多模态触发)
    """
    session_id: str
    query: Optional[str] = None  # 用户的自然语言输入
    bbox: Optional[List[float]] = None  # [min_lon, min_lat, max_lon, max_lat]
    selected_ids: Optional[List[str]] = None  # 点击选中的元素 ID
    active_component_id: Optional[str] = None  # 触发交互的组件