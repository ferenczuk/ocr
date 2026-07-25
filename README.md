# OCR PDF → Markdown (PyMuPDF4LLM + RapidOCR)

API em **FastAPI + Uvicorn** que recebe um PDF via `POST`, processa **somente a primeira página** e devolve **Markdown**.

Stack leve em **CPU**, voltada a documentos contábeis:

1. **PyMuPDF4LLM** — layout → Markdown (títulos, colunas, tabelas básicas)
2. Texto digital quando a página já tem camada de texto (melhor para CNPJ/valores)
3. **RapidOCR** (ONNX) automático em scans/imagens — **sem Tesseract** e sem Marker/PyTorch

---

## O que a API faz

| Comportamento | Detalhe |
|---|---|
| Entrada | Conteúdo binário do PDF no body (`application/pdf`) — ideal após baixar do S3 |
| Páginas | **Apenas a página 1** (`pages=[0]`) |
| Digital | Extração nativa via PyMuPDF4LLM |
| Scan | OCR automático com plugin RapidOCR |
| Saída | JSON com o Markdown da página |
| Auth | Token único no `.env` (`Authorization: Bearer ...`) |
| Hardware | CPU |

---

## Requisitos

- [Docker](https://docs.docker.com/get-docker/) e [Docker Compose](https://docs.docker.com/compose/)
- **≥ 2 GB de RAM** recomendados
- Na primeira execução o RapidOCR pode baixar modelos ONNX (cache no volume Docker)

> **Licença:** PyMuPDF/PyMuPDF4LLM usam licença AGPL (uso comercial fechado pode exigir licença Artifex).

---

## Deploy (passo a passo)

### 1. Clonar o repositório

```bash
git clone git@github.com:ferenczuk/ocr.git
cd ocr
```

### 2. Configurar o `.env`

```bash
cp .env.example .env
openssl rand -hex 32   # cole em API_TOKEN
```

Exemplo:

```env
API_TOKEN=cole_aqui_o_token_gerado
MAX_UPLOAD_MB=50
PORT=8000
OCR_DPI=250
FORCE_OCR=false
```

### 3. Subir

```bash
docker compose up -d --build
```

### 4. Health check

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Swagger: `http://localhost:8000/docs`

```bash
docker compose logs -f ocr
```

---

## Variáveis de ambiente

| Variável | Obrigatória | Padrão | Descrição |
|---|---|---|---|
| `API_TOKEN` | **Sim** | — | Token Bearer para `POST /ocr` |
| `MAX_UPLOAD_MB` | Não | `50` | Limite do PDF em MB |
| `PORT` | Não | `8000` | Porta no host |
| `OCR_DPI` | Não | `250` | DPI do OCR (maior = mais preciso/lento) |
| `FORCE_OCR` | Não | `false` | `true` força OCR mesmo com texto digital |

---

## Uso da API

### Health (sem auth)

```bash
curl -s http://localhost:8000/health
```

### OCR (body binário)

```bash
curl -X POST "http://localhost:8000/ocr?filename=documento.pdf" \
  -H "Authorization: Bearer SEU_TOKEN" \
  -H "Content-Type: application/pdf" \
  --data-binary @documento.pdf
```

#### Python (S3)

```python
import boto3
import requests

s3 = boto3.client("s3")
pdf_bytes = s3.get_object(Bucket="meu-bucket", Key="pasta/arquivo.pdf")["Body"].read()

resp = requests.post(
    "http://localhost:8000/ocr",
    params={"filename": "arquivo.pdf"},
    headers={
        "Authorization": "Bearer SEU_TOKEN",
        "Content-Type": "application/pdf",
    },
    data=pdf_bytes,
    timeout=120,
)
print(resp.json()["markdown"])
```

#### Resposta (`200`)

```json
{
  "markdown": "# Título\n\nTexto da primeira página...",
  "filename": "documento.pdf",
  "pages_processed": [0]
}
```

| HTTP | Situação |
|---|---|
| `401` | Token ausente/inválido |
| `400` | Body vazio / não é PDF |
| `413` | Maior que `MAX_UPLOAD_MB` |
| `415` | Content-Type inválido |
| `500` | Falha ao processar |
| `503` | Token não configurado / conversor iniciando |

---

## Comportamento

1. Só a **1ª página**
2. Markdown com **layout** (PyMuPDF4LLM)
3. OCR **só quando necessário** (scan / pouco texto); `FORCE_OCR=true` força sempre
4. Motor de OCR fixado em **RapidOCR** (não usa Tesseract)

Tempo típico em CPU: **segundos** por página.

---

## Troubleshooting

### `401`

Confirme `Authorization: Bearer <API_TOKEN>` e reinicie após mudar o `.env`.

### Timeout no cliente

```php
Http::timeout(120)
```

### OCR ruim em scan

- Suba `OCR_DPI` (ex.: `300`)
- Se o PDF digital tiver texto “lixo”, teste `FORCE_OCR=true`

### OOM

- Reduza `OCR_DPI` (ex.: `200`) e `MAX_UPLOAD_MB`

### Rebuild limpo

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

---

## Desenvolvimento local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## Estrutura

```text
ocr/
├── app/
│   ├── main.py        # /health e /ocr
│   ├── converter.py   # PyMuPDF4LLM + RapidOCR
│   ├── auth.py
│   └── config.py
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
└── README.md
```

---

## Exemplos PHP

### GuzzleHTTP

```php
<?php

require 'vendor/autoload.php';

use GuzzleHttp\Client;

$pdfBytes = file_get_contents('/caminho/para/documento.pdf');

$client = new Client(['base_uri' => 'http://localhost:8000']);

$response = $client->post('/ocr', [
    'timeout' => 120,
    'query' => ['filename' => 'documento.pdf'],
    'headers' => [
        'Authorization' => 'Bearer SEU_TOKEN',
        'Content-Type' => 'application/pdf',
    ],
    'body' => $pdfBytes,
]);

$data = json_decode((string) $response->getBody(), true);
echo $data['markdown'];
```

### Laravel HTTP

```php
<?php

use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Storage;

$pdfBytes = Storage::disk('s3')->get('pasta/arquivo.pdf');

$response = Http::timeout(120)
    ->withToken(env('OCR_API_TOKEN'))
    ->withBody($pdfBytes, 'application/pdf')
    ->post('http://localhost:8000/ocr?filename=arquivo.pdf');

if ($response->failed()) {
    throw new RuntimeException('OCR falhou: ' . $response->body());
}

$markdown = $response->json('markdown');
```

> Use `withBody(...)` e `filename` na query — não passe array no segundo argumento de `post()`.
