import fs from "node:fs";
import path from "node:path";

const appRoot = "/app";

const sourceHelper = `type DocumentAttachment = {
  url: string;
  fileName?: string;
  mimetype?: string;
  caption?: string;
};

function normalizeDocumentAttachment(entry: unknown): DocumentAttachment | undefined {
  if (typeof entry === "string" && entry.trim()) {
    return { url: entry.trim() };
  }
  if (!entry || typeof entry !== "object") {
    return undefined;
  }
  const record = entry as Record<string, unknown>;
  const rawUrl = record.url ?? record.documentUrl ?? record.mediaUrl ?? record.path;
  if (typeof rawUrl !== "string" || !rawUrl.trim()) {
    return undefined;
  }
  const document: DocumentAttachment = { url: rawUrl.trim() };
  const rawFileName = record.fileName ?? record.name;
  if (typeof rawFileName === "string" && rawFileName.trim()) {
    document.fileName = rawFileName.trim();
  }
  const rawMime = record.mimetype ?? record.mime ?? record.contentType;
  if (typeof rawMime === "string" && rawMime.trim()) {
    document.mimetype = rawMime.trim();
  }
  if (typeof record.caption === "string" && record.caption.trim()) {
    document.caption = record.caption.trim();
  }
  return document;
}

function resolveOutboundDocumentAttachments(payload: Record<string, unknown>): DocumentAttachment[] {
  const documents = Array.isArray(payload.documents)
    ? payload.documents.map(normalizeDocumentAttachment).filter(Boolean)
    : [];
  const documentUrls = Array.isArray(payload.documentUrls)
    ? payload.documentUrls.map(normalizeDocumentAttachment).filter(Boolean)
    : [];
  const singleDocument = normalizeDocumentAttachment(payload.documentUrl);
  return [
    ...(singleDocument ? [singleDocument] : []),
    ...documentUrls,
    ...documents,
  ] as DocumentAttachment[];
}

`;

const distHelper = `function normalizeDocumentAttachment(entry) {
  if (typeof entry === "string" && entry.trim()) return { url: entry.trim() };
  if (!entry || typeof entry !== "object") return void 0;
  const rawUrl = entry.url ?? entry.documentUrl ?? entry.mediaUrl ?? entry.path;
  if (typeof rawUrl !== "string" || !rawUrl.trim()) return void 0;
  const document = { url: rawUrl.trim() };
  const rawFileName = entry.fileName ?? entry.name;
  if (typeof rawFileName === "string" && rawFileName.trim()) document.fileName = rawFileName.trim();
  const rawMime = entry.mimetype ?? entry.mime ?? entry.contentType;
  if (typeof rawMime === "string" && rawMime.trim()) document.mimetype = rawMime.trim();
  if (typeof entry.caption === "string" && entry.caption.trim()) document.caption = entry.caption.trim();
  return document;
}
function resolveOutboundDocumentAttachments(payload) {
  const documents = Array.isArray(payload.documents) ? payload.documents.map(normalizeDocumentAttachment).filter(Boolean) : [];
  const documentUrls = Array.isArray(payload.documentUrls) ? payload.documentUrls.map(normalizeDocumentAttachment).filter(Boolean) : [];
  const singleDocument = normalizeDocumentAttachment(payload.documentUrl);
  return [
    ...(singleDocument ? [singleDocument] : []),
    ...documentUrls,
    ...documents
  ];
}

`;

const sourceDocumentBlock = `  // Documents are forced through WhatsApp's document upload path, even when the
  // file MIME would otherwise be detected as audio/image/video.
  const leadingCaption = remainingText.shift() || "";
  let attachmentCaptionUsed = false;
  for (const [index, document] of documentList.entries()) {
    const caption = index === 0 ? leadingCaption || document.caption : document.caption;
    attachmentCaptionUsed = true;
    try {
      const media = await loadWebMedia(document.url, {
        maxBytes: maxMediaBytes,
        localRoots: params.mediaLocalRoots,
      });
      const fileName = document.fileName ?? media.fileName ?? document.url.split("/").pop() ?? "file";
      const mimetype = document.mimetype ?? media.contentType ?? "application/octet-stream";
      await sendWithRetry(
        () =>
          msg.sendMedia({
            document: media.buffer,
            fileName,
            caption,
            mimetype,
          }),
        "media:document",
      );
      whatsappOutboundLog.info(
        \`Sent document reply to \${msg.from} (\${(media.buffer.length / (1024 * 1024)).toFixed(2)}MB)\`,
      );
      replyLogger.info(
        {
          correlationId: msg.id ?? newConnectionId(),
          connectionId: connectionId ?? null,
          to: msg.from,
          from: msg.to,
          text: caption ?? null,
          mediaUrl: document.url,
          mediaSizeBytes: media.buffer.length,
          mediaKind: "document",
          durationMs: Date.now() - replyStarted,
        },
        "auto-reply sent (document)",
      );
    } catch (error) {
      whatsappOutboundLog.error(\`Failed sending web document to \${msg.from}: \${formatError(error)}\`);
      replyLogger.warn({ err: error, mediaUrl: document.url }, "failed to send web document reply");
      if (index !== 0) {
        continue;
      }
      const warning =
        error instanceof Error ? \`⚠️ Document failed: \${error.message}\` : "⚠️ Document failed.";
      const fallbackTextParts = [remainingText.shift() ?? caption ?? "", warning].filter(Boolean);
      const fallbackText = fallbackTextParts.join("\\n");
      if (fallbackText) {
        whatsappOutboundLog.warn(\`Document skipped; sent text-only to \${msg.from}\`);
        await msg.reply(fallbackText);
      }
    }
  }

`;

