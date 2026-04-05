<?php

use App\Http\Controllers\AiProxyController;
use App\Http\Controllers\InternalAiSearchController;
use App\Http\Controllers\InternalAiToolsController;
use Illuminate\Support\Facades\Route;

Route::post('/ai/chat', AiProxyController::class);

// Endpoint ini dipakai oleh FastAPI dari docker network internal.
// Lindungi dengan header X-Search-Key.
Route::get('/internal/ai/search', InternalAiSearchController::class);
Route::get('/internal/ai/tools', [InternalAiToolsController::class, 'index']);
Route::get('/internal/ai/tools/{slug}', [InternalAiToolsController::class, 'show']);
