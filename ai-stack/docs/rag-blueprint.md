# Blueprint AI Core AryaKun (Crawler + Indexing + RAG)

Dokumen ini jadi acuan untuk AI core yang dipakai bersama oleh:
- Laravel website chat (`/v1/chat`)
- OpenClaw channel sosial (WA/Telegram/Discord via `/v1/chat/completions`)

Tujuan utama:
- Jawaban konsisten lintas channel
- Lebih paham isi website secara menyeluruh
- Navigasi link relevan hanya jika ada evidence
- Tetap conversational sebagai Xiao-An (bukan mengaku sebagai website)

## 1. Arsitektur

1. Ingestion
- Crawl dari `sitemap.xml` + BFS internal links
- Simpan halaman ter-normalisasi: path, title, content, public_url
- Persist cache ke disk (`KB_CACHE_PATH`) agar startup tidak cold

2. Indexing
- Full-page lexical index (token overlap + tf weighting)
- Chunk index (window + overlap) untuk menangkap detail section halaman panjang
- Site catalog index (path/title/section) untuk awareness navigasi global (`/tools`, `/pricing`, dll)

3. Retrieval
- Multi-query search generation dari user prompt + follow-up history
- Merge hasil Laravel internal search
- Chunk-first retrieval (evidence detail), lanjut search+crawl merge, lalu full-page fallback
- Context yang dikirim ke LLM dibatasi (`CONTEXT_MAX_PAGES`) agar stabil

4. Generation
- LLM (Groq) menerima:
  - `page_context` (grounding utama)
  - `site_catalog` (daftar halaman situs)
  - persona/policy Xiao-An
- LLM wajib output JSON terstruktur untuk post-processing

5. Guardrails / Post-processing
- Validasi URL agar tidak halusinasi (harus ada di KB/catalog)
- Relevance scoring berbasis evidence
- Link otomatis dihapus jika tidak relevan
- Fallback URL dipilih dari skor terbaik jika model gagal mengembalikan link padahal evidence kuat

## 2. Persona dan Respons

Persona inti:
- Nama: Xiao-An
- Peran: AI assistant AryaKun untuk melayani calon client/pengunjung
- Gaya: ramah, natural, conversational

Aturan penting:
- Jangan pernah mengaku "saya adalah website"
- Bila ditanya identitas: jawab sebagai Xiao-An (assistant AryaKun)
- Untuk pertanyaan umum/non-website: jawab normal tanpa memaksa link

## 3. Endpoint Kontrak

1. Laravel internal
- `POST /v1/chat`
- Output: `answer` (rendered), `answer_raw`, `recommended_url`, `related_items`, dll

2. OpenAI-compatible (untuk OpenClaw)
- `GET /v1/models`
- `POST /v1/chat/completions`
- Bearer auth via `OPENCLAW_COMPAT_API_KEY`

3. Legacy webhook (opsional)
- `POST /v1/openclaw`

4. Debugging RAG
- `GET /admin/rag/debug?q=...`
- Menampilkan search queries, chunk hits, page hits, context pages, catalog preview

## 4. Konfigurasi Kunci

Crawler/indexing:
- `CRAWL_MAX_PAGES`
- `CRAWL_DISCOVERY_MAX_PAGES`
- `CRAWL_PAGE_TEXT_MAX_CHARS`
- `KB_CACHE_PATH`

RAG context:
- `CONTEXT_MAX_PAGES`
- `CONTEXT_PAGE_CONTENT_CHARS`
- `RAG_CHUNK_SIZE_CHARS`
- `RAG_CHUNK_OVERLAP_CHARS`
- `RAG_CHUNK_TOP_K`
- `RAG_CONTEXT_CHUNKS`
- `RAG_MAX_CHUNKS_PER_PAGE`
- `SITE_CATALOG_MAX_ITEMS`

OpenClaw compatibility:
- `OPENCLAW_COMPAT_API_KEY`
- `OPENCLAW_COMPAT_MODEL_ID`
- `OPENAI_HISTORY_LIMIT`
- `OPENAI_MESSAGE_MAX_CHARS`

## 5. Strategy Tuning yang Disarankan

1. Jika AI belum paham detail halaman panjang (mis. `/tools`):
- Naikkan `CRAWL_PAGE_TEXT_MAX_CHARS`
- Naikkan `RAG_CHUNK_TOP_K`
- Naikkan `RAG_CONTEXT_CHUNKS`

2. Jika jawaban terlalu panjang atau sering timeout/502:
- Turunkan `CONTEXT_MAX_PAGES`
- Turunkan `CONTEXT_PAGE_CONTENT_CHARS`
- Turunkan `OPENAI_HISTORY_LIMIT`

3. Jika link masih sering tidak relevan:
- Turunkan `CONTEXT_MAX_PAGES`
- Evaluasi query via `/admin/rag/debug`
- Perbaiki metadata halaman (title/headings) di website

## 6. Checklist Verifikasi Produksi

1. Health
- `GET /health` menunjukkan pages/chunks/catalog > 0

2. Catalog
- `GET /admin/rag/debug?q=tools` memastikan `/tools` ada di `catalog_preview` atau `page_hits`

3. OpenClaw
- `openclaw channels status` harus `running, connected`
- DM test menghasilkan respons (bukan warning session error)

4. Konsistensi channel
- Pertanyaan sama di web dan WA memberi jawaban setara (konten + link relevan)

## 7. Roadmap Upgrade Lanjutan (Opsional)

1. Hybrid semantic retrieval (embeddings) + reranker
- Tambah vector store untuk recall semantic lebih tinggi
- Tetap gabung dengan lexical retrieval agar robust

2. Freshness pipeline
- Partial recrawl berbasis perubahan sitemap `lastmod`
- Prioritas crawl untuk halaman penting (pricing/tools/docs)

3. Evaluation harness
- Dataset Q/A internal per topik (pricing, fitur, tools, kontak)
- Auto-score: accuracy, relevance, link correctness
