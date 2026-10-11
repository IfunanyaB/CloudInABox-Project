FROM python:3.13-slim AS portal-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements-portal.txt ./requirements-portal.txt
RUN pip install --no-cache-dir -r requirements-portal.txt
COPY automation ./automation
COPY infrastructure ./infrastructure
COPY index.html ./index.html

FROM portal-base AS web
EXPOSE 8000
CMD ["uvicorn", "automation.api:app", "--host", "0.0.0.0", "--port", "8000"]

FROM portal-base AS worker
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl apt-transport-https lsb-release gnupg \
    && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
    && apt-get purge -y --auto-remove curl apt-transport-https lsb-release gnupg \
    && rm -rf /var/lib/apt/lists/*
CMD ["python", "-m", "automation.worker"]
