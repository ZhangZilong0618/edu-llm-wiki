# syntax=docker/dockerfile:1.6
# Edu-LLM-Wiki frontend (Vite dev server).
# The image runs `npm run dev` and is meant to be used with docker compose,
# which bind-mounts ./src for HMR. The container exposes 0.0.0.0:5173.

FROM node:20-alpine

WORKDIR /app

# Install deps separately to leverage Docker layer caching.
COPY package.json package-lock.json* ./
RUN npm install

# Source code is bind-mounted in dev; the COPY below only matters for
# `docker build` without compose (e.g. CI image smoke tests).
COPY . .

EXPOSE 5173

# --host 0.0.0.0 so the dev server is reachable from outside the
# container (default is 127.0.0.1 which would be container-local only).
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