const distDocumentBlock = `\t// Documents are forced through WhatsApp's document upload path, even when the
\t// file MIME would otherwise be detected as audio/image/video.
\tconst leadingCaption = remainingText.shift() || "";
\tlet attachmentCaptionUsed = false;
\tfor (const [index, document] of documentList.entries()) {
\t\tconst caption = index === 0 ? leadingCaption || document.caption : document.caption;
\t\tattachmentCaptionUsed = true;
\t\ttry {
\t\t\tconst media = await loadWebMedia(document.url, {
\t\t\t\tmaxBytes: maxMediaBytes,
\t\t\t\tlocalRoots: params.mediaLocalRoots
\t\t\t});
\t\t\tconst fileName = document.fileName ?? media.fileName ?? document.url.split("/").pop() ?? "file";
\t\t\tconst mimetype = document.mimetype ?? media.contentType ?? "application/octet-stream";
\t\t\tawait sendWithRetry(() => msg.sendMedia({
\t\t\t\tdocument: media.buffer,
\t\t\t\tfileName,
\t\t\t\tcaption,
\t\t\t\tmimetype
\t\t\t}), "media:document");
\t\t\twhatsappOutboundLog.info(\`Sent document reply to \${msg.from} (\${(media.buffer.length / (1024 * 1024)).toFixed(2)}MB)\`);
\t\t\treplyLogger.info({
\t\t\t\tcorrelationId: msg.id ?? newConnectionId(),
\t\t\t\tconnectionId: connectionId ?? null,
\t\t\t\tto: msg.from,
\t\t\t\tfrom: msg.to,
\t\t\t\ttext: caption ?? null,
\t\t\t\tmediaUrl: document.url,
\t\t\t\tmediaSizeBytes: media.buffer.length,
\t\t\t\tmediaKind: "document",
\t\t\t\tdurationMs: Date.now() - replyStarted
\t\t\t}, "auto-reply sent (document)");
\t\t} catch (error) {
\t\t\twhatsappOutboundLog.error(\`Failed sending web document to \${msg.from}: \${formatError(error)}\`);
\t\t\treplyLogger.warn({ err: error, mediaUrl: document.url }, "failed to send web document reply");
\t\t\tif (index !== 0) continue;
\t\t\tconst warning = error instanceof Error ? \`⚠️ Document failed: \${error.message}\` : "⚠️ Document failed.";
\t\t\tconst fallbackTextParts = [remainingText.shift() ?? caption ?? "", warning].filter(Boolean);
\t\t\tconst fallbackText = fallbackTextParts.join("\\n");
\t\t\tif (fallbackText) {
\t\t\t\twhatsappOutboundLog.warn(\`Document skipped; sent text-only to \${msg.from}\`);
\t\t\t\tawait msg.reply(fallbackText);
\t\t\t}
\t\t}
\t}

`;

function replaceOnce(contents, from, to, file) {
  if (!contents.includes(from)) {
    throw new Error(`patch anchor not found in ${file}: ${from.slice(0, 80)}`);
  }
  return contents.replace(from, to);
}

