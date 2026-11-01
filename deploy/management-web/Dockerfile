FROM python:3.12-slim
WORKDIR /app
COPY src/submodule/arcade-helper /tmp/arcade-helper
RUN pip install --no-cache-dir '/tmp/arcade-helper[web]' && rm -rf /tmp/arcade-helper && useradd --uid 10001 --create-home editor
COPY scripts/management_relay.py ./scripts/management_relay.py
COPY web/management ./web/management
USER editor
EXPOSE 8765
CMD ["python", "scripts/management_relay.py", "--host", "0.0.0.0", "--port", "8765"]
