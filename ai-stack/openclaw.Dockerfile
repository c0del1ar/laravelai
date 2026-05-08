ARG OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:latest
FROM ${OPENCLAW_IMAGE}

USER root
COPY openclaw-patches/apply-document-reply-patch.mjs /tmp/apply-document-reply-patch.mjs
RUN node /tmp/apply-document-reply-patch.mjs && rm -f /tmp/apply-document-reply-patch.mjs
USER node
