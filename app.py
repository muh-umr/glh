from flask import Flask, request, render_template, redirect, url_for, flash, Response
from flask_login import LoginManager, logout_user, login_required, current_user, UserMixin, login_user
from datetime import datetime, date
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import os
import csv
import io
import re




app = Flask(__name__)
load_dotenv()
app.secret_key = os.getenv("SECRET_KEY")



login_manager = LoginManager()
login_manager.init_app(app)

COLLECTION_SLOTS = ["09:00-11:00", "11:00-13:00", "14:00-16:00"]
DELIVERY_SLOTS = ["09:00-12:00", "12:00-15:00", "15:00-18:00"]
ORDER_STATUS_TRANSITIONS = {
    "Confirmed": {"Collection": ["Preparing", "Cancelled"], "Delivery": ["Preparing", "Cancelled"]},
    "Preparing": {
        "Collection": ["Ready for Collection", "Cancelled"],
        "Delivery": ["Out for Delivery", "Cancelled"],
    },
    "Ready for Collection": {"Collection": ["Completed"], "Delivery": []},
    "Out for Delivery": {"Collection": [], "Delivery": ["Completed"]},
    "Completed": {"Collection": [], "Delivery": []},
    "Cancelled": {"Collection": [], "Delivery": []},
}


LOYALTY_REWARDS = {
    "FIVE_OFF": {
        "title": "£5 Off Your Next Order",
        "subtitle": "Minimum spend £5",
        "points_required": 100,
    },
    "FREE_DELIVERY": {
        "title": "Free Delivery",
        "subtitle": "Removes standard delivery charge",
        "points_required": 250,
    },
}

#Open a SQLite connection with row access by column name so the rest of the app stays readable.

def get_db():
    db = sqlite3.connect("glh.db")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db

def is_alphanumeric(value, allow_spaces=False):
    if not value:
        return False

    value = value.strip()

    if allow_spaces:
        value = value.replace(" ", "")

    return value.isalnum()

# Validates a basic email format:
# - Local part allows letters, digits, underscores, hyphens and dots
# - Must not start or end with a dot
# - Requires a single @ followed by a domain name
# - Domain allows only word characters (letters, digits, underscore)
# - Requires at least one dot in the domain 
# Note: This is a simplified validation and does not fully comply with RFC email standards.
# It may accept some invalid emails (e.g., consecutive dots) and reject some valid ones.
def is_valid_email(email):
    if not email:
        return False
    email = email.strip()
    pattern = r"^((?!\.)[\w\-_.]*[^.])(@\w+)(\.\w+(\.\w+)?[^.\W])$"
    return re.match(pattern, email) is not None



def is_valid_address(address):
    if not address:
        return False
    
    address = address.strip()
    
    if not (5 <= len(address) <= 200):

        return False

    pattern = r"^[A-Za-z0-9\s,.\-]+$"
    return re.match(pattern, address) is not None
  
 


#Return the right set of time slots based on whether the order is for collection or delivery.
def get_slot_options(collection_or_delivery):
    return COLLECTION_SLOTS if collection_or_delivery == "Collection" else DELIVERY_SLOTS

#Keep the status flow in one place so order updates only move through valid next steps.
def get_next_statuses(status, collection_or_delivery):
    transitions = ORDER_STATUS_TRANSITIONS.get(status, {})
    return transitions.get(collection_or_delivery, [])

#Build the rewards list with an availability flag so the UI can show what the customer can actually redeem.
def get_loyalty_rewards(points):
    rewards = []
    for code, reward in LOYALTY_REWARDS.items():
        rewards.append(
            {
                "code": code,
                "title": reward["title"],
                "subtitle": reward["subtitle"],
                "points_required": reward["points_required"],
                "is_available": points >= reward["points_required"],
            }
        )
    return rewards

#Work out the discount and points cost here so checkout stays focused on placing the order.
def calculate_loyalty_discount(reward_code, subtotal, delivery_cost, available_points):
    if not reward_code:
        return 0.0, 0, None

    reward = LOYALTY_REWARDS.get(reward_code)
    if not reward or available_points < reward["points_required"]:
        return 0.0, 0, None

    if reward_code == "FIVE_OFF":
        return min(5.0, float(subtotal)), reward["points_required"], reward_code

    if reward_code == "FREE_DELIVERY":
        if float(delivery_cost) <= 0:
            return 0.0, 0, None
        return float(delivery_cost), reward["points_required"], reward_code

    return 0.0, 0, None

#Set up the base schema and patch in newer fields so the app can start cleanly on both fresh and existing databases.
def init_db():
    db = get_db()
    db.executescript("""
                     CREATE TABLE IF NOT EXISTS customer (
                     customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                     name TEXT NOT NULL,
email TEXT NOT NULL UNIQUE,
phone_number TEXT NOT NULL,
password_hash TEXT NOT NULL,
address TEXT,
loyalty_points INTEGER NOT NULL DEFAULT 0,
account_created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS producer (
producer_id INTEGER PRIMARY KEY AUTOINCREMENT,
business_registration_number TEXT NOT NULL UNIQUE,
business_name TEXT NOT NULL,
business_email TEXT NOT NULL UNIQUE,
business_phone_number TEXT NOT NULL,
password_hash TEXT NOT NULL,
business_address TEXT NOT NULL,
description TEXT,
image_url TEXT,
production_method TEXT,
sustainability_info TEXT
);

CREATE TABLE IF NOT EXISTS product (
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
CREATE TABLE IF NOT EXISTS orders (
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
CREATE TABLE IF NOT EXISTS order_items (
order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
order_id INTEGER NOT NULL,
product_id INTEGER NOT NULL,
quantity INTEGER NOT NULL,
price_at_purchase NUMERIC NOT NULL,
FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
FOREIGN KEY (product_id) REFERENCES product(product_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS basket (
basket_id INTEGER PRIMARY KEY AUTOINCREMENT,
customer_id INTEGER NOT NULL,
created_at TEXT NOT NULL,
FOREIGN KEY (customer_id) REFERENCES customer(customer_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS basket_item (
basket_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
basket_id INTEGER NOT NULL,
product_id INTEGER NOT NULL,
quantity INTEGER NOT NULL,
FOREIGN KEY (basket_id) REFERENCES basket(basket_id) ON DELETE CASCADE,
FOREIGN KEY (product_id) REFERENCES product(product_id) ON DELETE CASCADE
);

""")

    db.commit()
    db.close()




class User(UserMixin):
    def __init__(self, id, name, email, password_hash, user_type):
        self.id = id
        self.name = name
        self.email = email
        self.password_hash = password_hash
        self.user_type = user_type
    def get_id(self):
        return f"{self.user_type}:{self.id}"



#Send users to the sign-in screen that matches the part of the app they were trying to reach.
@login_manager.unauthorized_handler
def unauthorised():
    producer_routes = {
        "/producer-dashboard",
        "/manage-products",
        "/add-product",
        "/producer-stock",
        "/producer-orders",
    }

    if request.path in producer_routes or request.path.startswith("/producer-orders/"):
        return redirect(url_for("producer_signin"))

    return redirect(url_for("customer_signin"))

#Rebuild the logged-in user from the session id, with support for both customer and producer accounts.
@login_manager.user_loader
def load_user(user_id):
    db = get_db()

    if user_id.startswith("customer:"):
        actual_id = user_id.replace("customer:", "", 1)
        user = db.execute(
            "SELECT * FROM customer WHERE customer_id = ?",
            (actual_id,)
        ).fetchone()
        db.close()

        if user:
            return User(
                id=user["customer_id"],
                name=user["name"],
                email=user["email"],
                password_hash=user["password_hash"],
                user_type="customer"
            )

    elif user_id.startswith("producer:"):
        actual_id = user_id.replace("producer:", "", 1)
        user = db.execute(
            "SELECT * FROM producer WHERE producer_id = ?",
            (actual_id,)
        ).fetchone()
        db.close()

        if user:
            return User(
                id=user["producer_id"],
                name=user["business_name"],
                email=user["business_email"],
                password_hash=user["password_hash"],
                user_type="producer"
            )

    db.close()
    return None

#Fetch the current producer's products in one query so management pages can reuse the same data source.
def get_producer_products(db, producer_id):
    
    
    return db.execute(
        """
        SELECT
            product_id,
            name,
            description,
            price,
            category,
            image_url,
            is_available,
            stock
        FROM product
        WHERE producer_id = ?
        """,
        (producer_id,),
    ).fetchall()

