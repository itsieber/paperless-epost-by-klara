FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir requests

# Create paperless user with same UID as Paperless container
RUN groupadd -g 1000 paperless && \
    useradd -r -u 1000 -g paperless paperless

COPY fetcher.py .
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
