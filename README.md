# Website Laravel + internal AI bridge

Pola yang dipakai:

- Browser -> Laravel `/api/ai/chat`
- Laravel -> FastAPI internal (`http://ai_fastapi:8008`)
- OpenClaw (WA/Telegram/Discord) -> OpenClaw native codex (mode resmi) dengan website context endpoint Laravel
- OpenClaw (opsional compatibility) -> FastAPI OpenAI-compatible (`http://ai_fastapi:8008/v1/chat/completions`)
- FastAPI -> Laravel internal search (`http://laravel_franken:8000/api/internal/ai/search`)
- FastAPI -> Laravel internal tools manifest (`http://laravel_franken:8000/api/internal/ai/tools`)
- FastAPI -> Laravel internal structured catalog (`http://laravel_franken:8000/api/internal/ai/catalog`)
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
   - register provider `App\Providers\AiAutoIndexServiceProvider` agar model event otomatis kirim perubahan path ke AI index queue
   - set `AI_OPENCLAW_CONTEXT_KEY` untuk endpoint context OpenClaw native (`/api/ai/openclaw/context`)

3. Di project AI terpisah:
   - copy folder `ai-stack/`
   - `cp .env.example .env`
   - pastikan `AI_SHARED_NETWORK` sama dengan `AI_SHARED_NETWORK` di project Laravel
   - pastikan `SEARCH_API_URL=http://laravel_franken:8000/api/internal/ai/search`
   - samakan `SEARCH_API_KEY` dengan `AI_INTERNAL_SEARCH_KEY` di Laravel
   - pastikan `TOOL_MANIFEST_API_URL=http://laravel_franken:8000/api/internal/ai/tools`
   - pastikan `CATALOG_API_URL=http://laravel_franken:8000/api/internal/ai/catalog`
   - isi `SITE_NAVIGATION_BRIEF` untuk menegaskan fokus konten website (pricing, fitur, tentang Aryakun, kontak, dll)
   - atur parameter crawl/index (`CRAWL_*`, `RAG_*`, `SITE_CATALOG_MAX_ITEMS`) sesuai ukuran situs
   - set `OPENCLAW_WEBHOOK_KEY` (wajib jika profile `openclaw` dijalankan)
   - set `OPENCLAW_COMPAT_API_KEY` hanya jika pakai mode compatibility (`/v1/chat/completions`)
   - set `OPENCLAW_COMPAT_MODEL_ID` (default: `xiao-an`)
   - set `OPENCLAW_OWNER_NOTIFY_URL` ke endpoint Laravel internal notify (default: `/api/internal/ai/openclaw/owner-notify`)
   - set `OPENCLAW_OWNER_NOTIFY_KEY` (atau fallback ke `SEARCH_API_KEY`) untuk auth header ke endpoint notify
   - jika mau jalankan OpenClaw container di stack ini, set `OPENCLAW_IMAGE` sesuai image OpenClaw yang kamu pakai
   - `docker compose up -d --build`

4. Jalankan website compose.
5. (Opsional) Jalankan OpenClaw profile lewat preflight wrapper:
   ```bash
   cd ai-stack
   ./openclawd up
   ```
6. (Opsional) Aktifkan native DM gate plugin (cooldown + reminder + owner notify):
   ```bash
   cd ai-stack
   ./openclawd setup dm-gate
   ```

## Catatan

- FastAPI **tidak dipublish** ke host. Ia hanya `expose: 8008` di Docker network.
- FastAPI sekarang memakai volume `ai_fastapi_data` untuk cache knowledge base (`KB_CACHE_PATH`) agar indeks crawl tidak hilang saat container restart.
- OpenClaw sekarang memakai volume `openclaw_data` (`/home/node/.openclaw`) agar sesi channel/linking tidak hilang saat container recreate.
- Jika muncul error `EACCES ... /home/node/.openclaw/openclaw.json.*.tmp`, jalankan:
  - `docker compose --profile openclaw up -d openclaw_init_permissions`
  - `docker compose --profile openclaw restart openclaw`
