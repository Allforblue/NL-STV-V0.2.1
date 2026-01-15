import os
import shutil
from fastapi import APIRouter, UploadFile, File, Request, HTTPException
from typing import List

# 引入 session_service 单例
from core.services.session_service import session_service

router = APIRouter()


@router.post("/upload")
async def upload_data(
        request: Request,
        files: List[UploadFile] = File(...),
        session_id: str = "default"
):
    """
    1. 保存上传文件到 data_sandbox
    2. 调用 SessionManager 进行数据加载和基础画像 (毫秒级~秒级)
    3. 返回基础信息，不等待 LLM 语义分析
    """
    sandbox_path = "core/data_sandbox"
    os.makedirs(sandbox_path, exist_ok=True)

    saved_paths = []
    try:
        for file in files:
            # 简单过滤文件名
            if not file.filename.endswith(('.csv', '.parquet', '.shp', '.geojson', '.json')):
                continue

            file_path = os.path.join(sandbox_path, file.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            saved_paths.append(file_path)

        if not saved_paths:
            raise HTTPException(status_code=400, detail="没有有效的据文件被上传")

        # --- 核心修改 ---
        # 只调用 session_service，它会做 Ingestion 和 Basic Stats (Fast)
        # 不在这里调用 SemanticAnalyzer (Slow LLM)
        session_state = session_service.create_session(session_id, saved_paths)

        return {
            "status": "success",
            "message": f"成功加载 {len(saved_paths)} 个文件",
            # 这里返回的是基础摘要 (行数/列名)，还没打 Semantic Tags
            "summaries": session_state["summaries"]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件上传处理失败: {str(e)}")