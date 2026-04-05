# Website Laravel + internal AI bridge

Pola yang dipakai:

- Browser -> Laravel `/api/ai/chat`
- Laravel -> FastAPI internal (`http://ai_fastapi:8008`)
- OpenClaw (WA/Telegram/Discord) -> FastAPI OpenAI-compatible (`http://ai_fastapi:8008/v1/chat/completions`)
- FastAPI -> Laravel internal search (`http://laravel_franken:8000/api/internal/ai/search`)
- FastAPI -> Laravel internal tools manifest (`http://laravel_franken:8000/api/internal/ai/tools`)
- FastAPI -> Groq API (LLM response)

Blueprint arsitektur lengkap ada di [ai-stack/docs/rag-blueprint.md](/home/an/Project/myweb/laravelai/ai-stack/docs/rag-blueprint.md).

## Langkah cepat

1. Buat shared bridge sekali di host:
   ```bash
   docker network create ai_bridge_local
   ```

2. Di project Laravel:
   - pakai `website/docker-compose.with-ai-bridge.yml`
   - tambahkan isi `website/.env.ai.example` ke `.env`
   - copy file controller/service/config/route snippet ke project Laravel

3. Di project AI terpisah:
   - copy folder `ai-stack/`
   - `cp .env.example .env`
   - pastikan `AI_SHARED_NETWORK` sama dengan `AI_SHARED_NETWORK` di project Laravel
   - pastikan `SEARCH_API_URL=http://laravel_franken:8000/api/internal/ai/search`
   - samakan `SEARCH_API_KEY` dengan `AI_INTERNAL_SEARCH_KEY` di Laravel
   - pastikan `TOOL_MANIFEST_API_URL=http://laravel_franken:8000/api/internal/ai/tools`
   - isi `SITE_NAVIGATION_BRIEF` untuk menegaskan fokus konten website (pricing, fitur, tentang Aryakun, kontak, dll)
   - atur parameter crawl/index (`CRAWL_*`, `RAG_*`, `SITE_CATALOG_MAX_ITEMS`) sesuai ukuran situs
   - set `OPENCLAW_WEBHOOK_KEY` (opsional, hanya untuk endpoint `/v1/openclaw`)
   - set `OPENCLAW_COMPAT_API_KEY` (wajib jika OpenClaw pakai provider ke FastAPI)
   - set `OPENCLAW_COMPAT_MODEL_ID` (default: `xiao-an`)
   - jika mau jalankan OpenClaw container di stack ini, set `OPENCLAW_IMAGE` sesuai image OpenClaw yang kamu pakai
   - `docker compose up -d --build`

4. Jalankan website compose.
5. (Opsional) Jalankan OpenClaw terpisah: `docker compose --profile openclaw up -d`

## Catatan

- FastAPI **tidak dipublish** ke host. Ia hanya `expose: 8008` di Docker network.
- FastAPI sekarang memakai volume `ai_fastapi_data` untuk cache knowledge base (`KB_CACHE_PATH`) agar indeks crawl tidak hilang saat container restart.
- LLM dipanggil dari FastAPI ke Groq API, jadi `GROQ_API_KEY` wajib diisi di `ai-stack/.env`.
- Browser user hanya bicara ke route Laravel, jadi tidak perlu CORS untuk AI stack.
- `config/ai_catalog.php` perlu kamu sesuaikan dengan model Laravel yang benar.
- Output AI sekarang konsisten untuk Laravel chat dan OpenClaw: jawaban + link relevan + link terkait (jika ada).
- Link hanya diberikan jika pertanyaan memang relevan dengan halaman website; untuk chat umum/non-website tidak dipaksa ada link.
- AI core sekarang memakai pipeline crawler + indexing + retrieval bertingkat (chunk-first + page fallback), bukan regex template statis.
- Untuk pertanyaan "how to use / cara pakai tool", AI memprioritaskan tools manifest (input field, steps, output, error cases) dari endpoint internal Laravel.

## Browser / frontend

Frontend cukup panggil:

```js
fetch('/api/ai/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ message, history })
})
```

Response `answer` dari `/api/ai/chat` sudah berisi format navigasi (jawaban + link), dan `answer_raw` tetap disertakan untuk teks mentah.

## OpenClaw ke AI core (tanpa Laravel)

FastAPI menyediakan endpoint OpenAI-compatible untuk model provider OpenClaw:

