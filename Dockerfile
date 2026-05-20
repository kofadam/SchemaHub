FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Swagger UI and ReDoc static assets
# Download before building:
#   mkdir swagger-static
#   curl -sLo swagger-static/swagger-ui-bundle.js "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"
#   curl -sLo swagger-static/swagger-ui.css        "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"
#   curl -sLo swagger-static/redoc.standalone.js   "https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js"
#   curl -sLo swagger-static/favicon.png           "https://fastapi.tiangolo.com/img/favicon.png"
COPY swagger-static/ ./static/

EXPOSE 8000

RUN useradd -r -u 1000 appuser
USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
