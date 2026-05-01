-- postgres-init/01_create_litellm_db.sql
-- Runs automatically on first container start via docker-entrypoint-initdb.d
-- Creates the "litellm" database so LiteLLM has its own isolated schema
-- separate from the "postgres" database used by Langfuse.
-- This script is idempotent — safe to leave in place across restarts
-- (initdb.d only runs when the data directory is empty / first init).

SELECT 'CREATE DATABASE litellm'
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'litellm')\gexec