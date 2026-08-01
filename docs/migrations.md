# Database Migrations

IMS uses **Alembic** for database schema versioning.

Migrations ensure that database changes are reproducible and safe.

---

# Why We Use Migrations

Without migrations:

```bash
model change
↓
drop database
↓
data lost
```

With migrations:

```bash
model change
↓
generate migration
↓
apply migration safely
```
---

# Migration Workflow

When modifying database models:

1. Update SQLAlchemy models

Example:

`app/models/product.py`

2. Generate migration

```bash
alembic -c config/alembic.ini revision --autogenerate -m "description"
```

3. Inspect migration file

Location:


`migrations/versions/`

Example operations:

```py
op.create_table()
op.add_column()
op.create_index()
```

4. Apply migration

```bash
alembic -c config/alembic.ini upgrade head
```

---

# Rollback Migration

To revert the last migration:

```bash
alembic -c config/alembic.ini downgrade -1
```

---

# Current Schema

Tables currently managed by Alembic:

```bash
products
inventory_events
inventory_state
```

Alembic also maintains:

```bash
alembic_version
```

This table tracks the current schema version.

---

# Important Rule

Never use:

```py
Base.metadata.create_all()
```

after migrations are introduced.

Schema changes must go through Alembic.

---

# Example Development Flow

Add column to product:

1. Edit model

2. Generate migration

```bash
alembic -c config/alembic.ini revision --autogenerate -m "add product description"
```

3. Inspect migration

4. Apply migration

```bash
alembic -c config/alembic.ini upgrade head
```