```http
GET  /v1/models
POST /v1/chat/completions
Authorization: Bearer <OPENCLAW_COMPAT_API_KEY>
Content-Type: application/json
```

Konfigurasikan OpenClaw agar model default diarahkan ke FastAPI:

```bash
docker compose --profile openclaw exec -it openclaw openclaw config set models.providers.fastapi.baseUrl http://ai_fastapi:8008/v1
docker compose --profile openclaw exec -it openclaw openclaw config set models.providers.fastapi.api openai-completions
docker compose --profile openclaw exec -it openclaw openclaw config set models.providers.fastapi.apiKey '$OPENCLAW_COMPAT_API_KEY'
docker compose --profile openclaw exec -it openclaw openclaw config set models.providers.fastapi.models '[{"id":"xiao-an","name":"AI Core Xiao-An","reasoning":false,"input":["text"],"cost":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0},"contextWindow":128000,"maxTokens":4096}]'
docker compose --profile openclaw exec -it openclaw openclaw models set fastapi/xiao-an
```

Setelah ini, balasan DM channel (WA/Telegram/Discord) akan lewat AI core FastAPI, bukan model Anthropic default OpenClaw.

## Prompt tuning website

Supaya AI lebih dalam memahami konteks website, atur `SITE_NAVIGATION_BRIEF` di `ai-stack/.env`, contoh:

```env
SITE_NAVIGATION_BRIEF=Website aryakun.id berfokus pada layanan AI automation. Prioritaskan jawaban tentang pricing, fitur, siapa Aryakun, kontak, dan selalu berikan link halaman paling relevan jika tersedia.
```

Untuk memperluas "ingatan" website (lebih banyak halaman + konten lebih panjang), atur juga:

```env
CRAWL_MAX_PAGES=300
CRAWL_DISCOVERY_MAX_PAGES=500
CRAWL_PAGE_TEXT_MAX_CHARS=20000
CONTEXT_PAGE_CONTENT_CHARS=3000
CONTEXT_MAX_PAGES=10
TOOL_MANIFEST_API_URL=http://laravel_franken:8000/api/internal/ai/tools
TOOL_MANIFEST_TTL=300
TOOL_MANIFEST_MAX_ITEMS=200
RAG_CHUNK_SIZE_CHARS=900
RAG_CHUNK_OVERLAP_CHARS=140
RAG_CHUNK_TOP_K=24
RAG_CONTEXT_CHUNKS=8
RAG_MAX_CHUNKS_PER_PAGE=2
SITE_CATALOG_MAX_ITEMS=120
```

Setelah ubah parameter crawl, trigger re-crawl dengan restart service:

```bash
docker compose restart ai_fastapi
```

Jika channel sosial media sering 502 karena konteks percakapan terlalu panjang, set batas OpenAI-compatible:

```env
OPENAI_HISTORY_LIMIT=4
OPENAI_MESSAGE_MAX_CHARS=1800
```

Lalu deploy ulang FastAPI:

```bash
docker compose up -d --build ai_fastapi
```

## Debug relevansi RAG

Untuk cek kenapa sebuah pertanyaan belum akurat, gunakan endpoint debug:

```http
GET /admin/rag/debug?q=tools
```

Response debug menampilkan:
- query turunan yang dipakai AI
- hasil search Laravel yang tergabung
- hasil tools manifest yang relevan (khusus intent tutorial penggunaan tool)
- chunk hits + page hits dari crawler index
- context final yang dikirim ke LLM
- preview katalog halaman situs

### Endpoint legacy (opsional)

Endpoint berikut tetap tersedia untuk integrasi webhook custom:

```http
POST /v1/openclaw
X-OpenClaw-Key: <OPENCLAW_WEBHOOK_KEY>
```

Payload minimum:

```json
{
  "message": "Halo, ada promo apa?"
}
```

Field lain yang juga didukung untuk kompatibilitas:

- pesan: `text`, `content`, `data.message`, `data.text`, `event.message.text`
- user id: `user_id`, `sender_id`, `from`, `user.id`, `sender.id`, `data.user_id`, `data.sender_id`
- riwayat: `history` atau `messages` (`[{role: user|assistant, content|text: "..."}]`)

Response sukses akan mengirim `reply`, `text`, `message`, dan `response` (isi sama) + payload `ai` mentah.

## Penting

Pack ini dibuat untuk jadi baseline produksi kecil. Mapping model Laravel (`Tool`, `Product`, `Post`, `Page`) kemungkinan perlu kamu sesuaikan dengan project aslimu.
