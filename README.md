# OCR + to-xlsx (documentos contábeis)

API em **FastAPI + Uvicorn** com dois endpoints (mesmo `API_TOKEN`):

| Endpoint | Função | Observação |
|----------|--------|------------|
| `GET /health` | Healthcheck | Sem auth |
| `POST /ocr` | PDF → Markdown (1ª página) | **Inalterado** — PyMuPDF4LLM + RapidOCR |
| `POST /to-xlsx` | Arquivo → planilha `.xlsx` (base64) | Pipeline híbrido + OpenAI opcional |

---

## POST /ocr (existente)

Recebe PDF binário, processa **somente a primeira página**, devolve Markdown.

- Texto digital via PyMuPDF4LLM; scan via RapidOCR (ONNX)
- Body: bytes do PDF (`application/pdf` ou `octet-stream`)
- Auth: `Authorization: Bearer <API_TOKEN>`

```bash
curl -X POST "http://localhost:8000/ocr?filename=documento.pdf" \
  -H "Authorization: Bearer SEU_TOKEN" \
  -H "Content-Type: application/pdf" \
  --data-binary @documento.pdf
```

---

## POST /to-xlsx (novo)

Converte o **conteúdo binário** do arquivo (ex.: bytes do S3) em planilha Excel.

### Formatos suportados

| Formato | Extração | IA necessária? |
|--------|----------|----------------|
| **OFX / QFX** | Parser estruturado | Não (schema fixo) |
| **CNAB 240** | Parser FEBRABAN (segmento E) | Não (se parsear bem) |
| **MT940** | Parser SWIFT | Não (se parsear bem) |
| **CAMT.053** | XML ISO 20022 | Não (se parsear bem) |
| **CSV** | Delimitador `;`/`,` | Não (mapeamento de colunas) |
| **TXT** | Texto | Sim, em geral |
| **DOCX** | python-docx | Em geral sim |
| **PDF** | Todas as páginas (texto + OCR) | Em geral sim |
| **JPG / PNG** | RapidOCR | Sim |

### Schema (query `schema`)

| Valor | Comportamento |
|-------|----------------|
| *(omitido)* | Schema fixo: `data`, `descricao`, `valor`, `tipo`, `documento` |
| `schema=ia` | OpenAI **infere** as colunas |
| `schema=data,descricao,valor` | Colunas custom; IA preenche nessas chaves se precisar |

### Exemplo

```bash
# Schema fixo (padrão)
curl -X POST "http://localhost:8000/to-xlsx?filename=extrato.ofx" \
  -H "Authorization: Bearer SEU_TOKEN" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @extrato.ofx

# IA infere colunas
curl -X POST "http://localhost:8000/to-xlsx?filename=scan.jpg&schema=ia" \
  -H "Authorization: Bearer SEU_TOKEN" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @scan.jpg

# Colunas custom
curl -X POST "http://localhost:8000/to-xlsx?filename=doc.pdf&schema=data,descricao,valor" \
  -H "Authorization: Bearer SEU_TOKEN" \
  -H "Content-Type: application/pdf" \
  --data-binary @doc.pdf
```

### Resposta `200`

```json
{
  "filename": "extrato.xlsx",
  "source_format": "ofx",
  "schema_mode": "fixed",
  "columns": ["data", "descricao", "valor", "tipo", "documento"],
  "rows": 42,
  "xlsx_base64": "UEsDB..."
}
```

Salvar o arquivo:

```bash
python -c "import base64,sys,json; d=json.load(sys.stdin); open(d['filename'],'wb').write(base64.b64decode(d['xlsx_base64']))"
```

### Laravel

```php
$response = Http::timeout(180)
    ->withToken(env('OCR_API_TOKEN'))
    ->withBody($pdfBytes, 'application/octet-stream')
    ->post('http://localhost:8000/to-xlsx?filename=extrato.ofx');

$xlsx = base64_decode($response->json('xlsx_base64'));
file_put_contents(storage_path('app/extrato.xlsx'), $xlsx);
```

Com schema IA:

```php
->post('http://localhost:8000/to-xlsx?filename=scan.jpg&schema=ia');
```

---

## Requisitos

- Docker + Docker Compose
- **≥ 2 GB RAM** recomendados
- Conta OpenAI com chave (obrigatória quando `/to-xlsx` precisar de IA)

> **Licença:** PyMuPDF/PyMuPDF4LLM — AGPL / Artifex para uso comercial fechado.

---

## Deploy (passo a passo)

### 1. Atualizar o código

```bash
cd /caminho/do/ocr
git pull
```

### 2. Configurar o `.env`

```bash
cp .env.example .env   # se ainda não existir
```

Edite:

```env
API_TOKEN=seu_token_forte
MAX_UPLOAD_MB=50
PORT=8000
OCR_DPI=250
FORCE_OCR=false

OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_TIMEOUT_SECONDS=120
OPENAI_MAX_CHARS=100000
```

### 3. Rebuild e subir

```bash
docker compose up -d --build ocr
```

### 4. Health check

```bash
curl -s http://localhost:8000/health
# {"status":"ok"}
```

Swagger: `http://localhost:8000/docs`

### 5. Smoke tests

```bash
# /ocr antigo (não deve mudar)
curl -X POST "http://localhost:8000/ocr?filename=documento.pdf" \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/pdf" \
  --data-binary @documento.pdf

# /to-xlsx
curl -X POST "http://localhost:8000/to-xlsx?filename=extrato.ofx" \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @extrato.ofx
```

### 6. Logs

```bash
docker compose logs -f ocr
```

---

## Variáveis de ambiente

| Variável | Obrigatória | Padrão | Descrição |
|----------|-------------|--------|-----------|
| `API_TOKEN` | **Sim** | — | Bearer para `/ocr` e `/to-xlsx` |
| `MAX_UPLOAD_MB` | Não | `50` | Limite do body |
| `PORT` | Não | `8000` | Porta no host |
| `OCR_DPI` | Não | `250` | DPI do OCR |
| `FORCE_OCR` | Não | `false` | Força OCR em PDF digital |
| `OPENAI_API_KEY` | Para IA | — | Chave OpenAI (`/to-xlsx`) |
| `OPENAI_MODEL` | Não | `gpt-4o-mini` | Modelo |
| `OPENAI_TIMEOUT_SECONDS` | Não | `120` | Timeout da chamada |
| `OPENAI_MAX_CHARS` | Não | `100000` | Truncamento do texto enviado à IA |

---

## Erros comuns (`/to-xlsx`)

| HTTP | Situação |
|------|----------|
| `401` | Token inválido |
| `400` | Body vazio / formato inválido |
| `413` | Arquivo grande demais |
| `415` | Content-Type não suportado |
| `502` | Falha na OpenAI |
| `503` | `OPENAI_API_KEY` ausente quando a IA é necessária |

OFX/CNAB/CSV bem formados **não exigem** OpenAI com schema fixo.

---

## Estrutura

```text
ocr/
├── app/
│   ├── main.py           # /health, /ocr, /to-xlsx
│   ├── converter.py      # OCR 1ª página (inalterado)
│   ├── auth.py
│   ├── config.py
│   └── to_xlsx/          # pipeline híbrido
│       ├── detect.py
│       ├── pipeline.py
│       ├── structure.py
│       ├── workbook.py
│       └── extractors/
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```
