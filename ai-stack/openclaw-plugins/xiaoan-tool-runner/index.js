import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import fs from "node:fs/promises";
import path from "node:path";

const PLUGIN_ID = "xiaoan-tool-runner";
const DEFAULT_PREFIX = "/tool";
const DEFAULT_RUNNER_URL = "http://cli_tool_runner:37000";
const DEFAULT_TIMEOUT_MS = 240_000;
const MAX_REPLY_CHARS = 3000;
const MEDIA_CACHE_DIR = "/tmp/openclaw/xiaoan-tool-runner";

const trimTrailingSlash = (value) => String(value || "").replace(/\/+$/u, "");

const extractInboundText = (event) => {
  const candidates = [
    event?.cleanedBody,
    event?.bodyForAgent,
    event?.body,
    event?.content,
    event?.message?.body,
    event?.message?.content,
    event?.message?.text,
  ];
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
    if (value && typeof value === "object") {
      const nested = value.text || value.content || value.body;
      if (typeof nested === "string" && nested.trim()) {
        return nested.trim();
      }
    }
  }
  return "";
};

const resolveSenderId = (event, ctx) => {
  const senderId = String(event?.senderId || ctx?.senderId || "").trim();
  if (senderId) {
    return senderId;
  }
  const conversationId = String(event?.conversationId || ctx?.conversationId || "").trim();
  if (conversationId) {
    return conversationId;
  }
  return "unknown-sender";
};

const resolveRequestId = (event, ctx) =>
  String(
    event?.messageId ||
      event?.id ||
      event?.message?.id ||
      ctx?.messageId ||
      ctx?.sessionId ||
      ctx?.sessionKey ||
      "",
  ).trim();

const isToolCommand = (message, prefix) => {
  const raw = String(message || "").trim();
  const required = String(prefix || "").trim();
  if (!raw || !required) {
    return false;
  }
  return raw.toLowerCase() === required.toLowerCase() || raw.toLowerCase().startsWith(`${required.toLowerCase()} `);
};

const stripPrefix = (message, prefix) => String(message || "").trim().slice(String(prefix || "").trim().length).trim();

const splitCommandLine = (input) => {
  const out = [];
  let current = "";
  let quote = "";
  let escaped = false;

  for (const ch of String(input || "")) {
    if (escaped) {
      current += ch;
      escaped = false;
      continue;
    }
    if (ch === "\\") {
      escaped = true;
      continue;
    }
    if (quote) {
      if (ch === quote) {
        quote = "";
      } else {
        current += ch;
      }
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      continue;
    }
    if (/\s/u.test(ch)) {
      if (current) {
        out.push(current);
        current = "";
      }
      continue;
    }
    current += ch;
  }

  if (escaped) {
    current += "\\";
  }
  if (current) {
    out.push(current);
  }
  return out;
};

const parseKeyValueArgs = (tokens) => {
  const args = {};
  const positional = [];

  for (const token of tokens) {
    const normalized = token.startsWith("--") ? token.slice(2) : token;
    const eq = normalized.indexOf("=");
    if (eq > 0) {
      const key = normalized.slice(0, eq).trim();
      const value = normalized.slice(eq + 1).trim();
      if (/^[a-zA-Z0-9_]+$/u.test(key)) {
        args[key] = value;
        continue;
      }
    }
    positional.push(token);
  }

  return { args, positional };
};

const safeSlug = (value) => {
  const slug = String(value || "")
    .trim()
    .toLowerCase();
  return /^[a-z0-9][a-z0-9_-]{0,63}$/u.test(slug) ? slug : "";
};

const truncate = (value, max = MAX_REPLY_CHARS) => {
  const text = String(value || "").trim();
  if (text.length <= max) {
    return text;
  }
  return `${text.slice(0, max - 20).trim()}...\n[truncated]`;
};

const encodePathSegments = (value) =>
  String(value || "")
    .split("/")
    .filter(Boolean)
    .map((part) => encodeURIComponent(part))
    .join("/");

