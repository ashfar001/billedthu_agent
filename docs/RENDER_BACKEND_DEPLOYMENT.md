# Render Backend Deployment Notes

The Windows Agent should not run migrations and store activation should not
require a migration each time. Migrations belong to the Django backend deploy.

## Render Start Command

Do not use the placeholder:

```bash
python manage.py migrate && gunicorn your_project.wsgi
```

`your_project.wsgi` must be replaced with the real Django project module, for
example:

```bash
python manage.py migrate && gunicorn billeduthu.wsgi:application
```

or whatever the actual backend project package is.

## Why Activation Was Failing

If `/api/agent/activate/` returns a JSON 503 saying migrations are missing, the
production database does not have the activation tables yet.

Run migrations on Render production once:

```bash
python manage.py migrate
```

After the schema exists, setup-code activation should not need migrations again
until a future backend release adds new database changes.

## Agent Backend URL

The agent production default now points to:

```text
https://billeduthu.onrender.com
```

For later production domain rollout, set this at build/runtime:

```text
BILL_EDUTHU_API_URL=https://billeduthu.in
```
