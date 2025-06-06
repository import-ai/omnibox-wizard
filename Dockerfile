FROM ghcr.io/import-ai/omnibox-wizard-runtime:latest

WORKDIR /app
COPY ./ /app

EXPOSE 8000

ENTRYPOINT ["uvicorn", "wizard.api.server:app"]
CMD ["--host", "0.0.0.0", "--port", "8000"]

HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD wget -q -O- http://127.0.0.1:8000/api/v1/health || exit 1
