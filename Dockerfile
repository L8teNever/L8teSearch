FROM python:3.9-slim

WORKDIR /app

# Install system dependencies if needed (none identified for now)

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure upload folder exists
RUN mkdir -p static/uploads

EXPOSE 9999

CMD ["python", "app.py"]
