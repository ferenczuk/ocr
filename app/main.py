"""API FastAPI: PDF → Markdown (1ª página) via Marker."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.auth import require_token
from app.config import Settings, get_settings
from app.converter import MarkerConverter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_converter: MarkerConverter | None = None
_executor = ThreadPoolExecutor(max_workers=1)


class HealthResponse(BaseModel):
    status: str = "ok"


class OcrResponse(BaseModel):
    markdown: str
    filename: str
    pages_processed: list[int] = Field(default_factory=lambda: [0])


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _converter
    settings = get_settings()

    if not settings.api_token:
        logger.warning(
            "API_TOKEN vazio — POST /ocr retornará 503 até configurar o .env"
        )

    os_device = settings.torch_device
    logger.info("Inicializando Marker (TORCH_DEVICE=%s)", os_device)
    _converter = MarkerConverter(device=os_device)
    yield
    _executor.shutdown(wait=False, cancel_futures=True)
    _converter = None


app = FastAPI(
    title="OCR PDF → Markdown",
    description=(
        "Converte a primeira página de um PDF (digital, com imagens ou escaneado) "
        "em Markdown usando Marker em CPU."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


def get_converter() -> MarkerConverter:
    if _converter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversor ainda não está pronto",
        )
    return _converter


@app.get("/health", response_model=HealthResponse, tags=["ops"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post(
    "/ocr",
    response_model=OcrResponse,
    dependencies=[Depends(require_token)],
    tags=["ocr"],
)
async def ocr(
    file: Annotated[UploadFile, File(description="Arquivo PDF")],
    settings: Annotated[Settings, Depends(get_settings)],
    converter: Annotated[MarkerConverter, Depends(get_converter)],
) -> OcrResponse:
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Envie um arquivo com extensão .pdf",
        )

    content_type = (file.content_type or "").lower()
    if content_type and content_type not in (
        "application/pdf",
        "application/octet-stream",
        "binary/octet-stream",
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Content-Type inválido: {file.content_type}",
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arquivo vazio",
        )
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Arquivo excede o limite de {settings.max_upload_mb} MB",
        )
    if not data.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O arquivo não parece ser um PDF válido",
        )

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)

        loop = asyncio.get_running_loop()
        markdown = await loop.run_in_executor(
            _executor,
            converter.convert,
            str(tmp_path),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Falha na conversão OCR")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao processar o PDF: {exc}",
        ) from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    return OcrResponse(
        markdown=markdown,
        filename=filename,
        pages_processed=[0],
    )
