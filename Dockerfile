FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /laboratory
RUN addgroup --system lab && adduser --system --ingroup lab lab
COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts
RUN python -m pip install --no-cache-dir .
RUN mkdir -p /laboratory/data/cache && chown -R lab:lab /laboratory
USER lab

EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
