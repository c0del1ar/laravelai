<?php

return [
    'ai' => [
        'base_url' => env('AI_API_BASE_URL', 'http://ai_fastapi:8008'),
        'timeout' => (int) env('AI_API_TIMEOUT', 90),
        'auto_index_enabled' => filter_var(env('AI_AUTO_INDEX_ENABLED', true), FILTER_VALIDATE_BOOL),
        'auto_index_timeout' => (int) env('AI_AUTO_INDEX_TIMEOUT', 8),
        'internal_search_key' => env('AI_INTERNAL_SEARCH_KEY'),
        'internal_index_key' => env('AI_INTERNAL_INDEX_KEY', env('AI_INTERNAL_SEARCH_KEY')),
        'index_endpoint' => env('AI_INDEX_ENDPOINT', '/admin/index/events'),
    ],
];
