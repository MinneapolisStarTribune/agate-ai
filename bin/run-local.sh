#!/bin/bash

docker-compose down
cd ..
touch .env
cp .env .env.bak &&
cp conf/env/local.env .env &&
cp conf/docker/docker-compose.yml.local docker-compose.yml &&
docker-compose up --build &&
mv .env.bak .env