#Save uploaded images into the right static folder and return the path we can store in the database.
def save_uploaded_image(file_storage, folder_name):
    if not file_storage or file_storage.filename == "":
        return None

    filename = secure_filename(file_storage.filename)
    if not filename:
        return None

    upload_folder = os.path.join(app.static_folder, "images", folder_name)
    os.makedirs(upload_folder, exist_ok=True)

    file_path = os.path.join(upload_folder, filename)
    file_storage.save(file_path)

    return f"/static/images/{folder_name}/{filename}"



def get_producer_profile_completion(producer):
    required_fields = {
        "image_url": "profile image",
        "description": "description",
        "production_method": "production method",
        "sustainability_info": "sustainability information",
    }
    missing_fields = [
        label
        for field, label in required_fields.items()
        if not producer or not producer[field] or not str(producer[field]).strip()
    ]
    return len(missing_fields) == 0, missing_fields




#Keep dashboard summary numbers together here so the producer homepage stays easy to read.
def get_producer_metrics(db, producer_id):
    total_products = db.execute(
        "SELECT COUNT(*) FROM product WHERE producer_id = ?",
        (producer_id,),
    ).fetchone()[0]
    low_stock_products = db.execute(
        "SELECT COUNT(*) FROM product WHERE producer_id = ? AND stock < 5",
        (producer_id,),
    ).fetchone()[0]
    revenue_result = db.execute(

        """

        SELECT SUM(oi.quantity * oi.price_at_purchase)

        FROM order_items oi

        JOIN product p ON oi.product_id = p.product_id

        WHERE p.producer_id = ?

        """,

        (producer_id,),

    ).fetchone()[0]
    total_revenue = revenue_result if revenue_result is not None else 0

    return {
        "total_products": total_products,
        "low_stock_products": low_stock_products,
        "total_revenue": float(total_revenue),
    
    }
    
#Pull each producer's view of their orders, then attach the matching items and allowed next statuses.
def get_producer_orders(db, producer_id):
    orders = db.execute(
        """
        SELECT
            o.order_id,
            o.status,
            o.order_date,
            o.scheduled_time,
            o.scheduled_date,
            o.scheduled_slot,
            o.collection_or_delivery,
            c.name AS customer_name,
            c.email AS customer_email,
            c.phone_number AS customer_phone,
            COALESCE(SUM(oi.quantity * oi.price_at_purchase), 0) AS producer_total,
            COALESCE(o.loyalty_discount, 0) AS loyalty_discount
        FROM orders o
        JOIN customer c ON c.customer_id = o.customer_id
        JOIN order_items oi ON oi.order_id = o.order_id
        JOIN product p ON p.product_id = oi.product_id
        WHERE p.producer_id = ?
        GROUP BY
            o.order_id,
            o.status,
            o.order_date,
            o.scheduled_time,
            o.scheduled_date,
            o.scheduled_slot,
            o.collection_or_delivery,
            c.name,
            c.email,
            c.phone_number,
            o.loyalty_discount
        ORDER BY o.order_date DESC, o.order_id DESC
        """,
        (producer_id,)
    ).fetchall()

    order_ids = [order["order_id"] for order in orders]
    items_by_order = {}

    if order_ids:
        placeholders = ",".join(["?"] * len(order_ids))
        items = db.execute(
            f"""
            SELECT
                oi.order_id,
                p.name,
                oi.quantity,
                oi.price_at_purchase
            FROM order_items oi
            JOIN product p ON oi.product_id = p.product_id
            WHERE oi.order_id IN ({placeholders})
            AND p.producer_id = ?
            ORDER BY oi.order_id DESC, p.name COLLATE NOCASE
            """,
            order_ids + [producer_id],
        ).fetchall()

        for item in items:
            items_by_order.setdefault(item["order_id"], []).append(item)

    return [
        {
            "order_id": order["order_id"],
            "status": order["status"],
            "order_date": order["order_date"],
            "scheduled_time": order["scheduled_time"],
            "scheduled_date": order["scheduled_date"],
            "scheduled_slot": order["scheduled_slot"],
            "collection_or_delivery": order["collection_or_delivery"],
            "customer_name": order["customer_name"],
            "customer_email": order["customer_email"],
            "customer_phone": order["customer_phone"],
            "producer_total": float(order["producer_total"] or 0),
            "loyalty_discount": float(order["loyalty_discount"] or 0),
            "items": items_by_order.get(order["order_id"], []),
            "next_statuses": get_next_statuses(order["status"], order["collection_or_delivery"]),
        }
        for order in orders
    ]

#Build a full order history for the customer, including the items in each order.
def get_customer_orders(db, customer_id):
    orders = db.execute(
        """
        SELECT
            o.order_id,
            o.order_date,
            o.status,
            o.collection_or_delivery,
            o.scheduled_time,
            o.scheduled_date,
            o.scheduled_slot,
            o.total_price,
            COALESCE(o.loyalty_discount, 0) AS loyalty_discount,
            COALESCE(o.points_redeemed, 0) AS points_redeemed,
            o.loyalty_reward_code
        FROM orders o
        WHERE o.customer_id = ?
        ORDER BY datetime(o.order_date) DESC, o.order_id DESC
        """,
        (customer_id,)
    ).fetchall()

    order_ids = [order["order_id"] for order in orders]
    items_by_order = {}

    if order_ids:
        placeholders = ",".join(["?"] * len(order_ids))
        items = db.execute(
            f"""
            SELECT
                oi.order_id,
                p.name,
                oi.quantity,
                oi.price_at_purchase
            FROM order_items oi
            JOIN product p ON oi.product_id = p.product_id
            WHERE oi.order_id IN ({placeholders})
            ORDER BY oi.order_id DESC, p.name COLLATE NOCASE
            """,
            order_ids,
        ).fetchall()

        for item in items:
            items_by_order.setdefault(item["order_id"], []).append(item)

    return [
        {
            "order_id": order["order_id"],
            "order_date": datetime.strptime(order["order_date"], "%Y-%m-%dT%H:%M:%S.%f").strftime("%d %B %Y"),
            "status": order["status"],
            "collection_or_delivery": order["collection_or_delivery"],
            "scheduled_time": order["scheduled_time"],
            "scheduled_date": order["scheduled_date"],
            "scheduled_slot": order["scheduled_slot"],
            "total_price": float(order["total_price"] or 0),
            "loyalty_discount": float(order["loyalty_discount"] or 0),
            "points_redeemed": int(order["points_redeemed"] or 0),
            "loyalty_reward_code": order["loyalty_reward_code"],
            "items": items_by_order.get(order["order_id"], []),
        }
        for order in orders
    ]

#Count basket items for the signed-in customer so the header can stay in sync everywhere.
def get_cart_count(db, customer_id):
    basket = db.execute(
        "SELECT basket_id FROM basket WHERE customer_id = ?",
        (customer_id,)
    ).fetchone()

    if not basket:
        return 0

    count = db.execute(
        """
        SELECT COUNT(*)
        FROM basket_item
        WHERE basket_id = ?
        """,
        (basket["basket_id"],)
    ).fetchone()[0]

    return count or 0

#Make the cart count available to every template without repeating the same lookup in each route.
@app.context_processor
def inject_cart_count():
    if current_user.is_authenticated and current_user.user_type == "customer":
        db = get_db()
        count = get_cart_count(db, current_user.id)
        db.close()
        return {"cart_count": count}
    return {"cart_count": 0}

"""Routes of all the Pages"""

#Show a small featured set of producers on the homepage instead of loading the full directory.
@app.route("/")
def homepage():
    db = get_db()

    producers = db.execute(
        """
        SELECT
            producer_id,
            business_name,
            business_address,
            description,
            image_url,
            production_method,
            sustainability_info
        FROM producer
         WHERE image_url IS NOT NULL
          AND TRIM(image_url) != ''
          AND description IS NOT NULL
          AND TRIM(description) != ''
          AND production_method IS NOT NULL
          AND TRIM(production_method) != ''
          AND sustainability_info IS NOT NULL
          AND TRIM(sustainability_info) != ''
        ORDER BY producer_id ASC
        LIMIT 3
        """
    ).fetchall()

    db.close()

    return render_template("index.html", producers=producers)

