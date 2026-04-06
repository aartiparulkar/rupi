# ── Build stage ──
FROM node:20-alpine AS base

WORKDIR /app

# Install dependencies first (better layer caching)
COPY package*.json ./
RUN npm ci --omit=dev

# Copy all source files
COPY . .

# Create uploads directory
RUN mkdir -p uploads

# ── Production image ──
FROM node:20-alpine AS production

WORKDIR /app

COPY --from=base /app/node_modules ./node_modules
COPY --from=base /app .

# Run as non-root user for security
RUN addgroup -g 1001 -S nodejs && \
    adduser -S rupi -u 1001 && \
    chown -R rupi:nodejs /app

USER rupi

EXPOSE 5000

ENV NODE_ENV=production

CMD ["node", "backend/server.js"]