- FastAPI sekarang juga bisa menarik catalog terstruktur dari Laravel (`/internal/ai/catalog`) sebagai sinyal navigasi non-HTML (section/title/keywords/updated_at).
- LLM dipanggil dari FastAPI ke provider OpenAI-compatible. Default sekarang `LLM_PROVIDER=groq` dengan model `GROQ_MODEL=llama-3.1-8b-instant`.
- Untuk OpenAI, set `OPENAI_AUTH_MODE=api_key` + `OPENAI_API_KEY`. Opsi `OPENAI_AUTH_MODE=oauth` memakai bearer token di `OPENAI_OAUTH_ACCESS_TOKEN`.
- Browser user hanya bicara ke route Laravel, jadi tidak perlu CORS untuk AI stack.
- `config/ai_catalog.php` perlu kamu sesuaikan dengan model Laravel yang benar.
- Output AI sekarang konsisten untuk Laravel chat dan OpenClaw: jawaban + link relevan + link terkait (jika ada).
- Link hanya diberikan jika pertanyaan memang relevan dengan halaman website; untuk chat umum/non-website tidak dipaksa ada link.
- AI core sekarang memakai hybrid retrieval (lexical + semantic-hash) + reranker, lalu fallback chunk/page.
- AI core sekarang menggabungkan sumber crawl HTML + structured catalog Laravel + tool manifest, lalu intent-aware reranking.
- AI sekarang bisa dijalankan dalam mode customer-service only (`CS_ONLY_MODE=true`): tidak mengeksekusi aksi/tool, hanya panduan how-to dan info layanan.
- Scope website ketat tersedia (`STRICT_WEBSITE_SCOPE_ENABLED=true`): pertanyaan di luar konteks aryakun.id akan ditolak dan diarahkan kembali ke topik website.
- Retrieval sekarang pakai reranker kandidat lebih lebar (`RAG_RERANK_CANDIDATES`) + intent boost (pricing/contact/tutorial) supaya hasil konteks lebih presisi.
- Semantic retrieval sekarang bisa pakai embedding beneran (`EMBEDDING_PROVIDER=openai`) dengan vector store SQLite (`VECTOR_DB_PATH`), fallback ke local-hash jika auth OpenAI tidak tersedia.
- Untuk pertanyaan "how to use / cara pakai tool", AI memprioritaskan tools manifest + playbook (what-it-does, input tips, troubleshooting) dari endpoint internal Laravel.
- Ada tool hook layer (contoh: `noredirect`) untuk contoh input valid/invalid dan tips penggunaan yang lebih praktis.
- Response API sekarang menyertakan `confidence_score` dan `sources` (citation ringan) agar kualitas jawaban bisa diaudit.
- Memory percakapan lintas channel disimpan per `user_id` (`web`, `openclaw`, `openai-compatible`) dengan TTL.
- Response cache semantik aktif (`RESPONSE_CACHE_*`) untuk turunkan latency/cost pada pertanyaan berulang.
- Strict grounding aktif (`STRICT_GROUNDING_*`): jika konteks lemah, AI tidak memaksa link dan akan minta klarifikasi.
- Human handoff aktif (`HUMAN_HANDOFF_*`): jika user minta admin/human atau low-confidence streak, AI arahkan ke jalur kontak manusia.
- Tersedia observability endpoint `GET /admin/metrics` untuk pantau latency, error, confidence, memory, dan statistik route.
- Metrics sekarang termasuk flag kualitas (`low_confidence`, `handoff`, `cache_hit`, `ungrounded`) dan statistik prefix-gate.
- Intent router aktif (`tutorial|pricing|contact|troubleshoot|faq|smalltalk|navigation`) dengan retrieval policy berbeda per mode.
- A/B experiment prompt+model tersedia (`control|concise|advisor`) via env config, dan termonitor di metrics.
- Learning loop aktif: low-confidence/error case otomatis tercatat dan bisa dikoreksi via endpoint admin.
- AI Ops panel tersedia di `GET /admin/ops`.
- Tersedia incremental indexing endpoint `POST /admin/index/changed` agar update halaman bisa di-refresh tanpa full recrawl.
- SLO alerting tersedia via webhook jika error rate/latency/confidence melewati threshold.

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

## OpenClaw native OpenAI Codex (`openai-codex/gpt-5.4`) — mode resmi

