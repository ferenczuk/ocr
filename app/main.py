"""API FastAPI: PDF → Markdown (/ocr) e arquivo → planilha (/to-xlsx)."""

from __future__ import annotations

import asyncio
import base64
import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.auth import require_token
from app.config import Settings, get_settings
from app.converter import DocumentConverter
from app.to_xlsx.pipeline import StructureError, ToXlsxPipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_converter: DocumentConverter | None = None
_to_xlsx: ToXlsxPipeline | None = None
_executor = ThreadPoolExecutor(max_workers=1)

_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/octet-stream",
    "binary/octet-stream",
}

_TO_XLSX_CONTENT_TYPES = {
    "application/pdf",
    "application/octet-stream",
    "binary/octet-stream",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "text/plain",
    "text/csv",
    "application/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/xml",
    "text/xml",
    "application/x-ofx",
}


class HealthResponse(BaseModel):
    status: str = "ok"


class OcrResponse(BaseModel):
    markdown: str
    filename: str
    pages_processed: list[int] = Field(default_factory=lambda: [0])


class ToXlsxResponse(BaseModel):
    filename: str
    source_format: str
    schema_mode: str
    columns: list[str]
    rows: int
    xlsx_base64: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _converter, _to_xlsx
    settings = get_settings()

    if not settings.api_token:
        logger.warning(
            "API_TOKEN vazio — POST /ocr e /to-xlsx retornarão 503 até configurar o .env"
        )

    logger.info(
        "Inicializando conversor OCR (ocr_dpi=%s force_ocr=%s)",
        settings.ocr_dpi,
        settings.force_ocr,
    )
    _converter = DocumentConverter(
        ocr_dpi=settings.ocr_dpi,
        force_ocr=settings.force_ocr,
    )

    ocr_function = getattr(_converter, "_ocr_function", None)
    _to_xlsx = ToXlsxPipeline(
        ocr_dpi=settings.ocr_dpi,
        force_ocr=settings.force_ocr,
        openai_api_key=settings.openai_api_key,
        openai_model=settings.openai_model,
        openai_timeout=settings.openai_timeout_seconds,
        openai_max_chars=settings.openai_max_chars,
        ocr_function=ocr_function,
    )
    logger.info(
        "Pipeline /to-xlsx pronto (openai_model=%s key=%s)",
        settings.openai_model,
        "set" if settings.openai_api_key else "missing",
    )

    yield
    _executor.shutdown(wait=False, cancel_futures=True)
    _converter = None
    _to_xlsx = None


app = FastAPI(
    title="OCR PDF → Markdown / to-xlsx",
    description=(
        "POST /ocr: primeira página de PDF → Markdown (PyMuPDF4LLM + RapidOCR). "
        "POST /to-xlsx: PDF/JPG/TXT/CSV/DOCX/OFX/CNAB/MT940/CAMT → planilha (.xlsx base64), "
        "com schema fixo ou OpenAI."
    ),
    version="2.2.0",
    lifespan=lifespan,
)


def get_converter() -> DocumentConverter:
    if _converter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversor ainda não está pronto",
        )
    return _converter


def get_to_xlsx() -> ToXlsxPipeline:
    if _to_xlsx is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Pipeline /to-xlsx ainda não está pronto",
        )
    return _to_xlsx


@app.get("/health", response_model=HealthResponse, tags=["ops"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post(
    "/ocr",
    response_model=OcrResponse,
    dependencies=[Depends(require_token)],
    tags=["ocr"],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/pdf": {
                    "schema": {"type": "string", "format": "binary"}
                },
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                },
            },
        }
    },
)
async def ocr(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    converter: Annotated[DocumentConverter, Depends(get_converter)],
    filename: Annotated[
        str,
        Query(description="Nome opcional do arquivo (apenas metadado na resposta)"),
    ] = "document.pdf",
) -> OcrResponse:
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type and content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                "Content-Type inválido. Envie application/pdf ou "
                "application/octet-stream com o binário do PDF no body."
            ),
        )

    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf"

    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = await request.body()

    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body vazio — envie o conteúdo binário do PDF",
        )
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Arquivo excede o limite de {settings.max_upload_mb} MB",
        )
    if not data.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O conteúdo não parece ser um PDF válido",
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


@app.post(
    "/to-xlsx",
    response_model=ToXlsxResponse,
    dependencies=[Depends(require_token)],
    tags=["to-xlsx"],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                },
                "application/pdf": {
                    "schema": {"type": "string", "format": "binary"}
                },
            },
        }
    },
)
async def to_xlsx(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    pipeline: Annotated[ToXlsxPipeline, Depends(get_to_xlsx)],
    filename: Annotated[
        str,
        Query(description="Nome do arquivo com extensão (ajuda na detecção)"),
    ] = "document.bin",
    schema: Annotated[
        str | None,
        Query(
            description=(
                "Omitido = schema fixo contábil; "
                "'ia' = IA infere colunas; "
                "'data,descricao,valor' = colunas custom"
            )
        ),
    ] = None,
) -> ToXlsxResponse:
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type and content_type not in _TO_XLSX_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Content-Type não suportado: {content_type}",
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = await request.body()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body vazio — envie o conteúdo binário do arquivo",
        )
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Arquivo excede o limite de {settings.max_upload_mb} MB",
        )

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            _executor,
            lambda: pipeline.run(data, filename=filename, schema=schema),
        )
    except StructureError as exc:
        msg = str(exc)
        code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if "OPENAI_API_KEY" in msg
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code=code, detail=msg) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Falha em /to-xlsx")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao gerar planilha: {exc}",
        ) from exc

    return ToXlsxResponse(
        filename=result.filename,
        source_format=result.source_format,
        schema_mode=result.schema_mode,
        columns=result.columns,
        rows=result.rows,
        xlsx_base64=base64.b64encode(result.xlsx_bytes).decode("ascii"),
    )
