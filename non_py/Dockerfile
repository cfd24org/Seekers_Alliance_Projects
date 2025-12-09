# Simple Dockerfile for running the Streamlit frontend + bbest.py
# Note: Playwright requires additional setup. This image installs Chromium via playwright.

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install playwright and browsers
RUN python -m playwright install chromium

# Copy app and scripts
COPY . /app

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