#Load all available products along with their categories so the listing page has everything it needs up front.
@app.route("/products")
def products():
    db = get_db()

    products = db.execute("""
        SELECT
            p.product_id,
            p.name,
            p.description,
            p.price,
            p.category,
            p.image_url,
            p.stock,
            pr.business_name
        FROM product p
        JOIN producer pr ON p.producer_id = pr.producer_id
        WHERE p.is_available = 1
        ORDER BY p.name COLLATE NOCASE
    """).fetchall()

    categories = db.execute(
        """
        SELECT DISTINCT category
        FROM product
        WHERE is_available = 1
        ORDER BY category COLLATE NOCASE
        """
    ).fetchall()

    db.close()

    return render_template(
        "products.html",
        products=products,
        categories=[category["category"] for category in categories],
    )

#Fetch the selected product together with its producer details so the detail page can tell the full story in one view.
@app.route("/product/<int:product_id>")
def product_detail(product_id):
    db = get_db()

    product = db.execute(
        """
        SELECT
            p.product_id,
            p.name,
            p.description,
            p.price,
            p.category,
            p.image_url,
            p.stock,
            p.is_available,
            pr.producer_id,
            pr.business_name,
            pr.business_address,
            pr.description AS producer_description,
            pr.image_url AS producer_image,
            pr.production_method,
            pr.sustainability_info
        FROM product p
        JOIN producer pr ON p.producer_id = pr.producer_id
        WHERE p.product_id = ?
        """,
        (product_id,)
    ).fetchone()

    if not product or product["is_available"] != 1:
        db.close()
        return render_template("error-404.html"), 404

    related_products = db.execute(
        """
        SELECT
            p.product_id,
            p.name,
            p.description,
            p.price,
            p.category,
            p.image_url,
            p.stock,
            pr.business_name
        FROM product p
        JOIN producer pr ON p.producer_id = pr.producer_id
        WHERE p.category = ?
          AND p.product_id != ?
          AND p.is_available = 1
        ORDER BY p.name COLLATE NOCASE
        LIMIT 4
        """,
        (product["category"], product_id)
    ).fetchall()

    db.close()

    return render_template(
        "product-detail.html",
        product=product,
        related_products=related_products
    )

#Build the producer directory with category hints to make browsing easier for customers.
@app.route("/producers")
def producers():
    db = get_db()

    producers = db.execute(
        """
        SELECT
            pr.producer_id,
            pr.business_name,
            pr.business_address,
            pr.description,
            pr.image_url,
            pr.production_method,
            pr.sustainability_info,
            COALESCE(GROUP_CONCAT(DISTINCT p.category), '') AS categories
        FROM producer pr
        LEFT JOIN product p ON p.producer_id = pr.producer_id
         WHERE pr.image_url IS NOT NULL
          AND TRIM(pr.image_url) != ''
          AND pr.description IS NOT NULL
          AND TRIM(pr.description) != ''
          AND pr.production_method IS NOT NULL
          AND TRIM(pr.production_method) != ''
          AND pr.sustainability_info IS NOT NULL
          AND TRIM(pr.sustainability_info) != ''
        GROUP BY
            pr.producer_id,
            pr.business_name,
            pr.business_address,
            pr.description,
            pr.image_url,
            pr.production_method,
            pr.sustainability_info
        ORDER BY business_name COLLATE NOCASE
        """
    ).fetchall()

    categories = db.execute(
        """
        SELECT DISTINCT category
        FROM product
        WHERE category IS NOT NULL AND TRIM(category) != ''
        ORDER BY category COLLATE NOCASE
        """
    ).fetchall()

    db.close()
    return render_template(
        "producers.html",
        producers=producers,
        categories=[category["category"] for category in categories],
    )
    
#Show a producer's public profile and their products together so customers can explore the business in one place.
@app.route("/producer/<int:producer_id>")
def producer_public_profile(producer_id):
    db = get_db()

    producer = db.execute(
        """
        SELECT
            producer_id,
            business_name,
            business_email,
            business_phone_number,
            business_address,
            description,
            image_url,
            production_method,
            sustainability_info
        FROM producer
        WHERE producer_id = ?
        """,
        (producer_id,)
    ).fetchone()

    products = db.execute(
        """
        SELECT
            product_id,
            name,
            description,
            price,
            category,
            image_url,
            stock
        FROM product
        WHERE producer_id = ?
        ORDER BY name COLLATE NOCASE
        """,
        (producer_id,)
    ).fetchall()

    db.close()

    if not producer:
        return render_template("error-404.html"), 404

    return render_template(
        "producer-public-profile.html",
        producer=producer,
        products=products
    )
    
#This page is static, so the route just hands off to the template.
@app.route("/about")
def about():
    return render_template("about.html")

"""Customer Facing Pages"""

#Validate the signup form, hash the password, and create a new customer account in one pass.
@app.route("/customer-signup", methods=["POST", "GET"])
def customer_signup():
    if request.method == "POST":
    
        first_name = request.form.get("first_name", "").strip() 
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone_number = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        checkbox = request.form.get("checkbox")
        

        if not all([first_name, last_name, email, phone_number, password, confirm_password]):
            flash("All fields are required", "error")
            return redirect(url_for("customer_signup"))
        email = request.form.get("email", "").strip()
        
        name = f"{first_name} {last_name}".strip()
        
        if not name.replace(" ", "").isalpha() or len(name) < 2 or len(name) > 30:
            flash("Name can only contain letters and must be between 2-30 characters", "error")
            return redirect(url_for("customer_signup"))
        

        if not is_valid_email(email):
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("customer_signup"))

        clean_phone = phone_number.strip()

        if clean_phone.startswith("+"):
            clean_phone = clean_phone[1:]


        clean_phone = (
            clean_phone.replace(" ", "")
               .replace("-", "")
               .replace("(", "")
               .replace(")", "")
)


        if not clean_phone.isdigit() or not (7 <= len(clean_phone) <= 15):
            flash("Phone number must be 7–15 digits and contain only numbers.", "error")
            return redirect(url_for("customer_signup"))
        
        if not (8 <= len(password) <= 64):
            flash("Password must be between 8 and 64 characters long.", "error")
            return redirect(url_for("customer_signup"))
        
        if password != confirm_password:
            flash("Passwords do not match", "error")
            return redirect(url_for("customer_signup"))
        
        if not checkbox:
            flash("You must accept the Terms and Conditions.", "error")
            return redirect(url_for("customer_signup"))

        hashed_pw = generate_password_hash(password)

        
        db = get_db()
        existing_customer = db.execute( "SELECT customer_id FROM customer WHERE email = ?", (email,)).fetchone() 
        if existing_customer: 
            db.close() 
            flash("An account with this email already exists.", "error") 
            return redirect(url_for("customer_signup"))

        try:
            db.execute(
                "INSERT INTO customer(name, email, phone_number, password_hash, address, loyalty_points, account_created) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, email, clean_phone, hashed_pw, None, 0, datetime.now().isoformat())
            )
            db.commit()
            db.close()
            flash("Registration successful!", "success")
            return redirect(url_for("customer_signin"))
            
        except Exception as e:
            flash(f"Error: {e}", "error")
            return redirect(url_for("customer_signup"))

    return render_template("customer-signup.html")
    
