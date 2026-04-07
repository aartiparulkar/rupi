"""Initialize database tables for the configured Postgres backend (Supabase/local)."""

from models.database import init_db


if __name__ == "__main__":
	init_db()
	print("Database initialization completed.")
