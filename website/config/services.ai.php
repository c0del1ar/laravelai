<?php

return [
    'ai' => [
        'base_url' => env('AI_API_BASE_URL', 'http://ai_fastapi:8008'),
        'timeout' => (int) env('AI_API_TIMEOUT', 90),
        'auto_index_enabled' => filter_var(env('AI_AUTO_INDEX_ENABLED', true), FILTER_VALIDATE_BOOL),
        'auto_index_timeout' => (int) env('AI_AUTO_INDEX_TIMEOUT', 8),
        'internal_search_key' => env('AI_INTERNAL_SEARCH_KEY'),
        'internal_index_key' => env('AI_INTERNAL_INDEX_KEY', env('AI_INTERNAL_SEARCH_KEY')),
        'openclaw_context_key' => env('AI_OPENCLAW_CONTEXT_KEY', env('AI_INTERNAL_SEARCH_KEY')),
        'openclaw_context_cache_seconds' => (int) env('AI_OPENCLAW_CONTEXT_CACHE_SECONDS', 45),
        'public_base_url' => env('AI_PUBLIC_BASE_URL', env('APP_URL', '')),
        'owner_notify_email' => env('AI_OWNER_NOTIFY_EMAIL', ''),
        'assistant_name' => env('AI_ASSISTANT_NAME', 'Xiao-An'),
        'assistant_role' => env('AI_ASSISTANT_ROLE', 'AI customer service website Aryakun'),
        'assistant_style' => env(
            'AI_ASSISTANT_STYLE',
            'cewek manja, slang Chinese-Indonesian ringan (aiya, gege, lah), tetap sopan, jelas, dan ringkas'
        ),
        'assistant_identity_id' => env(
            'AI_ASSISTANT_IDENTITY_ID',
            'Aku Xiao-An, asisten AI customer service website Aryakun. Tugasku bantu pertanyaan seputar halaman, produk, tools, pricing, dan kontak.'
        ),
        'assistant_identity_en' => env(
            'AI_ASSISTANT_IDENTITY_EN',
            'I am Xiao-An, Aryakun website customer-service AI assistant. I help with pages, products, tools, pricing, and contact information.'
        ),
        'index_endpoint' => env('AI_INDEX_ENDPOINT', '/admin/index/events'),
    ],
];