const safeFileName = (value, fallback = "tool-output") => {
  const name = path
    .basename(String(value || fallback))
    .replace(/[^\w.\-()[\] ]+/gu, "_")
    .replace(/\s+/gu, " ")
    .trim();
  return (name || fallback).slice(0, 180);
};

const formatToolList = (tools, prefix) => {
  if (!Array.isArray(tools) || tools.length === 0) {
    return `Belum ada tool yang tersedia.`;
  }

  const lines = tools.slice(0, 20).map((tool) => {
    const required = Array.isArray(tool.required) && tool.required.length > 0 ? ` <${tool.required.join("> <")}>` : "";
    const description = tool.description ? ` - ${tool.description}` : "";
    return `${prefix} ${tool.slug}${required}${description}`;
  });

  return [`Tool tersedia:`, ...lines].join("\n");
};

const resolveFileMediaUrl = (file, runnerUrl) => {
  const explicitUrl = String(file?.url || "").trim();
  if (/^https?:\/\//iu.test(explicitUrl)) {
    return explicitUrl;
  }

  const rawPath = String(file?.path || "").trim();
  if (/^https?:\/\//iu.test(rawPath)) {
    return rawPath;
  }

  const appPrefix = "/app/";
  const relPath = rawPath.startsWith(appPrefix) ? rawPath.slice(appPrefix.length) : rawPath.replace(/^\/+/u, "");
  if (!relPath.startsWith("data/")) {
    return "";
  }
  return `${runnerUrl}/files/${encodePathSegments(relPath)}`;
};

const isWhatsAppVoiceFile = (file) => String(file?.variant || "").trim() === "whatsapp_voice";

const documentNameRe = /\.(csv|doc|docx|json|md|pdf|ppt|pptx|rtf|txt|xls|xlsx|zip|rar|7z|mp3)$/iu;

const isDocumentFile = (file) => {
  const variant = String(file?.variant || "").trim();
  const mime = String(file?.mime || "").trim().toLowerCase();
  const name = String(file?.name || file?.path || "").trim();
  if (variant === "download") {
    return true;
  }
  if (mime === "audio/mpeg" || mime === "application/pdf" || mime === "application/octet-stream") {
    return true;
  }
  if (mime.startsWith("text/")) {
    return true;
  }
  if (mime.startsWith("application/vnd.openxmlformats-officedocument.")) {
    return true;
  }
  if (mime.startsWith("application/vnd.ms-")) {
    return true;
  }
  return documentNameRe.test(name);
};

const isLikelyProblematicWhatsAppAudio = (file) => {
  const mime = String(file?.mime || "").trim().toLowerCase();
  const name = String(file?.name || file?.path || "").trim().toLowerCase();
  return mime === "audio/mpeg" || name.endsWith(".mp3");
};

const resolveRunFileSources = (payload, runnerUrl) => {
  if (!payload?.ok || !Array.isArray(payload.files)) {
    return [];
  }
  return payload.files
    .slice(0, 10)
    .map((file) => ({ file, url: resolveFileMediaUrl(file, runnerUrl) }))
    .filter((source) => source.url);
};

const resolveRunDocumentSources = (payload, runnerUrl) => {
  const sources = resolveRunFileSources(payload, runnerUrl).filter((source) => isDocumentFile(source.file));
  const downloadSources = sources.filter((source) => String(source.file?.variant || "").trim() === "download");
  return downloadSources.length > 0 ? downloadSources : sources;
};

const resolveRunMediaSources = (payload, runnerUrl) => {
  const sources = resolveRunFileSources(payload, runnerUrl).filter((source) => !isDocumentFile(source.file));
  const whatsappVoiceSources = sources.filter((source) => isWhatsAppVoiceFile(source.file));
  if (whatsappVoiceSources.length > 0) {
    return whatsappVoiceSources;
  }
  return sources.filter((source) => !isLikelyProblematicWhatsAppAudio(source.file));
};

