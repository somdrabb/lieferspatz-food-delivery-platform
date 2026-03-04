-- backend/sql/migrations/2025-09-12_add_is_demo.sql
ALTER TABLE restaurant ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0;

UPDATE restaurant
SET is_demo = 1
WHERE name IN (
  'Pasta Palace','Curry Corner','Burger Barn','Sushi Spot','Falafel Friends',
  'Waffle Works','Taco Town','Pho Place','Salad Studio','Pizza Piazza'
);
