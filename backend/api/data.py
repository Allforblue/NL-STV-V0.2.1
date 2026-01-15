import os
import shutil
from fastapi import APIRouter, UploadFile, File, Request, HTTPException
from typing import List
from core.profiler.semantic_analyzer import SemanticAnalyzer
from core.ingestion.loader_factory import LoaderFactory

router = APIRouter()


@router.post("/upload")
async def upload_data(
        request: Request,
        files: List[UploadFile] = File(...),
        session_id: str = "default"
):
    """
    1. 保存上传文件到 data_sandbox
    2. 调用 SemanticAnalyzer 生成数据摘要
    3. 将摘要和路径存入 Session
    """
    sandbox_path = "core/data_sandbox"
    os.makedirs(sandbox_path, exist_ok=True)

    saved_paths = []
    for file in files:
        file_path = os.path.join(sandbox_path, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        saved_paths.append(file_path)

    # 初始化分析器
    # 假设你已经在 main.py 中将 analyzer 放入了 app.state
    analyzer: SemanticAnalyzer = request.app.state.workflow.analyzer

    summaries = []
    try:
        for path in saved_paths:
            # 过滤掉 shp 的伴生文件，只分析主数据文件
            if path.endswith(('.csv', '.parquet', '.shp', '.geojson')):
                summary = analyzer.analyze(path)
                summaries.append(summary)

        # 将结果存入 session (这里调用你的 session_service)
        from core.services.session_service import session_manager
        session_manager.init_session(session_id, summaries)

        return {"status": "success", "summaries": summaries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据解析失败: {str(e)}")