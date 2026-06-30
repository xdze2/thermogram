.PHONY: dev

dev:
	uv run uvicorn thnodes.api.main:app --reload & \
	cd frontend && npm run dev
