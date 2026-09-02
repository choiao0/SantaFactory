#!/bin/sh
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
  CREATE ROLE sonarqube LOGIN PASSWORD '$SONAR_DB_PASSWORD';
  CREATE DATABASE sonarqube OWNER sonarqube;
EOSQL
