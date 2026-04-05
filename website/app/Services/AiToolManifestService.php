<?php

namespace App\Services;

use App\Models\Tool;

class AiToolManifestService
{
    public function listTools(int $limit = 100): array
    {
        $tools = Tool::query()
            ->where('is_active', true)
            ->orderBy('sort_order')
            ->orderBy('name')
            ->limit(max(1, min($limit, 300)))
            ->get();

        return $tools->map(fn (Tool $tool) => $this->buildManifest($tool))->values()->all();
    }

    public function getToolBySlug(string $slug): ?array
    {
        $tool = Tool::query()
            ->where('slug', $slug)
            ->where('is_active', true)
            ->first();

        if (! $tool) {
            return null;
        }

        return $this->buildManifest($tool);
    }

    public function buildManifest(Tool $tool): array
    {
        $schema = is_array($tool->input_schema) ? $tool->input_schema : [];
        $fields = is_array($schema['fields'] ?? null) ? $schema['fields'] : [];
        $settings = is_array($tool->settings) ? $tool->settings : [];

        $fieldSpecs = array_values(array_filter(array_map(function (array $field) {
            $key = (string) ($field['key'] ?? '');
            if ($key === '') {
                return null;
            }

            $rawOptions = is_array($field['options'] ?? null) ? $field['options'] : [];
            $options = array_values(array_filter(array_map(function ($option) {
                if (! is_array($option)) {
                    return null;
                }

                return [
                    'value' => (string) ($option['value'] ?? ''),
                    'label' => (string) ($option['label'] ?? ''),
                    'hint' => (string) ($option['hint'] ?? ''),
                ];
            }, $rawOptions)));

            return [
                'key' => $key,
                'label' => (string) ($field['label'] ?? $key),
                'type' => (string) ($field['type'] ?? 'text'),
                'required' => (bool) ($field['required'] ?? false),
                'placeholder' => (string) ($field['placeholder'] ?? ''),
                'hint' => (string) ($field['hint'] ?? ''),
                'default' => $field['default'] ?? null,
                'trigger_estimate' => (bool) ($field['trigger_estimate'] ?? false),
                'accept' => (string) ($field['accept'] ?? ''),
                'unit' => (string) ($field['unit'] ?? ''),
                'options' => $options,
            ];
        }, $fields)));

        $steps = $this->buildSteps($tool, $fieldSpecs, $settings);

        $outputExplained = (string) data_get($settings, 'ai_manifest.output_explained', '');
        if ($outputExplained === '') {
            $outputExplained = 'After execution, review the generated result area. For noredirect, output usually includes iframe preview, source code, and raw HTML.';
        }

        $faq = data_get($settings, 'ai_manifest.faq', []);
        if (! is_array($faq) || $faq === []) {
            $faq = [
                [
                    'q' => 'Kenapa tool tidak jalan?',
                    'a' => 'Pastikan semua field wajib terisi dan format input valid.',
                ],
                [
                    'q' => 'Kenapa hasil kosong?',
                    'a' => 'Coba input lain, pastikan URL/teks target benar, lalu jalankan ulang.',
                ],
            ];
        }

        $errorCases = data_get($settings, 'ai_manifest.error_cases', []);
        if (! is_array($errorCases) || $errorCases === []) {
            $errorCases = [
                'Validation failed: field wajib belum terisi atau format tidak valid.',
                'Insufficient tokens: top up token atau gunakan tool gratis.',
                'Tool processing failed: coba lagi dengan input lebih sederhana.',
            ];
        }

        return [
            'type' => 'tool',
            'slug' => (string) $tool->slug,
            'name' => (string) $tool->name,
            'url' => (string) $tool->url,
            'description' => (string) ($tool->description ?? ''),
            'category' => (string) ($tool->category?->name ?? ''),
            'pricing' => [
                'pricing_type' => (string) ($tool->pricing_type ?? ''),
                'price_label' => (string) ($tool->price_label ?? ''),
                'token_unit' => (string) ($tool->token_unit ?? ''),
                'token_cost' => (int) ($tool->token_cost ?? 0),
                'token_rate' => (int) ($tool->token_rate ?? 0),
            ],
            'input_schema' => [
                'fields' => $fieldSpecs,
            ],
            'steps' => $steps,
            'output_explained' => $outputExplained,
            'faq' => $faq,
            'error_cases' => $errorCases,
            'updated_at' => optional($tool->updated_at)->toAtomString(),
        ];
    }

    private function buildSteps(Tool $tool, array $fields, array $settings): array
    {
        $customSteps = data_get($settings, 'ai_manifest.steps', []);
        if (is_array($customSteps) && $customSteps !== []) {
            return array_values(array_map(fn ($v) => (string) $v, $customSteps));
        }

        $steps = [
            'Open the tool page: ' . $tool->url,
        ];

        if ($fields === []) {
            $steps[] = 'No input field is required. Click execute directly.';
        } else {
            foreach ($fields as $idx => $field) {
                $requiredText = $field['required'] ? ' (required)' : ' (optional)';
                $hint = trim((string) ($field['hint'] ?? ''));
                $label = trim((string) ($field['label'] ?? $field['key']));
                $line = 'Fill field #' . ($idx + 1) . ': ' . $label . $requiredText;
                if ($hint !== '') {
                    $line .= ' — ' . $hint;
                }
                $steps[] = $line;
            }
        }

        $steps[] = 'Click execute/process to run the tool.';
        $steps[] = 'Review the output section and copy/download the result as needed.';

        return $steps;
    }
}
