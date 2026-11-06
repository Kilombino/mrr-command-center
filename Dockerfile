# MRR Command Center, packaged for Umbrel and StartOS. Standard library only.
# Config, state and the audit database live in /data (MRR_DATA_DIR); the MRR API
# key is linked from the dashboard after signing in.
# 3.14: DATUM answers with SHA-256 digest auth, which urllib supports from 3.14 on.
FROM python:3.14-slim
WORKDIR /app
COPY dashboard.py mrr_bot.py audit.py LICENSE README.md ./
COPY www ./www
ENV MRR_DATA_DIR=/data MRR_PACKAGED=1 PYTHONUNBUFFERED=1
RUN mkdir -p /data && chown 1000:1000 /data
USER 1000:1000
EXPOSE 7160
CMD ["python3", "-I", "/app/dashboard.py"]
