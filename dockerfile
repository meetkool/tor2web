FROM python:3.9

# Update package list and install required packages
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
    tor \
    netcat-openbsd \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py .
COPY start.sh .

RUN chmod +x start.sh

# Expose the port your app runs on
EXPOSE 8080

CMD ["./start.sh"]