#Check the customer's credentials and start their session if everything matches.
@app.route("/customer-signin", methods=["POST", "GET"])
def customer_signin():
    if current_user.is_authenticated:
        return redirect(url_for("homepage"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        
        if not is_valid_email(email):
            flash("Please enter a valid email address", "error")
            return redirect(url_for("customer_signin"))        
        
        db = get_db()
        user = db.execute("SELECT * FROM customer WHERE email=?", 
        (email,)).fetchone()
        
        
        db.close()


        if user and check_password_hash(user["password_hash"], password):
            login_user(User(
                id=user["customer_id"],
                name=user["name"],
                email=user["email"],
                password_hash=user["password_hash"],
                user_type="customer"
            ), remember=True)
            return redirect(url_for("homepage"))
        else:
            flash("Invalid email or password", "error")
            return render_template("customer-signin.html")

    return render_template("customer-signin.html")
      


#Pull the current basket and calculate subtotal, delivery, and total so the page can render the latest checkout summary.
@app.route("/basket")
@login_required
def basket():
    if current_user.user_type != "customer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="customer",
        switch_url=url_for("logout", next=url_for("customer_signin"))
    )

    db = get_db()

    basket = db.execute(
        "SELECT basket_id FROM basket WHERE customer_id = ?",
        (current_user.id,)
    ).fetchone()

    items = []
    subtotal = 0
    delivery = 0
    total = 0
    free_delivery_gap = 0

    if basket:
        items = db.execute(
            """
            SELECT
                bi.basket_item_id,
                bi.quantity,
                p.product_id,
                p.name,
                p.price,
                p.image_url,
                p.stock,
                pr.business_name
            FROM basket_item bi
            JOIN product p ON bi.product_id = p.product_id
            JOIN producer pr ON p.producer_id = pr.producer_id
            WHERE bi.basket_id = ?
            ORDER BY p.name COLLATE NOCASE
            """,
            (basket["basket_id"],)
        ).fetchall()

        subtotal = sum(item["quantity"] * item["price"] for item in items)

        if subtotal == 0:
            delivery = 0
        elif subtotal >= 30:
            delivery = 0
        else:
            delivery = 3.50

        total = subtotal + delivery
        free_delivery_gap = max(0, 30 - subtotal)

    db.close()
    
    return render_template(
        "basket.html",
        items=items,
        subtotal=subtotal,
        delivery=delivery,
        total=total,
        free_delivery_gap=free_delivery_gap
    )

#Add a product to the basket while keeping the quantity within the available stock.
@app.route("/add-to-cart/<int:product_id>", methods=["POST"])
@login_required
def add_to_cart(product_id):
    if current_user.user_type != "customer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="customer",
        switch_url=url_for("logout", next=url_for("customer_signin"))
    )

    quantity = request.form.get("quantity", 1)

    try:
        quantity = int(quantity)
    except ValueError:
        quantity = 1

    if quantity < 1:
        quantity = 1

    db = get_db()

    product = db.execute(
        "SELECT product_id, stock, is_available FROM product WHERE product_id = ?",
        (product_id,)
    ).fetchone()

    if not product:
        db.close()
        flash("Product not found.", "error")
        return redirect(url_for("products"))

    if product["is_available"] != 1 or product["stock"] <= 0:
        db.close()
        flash("This product is unavailable.", "error")
        return redirect(url_for("products"))

    basket = db.execute(
        "SELECT basket_id FROM basket WHERE customer_id = ?",
        (current_user.id,)
    ).fetchone()

    if basket:
        basket_id = basket["basket_id"]
    else:
        cursor = db.execute(
            "INSERT INTO basket (customer_id, created_at) VALUES (?, ?)",
            (current_user.id, datetime.now().isoformat())
        )
        db.commit()
        basket_id = cursor.lastrowid

    existing_item = db.execute(
        """
        SELECT basket_item_id, quantity
        FROM basket_item
        WHERE basket_id = ? AND product_id = ?
        """,
        (basket_id, product_id)
    ).fetchone()

    if existing_item:
        new_quantity = existing_item["quantity"] + quantity

        if new_quantity > product["stock"]:
            new_quantity = product["stock"]

        db.execute(
            """
            UPDATE basket_item
            SET quantity = ?
            WHERE basket_item_id = ?
            """,
            (new_quantity, existing_item["basket_item_id"])
        )
    else:
        if quantity > product["stock"]:
            quantity = product["stock"]

        db.execute(
            """
            INSERT INTO basket_item (basket_id, product_id, quantity)
            VALUES (?, ?, ?)
            """,
            (basket_id, product_id, quantity)
        )

    db.commit()
    db.close()

    flash("Added to cart.", "info")
    return redirect(url_for("basket"))

#Update the basket quantity for this item, or remove it completely if the new value drops to zero.
@app.route("/update-basket-item/<int:basket_item_id>", methods=["POST"])
@login_required
def update_basket_item(basket_item_id):
    if current_user.user_type != "customer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="customer",
        switch_url=url_for("logout", next=url_for("customer_signin"))
    )

    quantity = request.form.get("quantity", 1)

    try:
        quantity = int(quantity)
    except ValueError:
        quantity = 1

    db = get_db()

    item = db.execute(
        """
        SELECT
            bi.basket_item_id,
            b.customer_id,
            p.stock
        FROM basket_item bi
        JOIN basket b ON bi.basket_id = b.basket_id
        JOIN product p ON bi.product_id = p.product_id
        WHERE bi.basket_item_id = ?
        """,
        (basket_item_id,)
    ).fetchone()

    if not item or item["customer_id"] != current_user.id:
        db.close()
        return "Unauthorized", 403

    if quantity <= 0:
        db.execute(
            "DELETE FROM basket_item WHERE basket_item_id = ?",
            (basket_item_id,)
        )
    else:
        if quantity > item["stock"]:
            db.close()
            flash(f"Only {item['stock']} of this item is available in stock.", "error")
            return redirect(url_for("basket"))

        db.execute(
            "UPDATE basket_item SET quantity = ? WHERE basket_item_id = ?",
            (quantity, basket_item_id)
        )

    db.commit()
    db.close()

    return redirect(url_for("basket"))

#Remove a basket item after confirming that it belongs to the logged-in customer.
@app.route("/remove-basket-item/<int:basket_item_id>", methods=["POST"])
@login_required
def remove_basket_item(basket_item_id):
    if current_user.user_type != "customer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="customer",
        switch_url=url_for("logout", next=url_for("customer_signin"))
    )

    db = get_db()

    item = db.execute(
        """
        SELECT bi.basket_item_id, b.customer_id
        FROM basket_item bi
        JOIN basket b ON bi.basket_id = b.basket_id
        WHERE bi.basket_item_id = ?
        """,
        (basket_item_id,)
    ).fetchone()

    if not item or item["customer_id"] != current_user.id:
        db.close()
        return "Unauthorized", 403

    db.execute(
        "DELETE FROM basket_item WHERE basket_item_id = ?",
        (basket_item_id,)
    )
    db.commit()
    db.close()

    flash("Item removed from cart.", "error")
    return redirect(url_for("basket"))

