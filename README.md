# 🍔 Lieferspatz – Full-Stack Food Delivery Platform

Lieferspatz is a modern food delivery platform built with FastAPI, Python, and JavaScript, designed to simulate a real-world delivery ecosystem similar to Uber Eats / Lieferando.

The platform supports customers, restaurants, and administrators, including real-time order updates, authentication, wallet systems, vouchers, and order management.

This project demonstrates backend architecture, API design, authentication, database modeling, and real-time communication.

## 🚀 Features

### 👤 Customer Features

- Browse restaurants
- Discover menus and items
- Add items to cart
- Checkout system
- Apply vouchers
- Wallet support
- Track orders
- Real-time order updates via WebSockets

### 🍽 Restaurant Features

- Restaurant dashboard
- Manage menu items
- Receive incoming orders
- Accept or reject orders
- Update order status
- View order history

### 🛠 Admin Features

- Admin dashboard
- View all restaurants
- Approve restaurant registrations
- Monitor orders
- System audit logs
- Manage platform visibility

## ⚡ Real-Time Order System

The system uses WebSockets to deliver live updates:
- Restaurants instantly receive new orders
- Customers get live status updates
- Admin can monitor system activity

This demonstrates event-driven architecture.

## 🧱 System Architecture

```
                ┌───────────────────────┐
                │       Customers       │
                │   Web / Mobile App    │
                └────────────┬──────────┘
                             │
                             ▼
                ┌───────────────────────┐
                │     FastAPI Server    │
                │   REST API + JWT      │
                └────────────┬──────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼

 ┌─────────────┐     ┌─────────────┐      ┌─────────────┐
 │ Auth System │     │ Order Logic │      │ Restaurants │
 │ JWT Login   │     │ Checkout    │      │ Menu Mgmt   │
 └──────┬──────┘     └──────┬──────┘      └──────┬──────┘
        │                   │                    │
        ▼                   ▼                    ▼

 ┌─────────────┐     ┌─────────────┐      ┌─────────────┐
 │ Wallets     │     │ Vouchers    │      │ Admin Tools │
 │ Payments    │     │ Discounts   │      │ Moderation  │
 └─────────────┘     └─────────────┘      └─────────────┘

                             │
                             ▼
                ┌───────────────────────┐
                │      Database         │
                │ SQLite / PostgreSQL   │
                └───────────────────────┘
```

Real-time updates handled through WebSockets reinforce the event-driven nature of this architecture.

The backend is designed using modular routers and clean architecture.

## 🧰 Tech Stack

### Backend

- Python
- FastAPI
- SQLAlchemy
- Pydantic
- JWT Authentication
- WebSockets

### Frontend

- HTML
- JavaScript
- Custom dashboards

### Database

- SQLite (development)
- Easily extendable to PostgreSQL

## 📁 Project Structure

```
lieferspatz/
│
├── main.py
├── database.py
├── models.py
├── schemas.py
│
├── auth.py
├── security.py
├── deps.py
│
├── routers/
│   ├── routers_auth.py
│   ├── routers_restaurants.py
│   ├── routers_orders.py
│   ├── routers_checkout.py
│   ├── routers_wallets.py
│   ├── routers_vouchers.py
│   ├── routers_admin.py
│   ├── routers_orders_admin.py
│   ├── routers_logs.py
│   └── routers_discovery.py
│
├── utils.py
├── ws.py
├── seed.py
│
└── requirements.txt
```

The project follows a modular router architecture, making it easy to scale and maintain.

## 🔐 Authentication & Security

The platform includes:

- JWT-based authentication
- Role-based access control
- Secure password hashing
- Protected endpoints

Roles supported:
- Customer
- Restaurant
- Admin

## 💳 Wallet & Voucher System

Customers can:

- Use internal wallet balance
- Apply promotional vouchers
- Combine payments with discounts

This simulates real-world delivery platform payment systems.

## 📦 Installation

1. Clone the repository
    ```
    git clone https://github.com/YOUR_USERNAME/lieferspatz.git
    cd lieferspatz
    ```
2. Create virtual environment
    ```
    python -m venv venv
    source venv/bin/activate
    ```
    **Windows**
    ```
    venv\Scripts\activate
    ```
3. Install dependencies
    ```
    pip install -r requirements.txt
    ```
4. Run the server
    ```
    uvicorn main:app --reload
    ```

Server will start at:

```
http://127.0.0.1:8000
```

## 📘 API Documentation

FastAPI automatically generates interactive documentation.

- Swagger UI: `http://127.0.0.1:8000/docs`
- Alternative docs: `http://127.0.0.1:8000/redoc`

## 🧪 Seed Development Data

You can populate the database with sample data.

```
python seed.py
```

This creates:
- Demo restaurants
- Demo menu items
- Sample users

## 📡 WebSocket Example

Real-time order updates are handled through WebSockets.

Example connection: `ws://localhost:8000/ws/orders`

Used for:
- Live restaurant order notifications
- Order status updates

## 🎯 Key Backend Concepts Demonstrated

This project showcases several production-grade backend patterns:
- REST API design
- Modular router architecture
- Database modeling
- Authentication & authorization
- WebSocket real-time updates
- Order lifecycle management
- Voucher & wallet systems
- Audit logging

## 🧠 What I Learned

Through building this project I practiced:
- Designing scalable APIs
- Structuring large FastAPI projects
- Building authentication systems
- Managing relational databases
- Implementing real-time communication
- Handling complex business logic

## 🚀 Future Improvements

Planned improvements include:
- PostgreSQL support
- Docker deployment
- Payment gateway integration
- Delivery driver system
- Push notifications
- Kubernetes deployment
- Microservice architecture

## 👨‍💻 Author

Your Name  
Backend Developer | Python | FastAPI | API Design  
GitHub: `https://github.com/YOUR_USERNAME`

## 💡 Why This Project Matters

This project simulates a real-world delivery platform backend and demonstrates how complex business logic can be structured into scalable API services.

## ⭐ If you like this project

Please consider giving it a star ⭐ on GitHub.

## 💡 Important tip for job applications

When recruiters see this project they should understand you know:

- Backend architecture
- API design
- Authentication
- Real-time systems
- Modular code structure

This README is structured exactly to show those skills.
