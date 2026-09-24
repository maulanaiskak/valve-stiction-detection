FROM python:3.12-slim

# Unbuffered stdout: without this, print() output sits in Python's block
# buffer (since Docker's stdout isn't a TTY) and never reaches `docker
# logs` until the buffer fills or the process exits -- found this because
# kafka_worker.py produced zero log output despite running and consuming
# correctly.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY detection/ .

CMD ["python", "main.py"]