#Handle the full checkout flow here: validate the order, apply loyalty rewards, create the order, and update stock.
@app.route("/checkout", methods=["GET", "POST"])
@login_required
def checkout():
    if current_user.user_type != "customer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="customer",
        switch_url=url_for("logout", next=url_for("customer_signin"))
    )

    db = get_db()

    customer = db.execute(
        """
        SELECT
            customer_id,
            name,
            email,
            phone_number,
            address,
            loyalty_points
        FROM customer
        WHERE customer_id = ?
        """,
        (current_user.id,)
    ).fetchone()

    basket = db.execute(
        "SELECT basket_id FROM basket WHERE customer_id = ?",
        (current_user.id,)
    ).fetchone()

    if not basket:
        db.close()
        flash("Your basket is empty.")
        return redirect(url_for("basket"))

    items = db.execute(
        """
        SELECT
            bi.basket_item_id,
            bi.product_id,
            bi.quantity,
            p.name,
            p.price,
            p.stock,
            p.is_available
        FROM basket_item bi
        JOIN product p ON bi.product_id = p.product_id
        WHERE bi.basket_id = ?
        ORDER BY p.name COLLATE NOCASE
        """,
        (basket["basket_id"],)
    ).fetchall()

    if not items:
        db.close()
        flash("Your basket is empty.")
        return redirect(url_for("basket"))

    subtotal = sum(item["quantity"] * item["price"] for item in items)

    if subtotal >= 30 or subtotal == 0:
        default_delivery = 0
    else:
        default_delivery = 3.50

    selected_method = request.form.get("collection_or_delivery", "Collection")
    slot_options = get_slot_options(selected_method)
    rewards = get_loyalty_rewards(customer["loyalty_points"] or 0)
    selected_reward = request.form.get("loyalty_reward_code", "")

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip() 
        email = request.form.get("email", "").strip().lower()
        phone_number = request.form.get("phone_number", "").strip() 
        collection_or_delivery = request.form.get("collection_or_delivery")
        scheduled_date = request.form.get("scheduled_date")
        scheduled_slot = request.form.get("scheduled_slot")
        selected_reward = request.form.get("loyalty_reward_code", "")

        if not all([full_name, email, phone_number, collection_or_delivery, scheduled_date, scheduled_slot]):
            db.close()
            flash("Please complete all required fields.", "error")
            return redirect(url_for("checkout"))
        
        
        if not full_name.replace(" ", "").isalpha() or len(full_name) < 2 or len(full_name) > 30:
            flash("Name can only contain letters and must be between 2-30 characters", "error")
            return redirect(url_for("checkout"))
        
        if not is_valid_email(email):
            db.close()
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("checkout"))
        
        clean_phone = phone_number.strip()

        if clean_phone.startswith("+"):
            clean_phone = clean_phone[1:]


        clean_phone = (
            clean_phone.replace(" ", "")
               .replace("-", "")
               .replace("(", "")
               .replace(")", "")
)


        if not clean_phone.isdigit() or not (7 <= len(clean_phone) <= 15):
            flash("Phone number must be 7–15 digits and contain only numbers.", "error")
            return redirect(url_for("checkout"))


        try:
            selected_date = datetime.strptime(scheduled_date, "%Y-%m-%d").date()
        except ValueError:
            db.close()
            flash("Please choose a valid date.", "error")
            return redirect(url_for("checkout"))

        if selected_date < date.today():
            db.close()
            flash("Scheduled date cannot be in the past.", "error")
            return redirect(url_for("checkout"))

        slot_options = get_slot_options(collection_or_delivery)
        if scheduled_slot not in slot_options:
            db.close()
            flash("Please choose a valid time slot.", "error")
            return redirect(url_for("checkout"))
        
        scheduled_date = selected_date.strftime("%d %B %Y")
            


        if collection_or_delivery == "Collection":
            delivery_cost = 0
            scheduled_time = f"Collection on {scheduled_date} during {scheduled_slot}"
        else:
            delivery_cost = 0 if subtotal >= 30 else 3.50
            scheduled_time = f"Delivery on {scheduled_date} during {scheduled_slot}"

        loyalty_discount, points_redeemed, reward_code = calculate_loyalty_discount(
            selected_reward,
            subtotal,
            delivery_cost,
            customer["loyalty_points"] or 0,
        )

        total_price = max(0, subtotal + delivery_cost - loyalty_discount)

        for item in items:
            if item["is_available"] != 1 or item["stock"] < item["quantity"]:
                db.close()
                flash(f"{item['name']} is no longer available in the requested quantity.", "error")
                return redirect(url_for("basket"))

        db.execute(
            """
            UPDATE customer
            SET name = ?, email = ?, phone_number = ?
            WHERE customer_id = ?
            """,
            (full_name, email, clean_phone, current_user.id)
        )

        current_user.name = full_name
        current_user.email = email

        cursor = db.execute(
            """
            INSERT INTO orders (
                customer_id,
                order_date,
                status,
                collection_or_delivery,
                scheduled_time,
                scheduled_date,
                scheduled_slot,
                total_price,
                loyalty_reward_code,
                loyalty_discount,
                points_redeemed
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                current_user.id,
                datetime.now().isoformat(),
                "Confirmed",
                collection_or_delivery,
                scheduled_time,
                scheduled_date,
                scheduled_slot,
                total_price,
                reward_code,
                loyalty_discount,
                points_redeemed,
            )
        )

        order_id = cursor.lastrowid

        for item in items:
            db.execute(
                """
                INSERT INTO order_items (
                    order_id,
                    product_id,
                    quantity,
                    price_at_purchase
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    order_id,
                    item["product_id"],
                    item["quantity"],
                    item["price"],
                )
            )

            new_stock = item["stock"] - item["quantity"]
            is_available = 1 if new_stock > 0 else 0

            db.execute(
                """
                UPDATE product
                SET stock = ?, is_available = ?
                WHERE product_id = ?
                """,
                (new_stock, is_available, item["product_id"])
            )

        points_earned = int(max(0, subtotal - loyalty_discount))
        db.execute(
            """
            UPDATE customer
            SET loyalty_points = loyalty_points + ? - ?
            WHERE customer_id = ?
            """,
            (points_earned, points_redeemed, current_user.id)
        )

        db.execute(
            "DELETE FROM basket_item WHERE basket_id = ?",
            (basket["basket_id"],)
        )

        db.commit()
        db.close()

        flash("Order placed successfully.", "success")
        return redirect(url_for("customer_dashboard", tab="customer-orders"))

    db.close()

    return render_template(
        "checkout.html",
        customer=customer,
        items=items,
        subtotal=subtotal,
        default_delivery=default_delivery,
        total=subtotal + default_delivery,
        slot_options=slot_options,
        rewards=rewards,
        selected_method=selected_method,
        selected_reward=selected_reward,
        min_date=date.today().isoformat(),
        COLLECTION_SLOTS=COLLECTION_SLOTS,
        DELIVERY_SLOTS=DELIVERY_SLOTS,
    )

#Use the tab value to decide which customer section should be shown when the dashboard loads.
@app.route("/customer-dashboard")
@login_required
def customer_dashboard():
    if current_user.user_type != "customer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="customer",
        switch_url=url_for("logout", next=url_for("customer_signin"))
    )
    active_tab = request.args.get("tab", "customer-profile")
    if active_tab not in {"customer-profile", "customer-orders", "customer-loyalty"}:
        active_tab = "customer-profile"
    return render_template("customer-dashboard.html", active_tab=active_tab)

#Let customers update their core profile details here and keep the session data in sync afterwards.
@app.route("/customer-profile", methods=["GET", "POST"])
@login_required
def customer_profile():
    if current_user.user_type != "customer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="customer",
        switch_url=url_for("logout", next=url_for("customer_signin"))
    )

    db = get_db()

    if request.method == "POST":
        name = request.form.get("name", "").strip() 
        email = request.form.get("email", "").strip().lower()
        phone_number = request.form.get("phone_number", "").strip() 
        address = request.form.get("address", "").strip() 

        if not all([name, email, phone_number]):
            db.close()
            flash("Name, email, and phone number are required.", "error")
            return redirect(url_for("customer_profile"))
            
            
        
        if not name.replace(" ", "").isalpha() or len(name) < 2 or len(name) > 30:
            flash("Name can only contain letters and must be between 2-30 characters", "error")
            return redirect(url_for("customer_profile"))
        
        clean_phone = phone_number.strip()

        if clean_phone.startswith("+"):
            clean_phone = clean_phone[1:]


        clean_phone = (
            clean_phone.replace(" ", "")
               .replace("-", "")
               .replace("(", "")
               .replace(")", "")
)


        if not clean_phone.isdigit() or not (7 <= len(clean_phone) <= 15):
            flash("Phone number must be 7–15 digits and contain only numbers.", "error")
            return redirect(url_for("customer_profile"))
        
        
        if not is_valid_email(email):
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("customer_profile"))
        
        if address and not is_valid_address(address):
            flash("Please enter a valid address", "error")
            return redirect(url_for("customer_profile"))
            
        existing_customer = db.execute(
            """
            SELECT customer_id
            FROM customer
            WHERE email = ? AND customer_id != ?
            """,
            (email, current_user.id)
        ).fetchone()

        if existing_customer:
            db.close()
            flash("An account with this email already exists.", "error")
            return redirect(url_for("customer_profile"))


        db.execute(
            """
            UPDATE customer
            SET name = ?, email = ?, phone_number = ?, address = ?
            WHERE customer_id = ?
            """,
            (name, email, clean_phone, address, current_user.id)
        )
        db.commit()
        db.close()

        current_user.name = name
        current_user.email = email

        flash("Profile updated successfully.", "success")
        return redirect(url_for("customer_dashboard", tab="customer-profile"))

    customer = db.execute(
        """
        SELECT name, email, phone_number, address
        FROM customer
        WHERE customer_id = ?
        """,
        (current_user.id,)
    ).fetchone()

    db.close()
    if request.args.get("partial") == "1":
        return render_template("customer-profile.html", customer=customer)

    return redirect(url_for("customer_dashboard", tab="customer-profile"))

#Load the customer's order history and support partial rendering for the dashboard tab view.
@app.route("/customer-orders")
@login_required
def customer_orders():
    if current_user.user_type != "customer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="customer",
        switch_url=url_for("logout", next=url_for("customer_signin"))
    )

    db = get_db()
    orders = get_customer_orders(db, current_user.id)
    db.close()

    if request.args.get("partial") == "1":
        return render_template("customer-orders.html", orders=orders)

    return redirect(url_for("customer_dashboard", tab="customer-orders"))

