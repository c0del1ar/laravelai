import fs from "node:fs/promises";
import path from "node:path";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const PLUGIN_ID = "xiaoan-dm-gate";
const DEFAULT_PREFIX = "/ia";
const DEFAULT_COOLDOWN_SECONDS = 60 * 60 * 7;
const ENGLISH_HINT_RE =
  /\b(hi|hello|hey|please|how|what|where|when|why|can|could|would|help|price|pricing|contact|tool|use)\b/i;

const escapeRegex = (value) => String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const parseBool = (value, fallback = false) => {
  const raw = String(value ?? "")
    .trim()
    .toLowerCase();
  if (["1", "true", "yes", "y", "on"].includes(raw)) {
    return true;
  }
  if (["0", "false", "no", "n", "off"].includes(raw)) {
    return false;
  }
  return fallback;
};

const parsePositiveInt = (value, fallback) => {
  const n = Number.parseInt(String(value ?? ""), 10);
  if (!Number.isFinite(n) || n <= 0) {
    return fallback;
  }
  return n;
};

const isLikelyEnglish = (text) => {
  const source = String(text || "").trim();
  if (!source) {
    return false;
  }
  if (ENGLISH_HINT_RE.test(source)) {
    return true;
  }
  const asciiLetters = source.match(/[a-z]/gi)?.length || 0;
  const letters = source.match(/[a-zA-Z\u00C0-\u024F]/g)?.length || 0;
  if (letters <= 0) {
    return false;
  }
  return asciiLetters / letters > 0.88;
};