Mode resmi untuk OpenClaw di repo ini adalah native codex + context endpoint Laravel.

1. Pastikan key webhook sudah diisi (wajib saat profile OpenClaw aktif):

```bash
cd ai-stack
./openclawdscr/openclaw_preflight.sh
```

2. Login OAuth Codex:

```bash
openclaw models auth login --provider openai-codex
```

3. Set model default:

```bash
openclaw config set agents.defaults.model.primary openai-codex/gpt-5.4
```

4. Batasi tool agar mode CS tidak mengeksekusi hal berisiko:

```bash
cd ai-stack
./openclawdscr/lock_openclaw_cs_mode.sh
```

Script di atas akan menulis allow-list + deny-list tool ke konfigurasi OpenClaw (dengan fallback key path antar versi), lalu restart service.
Untuk memasang ulang persona + hard CS scope ke workspace OpenClaw, jalankan juga:

```bash
cd ai-stack
CTX_KEY=<AI_OPENCLAW_CONTEXT_KEY> bash ./openclawdscr/setup_openclaw_xiaoan.sh
```

Nilai default policy:

```json
{
  "allow": ["session_status", "group:web", "group:memory"],
  "deny": ["exec", "terminal", "shell", "run", "read", "write", "edit", "apply_patch", "browser", "canvas"]
}
```

5. Jalankan/restart profile OpenClaw dengan wrapper (enforce webhook key):

```bash
# start
cd ai-stack
./openclawd up

# restart
./openclawd restart
```

6. Tambahkan system prompt override (atau prompt per channel) agar bot selalu grounding ke website:

```text
Anda adalah Xiao-An, asisten AI cewek manja untuk customer service website Aryakun.
Saat user tanya "siapa kamu", wajib jawab tegas bahwa kamu Xiao-An dan pekerjaanmu adalah customer service website Aryakun.
Gunakan slang Chinese-Indonesian ringan (aiya, gege, lah) secukupnya, tetap sopan dan ringkas.
Jangan pernah bilang "unfinished", "not configured", atau "belum punya identitas".
Sebelum menjawab pertanyaan website, ambil context dari:
GET https://<domain-kamu>/api/ai/openclaw/context?q=<urlencode-pertanyaan>&limit=8
Header: X-OpenClaw-Context-Key: <AI_OPENCLAW_CONTEXT_KEY>
Gunakan `assistant_profile` dan `response_policy` sebagai aturan identitas/persona.
Gunakan data `search`, `catalog`, dan `tools` sebagai sumber utama konten website.
Jika data tidak cukup, minta klarifikasi dan jangan mengarang.
Jangan pernah mengklaim mengeksekusi aksi akun/transaksi.
```

Endpoint context Laravel (GET):

```http
GET /api/ai/openclaw/context?q=<query>&limit=8
X-OpenClaw-Context-Key: <AI_OPENCLAW_CONTEXT_KEY>
```

Untuk deployment Docker internal, lebih stabil pakai base URL internal network:

```http
http://laravel_franken:8000/api/ai/openclaw/context
```

Hindari hostname container instance seperti `aryakunid-laravel_franken-1` karena bisa berubah saat recreate.

Fallback kompatibilitas (jika channel/web_fetch tidak bisa kirim custom header):

```http
GET /api/ai/openclaw/context?key=<AI_OPENCLAW_CONTEXT_KEY>&q=<query>&limit=8
```

Contoh response:

```json
{
  "query": "cara pakai no redirect checker",
  "generated_at": "2026-04-20T14:10:00+00:00",
  "site_context": {
    "search": [],
    "catalog": [],
    "tools": []
  }
}
```

### Native DM gate + owner notify

- OpenClaw native sekarang bisa dipasang plugin `xiaoan-dm-gate` untuk:
  - hanya merespons DM non-prefix dengan reminder sesuai cooldown
  - membisukan DM non-prefix selama masih dalam cooldown
  - tetap melewatkan DM prefix `/ia` ke AI normal
  - menolak DM prefix `/ia` yang jelas di luar jobdesk CS website, misalnya request membuat program, membahas website eksternal, matematika, atau general knowledge
  - mengirim notif email owner saat reminder pertama per sender di luar cooldown
