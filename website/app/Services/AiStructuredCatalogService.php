<?php

namespace App\Services;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Support\Arr;
use Illuminate\Support\Collection;
use Illuminate\Support\Str;

class AiStructuredCatalogService
{
    public function listCatalog(int $limit = 200, string $query = ''): array
    {
        $normalizedQuery = Str::lower(trim($query));
        $maxItems = max(1, min($limit, 500));

        $items = collect()
            ->merge($this->staticPages())
            ->merge($this->dynamicSources($normalizedQuery));

        $deduped = $items
            ->filter(fn ($item) => is_array($item))
            ->map(fn (array $item) => $this->normalizeCatalogItem($item))
            ->filter(fn (array $item) => $item['url'] !== '')
            ->unique(fn (array $item) => $item['url'])
            ->values();

        if ($normalizedQuery !== '') {
            $deduped = $deduped
                ->map(function (array $item) use ($normalizedQuery) {
                    $item['score'] = $this->score($normalizedQuery, $item);
                    return $item;
                })
                ->filter(fn (array $item) => (float) ($item['score'] ?? 0) > 0)
                ->sortByDesc('score')
                ->values();
        } else {
            $deduped = $deduped
                ->sortByDesc(function (array $item) {
                    return strtotime((string) ($item['updated_at'] ?? '1970-01-01T00:00:00+00:00')) ?: 0;
                })
                ->values();
        }

        return $deduped
            ->take($maxItems)
            ->map(function (array $item) {
                unset($item['score']);
                return $item;
            })
            ->all();
    }

    protected function staticPages(): Collection
    {
        $raw = config('ai_catalog.static_pages', []);
        if (! is_array($raw)) {
            return collect();
        }

        return collect($raw)->map(function ($item) {
            if (! is_array($item)) {
                return [];
            }

            return [
                'type' => (string) Arr::get($item, 'type', 'page'),
                'section' => (string) Arr::get($item, 'section', 'general'),
                'title' => (string) Arr::get($item, 'title', ''),
                'url' => $this->normalizeUrl((string) Arr::get($item, 'url', '')),
                'path' => $this->normalizePath((string) Arr::get($item, 'path', Arr::get($item, 'url', ''))),
                'summary' => trim((string) Arr::get($item, 'summary', '')),
                'keywords' => array_values(array_filter(array_map('strval', (array) Arr::get($item, 'keywords', [])))),
                'updated_at' => (string) Arr::get($item, 'updated_at', now()->toAtomString()),
            ];
        });
    }

    protected function dynamicSources(string $query): Collection
    {
        $items = collect();
        foreach ((array) config('ai_catalog.sources', []) as $source) {
            if (! is_array($source)) {
                continue;
            }
            $items = $items->merge($this->sourceItems($source, $query));
        }

        return $items;
    }

    protected function sourceItems(array $source, string $query): Collection
    {
        $modelClass = (string) ($source['model'] ?? '');
        if ($modelClass === '' || ! class_exists($modelClass) || ! is_subclass_of($modelClass, Model::class)) {
            return collect();
        }

        $titleField = (string) ($source['title_field'] ?? 'title');
        $slugField = (string) ($source['slug_field'] ?? 'slug');
        $contentFields = array_values(array_filter(array_map('strval', (array) ($source['content_fields'] ?? []))));
        $section = (string) ($source['section'] ?? ($source['type'] ?? 'general'));
        $type = (string) ($source['type'] ?? 'page');
        $urlPrefix = (string) ($source['url_prefix'] ?? '/');
        $updatedField = (string) ($source['updated_field'] ?? 'updated_at');
        $publishField = (string) ($source['publish_field'] ?? '');
        $publishedValues = (array) ($source['published_values'] ?? []);
        $limit = max(1, min((int) ($source['catalog_limit'] ?? $source['limit'] ?? 120), 300));

        $builder = $modelClass::query();

        if ($publishField !== '' && $publishedValues !== []) {
            $builder->whereIn($publishField, $publishedValues);
        }

        if ($query !== '') {
            $builder->where(function ($q) use ($titleField, $slugField, $contentFields, $query) {
                $q->where($titleField, 'like', '%' . $query . '%')
                    ->orWhere($slugField, 'like', '%' . $query . '%');

                foreach ($contentFields as $field) {
                    $q->orWhere($field, 'like', '%' . $query . '%');
                }
            });
        }

        $records = $builder->limit($limit)->get();

        return $records->map(function ($record) use (
            $type,
            $section,
            $titleField,
            $slugField,
            $contentFields,
            $urlPrefix,
            $updatedField
        ) {
            $title = trim((string) data_get($record, $titleField, ''));
            $slug = trim((string) data_get($record, $slugField, ''));
            $path = $this->buildPath($urlPrefix, $slug);
            $summary = $this->buildSummary($record, $contentFields);
            $updatedAt = data_get($record, $updatedField);
            $updated = method_exists($updatedAt, 'toAtomString') ? $updatedAt->toAtomString() : now()->toAtomString();

            return [
                'type' => $type,
                'section' => $section,
                'title' => $title !== '' ? $title : ($slug !== '' ? Str::headline($slug) : 'Untitled'),
                'url' => $this->normalizeUrl($path),
                'path' => $this->normalizePath($path),
                'summary' => $summary,
                'keywords' => $this->keywords($section, $title, $slug, $summary),
                'updated_at' => (string) $updated,
            ];
        });
    }

