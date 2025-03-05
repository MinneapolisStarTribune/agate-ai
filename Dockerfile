# pull official base image
FROM python:3.9-slim

# set work directory
WORKDIR /usr/src/app

ENV PYTHONPATH=/usr/src/app

# set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libcurl4-openssl-dev \
    libssl-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# install dependencies
RUN pip install --upgrade pip
COPY ./requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy project
COPY worker /usr/src/app/worker/
COPY api /usr/src/app/api/
COPY conf /usr/src/app/conf/
COPY . .

EXPOSE 8000
EXPOSE 80

# Let docker-compose.yml specify the command
CMD ["echo", "Please specify a command in docker-compose.yml"]