- Scope gate plugin aktif default (`OPENCLAW_NATIVE_CS_SCOPE_GATE_ENABLED=true`). Set ke `false` hanya jika ingin kembali membiarkan model menangani semua pesan prefixed.
- Laravel internal notify endpoint:
  - `POST /api/internal/ai/openclaw/owner-notify`
  - auth: header `X-Search-Key` (pakai `AI_INTERNAL_SEARCH_KEY`)
  - recipient email: `AI_OWNER_NOTIFY_EMAIL`

## OpenClaw compatibility ke AI core FastAPI (opsional)

Gunakan mode ini hanya jika kamu memang ingin OpenClaw diarahkan ke FastAPI OpenAI-compatible bridge.

FastAPI menyediakan endpoint:

```http
GET  /v1/models
POST /v1/chat/completions
Authorization: Bearer <OPENCLAW_COMPAT_API_KEY>
Content-Type: application/json
```

Konfigurasi provider `fastapi` di OpenClaw:

```bash
docker compose --profile openclaw exec -it openclaw openclaw config set models.providers.fastapi.baseUrl http://ai_fastapi:8008/v1
docker compose --profile openclaw exec -it openclaw openclaw config set models.providers.fastapi.api openai-completions
docker compose --profile openclaw exec -it openclaw openclaw config set models.providers.fastapi.apiKey '$OPENCLAW_COMPAT_API_KEY'
docker compose --profile openclaw exec -it openclaw openclaw config set models.providers.fastapi.models '[{"id":"xiao-an","name":"AI Core Xiao-An","reasoning":false,"input":["text"],"cost":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0},"contextWindow":128000,"maxTokens":4096}]'
docker compose --profile openclaw exec -it openclaw openclaw models set fastapi/xiao-an
```

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
CATALOG_API_URL=http://laravel_franken:8000/api/internal/ai/catalog
TOOL_MANIFEST_TTL=300
TOOL_MANIFEST_MAX_ITEMS=200
CATALOG_TTL=300
CATALOG_MAX_ITEMS=250
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

Dan aktifkan hard budget input ke LLM supaya request tidak melewati batas TPM:

```env
LLM_MAX_INPUT_TOKENS=2600
LLM_MAX_HISTORY_MESSAGES=4
LLM_MAX_HISTORY_CHARS=600
LLM_MAX_CONTEXT_PAGES=6
LLM_MAX_CONTEXT_CONTENT_CHARS=900
LLM_MAX_CONTEXT_SUMMARY_CHARS=260
LLM_MAX_SITE_CATALOG=30
LLM_MAX_TOOL_MANIFESTS=2
LLM_MAX_TOOL_FIELDS=8
LLM_MAX_TOOL_STEPS=6
```

Set provider + model utama (default Groq):

```env
LLM_PROVIDER=groq
GROQ_MODEL=llama-3.1-8b-instant
GROQ_FALLBACK_MODELS=llama-3.1-8b-instant,llama-3.1-70b-versatile,meta-llama/llama-4-scout-17b-16e-instruct
LLM_RETRY_MAX_ATTEMPTS=3
LLM_RETRY_BASE_DELAY_MS=350
```

Autentikasi OpenAI:

```env
# Opsi default (direkomendasikan untuk OpenAI API)
OPENAI_AUTH_MODE=api_key
OPENAI_API_KEY=<your-openai-api-key>

# Opsi alternatif bearer token
# OPENAI_AUTH_MODE=oauth
# OPENAI_OAUTH_ACCESS_TOKEN=<your-oauth-access-token>
```

Aktifkan semantic embeddings + vector store:

```env
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
VECTOR_DB_PATH=/var/lib/ai_fastapi/vector_store.db
SEMANTIC_TOP_K=10
SEMANTIC_MIN_SCORE=0.2
```

Aktifkan A/B experiment dan channel policy:

```env
AB_EXPERIMENT_ENABLED=true
AB_VARIANTS=control,concise,advisor
AB_MODEL_CONTROL=gpt-5.1
AB_MODEL_CONCISE=gpt-5-mini
AB_MODEL_ADVISOR=gpt-5.1
CHANNEL_POLICY_WEB_MAX_SENTENCES=5
CHANNEL_POLICY_OPENCLAW_MAX_SENTENCES=3
CHANNEL_POLICY_OPENAI_MAX_SENTENCES=4
```

