<?php

namespace App\Services;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Support\Arr;
use Illuminate\Support\Str;

class AiProductManifestService
{
    public function listProducts(int $limit = 100): array
    {
        $source = $this->resolveSource();
        if ($source === null) {
            return [];
        }

        $modelClass = (string) ($source['model'] ?? '');
        if ($modelClass === '' || ! class_exists($modelClass) || ! is_subclass_of($modelClass, Model::class)) {
            return [];
        }

        $builder = $modelClass::query();
        $this->applyPublishFilter($builder, $source);

        $updatedField = (string) ($source['updated_field'] ?? 'updated_at');
        $maxLimit = max(1, min($limit, 300));
        $records = $builder
            ->orderByDesc($updatedField)
            ->limit($maxLimit)
            ->get();

        return $records->map(fn (Model $product) => $this->buildManifest($product, $source))->values()->all();
    }

    public function getProductBySlug(string $slug): ?array
    {
        $source = $this->resolveSource();
        if ($source === null) {
            return null;
        }

        $modelClass = (string) ($source['model'] ?? '');
        if ($modelClass === '' || ! class_exists($modelClass) || ! is_subclass_of($modelClass, Model::class)) {
            return null;
        }

        $slugField = (string) ($source['slug_field'] ?? 'slug');
        $builder = $modelClass::query()->where($slugField, $slug);
        $this->applyPublishFilter($builder, $source);
        $product = $builder->first();
        if (! $product instanceof Model) {
            return null;
        }

        return $this->buildManifest($product, $source);
    }

    public function buildManifest(Model $product, array $source): array
    {
        $slugField = (string) ($source['slug_field'] ?? 'slug');
        $titleField = (string) ($source['title_field'] ?? 'name');
        $contentFields = array_values(array_filter(array_map('strval', (array) ($source['content_fields'] ?? []))));
        $slug = trim((string) data_get($product, $slugField, ''));
        $name = trim((string) data_get($product, $titleField, '')) ?: ($slug !== '' ? Str::headline($slug) : 'Untitled product');
        $description = $this->resolveDescription($product, $contentFields);
        $shortDescription = $this->resolveShortDescription($product, $description);
        $url = $this->buildUrl($product, $source, $slug);
        $catalogType = trim((string) data_get($product, 'catalog', ''));
        $price = (float) data_get($product, 'price', 0);
        $updatedAt = data_get($product, (string) ($source['updated_field'] ?? 'updated_at'));
        $updated = method_exists($updatedAt, 'toAtomString') ? $updatedAt->toAtomString() : now()->toAtomString();

        $steps = [
            'Open the product page: ' . ($url !== '' ? $url : '/products'),
            'Review the product description, pricing, and deliverables.',
            $price > 0
                ? 'If this is paid, complete checkout/payment flow from the website.'
                : 'If this is free, continue to download/access instructions on the page.',
            'If you need help, continue via the contact/support page.',
        ];

        $faq = [
            [
                'q' => 'Is this product free or paid?',
                'a' => $catalogType !== '' ? 'This product is marked as: ' . $catalogType . '.' : 'Please check the product page pricing label.',
            ],
            [
                'q' => 'Where can I access the product?',
                'a' => $url !== '' ? 'Use this page: ' . $url : 'Use the product listing page to open details.',
            ],
        ];

        $errorCases = [
            'Product not found: verify product slug or listing path.',
            'Access blocked: check login/subscription/payment requirement on product page.',
            'Download link unavailable: contact support from contact page.',
        ];

        return [
            'type' => 'product',
            'slug' => $slug,
            'name' => $name,
            'url' => $url,
            'description' => $description,
            'short_description' => $shortDescription,
            'category' => $catalogType,
            'pricing' => [
                'catalog_type' => $catalogType,
                'price' => $price,
                'currency' => strtoupper((string) config('cashier.currency', config('app.currency', 'USD'))),
                'price_label' => $this->priceLabel($catalogType, $price),
            ],
            'access' => [
                'download_url' => trim((string) data_get($product, 'download_url', '')),
                'requires_purchase' => $price > 0 && strtolower($catalogType) !== 'free',
            ],
            'media' => [
                'image_url' => trim((string) data_get($product, 'image_url', data_get($product, 'image', ''))),
                'video_url' => trim((string) data_get($product, 'video_url', '')),
            ],
            'steps' => $steps,
            'faq' => $faq,
            'error_cases' => $errorCases,
            'updated_at' => (string) $updated,
        ];
    }

    private function resolveSource(): ?array
    {
        foreach ((array) config('ai_catalog.sources', []) as $source) {
            if (! is_array($source)) {
                continue;
            }
            if ((string) ($source['type'] ?? '') === 'product') {
                return $source;
            }
        }
        return null;
    }

    private function resolveDescription(Model $product, array $contentFields): string
    {
        $candidates = array_merge($contentFields, ['description', 'short_description', 'excerpt', 'content']);
        foreach ($candidates as $field) {
            $value = trim(strip_tags((string) data_get($product, $field, '')));
            if ($value !== '') {
                return Str::limit($value, 360);
            }
        }
        return '';
    }

    private function resolveShortDescription(Model $product, string $fallback): string
    {
        $value = trim(strip_tags((string) data_get($product, 'short_description', data_get($product, 'excerpt', ''))));
        if ($value !== '') {
            return Str::limit($value, 180);
        }
        return Str::limit($fallback, 180);
    }

    private function buildUrl(Model $product, array $source, string $slug): string
    {
        $direct = trim((string) data_get($product, 'url', ''));
        if ($direct !== '') {
            return $direct;
        }

        $prefix = trim((string) Arr::get($source, 'url_prefix', '/'));
        $prefix = '/' . trim($prefix, '/');
        if ($prefix === '//') {
            $prefix = '/';
        }

        if ($slug === '') {
            return $prefix;
        }

        if ($prefix === '/') {
            return '/' . ltrim($slug, '/');
        }

        return rtrim($prefix, '/') . '/' . ltrim($slug, '/');
    }

    private function priceLabel(string $catalogType, float $price): string
    {
        if (strtolower($catalogType) === 'free' || $price <= 0) {
            return 'Free';
        }
        return (string) number_format($price, 2, '.', '');
    }

    private function applyPublishFilter($builder, array $source): void
    {
        $publishField = (string) ($source['publish_field'] ?? '');
        $publishedValues = (array) ($source['published_values'] ?? []);
        if ($publishField !== '' && $publishedValues !== []) {
            $builder->whereIn($publishField, $publishedValues);
        }
    }
}
