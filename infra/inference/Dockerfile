FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    MODEL_BUNDLE_PATH=/app/model PYTHONPATH=/app/src
WORKDIR /app
COPY infra/inference/requirements.lock /app/requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.lock
COPY src/mlops_agent/__init__.py src/mlops_agent/model_bundle.py src/mlops_agent/inference.py /app/src/mlops_agent/
COPY artifacts/inference/ /app/model/
ARG APP_VERSION
RUN APP_VERSION="$APP_VERSION" python -c "import os,re; v=os.environ['APP_VERSION']; assert re.fullmatch('[0-9a-f]{40}',v); open('/app/app-version','w').write(v)"
LABEL org.opencontainers.image.title="mlops-assignment3-inference" \
      org.opencontainers.image.revision=$APP_VERSION
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz',timeout=2)"
CMD ["python", "-m", "uvicorn", "mlops_agent.inference:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
