FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (if needed, none required for this app)
# RUN apt-get update && apt-get install -y --no-install-recommends ...

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose the port the app runs on
EXPOSE 8000

# Run the application with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]