Aktifkan SLO alerting:

```env
SLO_ALERT_ENABLED=true
SLO_ALERT_WEBHOOK_URL=https://your-webhook-url
SLO_ALERT_COOLDOWN_SECONDS=300
SLO_HTTP_5XX_RATE_THRESHOLD=0.05
SLO_CHAT_LATENCY_MS_THRESHOLD=5000
SLO_CHAT_CONFIDENCE_THRESHOLD=0.45
SLO_MIN_SAMPLE_SIZE=20
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
- intent profile + query bias yang aktif
- hasil search Laravel yang tergabung
- hasil tools manifest yang relevan (khusus intent tutorial penggunaan tool)
- kandidat structured catalog Laravel
- chunk hits + page hits dari crawler index
- context final yang dikirim ke LLM
- preview katalog halaman situs

## Incremental indexing

Untuk update sebagian halaman tanpa full recrawl:

```http
POST /admin/index/changed
X-Index-Key: <INTERNAL_INDEX_KEY>
Content-Type: application/json
```

Payload:

```json
{
  "paths": ["/tools/noredirect", "/pricing"],
  "urls": ["https://aryakun.id/blog/some-post"]
}
```

Di sisi Laravel, tersedia endpoint forwarder internal:

```http
POST /api/internal/ai/index/changed
X-Search-Key: <AI_INTERNAL_SEARCH_KEY>
```

Endpoint ini meneruskan perubahan ke FastAPI dengan `X-Index-Key`.

## Auto-index dari event Laravel (publish/update/delete)

Event model sekarang bisa otomatis trigger indexing ke FastAPI queue endpoint (`/admin/index/events`), jadi tidak perlu panggil endpoint manual setiap update konten.

File utama:
- `website/app/Services/AiAutoIndexObserverRegistrar.php`
- `website/app/Services/AiIndexBridgeService.php`
- `website/app/Providers/AiAutoIndexServiceProvider.php`

Aktifkan provider di project Laravel kamu:

- Laravel <=10: tambahkan `App\Providers\AiAutoIndexServiceProvider::class` ke `config/app.php` bagian `providers`.
- Laravel 11: daftarkan provider di `bootstrap/app.php` sesuai pola project kamu.

Konfigurasi env:

```env
AI_AUTO_INDEX_ENABLED=true
AI_AUTO_INDEX_TIMEOUT=8
AI_INDEX_ENDPOINT=/admin/index/events
```

Untuk tiap source di `config/ai_catalog.php`, kamu bisa aktifkan filter publish:

```php
'publish_field' => 'status',
'published_values' => ['published', 'active', 1, true],
```

Jika `publish_field` dipakai, draft/unpublished tidak akan dipush kecuali ada transisi dari/ke status published.

Untuk mode event queue (debounced auto-index), gunakan endpoint:

```http
POST /admin/index/events
X-Index-Key: <INTERNAL_INDEX_KEY>
Content-Type: application/json
```

Payload sama dengan `/admin/index/changed`, bedanya proses refresh dilakukan async di background.

## Regression Eval

Jalankan evaluasi regresi setelah deploy:

```bash
cd ai-stack/evals
./run_regression.sh http://127.0.0.1:8008 0.66
```

- Exit code `0`: lulus threshold.
- Exit code `2`: rata-rata score di bawah threshold.

Alternatif dari root project:

```bash
make eval EVAL_BASE_URL=http://127.0.0.1:8008 EVAL_MIN_SCORE=0.66
```

## CI Otomatis (Push/PR)

Workflow tersedia di `.github/workflows/ai-regression.yml`:
- `compile-check` selalu jalan (syntax compile Python).
- `eval` jalan otomatis jika secret provider LLM tersedia (misalnya `OPENAI_API_KEY` atau `GROQ_API_KEY`).

Set minimal secret repository:

```text
OPENAI_API_KEY=<your-openai-api-key>
```

## Learning Loop

Endpoint admin learning:

```http
GET  /admin/learning/failures?limit=100
POST /admin/learning/corrections
GET  /admin/learning/export?limit=1000
POST /v1/feedback
```

Header untuk endpoint admin learning:

```http
X-Index-Key: <INTERNAL_INDEX_KEY>
```

`/admin/learning/corrections` payload:

```json
{
  "event_id": "evt_xxx",
  "corrected_answer": "jawaban yang benar",
  "corrected_url": "https://aryakun.id/tools/noredirect",
  "tags": ["tools", "tutorial"]
}
```

`/v1/feedback` payload (dari web/openclaw bridge):

```json
{
  "message": "how to use no redirect checker",
  "answer": "jawaban dari AI",
  "recommended_url": "/tools/noredirect",
  "user_id": "user-123",
  "channel": "web",
  "reason": "jawaban kurang detail di input field",
  "intent_mode": "tutorial",
  "rating": -1,
  "response_id": "res_xxxxx"
}
```

UI ringkas tersedia di:

```http
GET /admin/ops
```

## Model fallback (anti rate-limit / timeout)

Aktifkan fallback model OpenAI di `.env`:

```env
LLM_PROVIDER=openai
OPENAI_MODEL=gpt-5.1
OPENAI_FALLBACK_MODELS=gpt-5.1,gpt-5-mini,gpt-5-nano
LLM_RETRY_MAX_ATTEMPTS=3
LLM_RETRY_BASE_DELAY_MS=350
LOW_CONFIDENCE_THRESHOLD=0.42
CS_ONLY_MODE=true
STRICT_WEBSITE_SCOPE_ENABLED=true
```

## Eval otomatis (quality gate)

Dataset eval ada di `ai-stack/evals/eval_cases.jsonl`.

Jalankan evaluasi:

```bash
cd ai-stack/evals
python3 run_eval.py --base-url http://127.0.0.1:8008
```

Atau via script regression (dengan CS gate threshold default):

```bash
./ai-stack/evals/run_regression.sh http://127.0.0.1:8008 0.66
```

Hasil tersimpan di `ai-stack/evals/eval_report.json` dengan metrik:
- keyword coverage
- URL relevance
- confidence
- latency
- total score rata-rata
- execution refusal rate (CS-only)
- hallucinated URL rate
- how-to completeness
- handoff accuracy

## Fine-tuning Xiao-An (LoRA)

Pipeline fine-tuning sudah disiapkan di folder `ai-stack/training/`:

1. Export data learning:

```bash
make ft-export INDEX_KEY=<INTERNAL_INDEX_KEY>
```

2. Prepare dataset SFT:

```bash
make ft-prepare
```

3. (Opsional tapi direkomendasikan) Prepare dataset DPO dari feedback:

```bash
make ft-prepare-dpo
```

4. Jalankan training LoRA (di mesin GPU):

```bash
python3 ai-stack/training/train_lora.py \
  --model Qwen/Qwen2.5-7B-Instruct \
  --train-file ai-stack/training/data/train.jsonl \
  --valid-file ai-stack/training/data/valid.jsonl \
  --output-dir ai-stack/training/output/lora-xiaoan-v1 \
  --epochs 2 --lr 2e-4 --batch-size 2 --grad-accum 8 \
  --max-seq-len 2048 --load-in-4bit --bf16 --gradient-checkpointing
```

Detail langkah dan script ada di:
- `ai-stack/training/README.md`
- `ai-stack/training/export_learning.py`
- `ai-stack/training/prepare_sft_dataset.py`
- `ai-stack/training/prepare_dpo_dataset.py`
- `ai-stack/training/train_lora.py`
- `ai-stack/training/train_dpo.py`
- `ai-stack/training/merge_lora.py`

### Endpoint legacy (opsional)

Endpoint berikut tetap tersedia untuk integrasi webhook custom:

```http
POST /v1/openclaw
X-OpenClaw-Key: <OPENCLAW_WEBHOOK_KEY>
```

Saat profile `openclaw` dijalankan, `OPENCLAW_WEBHOOK_KEY` wajib diisi (wrapper preflight akan menolak start/restart jika kosong atau placeholder).

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
