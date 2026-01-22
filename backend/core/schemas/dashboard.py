from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union
from enum import Enum


# --- 基础枚举 ---

class ComponentType(str, Enum):
    MAP = "map"
    CHART = "chart"
    KPI = "kpi"
    INSIGHT = "insight"
    TABLE = "table"


class LayoutZone(str, Enum):
    """适配原型图的固定布局区域"""
    CENTER_MAIN = "center_main"  # 中间大地图区域
    RIGHT_SIDEBAR = "right_sidebar"  # 右侧图表区域 (可容纳多个)
    BOTTOM_INSIGHT = "bottom_insight"  # 下方数据洞察结果区域
    LEFT_HISTORY = "left_history"  # 左侧历史记录区 (由系统管理)


class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"
    SCATTER = "scatter"
    PIE = "pie"
    HEATMAP = "heatmap"
    TABLE = "table"  # [新增] 允许 LLM 将 table 视为一种图表类型，增加容错性


class InteractionType(str, Enum):
    """交互行为类型"""
    BBOX = "bbox"  # 空间框选
    CLICK = "click"  # 实体点击
    FILTER = "filter"  # 联动过滤


# --- 联动逻辑定义 ---

class ComponentLink(BaseModel):
    """组件间的联动关系：定义该组件的操作会影响哪些其他组件"""
    target_id: str = Field(..., description="响应联动的目标组件ID")
    interaction_type: InteractionType
    link_key: str = Field(..., description="关联的字段名，如 'zone_id' 或 'district'")


# --- 细分配置 ---

class LayoutConfig(BaseModel):
    """看板布局配置：结合固定区域与栅格坐标"""
    zone: LayoutZone = Field(..., description="所属布局区域")
    # 将 int 改为 float
    x: float = 0
    y: float = 0
    w: float = 12
    h: float = 6


class MapLayerConfig(BaseModel):
    layer_id: str
    layer_type: str = Field(..., description="Deck.gl 图层类型")
    data_api: str = Field(..., description="获取数据的后端路由")
    color_range: Optional[List[str]] = None
    opacity: float = 0.8
    visible: bool = True
    params: Dict[str, Any] = Field(default_factory=dict)


class ChartConfig(BaseModel):
    chart_type: ChartType
    x_axis: Optional[str] = None
    y_axis: Optional[List[str]] = None
    series_name: str
    unit: Optional[str] = None
    stack: bool = False


class InsightCard(BaseModel):
    summary: str
    detail: str
    tags: List[str] = Field(default_factory=list)


# --- 核心组件定义 ---

class DashboardComponent(BaseModel):
    id: str = Field(..., description="组件唯一ID")
    title: str = "分析组件"  # 设置默认值，防止缺失时报错
    type: ComponentType
    layout: LayoutConfig

    # 数据负载：兼容 Plotly JSON, DataFrame records, 或纯文本
    data_payload: Optional[Union[Dict[str, Any], List[Any], str]] = None

    map_config: Optional[List[MapLayerConfig]] = None
    chart_config: Optional[ChartConfig] = None
    insight_config: Optional[InsightCard] = None

    # [关键修改] 联动定义
    links: List[ComponentLink] = Field(default_factory=list, description="该组件触发的联动规则")

    interactions: List[str] = Field(default_factory=list, description="支持的交互行为列表")


# --- 根协议 ---

class DashboardSchema(BaseModel):
    dashboard_id: str
    title: str
    description: Optional[str] = None

    initial_view_state: Dict[str, Any] = Field(
        default={"longitude": 121.47, "latitude": 31.23, "zoom": 11}
    )

    components: List[DashboardComponent]

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="存储 last_code, snapshot_id 等关键上下文"
    )
