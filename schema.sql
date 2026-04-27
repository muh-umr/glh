CREATE TABLE customer (
customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
name TEXT NOT NULL,
email TEXT NOT NULL UNIQUE,
phone_number TEXT NOT NULL,
password_hash TEXT NOT NULL,
address TEXT,
loyalty_points INTEGER NOT NULL DEFAULT 0,
account_created TEXT NOT NULL
);
CREATE TABLE producer (
producer_id INTEGER PRIMARY KEY AUTOINCREMENT,
business_registration_number TEXT NOT NULL UNIQUE,
business_name TEXT NOT NULL,
business_email TEXT NOT NULL UNIQUE,
business_phone_number TEXT NOT NULL,
password_hash TEXT NOT NULL,
business_address TEXT NOT NULL,
description TEXT ,
image_url TEXT,
production_method TEXT,
sustainability_info TEXT
);

CREATE TABLE product (
product_id INTEGER PRIMARY KEY AUTOINCREMENT,
producer_id INTEGER NOT NULL,
name TEXT NOT NULL,
description TEXT NOT NULL,
price NUMERIC NOT NULL,
category TEXT NOT NULL,
image_url TEXT NOT NULL,
is_available INTEGER NOT NULL,
stock INTEGER NOT NULL,
FOREIGN KEY (producer_id) REFERENCES producer(producer_id) ON DELETE CASCADE
);

CREATE TABLE orders (
order_id INTEGER PRIMARY KEY AUTOINCREMENT,
customer_id INTEGER NOT NULL,
order_date TEXT NOT NULL,
status TEXT NOT NULL,
collection_or_delivery TEXT NOT NULL,
scheduled_time TEXT NOT NULL,
scheduled_date TEXT NOT NULL DEFAULT '',
scheduled_slot TEXT NOT NULL DEFAULT '',
total_price NUMERIC NOT NULL,
loyalty_reward_code TEXT,
loyalty_discount NUMERIC NOT NULL DEFAULT 0,
points_redeemed INTEGER NOT NULL DEFAULT 0,
FOREIGN KEY (customer_id) REFERENCES customer(customer_id) ON DELETE CASCADE
);

CREATE TABLE order_items (
order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
order_id INTEGER NOT NULL,
product_id INTEGER NOT NULL,
quantity INTEGER NOT NULL,
price_at_purchase NUMERIC NOT NULL,
FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
FOREIGN KEY (product_id) REFERENCES product(product_id) ON DELETE CASCADE
);

CREATE TABLE basket (
basket_id INTEGER PRIMARY KEY AUTOINCREMENT,
customer_id INTEGER NOT NULL,
created_at TEXT NOT NULL,
FOREIGN KEY (customer_id) REFERENCES customer(customer_id) ON DELETE CASCADE
);

CREATE TABLE basket_item (
basket_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
basket_id INTEGER NOT NULL,
product_id INTEGER NOT NULL,
quantity INTEGER NOT NULL,
FOREIGN KEY (basket_id) REFERENCES basket(basket_id) ON DELETE CASCADE,
FOREIGN KEY (product_id) REFERENCES product(product_id) ON DELETE CASCADE
);


