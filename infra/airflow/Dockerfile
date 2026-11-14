FROM ghcr.io/astral-sh/uv:0.9.9@sha256:f6e3549ed287fee0ddde2460a2a74a2d74366f84b04aaa34c1f19fec40da8652 AS uv
FROM apache/airflow:3.1.3-python3.12@sha256:94096e4d3f8819f96b2f37c182d734cc45b6a096080015d6b5978c8a4d3295ba
USER root
COPY infra/airflow/requirements.lock /opt/project/requirements.lock
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    /bin/uv venv /opt/training --python /usr/local/bin/python \
    && /bin/uv pip sync --python /opt/training/bin/python --no-cache --require-hashes /opt/project/requirements.lock
COPY src/mlops_agent/__init__.py src/mlops_agent/dataset.py src/mlops_agent/training.py src/mlops_agent/pipeline.py src/mlops_agent/workflow_task.py /opt/project/src/mlops_agent/
COPY infra/airflow/dags/ /opt/project/dags/
ARG APP_VERSION
RUN APP_VERSION="$APP_VERSION" python -c "import os,re; v=os.environ['APP_VERSION']; assert re.fullmatch('[0-9a-f]{40}',v); open('/opt/project/revision','w').write(v)" \
    && chmod -R a+rX /opt/project /opt/training
ENV PYTHONPATH=/opt/project/src
USER airflow
RUN /opt/training/bin/python -c 'from mlops_agent.pipeline import Pipeline; import mlflow.sklearn'
LABEL org.opencontainers.image.title="mlops-assignment3-airflow" org.opencontainers.image.revision=$APP_VERSION
