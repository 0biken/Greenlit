-- The running app connects as this role. It must not own tables or bypass row-level security (SEC §5).
CREATE ROLE greenlit_app LOGIN PASSWORD 'greenlit_app' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE greenlit TO greenlit_app;
GRANT USAGE ON SCHEMA public TO greenlit_app;
ALTER DEFAULT PRIVILEGES FOR ROLE greenlit_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO greenlit_app;
ALTER DEFAULT PRIVILEGES FOR ROLE greenlit_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO greenlit_app;
-- Lets the test suite switch to the app role (SET ROLE) to prove isolation.
GRANT greenlit_app TO greenlit_owner;