#Export the customers order history as csv 
@app.route("/customer-orders/export")
@login_required
def export_customer_orders():
    if current_user.user_type != "customer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="customer",
        switch_url=url_for("logout", next=url_for("customer_signin"))
    )

    db = get_db()
    orders = get_customer_orders(db, current_user.id)
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
    "Order ID", 
    "Date", 
    "Status",
    "Method", 
    "Products",
    "Total",
    ])

    for order in orders:
        products = ", ".join(
            f"{item['name']} x{item['quantity']} "
            for item in order["items"]
        )
        writer.writerow([
        order["order_id"],
        order["order_date"],
        order["status"],
        order["collection_or_delivery"],
        products,
        order["total_price"]
    ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=customer_orders.csv"}
    )


#Show the customer's current points and the rewards they can unlock or redeem.
@app.route("/customer-loyalty")
@login_required
def customer_loyalty():
    if current_user.user_type != "customer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="customer",
        switch_url=url_for("logout", next=url_for("customer_signin"))
    )

    db = get_db()

    customer = db.execute(
        """
        SELECT
            name,
            loyalty_points
        FROM customer
        WHERE customer_id = ?
        """,
        (current_user.id,)
    ).fetchone()

    db.close()

    if not customer:
        return "Unauthorized", 403

    points = customer["loyalty_points"] or 0

    rewards = get_loyalty_rewards(points)

    if request.args.get("partial") == "1":
        return render_template(
            "customer-loyalty.html",
            customer=customer,
            points=points,
            rewards=rewards
        )

    return redirect(url_for("customer_dashboard", tab="customer-loyalty"))

"""Producer Facing Pages"""


#Register a new producer account
@app.route("/producer-signup", methods= ["GET", "POST"])
def producer_signup():
    if request.method == "POST":
        
        business_registration_number = request.form.get("business_registration_number", "").strip()
        business_name = request.form.get("business_name", "").strip()
        business_address = request.form.get("business_address", "").strip()
        
        business_email = request.form.get("business_email", "").strip().lower() 
        business_phone_number = request.form.get("business_phone_number", "").strip()
        
        
        
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        checkbox = request.form.get("checkbox")


        
        if not all([business_registration_number, business_name, business_address, business_email, business_phone_number, password, confirm_password]):
            flash("All fields are required", "error")
            return redirect(url_for("producer_signup"))
        
        
        
        if not is_alphanumeric(business_registration_number, allow_spaces=True):
            flash("Business registration number must only contain letters and numbers", "error")
            return redirect(url_for("producer_signup"))

        if len(business_registration_number) > 30:
            flash("Business registration number must be less than 30 characters", "error")
            return redirect(url_for("producer_signup"))

        if not is_alphanumeric(business_name, allow_spaces=True):
            flash("Business name must only contain letters and numbers ", "error")
            return redirect(url_for("producer_signup"))

        if len(business_name) < 2 or len(business_name) > 30:
            flash("Business name must be between 2 and 30 characters", "error")
            return redirect(url_for("producer_signup"))
 
    
        if not is_valid_email(business_email):
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("producer_signup"))
        
        
        
        clean_phone = business_phone_number.strip()

        if clean_phone.startswith("+"):
            clean_phone = clean_phone[1:]


        clean_phone = (
            clean_phone.replace(" ", "")
               .replace("-", "")
               .replace("(", "")
               .replace(")", "")
)


        if not clean_phone.isdigit() or not (7 <= len(clean_phone) <= 15):
            flash("Phone number must be 7–15 digits and contain only numbers.", "error")
            return redirect(url_for("producer_signup"))
                
        if not is_valid_address(business_address) :
            flash("Please enter a valid business address", "error")
            return redirect(url_for("producer_signup"))
        
        if not (8 <= len(password) <= 64):
            flash("Password must be between 8 and 64 characters long.", "error")
            return redirect(url_for("producer_signup"))
        
        if password != confirm_password:
            flash("Passwords do not match", "error")
            return redirect(url_for("producer_signup"))
        
        if not checkbox:
            flash("You must accept the Terms and Conditions.", "error")
            return redirect(url_for("producer_signup"))
        
        
        hashed_pw = generate_password_hash(password)
        

        
        db = get_db()
        existing_producer = db.execute( "SELECT producer_id FROM producer WHERE business_email = ?", (business_email,) ).fetchone() 
        if existing_producer: 
            db.close() 
            flash("An account with this email already exists.", "error") 
            return redirect(url_for("producer_signup"))
        
        existing_business = db.execute("SELECT producer_id FROM producer WHERE business_registration_number = ?", (business_registration_number,)).fetchone()

        if existing_business:
            db.close()
            flash("This business registration number is already registered.", "error")
            return redirect(url_for("producer_signup"))
        try:
            db.execute(
                "INSERT INTO producer (business_registration_number, business_name, business_email, business_phone_number, password_hash, business_address, description, image_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (business_registration_number, business_name, business_email, clean_phone, hashed_pw, business_address, None, None)
            )
            
            db.commit()
            
            db.close()
            flash("Registration successful!", "success")
            return redirect(url_for("producer_signin"))
            
        except Exception as e:
            print(e)
            flash(f"Error: {e}", "error")
            return redirect(url_for("producer_signup"))

    return render_template("producer-signup.html")
    

        
#Authenticate the producer and send them straight to their dashboard once the login succeeds.

@app.route("/producer-signin", methods = ["POST", "GET"])
def producer_signin():
    if current_user.is_authenticated:
        return redirect(url_for("homepage"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        
        if not is_valid_email(email):
            flash("Please enter a valid email address", "error")
            return redirect(url_for("producer_signin"))
        
        db = get_db()
        user = db.execute("SELECT * FROM producer WHERE business_email=?", 
        (email,)).fetchone()
        db.close()

        if user and check_password_hash(user["password_hash"], password):
            login_user(User(
                id=user["producer_id"],
                name=user["business_name"],
                email=user["business_email"],
                password_hash=user["password_hash"],
                user_type="producer"
            ), remember=True)
            return redirect(url_for("producer_dashboard"))
        else:
            flash("Invalid email or password", "error")
            return render_template("producer-signin.html")

    return render_template("producer-signin.html")

#Save producer profile changes here, including the  profile image and sustainability details.
@app.route("/producer-profile", methods=["GET", "POST"])
@login_required
def producer_profile():
    if current_user.user_type != "producer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="producer",
        switch_url=url_for("logout", next=url_for("producer_signin"))
    )

    db = get_db()

    if request.method == "POST":
        business_name = request.form.get("business_name", "").strip()
        business_email = request.form.get("business_email", "").strip().lower()
        business_phone_number = request.form.get("business_phone_number", "").strip()
        business_address = request.form.get("business_address", "").strip()
        description = request.form.get("description", "").strip()
        production_method = request.form.get("production_method", "").strip()
        sustainability_info = request.form.get("sustainability_info", "").strip()


        if not all([business_name, business_email, business_phone_number, business_address]):
            db.close()
            flash("Business name, email, phone number, and address are required.", "error")
            
            return redirect(url_for("producer_dashboard"))
        
        
        
        if not is_alphanumeric(business_name, allow_spaces=True) or len(business_name) < 2 or len(business_name) > 30:
            flash("Business Name can only contain letters and numbers and must be between 2-30 characters", "error")
            return redirect(url_for("producer_dashboard"))

        if not is_valid_email(business_email):
            db.close()
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("producer_dashboard"))
        
        clean_phone = business_phone_number.strip()

        if clean_phone.startswith("+"):
            clean_phone = clean_phone[1:]


        clean_phone = (
            clean_phone.replace(" ", "")
               .replace("-", "")
               .replace("(", "")
               .replace(")", "")
)


        if not clean_phone.isdigit() or not (7 <= len(clean_phone) <= 15):
            flash("Phone number must be 7–15 digits and contain only numbers.", "error")
            return redirect(url_for("producer_dashboard"))
        
        
        
        if not is_valid_address(business_address):
            flash("Please enter a valid business address", "error")
            return redirect(url_for("producer_dashboard"))
        
        
            
        if description and (not is_alphanumeric(description, allow_spaces=True) or len(description) < 10 or len(description) > 500):
            flash("Description can only contain letters and must be between 10 and 500 characters long", "error")
            return redirect(url_for("producer_dashboard"))

        
        
        
        if production_method and (not is_alphanumeric(production_method, allow_spaces=True) or len(production_method) > 500):
            flash("Production methods can only contain letters and numbers and cannot be greater than 500 characters", "error")
            return redirect(url_for("producer_dashboard"))

        if sustainability_info and (not is_alphanumeric(sustainability_info, allow_spaces=True) or len(sustainability_info) > 500):
            flash("Sustainability Info can only contain letters and numbers and cannot be greater than 500 characters", "error")
            return redirect(url_for("producer_dashboard"))
        
        existing_producer = db.execute(
            """
            SELECT producer_id
            FROM producer
            WHERE business_email = ? AND producer_id != ?
            """,
            (business_email, current_user.id)
        ).fetchone()

        if existing_producer:
            db.close()
            flash("An account with this email already exists.", "error")
            return redirect(url_for("producer_dashboard"))
        
        current_producer = db.execute(
            "SELECT description, production_method, sustainability_info, image_url FROM producer WHERE producer_id = ?",
            (current_user.id,)
        ).fetchone()

        final_description = description if description else current_producer["description"]
        final_production_method = production_method if production_method else current_producer["production_method"]
        final_sustainability_info = sustainability_info if sustainability_info else current_producer["sustainability_info"]
                            

        image_url= None
        profile_image = request.files.get("profile_image")
        if profile_image and profile_image.filename != "":
            image_url = save_uploaded_image(profile_image, "profiles")
        if image_url:
            db.execute(
                """
                UPDATE producer
                SET business_name = ?,
                    business_email = ?,
                    business_phone_number = ?,
                    business_address = ?,
                    description = ?,
                    production_method = ?,
                    sustainability_info = ?,
                    image_url = ?
                WHERE producer_id = ?
                """,
                (
                    business_name,
                    business_email,
                    clean_phone,
                    business_address,
                    final_description,
                    final_production_method,
                    final_sustainability_info,
                    image_url,
                    current_user.id,
                ),
            )
        else:
            db.execute(
                """
                UPDATE producer
                SET business_name = ?,
                    business_email = ?,
                    business_phone_number = ?,
                    business_address = ?,
                    description = ?,
                    production_method = ?,
                    sustainability_info = ?
                WHERE producer_id = ?
                """,
                (
                    business_name,
                    business_email,
                    clean_phone,
                    business_address,
                    final_description,
                    final_production_method,
                    final_sustainability_info,
                    current_user.id,
                ),
            )

        db.commit()
        db.close()

        current_user.name = business_name
        current_user.email = business_email

        flash("Producer profile updated successfully.", "success")
        return redirect(url_for("producer_dashboard"))

    producer = db.execute(
        """
        SELECT
            business_registration_number,
            business_name,
            business_email,
            business_phone_number,
            business_address,
            description,
            image_url,
            production_method,
            sustainability_info
        FROM producer
        WHERE producer_id = ?
        """,
        (current_user.id,),
    ).fetchone()

    metrics = get_producer_metrics(db, current_user.id)
    orders = get_producer_orders(db, current_user.id)
    recent_orders = orders
    profile_complete, missing_profile_fields = get_producer_profile_completion(producer)

    db.close()

    return render_template(
        "producer-dashboard.html",
        producer=producer,
        metrics=metrics,
        orders=orders,
        recent_orders=recent_orders,
        profile_complete=profile_complete,
        missing_profile_fields=missing_profile_fields,
    )

