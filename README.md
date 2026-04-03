# Website Laravel + internal AI bridge

Pola yang dipakai:

- Browser -> Laravel `/api/ai/chat`
- Laravel -> FastAPI internal (`http://ai_fastapi:8008`)
- FastAPI -> Laravel internal search (`http://laravel_franken:8000/api/internal/ai/search`)
- FastAPI -> Groq API (LLM response)

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
   - `docker compose up -d --build`

4. Jalankan website compose.

## Catatan

- FastAPI **tidak dipublish** ke host. Ia hanya `expose: 8008` di Docker network.
- LLM dipanggil dari FastAPI ke Groq API, jadi `GROQ_API_KEY` wajib diisi di `ai-stack/.env`.
- Browser user hanya bicara ke route Laravel, jadi tidak perlu CORS untuk AI stack.
- `config/ai_catalog.php` perlu kamu sesuaikan dengan model Laravel yang benar.

## Browser / frontend

Frontend cukup panggil:

```js
fetch('/api/ai/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ message, history })
})
```

## Penting

Pack ini dibuat untuk jadi baseline produksi kecil. Mapping model Laravel (`Tool`, `Product`, `Post`, `Page`) kemungkinan perlu kamu sesuaikan dengan project aslimu.
