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
    LEFT_HISTORY = "left_history"  # 左侧历史记录区


class ChartType(str, Enum):
    BAR = "bar"
    LINE = "line"            # 常用于时间趋势分析
    SCATTER = "scatter"
    PIE = "pie"
    HEATMAP = "heatmap"
    TABLE = "table"
    # [新增] 时间轴热力图：展示 24小时 x 7天 的分布或随时间演变的强度
    TIMELINE_HEATMAP = "timeline_heatmap"


class InteractionType(str, Enum):
    """交互行为类型"""
    BBOX = "bbox"           # 空间框选
    CLICK = "click"         # 实体点击
    FILTER = "filter"       # 属性过滤
    # [新增] 时间范围联动：拖动时间轴或选择时间段
    TIME_FILTER = "time_filter"


# --- 联动逻辑定义 ---

class ComponentLink(BaseModel):
    """组件间的联动关系定义"""
    target_id: str = Field(..., description="响应联动的目标组件ID")
    interaction_type: InteractionType
    link_key: str = Field(..., description="关联的字段名，如 'zone_id' 或 'timestamp'")


# --- 细分配置 ---

class LayoutConfig(BaseModel):
    """看板布局配置：支持浮点数以实现精确对齐"""
    zone: LayoutZone = Field(..., description="所属布局区域")
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
    # [新增] 时间聚合粒度提示：如 '1H' (小时), '1D' (天), '15T' (15分钟)
    # 这将指引 CodeGenerator 生成对应的 df.resample() 代码
    time_bucket: Optional[str] = None


class InsightCard(BaseModel):
    summary: str
    detail: str
    tags: List[str] = Field(default_factory=list)


# --- 核心组件定义 ---

class DashboardComponent(BaseModel):
    id: str = Field(..., description="组件唯一ID")
    title: str = "分析组件"
    type: ComponentType
    layout: LayoutConfig

    # 数据负载：兼容 Plotly JSON, DataFrame records, 或纯文本
    data_payload: Optional[Union[Dict[str, Any], List[Any], str]] = None

    map_config: Optional[List[MapLayerConfig]] = None
    chart_config: Optional[ChartConfig] = None
    insight_config: Optional[InsightCard] = None

    # 联动定义
    links: List[ComponentLink] = Field(default_factory=list, description="该组件触发的联动规则")

    interactions: List[str] = Field(default_factory=list, description="支持的交互行为列表")


# --- 根协议 ---

class DashboardSchema(BaseModel):
    dashboard_id: str
    title: str
    description: Optional[str] = None

    initial_view_state: Dict[str, Any] = Field(
        default={"longitude": -74.0, "latitude": 40.7, "zoom": 11}
    )

    # [新增] 全局时间范围：看板初始化或回溯时的时间状态
    # 格式示例: ["2025-01-01 00:00:00", "2025-01-07 23:59:59"]
    global_time_range: Optional[List[str]] = Field(
        None,
        description="看板当前的全局时间过滤范围"
    )

    components: List[DashboardComponent]

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="存储 last_code, snapshot_id, time_metadata 等关键上下文"
    )