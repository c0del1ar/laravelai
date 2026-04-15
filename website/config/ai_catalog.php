<?php

return [
    'static_pages' => [
        [
            'type' => 'page',
            'section' => 'home',
            'title' => 'AryaKun Home',
            'path' => '/',
            'url' => '/',
            'summary' => 'Halaman utama AryaKun berisi ringkasan layanan dan arah navigasi utama.',
            'keywords' => ['aryakun', 'home', 'layanan', 'fitur'],
        ],
        [
            'type' => 'page',
            'section' => 'pricing',
            'title' => 'Pricing',
            'path' => '/pricing',
            'url' => '/pricing',
            'summary' => 'Informasi paket, plan, dan harga layanan AryaKun.',
            'keywords' => ['pricing', 'harga', 'paket', 'plan'],
        ],
        [
            'type' => 'page',
            'section' => 'contact',
            'title' => 'Contact',
            'path' => '/contact',
            'url' => '/contact',
            'summary' => 'Halaman kontak untuk support, kerja sama, dan pertanyaan lanjutan.',
            'keywords' => ['contact', 'kontak', 'support', 'whatsapp', 'email'],
        ],
        [
            'type' => 'page',
            'section' => 'about',
            'title' => 'About AryaKun',
            'path' => '/about',
            'url' => '/about',
            'summary' => 'Profil AryaKun, fokus layanan, dan latar belakang tim.',
            'keywords' => ['about', 'tentang', 'aryakun', 'profil'],
        ],
    ],

    // Ubah mapping ini agar sesuai model Laravel kamu.
    // Jika model tidak ada, service akan melewatinya tanpa error.
    'sources' => [
        [
            'model' => App\Models\Tool::class,
            'type' => 'tool',
            'section' => 'tools',
            'title_field' => 'name',
            'slug_field' => 'slug',
            'content_fields' => ['description', 'excerpt'],
            'url_prefix' => '/tools/',
            'limit' => 4,
            'catalog_limit' => 120,
            'auto_index' => true,
            // Opsional: aktifkan jika model punya status publish.
            // 'publish_field' => 'status',
            // 'published_values' => ['published', 'active', 1, true],
        ],
        [
            'model' => App\Models\Product::class,
            'type' => 'product',
            'section' => 'products',
            'title_field' => 'name',
            'slug_field' => 'slug',
            'content_fields' => ['description', 'excerpt'],
            'url_prefix' => '/products/',
            'limit' => 4,
            'catalog_limit' => 120,
            'auto_index' => true,
            // 'publish_field' => 'status',
            // 'published_values' => ['published', 'active', 1, true],
        ],
        [
            'model' => App\Models\Post::class,
            'type' => 'blog',
            'section' => 'blog',
            'title_field' => 'title',
            'slug_field' => 'slug',
            'content_fields' => ['excerpt', 'content'],
            'url_prefix' => '/blog/',
            'limit' => 4,
            'catalog_limit' => 160,
            'auto_index' => true,
            // 'publish_field' => 'status',
            // 'published_values' => ['published', 'active', 1, true],
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
