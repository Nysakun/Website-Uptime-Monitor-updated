FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies first (so Docker can cache this layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project
COPY . .

EXPOSE 8000

CMD ["uvicorn", "monitor.api:app", "--host", "0.0.0.0", "--port", "8000"] 