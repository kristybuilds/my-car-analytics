# Use a slim version of Python to keep the image small
FROM python:3.10-slim

# Set the working directory inside the container
WORKDIR /app

# Copy your requirements first (best practice for caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your project code (including the assets folder)
COPY . .

# ENTRYPOINT tells the container to start with 'python'
# We will pass the specific script name later in GCP
ENTRYPOINT ["python"]