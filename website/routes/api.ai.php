<?php

use App\Http\Controllers\AiProxyController;
use App\Http\Controllers\InternalAiSearchController;
use Illuminate\Support\Facades\Route;

Route::post('/ai/chat', AiProxyController::class);

// Endpoint ini dipakai oleh FastAPI dari docker network internal.
// Lindungi dengan header X-Search-Key.
Route::get('/internal/ai/search', InternalAiSearchController::class);