const fetchMediaBuffer = async (url, timeoutMs) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`media fetch failed with status ${response.status}`);
    }
    return Buffer.from(await response.arrayBuffer());
  } finally {
    clearTimeout(timer);
  }
};

const cacheSources = async ({ sources, requestId, logger, label }) => {
  if (sources.length === 0) {
    return [];
  }

  await fs.mkdir(MEDIA_CACHE_DIR, { recursive: true, mode: 0o700 });
  const cached = [];
  for (let index = 0; index < sources.length; index += 1) {
    const { file = {}, url: sourceUrl } = sources[index];
    try {
      const buffer = await fetchMediaBuffer(sourceUrl, 60_000);
      const name = safeFileName(file.name || file.path, `tool-output-${index + 1}`);
      const outputPath = path.join(MEDIA_CACHE_DIR, `${Date.now()}-${safeFileName(requestId || "request")}-${index}-${name}`);
      await fs.writeFile(outputPath, buffer, { mode: 0o600 });
      cached.push({ file, path: outputPath });
    } catch (error) {
      logger?.warn?.(`[${PLUGIN_ID}] ${label} cache failed url=${sourceUrl}: ${String(error)}`);
    }
  }
  return cached;
};

const cacheRunMediaFiles = async ({ payload, runnerUrl, requestId, logger }) => {
  const cached = await cacheSources({
    sources: resolveRunMediaSources(payload, runnerUrl),
    requestId,
    logger,
    label: "media",
  });
  return cached.map((entry) => entry.path);
};

const cacheRunDocuments = async ({ payload, runnerUrl, requestId, logger }) => {
  const cached = await cacheSources({
    sources: resolveRunDocumentSources(payload, runnerUrl),
    requestId,
    logger,
    label: "document",
  });
  return cached.map(({ file, path: cachedPath }) => ({
    url: cachedPath,
    fileName: safeFileName(file.name || file.path || path.basename(cachedPath), path.basename(cachedPath)),
    mimetype: String(file.mime || "").trim() || undefined,
  }));
};

const formatRunResponse = (payload, options = {}) => {
  if (!payload || typeof payload !== "object") {
    return "Tool selesai, tapi response tidak valid.";
  }

  if (!payload.ok) {
    const detail = payload.error || payload.stderr || payload.stdout || "unknown error";
    return truncate(`Tool gagal: ${detail}`);
  }

  const parts = [];
  if (payload.message) {
    parts.push(String(payload.message));
  } else if (payload.stdout) {
    parts.push(String(payload.stdout));
  } else {
    parts.push("Tool selesai.");
  }

  if (options.includeFileLines !== false && Array.isArray(payload.files) && payload.files.length > 0) {
    const fileLines = payload.files
      .slice(0, 10)
      .map((file) => {
        const name = file?.name || file?.path || "file";
        const caption = file?.caption ? ` - ${file.caption}` : "";
        return `File: ${name}${caption}`;
      })
      .join("\n");
    parts.push(fileLines);
  }

  return truncate(parts.filter(Boolean).join("\n"));
};

const buildRunReply = async ({ payload, runnerUrl, requestId, logger }) => {
  const documents = await cacheRunDocuments({ payload, runnerUrl, requestId, logger });
  const mediaUrls = documents.length === 0 ? await cacheRunMediaFiles({ payload, runnerUrl, requestId, logger }) : [];
  const text = formatRunResponse(payload, { includeFileLines: documents.length === 0 && mediaUrls.length === 0 });
  if (documents.length === 0 && mediaUrls.length === 0) {
    return { text };
  }
  return { text, ...(documents.length > 0 ? { documents } : {}), ...(mediaUrls.length > 0 ? { mediaUrls } : {}) };
};

const fetchJSON = async ({ url, method = "GET", body, timeoutMs }) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const headers = {};
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
    }

    const response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const text = await response.text();
    let parsed = {};
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = { error: text };
      }
    }
    return { ok: response.ok, status: response.status, data: parsed };
  } finally {
    clearTimeout(timer);
  }
};