const stripRequiredPrefix = (message, prefix) => {
  const raw = String(message || "");
  const required = String(prefix || "").trim();
  if (!required) {
    return { prefixed: true, stripped: raw.trim() };
  }

  const pattern = new RegExp(
    `(^|[\\s<>\\[\\]\\(\\){}.,;:|])${escapeRegex(required)}(?=$|[\\s:;,\\-–—.!?])`,
    "i",
  );
  const match = pattern.exec(raw);
  if (!match) {
    return { prefixed: false, stripped: raw.trim() };
  }

  const rest = raw.slice(match.index + match[0].length).replace(/^[\s:;,\-–—.!?]+/u, "").trim();
  return { prefixed: true, stripped: rest };
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

const resolveReminderText = (message, prefix) => {
  const key = isLikelyEnglish(message)
    ? "OPENCLAW_PREFIX_REMINDER_TEXT_EN"
    : "OPENCLAW_PREFIX_REMINDER_TEXT";
  const fallback = isLikelyEnglish(message)
    ? "Sorry, Ar gege is still busy right now. Please try again later, or chat with me first using prefix {prefix}."
    : "Maaf, Ar gege masih sibuk. Coba kabari lagi nanti atau ngobrol sama aku dulu pakai prefix {prefix} ya.";
  return String(process.env[key] || fallback).replace(/\{prefix\}/g, prefix);
};

const resolveStateFile = (api) => {
  const stateDir = api.runtime.state.resolveStateDir();
  return path.join(stateDir, "plugins", PLUGIN_ID, "sender-cooldown.json");
};

const makeEmptyState = () => ({ reminders: {} });

const safeMessagePreview = (text) => {
  const trimmed = String(text || "").trim();
  if (!trimmed) {
    return "";
  }
  return trimmed.length > 500 ? `${trimmed.slice(0, 500)}...` : trimmed;
};

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

export default definePluginEntry({
  id: PLUGIN_ID,
  name: "Xiao-An DM Gate",
  description: "Native DM prefix gate + cooldown reminder.",
  register(api) {
    const logger = api.logger;
    const stateFile = resolveStateFile(api);
    const requiredPrefix = String(process.env.OPENCLAW_REQUIRED_PREFIX || DEFAULT_PREFIX).trim() || DEFAULT_PREFIX;
    const cooldownSeconds = parsePositiveInt(
      process.env.OPENCLAW_PREFIX_REMINDER_COOLDOWN_SECONDS,
      DEFAULT_COOLDOWN_SECONDS,
    );
    const enabled = parseBool(process.env.OPENCLAW_NATIVE_DM_GATE_ENABLED, true);

    let loaded = false;
    let state = makeEmptyState();
    let stateMutex = Promise.resolve();

    const withStateLock = async (fn) => {
      const run = async () => fn();
      stateMutex = stateMutex.then(run, run);
      return stateMutex;
    };

    const loadState = async () => {
      if (loaded) {
        return;
      }
      loaded = true;
      try {
        const raw = await fs.readFile(stateFile, "utf8");
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object" && parsed.reminders && typeof parsed.reminders === "object") {
          state = parsed;
        }
      } catch (error) {
        const code = error && typeof error === "object" ? error.code : "";
        if (code !== "ENOENT") {
          logger.warn(`[${PLUGIN_ID}] failed to load state file: ${String(error)}`);
        }
      }
    };

    const saveState = async () => {
      const dir = path.dirname(stateFile);
      await fs.mkdir(dir, { recursive: true });
      const tmpFile = `${stateFile}.tmp`;
      await fs.writeFile(tmpFile, `${JSON.stringify(state)}\n`, "utf8");
      await fs.rename(tmpFile, stateFile);
    };

    const shouldSendReminder = async (senderKey) =>
      withStateLock(async () => {
        await loadState();
        const now = Math.floor(Date.now() / 1000);
        const previous = Number(state.reminders?.[senderKey] || 0);
        const staleBefore = now - Math.max(cooldownSeconds * 4, 60 * 60 * 24);
        let dirty = false;

        for (const [key, value] of Object.entries(state.reminders || {})) {
          const ts = Number(value || 0);
          if (!Number.isFinite(ts) || ts < staleBefore) {
            delete state.reminders[key];
            dirty = true;
          }
        }

        if (!Number.isFinite(previous) || previous <= 0 || now - previous >= cooldownSeconds) {
          state.reminders[senderKey] = now;
          dirty = true;
          if (dirty) {
            await saveState();
          }
          return true;
        }

        if (dirty) {
          await saveState();
        }
        return false;
      });

    const evaluateGate = async ({ message, senderId, channelId, phase }) => {
      if (!message) {
        return undefined;
      }

      if (message.startsWith("/") && !message.toLowerCase().startsWith(requiredPrefix.toLowerCase())) {
        return undefined;
      }

      const { prefixed, stripped } = stripRequiredPrefix(message, requiredPrefix);
      if (prefixed && stripped) {
        return undefined;
      }

      const reminder = resolveReminderText(message, requiredPrefix);
      if (prefixed && !stripped) {
        logger.info(
          `[${PLUGIN_ID}] gate phase=${phase} sender=${senderId} channel=${channelId} mode=reply reason=prefix-only`,
        );
        return { handled: true, reply: { text: reminder } };
      }

      const senderKey = `${channelId}:${senderId}`;
      const remindNow = await shouldSendReminder(senderKey);
      if (remindNow) {
        logger.info(
          `[${PLUGIN_ID}] gate phase=${phase} sender=${senderId} channel=${channelId} mode=reply reason=cooldown-first message="${safeMessagePreview(message)}"`,
        );
        return { handled: true, reply: { text: reminder } };
      }

      logger.info(
        `[${PLUGIN_ID}] gate phase=${phase} sender=${senderId} channel=${channelId} mode=silent reason=cooldown-active`,
      );
      return { handled: true, reply: { text: "NO_REPLY" } };
    };

    api.on("inbound_claim", async (event, ctx) => {
      if (!enabled) {
        return undefined;
      }
      if (!event || event.isGroup === true) {
        return undefined;
      }

      const message = extractInboundText(event);
      if (!message) {
        return undefined;
      }

      const senderId = resolveSenderId(event, ctx);
      const channelId = String(ctx?.channelId || event?.channel || "unknown-channel").trim();
      return await evaluateGate({ message, senderId, channelId, phase: "inbound_claim" });
    });

    api.on("before_agent_reply", async (event, ctx) => {
      if (!enabled) {
        return undefined;
      }

      const message = String(event?.cleanedBody || "").trim() || extractInboundText(event);
      if (!message) {
        logger.info(`[${PLUGIN_ID}] gate phase=before_agent_reply skipped reason=empty-message`);
        return undefined;
      }

      const channelId = String(ctx?.channelId || "unknown-channel").trim();
      if (channelId && channelId !== "whatsapp") {
        return undefined;
      }

      const senderId =
        String(ctx?.senderId || ctx?.sessionKey || ctx?.sessionId || "").trim() ||
        resolveSenderId(event, ctx);
      return await evaluateGate({
        message,
        senderId: senderId || "unknown-sender",
        channelId,
        phase: "before_agent_reply",
      });
    });
  },
});
