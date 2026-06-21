# ── Frontend (React + Vite) dev image ────────────────────────────────────
# Serves the Vite dev server with HMR. For production, add a build stage that
# runs `npm run build` and serves dist/ via nginx (noted in README).
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173
# --host exposes the dev server outside the container.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
