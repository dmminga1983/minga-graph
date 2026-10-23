-- users and their orders
CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL
);
CREATE TABLE orders (
  id SERIAL PRIMARY KEY,
  user_id INT REFERENCES users(id),
  total NUMERIC
);
CREATE VIEW big_orders AS SELECT o.id, u.name FROM orders o JOIN users u ON u.id = o.user_id WHERE o.total > 100;
