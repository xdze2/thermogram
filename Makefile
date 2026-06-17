.PHONY: dev api frontend build test

dev: ## Start both API and frontend dev server (requires tmux)
	tmux new-session -d -s thnodes -x 220 -y 50 \; \
	  send-keys 'make api' C-m \; \
	  split-window -h \; \
	  send-keys 'make frontend' C-m \; \
	  attach

api: ## Run FastAPI dev server (port 8000, auto-reload)
	uv run uvicorn api:app --reload

frontend: ## Run Vite dev server (port 5173, proxied to FastAPI)
	cd frontend && npm run dev

build: ## Build frontend into frontend/dist/
	cd frontend && npm run build

test: ## Run all backend tests
	uv run pytest -v
