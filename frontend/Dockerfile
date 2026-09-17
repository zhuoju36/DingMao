# 构建阶段
FROM node:20-alpine AS builder

# 安装 pnpm
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

WORKDIR /app

# 复制 lockfile 与 manifest
COPY pnpm-lock.yaml* package.json .npmrc ./

# 安装依赖（冻结 lockfile）
RUN pnpm install --frozen-lockfile

# 复制源码
COPY . .

# 构建
RUN pnpm run build

# 运行阶段
FROM nginx:1.27-alpine

# 拷贝构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 拷贝 Nginx 配置（可选，本地用 docker-compose.dev.yml 时不需要）
# COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]