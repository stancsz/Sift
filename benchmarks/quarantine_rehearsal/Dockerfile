FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
WORKDIR /app
COPY runner.py /app/runner.py
USER 10001:10001
ENTRYPOINT ["python", "/app/runner.py"]
