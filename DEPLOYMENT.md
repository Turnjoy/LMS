# Deployment

## Supabase

1. Create a Supabase project.
2. In the Supabase dashboard, open **Connect** and copy the **Session pooler** connection string for Postgres.
3. Use that value as Render's `DATABASE_URL`.

Render does not support outbound IPv6-only database connections, so avoid Supabase's direct `db.<project-ref>.supabase.co` connection string unless your Supabase project has the IPv4 add-on. The shared pooler connection usually looks like:

```text
postgres://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

The app normalizes `postgres://` to `postgresql://` for SQLAlchemy.

## Render

1. Push this repository to GitHub.
2. In Render, create a new **Blueprint** from the repository, or create a Python web service manually.
3. If creating manually, use:

```text
Build command: pip install -r requirements.txt
Start command: gunicorn run:app
Health check path: /healthz
```

4. Set these environment variables:

```text
FLASK_CONFIG=production
SECRET_KEY=<a long random secret>
DATABASE_URL=<your Supabase session pooler connection string>
TENANT_DOMAIN=<your Render or custom domain, optional>
```

The database tables are created at app startup with `db.create_all()`. After the first successful deploy, open `/signup` and create the first admin account for the active tenant.