export default definePluginEntry({
  id: PLUGIN_ID,
  name: "Xiao-An Tool Runner",
  description: "Routes /tool commands to cli-stack tool runner.",
  register(api) {
    const logger = api.logger;
    const enabled = true;
    const prefix = DEFAULT_PREFIX;
    const runnerUrl = trimTrailingSlash(DEFAULT_RUNNER_URL);
    const timeoutMs = DEFAULT_TIMEOUT_MS;

    const getTools = async () => {
      const result = await fetchJSON({
        url: `${runnerUrl}/tools`,
        timeoutMs: Math.min(timeoutMs, 30_000),
      });
      if (!result.ok) {
        throw new Error(result.data?.error || `tool list failed with status ${result.status}`);
      }
      return Array.isArray(result.data?.items) ? result.data.items : [];
    };

    const runTool = async ({ tool, args, requestId }) => {
      const result = await fetchJSON({
        url: `${runnerUrl}/run`,
        method: "POST",
        timeoutMs,
        body: {
          tool,
          args,
          request_id: requestId,
        },
      });
      return result.data;
    };

    const buildArgs = async ({ slug, rawArgs, tokens }) => {
      const { args, positional } = parseKeyValueArgs(tokens);
      if (Object.keys(args).length > 0) {
        return args;
      }

      const tools = await getTools();
      const toolInfo = tools.find((item) => item?.slug === slug);
      const required = Array.isArray(toolInfo?.required) ? toolInfo.required : [];
      if (required.length === 1) {
        return { [required[0]]: rawArgs.trim() };
      }
      if (positional.length === 1) {
        return { value: positional[0] };
      }
      return {};
    };

    const handleToolCommand = async ({ message, event, ctx }) => {
      const senderId = resolveSenderId(event, ctx);
      const channelId = String(ctx?.channelId || event?.channel || "unknown-channel").trim();
      const requestId = resolveRequestId(event, ctx);
      const body = stripPrefix(message, prefix);

      if (!body) {
        try {
          const tools = await getTools();
          return { handled: true, reply: { text: formatToolList(tools, prefix) } };
        } catch (error) {
          logger.warn(`[${PLUGIN_ID}] list failed sender=${senderId} channel=${channelId}: ${String(error)}`);
          return { handled: true, reply: { text: "Tool runner belum tersedia. Coba lagi nanti." } };
        }
      }

      const tokens = splitCommandLine(body);
      const slug = safeSlug(tokens.shift());
      if (!slug) {
        return { handled: true, reply: { text: `Format: ${prefix} <tool> <argumen>` } };
      }

      const rawArgs = body.slice(body.indexOf(slug) + slug.length).trim();
      try {
        const args = await buildArgs({ slug, rawArgs, tokens });
        logger.info(
          `[${PLUGIN_ID}] run sender=${senderId} channel=${channelId} tool=${slug} request=${requestId || "-"}`,
        );
        const payload = await runTool({ tool: slug, args, requestId });
        return { handled: true, reply: await buildRunReply({ payload, runnerUrl, requestId, logger }) };
      } catch (error) {
        logger.warn(`[${PLUGIN_ID}] run failed sender=${senderId} channel=${channelId} tool=${slug}: ${String(error)}`);
        return { handled: true, reply: { text: "Tool gagal dijalankan. Coba lagi nanti atau cek format command." } };
      }
    };

    api.on("inbound_claim", async (event, ctx) => {
      if (!enabled) {
        return undefined;
      }

      const message = extractInboundText(event);
      if (!isToolCommand(message, prefix)) {
        return undefined;
      }

      return await handleToolCommand({ message, event, ctx });
    });

    api.on("before_agent_reply", async (event, ctx) => {
      if (!enabled) {
        return undefined;
      }

      const message = String(event?.cleanedBody || "").trim() || extractInboundText(event);
      if (!isToolCommand(message, prefix)) {
        return undefined;
      }

      return await handleToolCommand({ message, event, ctx });
    });
  },
});
