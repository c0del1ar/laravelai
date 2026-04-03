<?php

namespace App\Services;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Support\Collection;
use Illuminate\Support\Str;

class AiWebsiteSearchService
{
    public function search(string $query): array
    {
        $items = collect();

        foreach (config('ai_catalog.sources', []) as $source) {
            $items = $items->merge($this->searchSource($source, $query));
        }

        return $items
            ->sortByDesc('score')
            ->values()
            ->take(8)
            ->map(function (array $item) {
                unset($item['score']);
                return $item;
            })
            ->all();
    }

    protected function searchSource(array $source, string $query): array
    {
        $modelClass = $source['model'] ?? null;
        $titleField = $source['title_field'] ?? 'title';
        $slugField = $source['slug_field'] ?? 'slug';
        $contentFields = $source['content_fields'] ?? [];
        $limit = (int) ($source['limit'] ?? 4);
        $urlPrefix = rtrim((string) ($source['url_prefix'] ?? '/'), '/');
        $type = (string) ($source['type'] ?? 'page');

        if (! $modelClass || ! class_exists($modelClass)) {
            return [];
        }

        /** @var Model $model */
        $model = new $modelClass();

        $builder = $modelClass::query();

        $builder->where(function ($q) use ($titleField, $contentFields, $query) {
            $q->where($titleField, 'like', '%' . $query . '%');

            foreach ($contentFields as $field) {
                $q->orWhere($field, 'like', '%' . $query . '%');
            }
        });

        $records = $builder->limit($limit)->get();

        return $records->map(function ($record) use ($titleField, $slugField, $contentFields, $urlPrefix, $type, $query) {
            $title = (string) data_get($record, $titleField, 'Tanpa judul');
            $slug = (string) data_get($record, $slugField, '');
            $summary = $this->buildSummary($record, $contentFields);
            $score = $this->score($query, $title . ' ' . $summary);

            return [
                'type' => $type,
                'title' => $title,
                'url' => $this->makeUrl($urlPrefix, $slug),
                'summary' => $summary,
                'score' => $score,
            ];
        })->all();
    }

    protected function buildSummary($record, array $contentFields): string
    {
        foreach ($contentFields as $field) {
            $value = trim(strip_tags((string) data_get($record, $field, '')));
            if ($value !== '') {
                return Str::limit($value, 220);
            }
        }

        return '';
    }

    protected function makeUrl(string $prefix, string $slug): string
    {
        if ($slug === '') {
            return $prefix === '' ? '/' : $prefix;
        }

        return ($prefix === '' ? '' : $prefix) . '/' . ltrim($slug, '/');
    }

    protected function score(string $query, string $haystack): int
    {
        $queryTokens = collect(preg_split('/\s+/', Str::lower($query), -1, PREG_SPLIT_NO_EMPTY));
        $text = Str::lower($haystack);

        $score = 0;
        foreach ($queryTokens as $token) {
            if (Str::contains($text, $token)) {
                $score += 2;
            }
        }

        if (Str::contains($text, Str::lower($query))) {
            $score += 5;
        }

        return $score;
    }
}
