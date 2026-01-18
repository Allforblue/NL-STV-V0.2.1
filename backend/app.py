import streamlit as st
import requests
import json
import uuid
import plotly.graph_objects as go

# --- 配置 ---
st.set_page_config(layout="wide", page_title="NL-STV 原型测试")
API_BASE_URL = "http://localhost:8000/api/v1"

# --- Session 初始化 ---
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = []  # 存储对话历史
    st.session_state.uploaded = False

# --- 侧边栏：数据上传 ---
with st.sidebar:
    st.title("📂 数据接入")
    st.caption(f"Session ID: `{st.session_state.session_id}`")

    uploaded_files = st.file_uploader(
        "上传 CSV / Parquet / Shapefile (需同时上传 shp/shx/dbf)",
        accept_multiple_files=True
    )

    if uploaded_files and st.button("🚀 开始上传并初始化"):
        with st.spinner("正在上传并预处理数据 (采样模式)..."):
            # 构造 Multipart/form-data
            files_list = []
            for f in uploaded_files:
                # requests 处理文件上传的格式: (field_name, (filename, file_obj, content_type))
                files_list.append(('files', (f.name, f, f.type)))

            try:
                resp = requests.post(
                    f"{API_BASE_URL}/data/upload",
                    params={"session_id": st.session_state.session_id},
                    files=files_list
                )

                if resp.status_code == 200:
                    st.success(f"✅ 上传成功！后端已接收 {len(uploaded_files)} 个文件。")
                    st.session_state.uploaded = True

                    # 展示简单的文件摘要
                    data = resp.json()
                    if "summaries" in data:
                        with st.expander("查看数据摘要"):
                            st.json(data["summaries"])
                else:
                    st.error(f"上传失败: {resp.text}")
            except Exception as e:
                st.error(f"连接后端失败: {e}")

# --- 主界面：智能对话 ---
st.title("🤖 NL-STV 智能时空分析平台")

# 1. 展示历史消息
# [关键修复] 使用 enumerate 获取消息索引(msg_index)，用于生成唯一的 key
for msg_index, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        # 如果是纯文本消息
        if "content" in msg:
            st.markdown(msg["content"])

        # 如果是后端返回的 Dashboard 结果
        if "dashboard" in msg:
            dashboard = msg["dashboard"]
            st.subheader(dashboard.get("title", "分析看板"))

            # 获取组件列表
            components = dashboard.get("components", [])

            # 简单的两列布局
            col1, col2 = st.columns(2)

            for i, comp in enumerate(components):
                # 决定放在哪一列
                # 地图和图表按顺序排列，Insight 通常占满整行
                if comp["type"] == "insight":
                    target_col = st.container()
                else:
                    target_col = col1 if i % 2 == 0 else col2

                with target_col:
                    with st.container(border=True):
                        # 组件标题
                        # st.markdown(f"**{comp['title']}**")

                        # === 渲染 Plotly 图表/地图 ===
                        if comp["type"] in ["map", "chart"]:
                            if comp.get("data_payload"):
                                try:
                                    # 将后端返回的 JSON 转换为 Plotly Figure 对象
                                    fig = go.Figure(comp["data_payload"])

                                    # [关键修复] 指定唯一的 key
                                    # 格式: chart_消息索引_组件ID
                                    unique_key = f"chart_{msg_index}_{comp['id']}"

                                    st.plotly_chart(
                                        fig,
                                        use_container_width=True,
                                        key=unique_key
                                    )
                                except Exception as e:
                                    st.error(f"图表渲染失败: {e}")
                            else:
                                st.warning("暂无数据载荷")

                        # === 渲染 智能洞察 ===
                        elif comp["type"] == "insight":
                            config = comp.get("insight_config", {})
                            if config:
                                st.info(f"💡 **核心结论**: {config.get('summary', '')}")
                                st.markdown(config.get("detail", ""))
                                tags = config.get("tags", [])
                                if tags:
                                    # 以此类推渲染标签
                                    st.markdown("🏷️ " + "  ".join([f"`{t}`" for t in tags]))

# 2. 处理用户输入
if prompt := st.chat_input("输入分析指令 (例如: 分析各行政区的订单占比)"):
    if not st.session_state.uploaded:
        st.warning("⚠️ 请先在左侧上传数据文件！")
        st.stop()

    # 添加用户消息到历史
    st.session_state.messages.append({"role": "user", "content": prompt})
    # 立即在界面显示用户输入
    with st.chat_message("user"):
        st.markdown(prompt)

    # 调用后端 API
    with st.chat_message("assistant"):
        with st.spinner("AI 正在思考、生成代码并执行全量数据分析..."):
            try:
                payload = {
                    "session_id": st.session_state.session_id,
                    "query": prompt,
                    "bbox": [],
                    "selected_ids": [],
                    "force_new": False
                }

                # 发送 POST 请求
                resp = requests.post(f"{API_BASE_URL}/chat/interact", json=payload)

                if resp.status_code == 200:
                    dashboard_data = resp.json()

                    # 保存到历史状态
                    st.session_state.messages.append({
                        "role": "assistant",
                        "dashboard": dashboard_data
                    })

                    # 强制刷新页面以渲染新内容
                    st.rerun()

                else:
                    st.error(f"分析失败 (HTTP {resp.status_code}): {resp.text}")
            except Exception as e:
                st.error(f"请求异常: {e}")