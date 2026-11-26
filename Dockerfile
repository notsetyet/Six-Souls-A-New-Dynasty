FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BYOK_ENABLED_PROVIDERS=deepseek

WORKDIR /app
COPY requirements-scene.txt ./
RUN pip install --no-cache-dir -r requirements-scene.txt \
    && useradd --create-home --uid 1000 game

# Explicit allowlist: never COPY the working directory's reports or credentials.
COPY --chown=game:game scene_app.py ./
COPY --chown=game:game game/ ./game/
COPY --chown=game:game scene_web/ ./scene_web/
COPY --chown=game:game assets/ ./assets/

USER game
EXPOSE 7860
# Sessions are process-local; multiple workers would intermittently lose games.
CMD ["uvicorn", "scene_app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--no-access-log"]