function patchDeliverFile(file, { helper, documentBlock, compiled }) {
  let contents = fs.readFileSync(file, "utf8");
  if (contents.includes("resolveOutboundDocumentAttachments")) {
    return false;
  }

  const deliverAnchor = compiled ? "async function deliverWebReply(params)" : "export async function deliverWebReply(params: {";
  contents = replaceOnce(contents, deliverAnchor, `${helper}${deliverAnchor}`, file);
  const mediaLine = compiled
    ? "\tconst mediaList = resolveOutboundMediaUrls(replyResult);\n"
    : "  const mediaList = resolveOutboundMediaUrls(replyResult);\n";
  const documentLine = compiled
    ? "\tconst mediaList = resolveOutboundMediaUrls(replyResult);\n\tconst documentList = resolveOutboundDocumentAttachments(replyResult);\n"
    : "  const mediaList = resolveOutboundMediaUrls(replyResult);\n  const documentList = resolveOutboundDocumentAttachments(replyResult as Record<string, unknown>);\n";
  contents = replaceOnce(contents, mediaLine, documentLine, file);
  contents = replaceOnce(
    contents,
    compiled ? "\tif (mediaList.length === 0 && textChunks.length) {\n" : "  if (mediaList.length === 0 && textChunks.length) {\n",
    compiled
      ? "\tif (mediaList.length === 0 && documentList.length === 0 && textChunks.length) {\n"
      : "  if (mediaList.length === 0 && documentList.length === 0 && textChunks.length) {\n",
    file,
  );
  const mediaStart = compiled
    ? `\tconst remainingText = [...textChunks];
\tawait sendMediaWithLeadingCaption({
\t\tmediaUrls: mediaList,
\t\tcaption: remainingText.shift() || "",
`
    : `  // Media (with optional caption on first item)
  const leadingCaption = remainingText.shift() || "";
  await sendMediaWithLeadingCaption({
    mediaUrls: mediaList,
    caption: leadingCaption,
`;
  const mediaReplacement = compiled
    ? `\tconst remainingText = [...textChunks];
${documentBlock}\tawait sendMediaWithLeadingCaption({
\t\tmediaUrls: mediaList,
\t\tcaption: attachmentCaptionUsed ? "" : leadingCaption,
`
    : `${documentBlock}  // Media (with optional caption on first item)
  await sendMediaWithLeadingCaption({
    mediaUrls: mediaList,
    caption: attachmentCaptionUsed ? "" : leadingCaption,
`;
  contents = replaceOnce(contents, mediaStart, mediaReplacement, file);

  fs.writeFileSync(file, contents);
  return true;
}

function patchReplyPayload(file) {
  let contents = fs.readFileSync(file, "utf8");
  if (contents.includes("documentUrls: Array.isArray(payload.documentUrls)")) {
    return false;
  }
  contents = replaceOnce(
    contents,
    `\t\tmediaUrl: typeof payload.mediaUrl === "string" ? payload.mediaUrl : void 0,
\t\treplyToId: typeof payload.replyToId === "string" ? payload.replyToId : void 0
`,
    `\t\tmediaUrl: typeof payload.mediaUrl === "string" ? payload.mediaUrl : void 0,
\t\tdocumentUrls: Array.isArray(payload.documentUrls) ? payload.documentUrls.filter((entry) => typeof entry === "string" && entry.length > 0) : void 0,
\t\tdocumentUrl: typeof payload.documentUrl === "string" ? payload.documentUrl : void 0,
\t\tdocuments: Array.isArray(payload.documents) ? payload.documents.filter((entry) => typeof entry === "string" || entry && typeof entry === "object") : void 0,
\t\treplyToId: typeof payload.replyToId === "string" ? payload.replyToId : void 0
`,
    file,
  );
  contents = replaceOnce(
    contents,
    `\tconst mediaCount = mediaUrls.length;
\tconst hasText = Boolean(trimmedText);
\tconst hasMedia = mediaCount > 0;
`,
    `\tconst mediaCount = mediaUrls.length;
\tconst documentCount = (Array.isArray(payload.documentUrls) ? payload.documentUrls.length : 0) + (payload.documentUrl ? 1 : 0) + (Array.isArray(payload.documents) ? payload.documents.length : 0);
\tconst hasText = Boolean(trimmedText);
\tconst hasMedia = mediaCount > 0 || documentCount > 0;
`,
    file,
  );
  contents = replaceOnce(
    contents,
    `\t\tmediaCount,
\t\thasText,
`,
    `\t\tmediaCount,
\t\tdocumentCount,
\t\thasText,
`,
    file,
  );
  fs.writeFileSync(file, contents);
  return true;
}

const sourceFile = path.join(appRoot, "extensions/whatsapp/src/auto-reply/deliver-reply.ts");
const distDeliverFiles = fs.readdirSync(path.join(appRoot, "dist"))
  .filter((name) => /^deliver-reply-.*\.js$/u.test(name))
  .map((name) => path.join(appRoot, "dist", name));
const replyPayloadFile = fs.readdirSync(path.join(appRoot, "dist"))
  .find((name) => /^reply-payload-.*\.js$/u.test(name));

const patched = [];
if (fs.existsSync(sourceFile) && patchDeliverFile(sourceFile, { helper: sourceHelper, documentBlock: sourceDocumentBlock, compiled: false })) {
  patched.push(sourceFile);
}
for (const file of distDeliverFiles) {
  if (patchDeliverFile(file, { helper: distHelper, documentBlock: distDocumentBlock, compiled: true })) {
    patched.push(file);
  }
}
if (replyPayloadFile) {
  const fullPath = path.join(appRoot, "dist", replyPayloadFile);
  if (patchReplyPayload(fullPath)) {
    patched.push(fullPath);
  }
}

console.log(`OpenClaw document reply patch applied (${patched.length} files changed).`);
