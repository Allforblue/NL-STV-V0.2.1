import streamlit as st
import requests
import json
import uuid
import plotly.graph_objects as go
from datetime import datetime

# --- 配置 ---
st.set_page_config(layout="wide", page_title="NL-STV Pro - 高交互时空分析平台")
API_BASE_URL = "http://localhost:8000/api/v1"

# --- Session 状态初始化 ---
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.current_dashboard = None  # 当前显示的看板快照
    st.session_state.history = []  # 左侧历史快照列表
    st.session_state.uploaded = False


# --- 工具函数：调用后端接口 ---
def call_interact(payload):
    try:
        resp = requests.post(f"{API_BASE_URL}/chat/interact", json=payload)
        if resp.status_code == 200:
            st.session_state.current_dashboard = resp.json()
            # 每次交互完，刷新历史列表
            update_history_list()
            st.rerun()
        else:
            st.error(f"分析失败: {resp.text}")
    except Exception as e:
        st.error(f"连接失败: {e}")


def update_history_list():
    try:
        resp = requests.get(f"{API_BASE_URL}/session/{st.session_state.session_id}/history")
        if resp.status_code == 200:
            st.session_state.history = resp.json().get("history", [])
    except:
        pass


def render_visual_component(comp, height=400):
    """
    通用组件渲染器：具备高度容错性
    处理 Plotly 非法属性导致的 ValueError，并在失败时尝试渲染为数据表格
    """
    payload = comp.get("data_payload")
    if not payload:
        st.warning("暂无数据载荷")
        return

    try:
        # 1. 尝试作为 Plotly 图表渲染 (处理 Dict 类型的 payload)
        if isinstance(payload, dict) and ("data" in payload or "layout" in payload):
            # 移除图表对象内部可能存在的标题，实现彻底去冗余
            if "layout" in payload and "title" in payload["layout"]:
                payload["layout"]["title"] = None

            fig = go.Figure(payload)
            fig.update_layout(height=height, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, use_container_width=True, key=f"viz_{comp['id']}")

        # 2. 尝试作为数据表格渲染 (处理 List 类型的 payload，即 DataFrame records)
        elif isinstance(payload, list):
            st.dataframe(payload, use_container_width=True, height=height)

        # 3. 兜底：如果是字符串或未知字典
        else:
            st.write(payload)

    except Exception as e:
        # 容错处理：如果 Plotly 包含非法参数(如幻觉出的中文属性)，降级为表格显示
        st.error(f"组件渲染异常: {e}")
        with st.expander("查看原始数据 (降级展示)"):
            if isinstance(payload, (list, dict)):
                st.write("后端返回的数据结构不符合 Plotly 标准，已转为表格形式：")
                st.dataframe(payload)
            else:
                st.code(str(payload))


# --- 侧边栏：文件上传 + 历史记录 (回溯核心) ---
with st.sidebar:
    st.title("🛰️ NL-STV 控制台")
    st.caption(f"会话 ID: `{st.session_state.session_id}`")

    # 1. 数据上传区
    with st.expander("📂 数据上传", expanded=not st.session_state.uploaded):
        uploaded_files = st.file_uploader("上传 CSV / Parquet / Shapefile", accept_multiple_files=True)
        if uploaded_files and st.button("初始化环境"):
            files_list = [('files', (f.name, f, f.type)) for f in uploaded_files]
            resp = requests.post(f"{API_BASE_URL}/data/upload", params={"session_id": st.session_state.session_id},
                                 files=files_list)
            if resp.status_code == 200:
                st.session_state.uploaded = True
                st.success("数据已就绪")
                update_history_list()

    # 2. 历史回溯区 (实现原型图左侧回溯)
    st.markdown("---")
    st.subheader("📜 历史分析快照")
    if not st.session_state.history:
        st.info("暂无历史记录")
    else:
        # 按时间倒序排列
        for item in reversed(st.session_state.history):
            # 点击历史条目进行“回溯”
            btn_label = f"🕒 {item['time']}\n{item['summary']}"
            if st.button(btn_label, key=item['snapshot_id'], use_container_width=True):
                payload = {
                    "session_id": st.session_state.session_id,
                    "trigger_type": "backtrack",
                    "target_snapshot_id": item['snapshot_id']
                }
                call_interact(payload)

