<?php

namespace App\Services;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Support\Arr;
use Illuminate\Support\Facades\Log;

class AiAutoIndexObserverRegistrar
{
    public function __construct(
        private readonly AiIndexBridgeService $indexBridge,
    ) {
    }

    public function register(): void
    {
        if (! (bool) config('services.ai.auto_index_enabled', true)) {
            return;
        }

        foreach ((array) config('ai_catalog.sources', []) as $source) {
            if (! is_array($source)) {
                continue;
            }

            $modelClass = (string) ($source['model'] ?? '');
            if ($modelClass === '' || ! class_exists($modelClass) || ! is_subclass_of($modelClass, Model::class)) {
                continue;
            }

            $modelClass::saved(function (Model $model) use ($source) {
                $this->handleSaved($model, $source);
            });

            $modelClass::deleted(function (Model $model) use ($source) {
                $this->handleDeleted($model, $source);
            });

            if (in_array('Illuminate\\Database\\Eloquent\\SoftDeletes', class_uses_recursive($modelClass), true)) {
                $modelClass::restored(function (Model $model) use ($source) {
                    $this->handleRestored($model, $source);
                });
                $modelClass::forceDeleted(function (Model $model) use ($source) {
                    $this->handleDeleted($model, $source);
                });
            }
        }
    }

    protected function handleSaved(Model $model, array $source): void
    {
        if (! $this->shouldAutoIndexSource($source)) {
            return;
        }

        if (! $model->wasRecentlyCreated && ! $this->hasRelevantChanges($model, $source)) {
            return;
        }

        if (! $this->shouldSyncForPublishState($model, $source)) {
            return;
        }

        $paths = [];
        $current = $this->buildPath($model, $source, false);
        if ($current !== '') {
            $paths[] = $current;
        }

        $slugField = (string) ($source['slug_field'] ?? 'slug');
        if ($model->wasChanged($slugField)) {
            $old = $this->buildPath($model, $source, true);
            if ($old !== '') {
                $paths[] = $old;
            }
        }

        $publishField = (string) ($source['publish_field'] ?? '');
        if ($publishField !== '' && $model->wasChanged($publishField)) {
            $old = $this->buildPath($model, $source, true);
            if ($old !== '') {
                $paths[] = $old;
            }
        }

        $this->dispatchPaths($paths);
    }

    protected function handleDeleted(Model $model, array $source): void
    {
        if (! $this->shouldAutoIndexSource($source)) {
            return;
        }

        if (! $this->shouldSyncForDeletedPublishState($model, $source)) {
            return;
        }

        $old = $this->buildPath($model, $source, true);
        $this->dispatchPaths([$old]);
    }

    protected function handleRestored(Model $model, array $source): void
    {
        if (! $this->shouldAutoIndexSource($source)) {
            return;
        }

        if (! $this->shouldSyncForPublishState($model, $source)) {
            return;
        }

        $current = $this->buildPath($model, $source, false);
        $this->dispatchPaths([$current]);
    }

    protected function shouldAutoIndexSource(array $source): bool
    {
        return (bool) ($source['auto_index'] ?? true);
    }

    protected function shouldSyncForPublishState(Model $model, array $source): bool
    {
        $publishField = (string) ($source['publish_field'] ?? '');
        if ($publishField === '') {
            return true;
        }

        $current = data_get($model, $publishField);
        $original = method_exists($model, 'getOriginal') ? $model->getOriginal($publishField) : null;
        return $this->isPublishedValue($current, $source) || $this->isPublishedValue($original, $source);
    }

    protected function shouldSyncForDeletedPublishState(Model $model, array $source): bool
    {
        $publishField = (string) ($source['publish_field'] ?? '');
        if ($publishField === '') {
            return true;
        }
        $original = method_exists($model, 'getOriginal') ? $model->getOriginal($publishField) : null;
        return $this->isPublishedValue($original, $source);
    }

    protected function isPublishedValue(mixed $value, array $source): bool
    {
        $publishedValues = $source['published_values'] ?? [1, '1', true, 'true', 'published', 'active', 'public', 'online'];
        foreach ((array) $publishedValues as $candidate) {
            if ((string) $value === (string) $candidate) {
                return true;
            }
        }

        return false;
    }

    protected function hasRelevantChanges(Model $model, array $source): bool
    {
        if (! method_exists($model, 'wasChanged')) {
            return true;
        }

        $fields = array_filter(array_unique(array_merge(
            [
                (string) ($source['slug_field'] ?? 'slug'),
                (string) ($source['title_field'] ?? 'title'),
                (string) ($source['publish_field'] ?? ''),
            ],
            array_map(static fn ($field) => (string) $field, (array) ($source['content_fields'] ?? []))
        )));

        if ($fields === []) {
            return true;
        }

        foreach ($fields as $field) {
            if ($model->wasChanged($field)) {
                return true;
            }
        }

        return false;
    }

    protected function buildPath(Model $model, array $source, bool $useOriginal): string
    {
        $slugField = (string) ($source['slug_field'] ?? 'slug');
        $slug = '';
        if ($useOriginal && method_exists($model, 'getOriginal')) {
            $slug = trim((string) $model->getOriginal($slugField, ''));
        }
        if ($slug === '') {
            $slug = trim((string) data_get($model, $slugField, ''));
        }

        $prefix = trim((string) Arr::get($source, 'url_prefix', '/'));
        $prefix = $prefix === '' ? '/' : $prefix;
        $normalizedPrefix = '/' . trim($prefix, '/');
        if ($normalizedPrefix === '//') {
            $normalizedPrefix = '/';
        }
        if ($normalizedPrefix !== '/' && str_ends_with($normalizedPrefix, '/')) {
            $normalizedPrefix = rtrim($normalizedPrefix, '/');
        }

        if ($slug === '') {
            return $normalizedPrefix;
        }

        if ($normalizedPrefix === '/') {
            return '/' . ltrim($slug, '/');
        }

        return $normalizedPrefix . '/' . ltrim($slug, '/');
    }

    /**
     * @param  array<int, string>  $paths
     */
    protected function dispatchPaths(array $paths): void
    {
        $clean = array_values(array_unique(array_filter(array_map(static fn ($path) => trim((string) $path), $paths))));
        if ($clean === []) {
            return;
        }

        try {
            $this->indexBridge->push($clean, []);
        } catch (\Throwable $e) {
            Log::warning('AI auto-index dispatch failed', [
                'paths' => $clean,
                'error' => $e->getMessage(),
            ]);
        }
    }
}
