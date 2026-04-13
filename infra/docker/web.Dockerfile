FROM node:22-alpine

WORKDIR /app
RUN corepack enable
COPY package.json pnpm-workspace.yaml tsconfig.base.json ./
COPY packages/shared/typescript/package.json packages/shared/typescript/package.json
COPY apps/web/package.json apps/web/package.json
COPY packages/shared/typescript packages/shared/typescript
COPY apps/web apps/web
RUN pnpm install --no-frozen-lockfile

WORKDIR /app/apps/web
CMD ["pnpm", "dev", "--hostname", "0.0.0.0", "--port", "3000"]
