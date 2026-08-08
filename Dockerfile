# Use the official lightweight Python 3.11 image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file first to leverage Docker cache
COPY requirements.txt .

# Install all required Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Run the FastAPI server using Uvicorn
# Render dynamically assigns a port using the $PORT environment variable
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
