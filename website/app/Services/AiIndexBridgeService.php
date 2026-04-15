<?php

namespace App\Services;

use Illuminate\Http\Client\ConnectionException;
use Illuminate\Support\Facades\Http;
use Symfony\Component\HttpFoundation\Response;

class AiIndexBridgeService
{
    public function push(array $paths = [], array $urls = []): array
    {
        if (! (bool) config('services.ai.auto_index_enabled', true)) {
            return [
                'status' => Response::HTTP_OK,
                'body' => ['ok' => true, 'skipped' => 'auto-index disabled'],
            ];
        }

        $normalizedPaths = $this->normalizePaths($paths);
        $normalizedUrls = $this->normalizeUrls($urls);
        if ($normalizedPaths === [] && $normalizedUrls === []) {
            return [
                'status' => Response::HTTP_OK,
                'body' => ['ok' => true, 'skipped' => 'no paths/urls'],
            ];
        }

        $baseUrl = rtrim((string) config('services.ai.base_url', ''), '/');
        $endpoint = (string) config('services.ai.index_endpoint', '/admin/index/events');
        $timeout = (int) config('services.ai.auto_index_timeout', config('services.ai.timeout', 20));
        $indexKey = (string) config('services.ai.internal_index_key', '');

        if ($baseUrl === '') {
            return [
                'status' => Response::HTTP_BAD_REQUEST,
                'body' => ['ok' => false, 'error' => 'AI base URL not configured'],
            ];
        }

        try {
            $response = Http::timeout($timeout)
                ->acceptJson()
                ->withHeaders([
                    'X-Index-Key' => $indexKey,
                ])
                ->post($baseUrl . $endpoint, [
                    'paths' => $normalizedPaths,
                    'urls' => $normalizedUrls,
                ]);

            return [
                'status' => $response->status(),
                'body' => $response->json() ?? ['ok' => false],
            ];
        } catch (ConnectionException $e) {
            return [
                'status' => Response::HTTP_BAD_GATEWAY,
                'body' => [
                    'ok' => false,
                    'error' => 'AI index service unavailable',
                    'detail' => $e->getMessage(),
                ],
            ];
        }
    }

    /**
     * @param  array<int, string>  $paths
     * @return array<int, string>
     */
    protected function normalizePaths(array $paths): array
    {
        $normalized = [];
        foreach ($paths as $path) {
            $value = trim((string) $path);
            if ($value === '') {
                continue;
            }
            if (str_starts_with($value, 'http://') || str_starts_with($value, 'https://')) {
                $parsedPath = parse_url($value, PHP_URL_PATH);
                $value = is_string($parsedPath) ? $parsedPath : '/';
            }
            $value = '/' . ltrim($value, '/');
            if ($value !== '/' && str_ends_with($value, '/')) {
                $value = rtrim($value, '/');
            }
            $normalized[] = $value;
        }

        return array_values(array_unique($normalized));
    }

    /**
     * @param  array<int, string>  $urls
     * @return array<int, string>
     */
    protected function normalizeUrls(array $urls): array
    {
        $normalized = [];
        foreach ($urls as $url) {
            $value = trim((string) $url);
            if ($value === '') {
                continue;
            }
            $normalized[] = $value;
        }

        return array_values(array_unique($normalized));
    }
}
