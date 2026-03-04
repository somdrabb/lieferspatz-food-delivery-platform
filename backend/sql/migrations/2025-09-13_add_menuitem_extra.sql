-- backend/sql/migrations/2025-09-13_add_menuitem_extra.sql
ALTER TABLE menuitem ADD COLUMN extra_json TEXT NOT NULL DEFAULT '{}';
