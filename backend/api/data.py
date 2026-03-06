import os
import shutil
import re
import logging
from fastapi import APIRouter, UploadFile, File, Request, HTTPException
from typing import List
from core.services.session_service import session_service

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/upload")
async def upload_data(
        request: Request,
        files: List[UploadFile] = File(...),
        session_id: str = "default"
):
    """
    1. 保存上传文件到 data_sandbox 下的 session 专属目录 (多用户隔离)
    2. 自动清洗文件名，确保生成的变量名在 Python 中合法且唯一
    3. 筛选出主数据文件 (Entry Points) 传给 SessionManager
    """
    sandbox_root = "core/data_sandbox"
    session_sandbox = os.path.join(sandbox_root, session_id)

    # [增强] 重新上传时清理旧沙箱，确保数据环境纯净
    if os.path.exists(session_sandbox):
        shutil.rmtree(session_sandbox)
    os.makedirs(session_sandbox, exist_ok=True)

    # 定义允许上传的扩展名和作为加载入口的扩展名
    ALLOWED_EXTENSIONS = ('.csv', '.parquet', '.json', '.geojson', '.shp', '.shx', '.dbf', '.prj')
    # shp, geojson 等是时空数据的入口
    LOADABLE_EXTENSIONS = ('.csv', '.parquet', '.shp', '.geojson', '.json')

    saved_paths = []
    load_targets = []
    seen_vars = set()  # 用于检测变量名冲突

    try:
        for file in files:
            # 1. 更严格的文件名清洗：仅保留字母、数字和下划线
            base_name = os.path.splitext(file.filename)[0].lower()
            ext = os.path.splitext(file.filename)[1].lower()

            # 将非字母数字字符替换为下划线，合并连续下划线，去除首部数字
            clean_base = re.sub(r'[^a-z0-9_]', '_', base_name)
            clean_base = re.sub(r'_+', '_', clean_base).strip('_')

            # Python 变量名不能以数字开头
            if clean_base and clean_base[0].isdigit():
                clean_base = f"data_{clean_base}"

            clean_filename = f"{clean_base}{ext}"

            if ext not in ALLOWED_EXTENSIONS:
                logger.warning(f"跳过不支持的文件类型: {file.filename}")
                continue

            file_path = os.path.join(session_sandbox, clean_filename)

            # 保存文件
            with open(file_path, "wb") as buffer:
                await file.seek(0)
                shutil.copyfileobj(file.file, buffer)

            saved_paths.append(file_path)

            # 2. 筛选主入口文件，并处理变量名冲突
            if ext in LOADABLE_EXTENSIONS:
                var_name = f"df_{clean_base}"
                if var_name in seen_vars:
                    # 如果冲突（如同时上传了 data.csv 和 data.json），附加后缀
                    var_name = f"{var_name}_{ext.strip('.')}"

                seen_vars.add(var_name)
                load_targets.append(file_path)

        if not load_targets:
            raise HTTPException(status_code=400, detail="未找到有效的可加载数据文件 (.csv, .parquet, .shp, .geojson)")

        # 3. 初始化 Session
        # 内部会触发 basic_stats 提取物理指纹（行列数、CRS、Bounds等）
        logger.info(f">>> [Data] 开始为 Session {session_id} 初始化数据画像，目标文件数: {len(load_targets)}")
        session_state = session_service.create_session(session_id, load_targets)

        return {
            "status": "success",
            "session_id": session_id,
            "datasets": [s["variable_name"] for s in session_state["summaries"]],
            "is_geospatial": any(s.get("is_geospatial") for s in session_state["summaries"]),
            "ready": True
        }

    except Exception as e:
        logger.error(f"Session {session_id} 数据处理失败: {str(e)}")
        # 发生错误时尝试清理
        if os.path.exists(session_sandbox):
            shutil.rmtree(session_sandbox)
        raise HTTPException(status_code=500, detail=f"文件处理失败: {str(e)}")