#Gather the producer summary, profile details, and recent orders so the dashboard has the main business snapshot.
@app.route("/producer-dashboard")
@login_required
def producer_dashboard():
    if current_user.user_type != "producer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="producer",
        switch_url=url_for("logout", next=url_for("producer_signin"))
    )

    db = get_db()

    metrics = get_producer_metrics(db, current_user.id)

    producer = db.execute(
        """
        SELECT
            business_registration_number,
            business_name,
            business_email,
            business_phone_number,
            business_address,
            description,
            image_url,
            production_method,
            sustainability_info
        FROM producer
        WHERE producer_id = ?
        """,
        (current_user.id,),
    ).fetchone()
    
    recent_orders = get_producer_orders(db, current_user.id)
    orders = get_producer_orders(db, current_user.id)
    profile_complete, missing_profile_fields = get_producer_profile_completion(producer)



    db.close()

    return render_template(
        "producer-dashboard.html",
        metrics=metrics,
        orders=orders,
        producer=producer,
        recent_orders=recent_orders,
        profile_complete=profile_complete,
        missing_profile_fields=missing_profile_fields,
    )

#Load the producer's product list for the management screen.
@app.route("/manage-products")
@login_required
def manage_products():
    if current_user.user_type != "producer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="producer",
        switch_url=url_for("logout", next=url_for("producer_signin"))
    )
    
    db = get_db()
    products = get_producer_products(db, current_user.id)
    db.close()
    return render_template("producer-products.html", products = products)


