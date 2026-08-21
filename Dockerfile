FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /laboratory
RUN addgroup --system lab && adduser --system --ingroup lab lab
COPY pyproject.toml README.md ./
COPY app ./app
COPY scripts ./scripts
COPY reports/phase2_demo_report.json ./reports/phase2_demo_report.json
RUN python -m pip install --no-cache-dir .
RUN mkdir -p /laboratory/data/cache && chown -R lab:lab /laboratory
USER lab

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