    protected function normalizeCatalogItem(array $item): array
    {
        $url = $this->normalizeUrl((string) ($item['url'] ?? ''));
        $path = $this->normalizePath((string) ($item['path'] ?? $url));
        $keywords = array_values(array_unique(array_filter(array_map('strval', (array) ($item['keywords'] ?? [])))));

        return [
            'type' => (string) ($item['type'] ?? 'page'),
            'section' => (string) ($item['section'] ?? 'general'),
            'title' => trim((string) ($item['title'] ?? '')) ?: $path,
            'url' => $url,
            'path' => $path,
            'summary' => Str::limit(trim((string) ($item['summary'] ?? '')), 280),
            'keywords' => $keywords,
            'updated_at' => (string) ($item['updated_at'] ?? now()->toAtomString()),
        ];
    }

    protected function buildSummary($record, array $contentFields): string
    {
        foreach ($contentFields as $field) {
            $value = trim(strip_tags((string) data_get($record, $field, '')));
            if ($value !== '') {
                return Str::limit($value, 280);
            }
        }

        return '';
    }

    protected function buildPath(string $prefix, string $slug): string
    {
        $cleanPrefix = '/' . trim($prefix, '/');
        if ($cleanPrefix === '//') {
            $cleanPrefix = '/';
        }

        if ($slug === '') {
            return $cleanPrefix;
        }

        if ($cleanPrefix === '/') {
            return '/' . ltrim($slug, '/');
        }

        return rtrim($cleanPrefix, '/') . '/' . ltrim($slug, '/');
    }

    protected function normalizeUrl(string $url): string
    {
        $trimmed = trim($url);
        if ($trimmed === '') {
            return '';
        }
        if (Str::startsWith($trimmed, ['http://', 'https://'])) {
            return $trimmed;
        }
        return $this->normalizePath($trimmed);
    }

    protected function normalizePath(string $path): string
    {
        $value = trim($path);
        if ($value === '') {
            return '/';
        }
        if (Str::startsWith($value, ['http://', 'https://'])) {
            $parsed = parse_url($value, PHP_URL_PATH);
            $value = is_string($parsed) ? $parsed : '/';
        }
        $normalized = '/' . ltrim($value, '/');
        if ($normalized !== '/' && Str::endsWith($normalized, '/')) {
            return rtrim($normalized, '/');
        }
        return $normalized;
    }

    protected function keywords(string $section, string $title, string $slug, string $summary): array
    {
        $parts = collect([$section, $title, $slug, $summary])
            ->map(fn ($v) => Str::lower((string) $v))
            ->map(fn ($v) => preg_replace('/[^a-z0-9\-_ ]+/', ' ', $v) ?: '')
            ->flatMap(fn ($v) => preg_split('/\s+/', trim($v), -1, PREG_SPLIT_NO_EMPTY) ?: [])
            ->filter(fn ($v) => strlen((string) $v) >= 3)
            ->map(fn ($v) => str_replace('-', ' ', (string) $v))
            ->flatMap(fn ($v) => preg_split('/\s+/', trim($v), -1, PREG_SPLIT_NO_EMPTY) ?: [])
            ->filter(fn ($v) => strlen((string) $v) >= 3)
            ->unique()
            ->values();

        return $parts->take(20)->all();
    }

    protected function score(string $query, array $item): float
    {
        $text = Str::lower(implode(' ', [
            (string) ($item['title'] ?? ''),
            (string) ($item['section'] ?? ''),
            (string) ($item['summary'] ?? ''),
            implode(' ', (array) ($item['keywords'] ?? [])),
            (string) ($item['path'] ?? ''),
            (string) ($item['url'] ?? ''),
        ]));

        $tokens = array_values(array_filter(preg_split('/\s+/', $query, -1, PREG_SPLIT_NO_EMPTY) ?: []));
        if ($tokens === []) {
            return 0.0;
        }

        $score = 0.0;
        foreach ($tokens as $token) {
            if (Str::contains($text, $token)) {
                $score += 1.5;
            }
            if (Str::contains((string) ($item['title'] ?? ''), $token)) {
                $score += 2.2;
            }
            if (Str::contains((string) ($item['section'] ?? ''), $token)) {
                $score += 1.2;
            }
        }

        if (Str::contains($text, $query)) {
            $score += 3.0;
        }

        return $score;
    }
}
