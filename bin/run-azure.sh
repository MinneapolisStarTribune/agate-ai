#!/bin/bash

docker-compose down && \
cd .. && \
cp conf/env/azure.env .env && \
cp conf/docker/docker-compose.yml.azure docker-compose.yml && \
docker-compose up --build &&
mv .env.bak .env
