# OCR PDF → Markdown (Marker + CPU)

API em **FastAPI + Uvicorn** que recebe um PDF via `POST`, processa **somente a primeira página** com **Marker** (OCR via Surya) e devolve o conteúdo em **Markdown**.

Funciona com PDFs digitais, com imagens e **escaneados** (`force_ocr` ativo). O runtime é focada em **CPU**.

> **Licença:** o Marker usa código GPL e pesos com restrições comerciais. Avalie a [licença do projeto](https://github.com/datalab-to/marker) antes de uso comercial.

---

## O que a API faz

| Comportamento | Detalhe |
|---|---|
| Entrada | Arquivo PDF (`multipart/form-data`) |
| Páginas | **Apenas a página 1** (índice `0`), mesmo em PDFs longos |
| OCR | Forçado — lê texto de scans e regiões com imagem |
| Saída | JSON com o Markdown da página |
| Auth | Token único definido no `.env` (`Authorization: Bearer ...`) |
| Hardware | CPU (`TORCH_DEVICE=cpu`) |

---

## Requisitos

- [Docker](https://docs.docker.com/get-docker/) e [Docker Compose](https://docs.docker.com/compose/)
- Máquina com **pelo menos 8 GB de RAM** recomendados (Marker em CPU é pesado)
- Espaço em disco para baixar os modelos na primeira execução (alguns GB)

---

## Deploy (passo a passo)

### 1. Clonar o repositório

```bash
git clone git@github.com:ferenczuk/ocr.git
cd ocr
```

(Ajuste a URL se o remote for outro.)

### 2. Configurar o `.env`

```bash
cp .env.example .env
```

Edite o arquivo `.env` e defina um token forte:

```bash
# Gere um token aleatório
openssl rand -hex 32
```

Exemplo de `.env`:

```env
API_TOKEN=cole_aqui_o_token_gerado
TORCH_DEVICE=cpu
MAX_UPLOAD_MB=50
PORT=8000
```

> Sem `API_TOKEN` válido, o endpoint `/ocr` recusa as requisições.

### 3. Subir com Docker Compose

```bash
docker compose up -d --build
```

Na **primeira** subida o container pode demorar: o Marker baixa os modelos de OCR/layout. Os arquivos ficam no volume `marker_cache` e não precisam ser baixados de novo.

### 4. Verificar se está no ar

```bash
curl http://localhost:8000/health
```

Resposta esperada:

```json
{"status":"ok"}
```

Swagger interativo (opcional):

```text
http://localhost:8000/docs
```

### 5. Parar / reiniciar

```bash
docker compose down
docker compose up -d
docker compose logs -f ocr
```

---

## Variáveis de ambiente

| Variável | Obrigatória | Padrão | Descrição |
|---|---|---|---|
| `API_TOKEN` | **Sim** | — | Token Bearer para autenticar `POST /ocr` |
| `TORCH_DEVICE` | Não | `cpu` | Dispositivo PyTorch (`cpu` neste deploy) |
| `MAX_UPLOAD_MB` | Não | `50` | Tamanho máximo do PDF em MB |
| `PORT` | Não | `8000` | Porta publicada no host |

O `docker-compose.yml` carrega o arquivo `.env` automaticamente (`env_file: .env`).

---

## Uso da API

### Health check (sem autenticação)

```bash
curl -s http://localhost:8000/health
```

### OCR — converter PDF (primeira página)

```bash
curl -X POST "http://localhost:8000/ocr" \
  -H "Authorization: Bearer SEU_TOKEN" \
  -F "file=@documento.pdf"
```

Substitua `SEU_TOKEN` pelo valor de `API_TOKEN` do `.env`.

#### Resposta de sucesso (`200`)

```json
{
  "markdown": "# Título extraído\n\nTexto da primeira página...",
  "filename": "documento.pdf",
  "pages_processed": [0]
}
```

#### Erros comuns

| HTTP | Situação |
|---|---|
| `401` | Token ausente ou inválido |
| `400` | Não é PDF / arquivo vazio |
| `413` | Arquivo maior que `MAX_UPLOAD_MB` |
| `500` | Falha interna do Marker ao processar |
| `503` | `API_TOKEN` não configurado ou conversor ainda iniciando |

---

## Comportamento do OCR

1. **Só a primeira página** — páginas seguintes são ignoradas de propósito (menor custo de CPU/RAM).
2. **OCR forçado** — adequado para PDFs escaneados e páginas cujo texto está embutido em imagem.
3. **Markdown estruturado** — o Marker preserva o máximo possível de títulos, parágrafos, tabelas e layout.
4. **Imagens** — o texto contido nas imagens da página é reconhecido via OCR; arquivos de imagem embutidos **não** são retornados na resposta (apenas o Markdown).

Tempo típico em CPU: da ordem de **segundos a dezenas de segundos** por página, conforme complexidade e hardware.

---

## Troubleshooting

### `401 Token inválido` / `Token ausente`

- Confirme o header: `Authorization: Bearer <mesmo valor do API_TOKEN>`
- Não use aspas extras no `.env`
- Após alterar o `.env`, reinicie: `docker compose up -d`

### Container demora ou parece “travado” no primeiro start

- Normal na primeira execução (download dos modelos). Acompanhe:

```bash
docker compose logs -f ocr
```

- O healthcheck tem `start_period` alto (~3 min) por causa disso.

### Erro de memória (OOM / killed)

- Aumente a RAM da máquina (recomendado ≥ 8 GB)
- Reduza `MAX_UPLOAD_MB` e envie PDFs menores
- Evite processar PDFs muito pesados (mesmo lendo só a 1ª página, o arquivo inteiro é enviado)

### Porta já em uso

Altere `PORT` no `.env`, por exemplo `PORT=8080`, e suba de novo:

```bash
docker compose up -d
```

### Rebuild limpo

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

---

## Desenvolvimento local (opcional)

Se preferir rodar fora do Docker (ainda em CPU):

```bash
python -m venv .venv
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
cp .env.example .env   # configure API_TOKEN
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## Estrutura do projeto

```text
ocr/
├── app/
│   ├── main.py        # rotas /health e /ocr
│   ├── converter.py   # Marker (página 0 + force_ocr)
│   ├── auth.py        # Bearer token
│   └── config.py      # settings do .env
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
└── README.md
```
