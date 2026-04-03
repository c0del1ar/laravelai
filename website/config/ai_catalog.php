<?php

return [
    // Ubah mapping ini agar sesuai model Laravel kamu.
    // Jika model tidak ada, service akan melewatinya tanpa error.
    'sources' => [
        [
            'model' => App\Models\Tool::class,
            'type' => 'tool',
            'title_field' => 'name',
            'slug_field' => 'slug',
            'content_fields' => ['description', 'excerpt'],
            'url_prefix' => '/tools/',
            'limit' => 4,
        ],
        [
            'model' => App\Models\Product::class,
            'type' => 'product',
            'title_field' => 'name',
            'slug_field' => 'slug',
            'content_fields' => ['description', 'excerpt'],
            'url_prefix' => '/products/',
            'limit' => 4,
        ],
        [
            'model' => App\Models\Post::class,
            'type' => 'blog',
            'title_field' => 'title',
            'slug_field' => 'slug',
            'content_fields' => ['excerpt', 'content'],
            'url_prefix' => '/blog/',
            'limit' => 4,
        ],
        /* [
            'model' => App\Models\Page::class,
            'type' => 'page',
            'title_field' => 'title',
            'slug_field' => 'slug',
            'content_fields' => ['excerpt', 'body', 'content'],
            'url_prefix' => '/',
            'limit' => 3,
        ], */
    ],
];