# --- 主界面布局 (左中右+下结构) ---

if st.session_state.current_dashboard:
    db = st.session_state.current_dashboard

    # [新增] 显示全局时间范围状态
    if db.get("global_time_range"):
        st.info(f"📅 **当前分析时段**: {db['global_time_range'][0]} 至 {db['global_time_range'][1]}")

    # 定义栅格：主展示区(占8/12) : 侧边统计区(占4/12)
    col_main, col_right = st.columns([2, 1])

    components = db.get("components", [])

    # 按布局区域(Zone)对组件进行分组
    center_maps = [c for c in components if c['layout']['zone'] == "center_main"]
    right_sidebar_items = [c for c in components if c['layout']['zone'] == "right_sidebar"]
    bottom_insights = [c for c in components if c['layout']['zone'] == "bottom_insight"]

    # 1. 中间主区域：通常是大地图
    with col_main:
        for comp in center_maps:
            st.subheader(f"📍 {comp['title']}")
            render_visual_component(comp, height=600)

            # 模拟地图框选交互 (联动触发源)
            c1, c2 = st.columns(2)
            if c1.button("🔍 模拟框选该区域 (纽约 BBox)", key=f"bbox_{comp['id']}"):
                payload = {
                    "session_id": st.session_state.session_id,
                    "trigger_type": "ui",
                    "active_component_id": comp['id'],
                    # 纽约坐标范围
                    "bbox": [-74.02, 40.69, -73.85, 40.82],
                }
                call_interact(payload)

            # [新增] 模拟时间维度交互
            if c2.button("🕒 模拟选择高峰时段 (Time Range)", key=f"time_{comp['id']}"):
                payload = {
                    "session_id": st.session_state.session_id,
                    "trigger_type": "ui",
                    "active_component_id": comp['id'],
                    # 模拟 2025年1月1日 早高峰范围
                    "time_range": ["2025-01-01 07:00:00", "2025-01-01 10:00:00"],
                }
                call_interact(payload)

    # 2. 右侧边栏：统计图表或明细表
    with col_right:
        st.markdown("### 📊 维度统计")
        for comp in right_sidebar_items:
            with st.container(border=True):
                st.write(f"**{comp['title']}**")
                render_visual_component(comp, height=350)

                # 联动模拟：点选特定 ID
                if st.button(f"🔗 选中实体下钻", key=f"link_{comp['id']}"):
                    payload = {
                        "session_id": st.session_state.session_id,
                        "trigger_type": "ui",
                        "active_component_id": comp['id'],
                        "selected_ids": ["sample_id_001"]  # 模拟点击选中
                    }
                    call_interact(payload)

    # 3. 下方全宽区域：AI 智能洞察结果
    st.markdown("---")
    for comp in bottom_insights:
        st.markdown(f"### 💡 {comp['title']}")
        config = comp.get("insight_config", {})
        if config:
            st.info(config.get("summary", "无摘要结论"))
            st.markdown(config.get("detail", "暂无深度分析内容"))
            tags = config.get("tags", [])
            if tags:
                st.markdown(" ".join([f"[:blue[{t}]]" for t in tags]))
        else:
            render_visual_component(comp, height=200)

else:
    # 初始状态提示
    st.info("👋 准备就绪！请在左侧上传数据文件，然后在下方输入您的分析问题。")

# --- 底部固定对话框 (NL 输入) ---
st.markdown("<br><br>", unsafe_allow_html=True)
if prompt := st.chat_input("输入分析指令 (例如: 分析曼哈顿地区的订单分布)"):
    if not st.session_state.uploaded:
        st.warning("⚠️ 请先在左侧上传并初始化数据集。")
    else:
        payload = {
            "session_id": st.session_state.session_id,
            "trigger_type": "nl",
            "query": prompt,
            "force_new": False
        }
        call_interact(payload)