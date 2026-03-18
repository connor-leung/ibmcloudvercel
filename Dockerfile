FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY deploy_ibm.py .

ENV PYTHONPATH=/app/src

EXPOSE 8080

CMD ["python3", "-c", \
     "import os; from integration.server import run_server; \
      run_server('0.0.0.0', int(os.getenv('PORT', '8080')), '/data/store.json')"]