#Create a new product record and set its availability based on the opening stock level.
@app.route("/add-product", methods=["POST"])
@login_required
def add_product():
    if current_user.user_type != "producer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="producer",
        switch_url=url_for("logout", next=url_for("producer_signin"))
    )

    product_name = request.form.get("product_name", "").strip() 
    description = request.form.get("description", "").strip() 
    price = request.form.get("price")
    stock = request.form.get("stock")
    category = request.form.get("category", "").strip() 
    product_image = request.files.get("product_image")

    if not all([product_name, description, price, stock, category, product_image]):
        flash("All fields are required", "error")
        return redirect(url_for("manage_products"))
    
    if len(product_name) < 2 or len(product_name) > 50:
        flash("Product name must be between 2 and 50 characters long", "error")
        return redirect(url_for("manage_products"))
    
    if not is_alphanumeric(product_name, allow_spaces=True):
        flash("Product name can only contain letters and numbers", "error")
        return redirect(url_for("manage_products"))
    
    if len(description) < 10 or len(description) > 500:
        flash("Description must be between 10 and 500 characters long", "error")
        return redirect(url_for("manage_products"))
    
    if not is_alphanumeric(description, allow_spaces=True):
        flash("Description must only contain letters and numbers", "error")
        return redirect(url_for("manage_products"))
    

    
    allowed_categories = ["Fruit", "Vegetables", "Dairy", "Bakery", "Drinks", "Meat", "Other"]

    if category not in allowed_categories:
        flash("Please select a valid category.", "error")
        return redirect(url_for("manage_products"))
    
    
        
    try: 
        price = float(request.form.get("price")) 
        stock = int(request.form.get("stock")) 
    except (TypeError, ValueError): 
        flash("Price and stock must be valid numbers.", "error")
        return redirect(url_for("manage_products")) 
    if price <= 0 or price > 10000:  
        flash("Price must be greater than 0 and reasonable", "error")
        return redirect(url_for("manage_products"))
    if stock < 0 or stock > 10000: 
        flash("Stock cannot be negative and must be reasonable", "error") 
        return redirect(url_for("manage_products")) 

    

    image_url = save_uploaded_image(product_image, "products")
    is_available = 1 if int(stock) > 0 else 0
    # 1 represents true 
    # 0 represents false

    db = get_db()
    db.execute("""
        INSERT INTO product (
            producer_id,
            name,
            description,
            price,
            category,
            image_url,
            is_available,
            stock
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        current_user.id,
        product_name,
        description,
        float(price),
        category,
        image_url,
        is_available,
        int(stock)
    ))
    db.commit()
    db.close()

    flash("Product added successfully!", "success")
    return redirect(url_for("manage_products"))

#Update the product details here, keeping the existing image when no new upload is provided.
@app.route("/update-product/<int:product_id>", methods=["POST"])
@login_required
def update_product(product_id):
    if current_user.user_type != "producer":
        return "Unauthorized", 403

    product_name = request.form.get("product_name", "").strip() 
    description = request.form.get("description", "").strip() 
    price = request.form.get("price")
    stock = request.form.get("stock")
    category = request.form.get("category", "").strip() 
    product_image = request.files.get("product_image")
    

    if not all([product_name, description, price, stock, category]):
        flash("All fields are required.", "error")
        return redirect(url_for("manage_products"))
    
    if len(product_name) < 2 or len(product_name) > 50:
        flash("Product name must be between 2 and 50 characters long", "error")
        return redirect(url_for("manage_products"))
    
    if not is_alphanumeric(product_name, allow_spaces=True):
        flash("Product name can only contain letters and numbers", "error")
        return redirect(url_for("manage_products"))
    
    if len(description) < 10 or len(description) > 500:
        flash("Description must be between 10 and 500 characters long", "error")
        return redirect(url_for("manage_products"))
    
    if not is_alphanumeric(description, allow_spaces=True):
        flash("Description must only contain letters and numbers", "error")
        return redirect(url_for("manage_products"))
    
    
    try: 
        price = float(request.form.get("price")) 
        stock = int(request.form.get("stock")) 
    except (TypeError, ValueError): 
        flash("Price and stock must be valid numbers.", "error")
        return redirect(url_for("manage_products")) 
    if price <= 0 or price > 10000:  
        flash("Price must be greater than 0 and reasonable", "error")
        return redirect(url_for("manage_products"))
    if stock < 0 or stock > 10000: 
        flash("Stock cannot be negative and must be reasonable", "error") 
        return redirect(url_for("manage_products")) 
    
    allowed_categories = ["Fruit", "Vegetables", "Dairy", "Bakery", "Drinks", "Meat", "Other"]

    if category not in allowed_categories:
        flash("Please select a valid category.", "error")
        return redirect(url_for("manage_products"))

    db = get_db()
    existing_product = db.execute(
        """
        SELECT product_id, image_url
        FROM product
        WHERE product_id = ? AND producer_id = ?
        """,
        (product_id, current_user.id),
    ).fetchone()

    if not existing_product:
        db.close()
        return "Unauthorized", 403

    image_url = save_uploaded_image(product_image, "products") or existing_product["image_url"]
    is_available = 1 if int(stock) > 0 else 0

    db.execute(
        """
        UPDATE product
        SET name = ?,
            description = ?,
            price = ?,
            category = ?,
            image_url = ?,
            is_available = ?,
            stock = ?
        WHERE product_id = ? AND producer_id = ?
        """,
        (
            product_name,
            description,
            float(price),
            category,
            image_url,
            is_available,
            int(stock),
            product_id,
            current_user.id,
        ),
    )
    db.commit()
    db.close()

    flash("Product updated successfully.", "success")
    return redirect(url_for("manage_products"))

#Only delete products that belong to this producer and are not already tied to past orders.
@app.route("/delete-product/<int:product_id>", methods=["POST"])
@login_required
def delete_product(product_id):
    if current_user.user_type != "producer":
        return "Unauthorized", 403

    db = get_db()
    product = db.execute(
        """
        SELECT product_id
        FROM product
        WHERE product_id = ? AND producer_id = ?
        """,
        (product_id, current_user.id),
    ).fetchone()

    if not product:
        db.close()
        return "Unauthorized", 403

    linked_order = db.execute(
        "SELECT 1 FROM order_items WHERE product_id = ? LIMIT 1",
        (product_id,),
    ).fetchone()

    if linked_order:
        db.close()
        flash("This product cannot be deleted because it exists in order history.", "error")
        return redirect(url_for("manage_products"))

    db.execute("DELETE FROM basket_item WHERE product_id = ?", (product_id,))
    db.execute(
        "DELETE FROM product WHERE product_id = ? AND producer_id = ?",
        (product_id, current_user.id),
    )
    db.commit()
    db.close()

    flash("Product deleted successfully.", "success")
    return redirect(url_for("manage_products"))


#Bulk update stock levels from the stock management page and keep product availability aligned with the new values.
@app.route("/producer-stock", methods=["GET", "POST"])
@login_required
def producer_stock():
    if current_user.user_type != "producer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="producer",
        switch_url=url_for("logout", next=url_for("producer_signin"))
    )

    db = get_db()

    if request.method == "POST":
        product_ids = request.form.getlist("product_id")
        quantities = request.form.getlist("stock")

        for product_id, stock in zip(product_ids, quantities):
            try:
                stock_value = int(stock)
            except (TypeError, ValueError):
                db.close()
                flash("Stock must be a valid number.", "error")
                return redirect(url_for("producer_stock"))
            if stock_value < 0 or stock_value > 10000: 
                db.close()
                flash("Stock cannot be negative and must be reasonable", "error") 
                return redirect(url_for("producer_stock")) 
            is_available = 1 if stock_value > 0 else 0

            db.execute(
                """
                UPDATE product
                SET stock = ?, is_available = ?
                WHERE product_id = ? AND producer_id = ?
                """,
                (stock_value, is_available, product_id, current_user.id),
            )


        db.commit()
        db.close()
        flash("Stock updated successfully.", "success")
        return redirect(url_for("producer_stock"))

    products = db.execute(
        """
        SELECT
            product_id,
            name,
            category,
            image_url,
            stock
        FROM product
        WHERE producer_id = ?
        ORDER BY name COLLATE NOCASE
        """,
        (current_user.id,),
    ).fetchall()

    db.close()
    return render_template("producer-stock.html", products=products)


#Show the producer's orders with the order items already grouped for display.
@app.route("/producer-orders")
@login_required
def producer_orders():
    if current_user.user_type != "producer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="producer",
        switch_url=url_for("logout", next=url_for("producer_signin"))
    )

    db = get_db()
    orders = get_producer_orders(db, current_user.id)
    db.close()
    return render_template("producer-orders.html", orders=orders)

#Export producers order as csv
@app.route("/export-producer-orders")
@login_required
def export_producer_orders():
    if current_user.user_type != "producer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="producer",
        switch_url=url_for("logout", next=url_for("producer_signin"))
    )

    db = get_db()

    orders = get_producer_orders(db, current_user.id)

    db.close()

    output = io.StringIO()
    writer = csv.writer(output)


    writer.writerow([
        "Order ID",
        "Order Date",
        "Customer Name",
        "Method",
        "Products",
        "Total"
    ])


    for order in orders:

        products = ", ".join(
            f"{item['name']} x{item['quantity']}"
            for item in order["items"]
        )

        writer.writerow([
            order["order_id"],
            order["order_date"],
            order["customer_name"],
            order["collection_or_delivery"],
            products,  
            f"{order['producer_total']:.2f}"
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=producer_orders.csv"
        }
    )


#Change the order status only if this producer owns part of the order and the new step is allowed.
@app.route("/producer-orders/<int:order_id>/status", methods=["POST"])
@login_required
def update_producer_order_status(order_id):
    if current_user.user_type != "producer":
        return render_template(
        "error-403.html",
        user_type=current_user.user_type,
        required_type="producer",
        switch_url=url_for("logout", next=url_for("producer_signin"))
    )

    new_status = request.form.get("status")
    db = get_db()

    order = db.execute(
        """
        SELECT DISTINCT
            o.order_id,
            o.status,
            o.collection_or_delivery
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.order_id
        JOIN product p ON p.product_id = oi.product_id
        WHERE o.order_id = ? AND p.producer_id = ?
        """,
        (order_id, current_user.id),
    ).fetchone()

    if not order:
        db.close()
        return "Unauthorized", 403

    if new_status not in get_next_statuses(order["status"], order["collection_or_delivery"]):
        db.close()
        flash("That order status change is not allowed.", "error")
        return redirect(url_for("producer_orders"))

    db.execute(
        "UPDATE orders SET status = ? WHERE order_id = ?",
        (new_status, order_id),
    )
    db.commit()
    db.close()

    flash("Order status updated successfully.", "success")
    return redirect(url_for("producer_orders"))



#These route currently just serves the under construction pages template as they will be implemented in the future development
@app.route("/forgot-password")
def forgot_password():
    return render_template("under-construction.html", page_title="Forgot Password")

@app.route("/terms-condition") 
def terms_condition():
    return render_template("under-construction.html", page_title="Terms & Condition")

@app.route("/privacy-policy")
def privacy_policy():
    return render_template("under-construction.html", page_title="Privacy & Policy")



#End the current session and optionally send the user back to the page the app requested.
@app.route('/logout')
def logout():
    next_url = request.args.get("next")
    logout_user()

    if next_url:
        return redirect(next_url)

    return redirect(url_for('homepage'))


#Deletes the user account 
@app.route("/delete-account", methods=["POST"])
@login_required
def delete_account():
    db = get_db()
    if current_user.user_type == "customer":
        db.execute(
            "DELETE FROM customer WHERE customer_id = ?",
            (current_user.id,)
            )
    elif current_user.user_type == "producer":
        db.execute(
            "DELETE FROM producer WHERE producer_id = ?",
    (current_user.id,)
    )

    db.commit()
    db.close()

    logout_user()
    flash("Account deleted successfully.", "success")
    return redirect(url_for("homepage"))


#Render a custom 404 page so missing routes still feel consistent with the rest of the app.
@app.errorhandler(404)
def page_not_found(e):
    return render_template("error-404.html"), 404


if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True)
