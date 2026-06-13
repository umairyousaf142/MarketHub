# MarketHub

> 🚀 Production-grade Amazon-style multi-vendor marketplace backend built with Django REST Framework.

MarketHub is a scalable and production-ready multi-vendor e-commerce marketplace backend designed using a **Modular Monolith Architecture**. It enables multiple vendors to sell products through a single platform while providing robust inventory management, order processing, payments, analytics, and notification systems.

---

## ✨ Features

### 👥 User Management

* JWT Authentication & Authorization
* Role-Based Access Control (Admin, Vendor, Customer)
* Custom User Model
* Multiple User Addresses
* Email Verification

### 🏪 Vendor Management

* Vendor Onboarding Workflow
* KYC Document Verification
* Vendor Approval State Machine
* Commission Plans & Vendor Settlements

### 📦 Product Catalog

* Nested Categories (MPTT)
* Products & Variants
* Product Attributes (Size, Color, etc.)
* Brand Management
* Full-Text Search Support

### 📊 Inventory Management

* Transaction-Based Stock Tracking
* Inventory Audit Trail
* Low Stock Alerts
* Warehouse-Ready Design

### 🛒 Shopping Experience

* Guest & Authenticated Carts
* Cart Merge on Login
* Price Snapshotting
* Coupon & Discount Engine

### 📋 Order Management

* Multi-Vendor Order Splitting
* Vendor-Specific SubOrders
* Order State Machine
* Invoice Generation
* Order Tracking

### 💳 Payments

* Payment Processing
* Commission Calculation
* Vendor Settlements
* Refund Support
* Stripe-Ready Architecture

### ⭐ Reviews & Ratings

* Verified Purchase Reviews
* Product Ratings
* Review Moderation

### 🔔 Notifications

* Email Notifications
* SMS Notifications
* In-App Notifications
* Event-Driven Architecture

### 📈 Analytics

* Revenue Analytics
* Vendor Performance Tracking
* Top Products Reporting
* Daily Analytics Snapshots

---

## 🏗️ Architecture

MarketHub follows a **Modular Monolith Architecture**, allowing clean separation of business domains while maintaining deployment simplicity.

```text
apps/
├── accounts/
├── vendors/
├── catalog/
├── inventory/
├── cart/
├── orders/
├── payments/
├── coupons/
├── reviews/
├── notifications/
└── analytics/
```

Each module is isolated with its own models, serializers, services, permissions, and API endpoints.

---

## 🛠️ Tech Stack

| Layer           | Technology                  |
| --------------- | --------------------------- |
| Backend         | Django 5.x                  |
| API             | Django REST Framework       |
| Database        | PostgreSQL                  |
| Cache           | Redis                       |
| Background Jobs | Celery + Celery Beat        |
| Authentication  | SimpleJWT                   |
| Search          | PostgreSQL Full-Text Search |
| Future Search   | Elasticsearch               |
| Containers      | Docker & Docker Compose     |
| Web Server      | Nginx + Gunicorn            |
| CI/CD           | GitHub Actions              |

---

## 🚀 Getting Started

### Clone the Repository

```bash
git clone https://github.com/your-username/MarketHub.git
cd MarketHub
```

### Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Configure Environment Variables

Create a `.env` file:

```env
DEBUG=True

DB_NAME=markethub
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost
DB_PORT=5432

SECRET_KEY=your-secret-key
```

### Run Migrations

```bash
python manage.py migrate
```

### Start Development Server

```bash
python manage.py runserver
```

---

## 📅 Development Roadmap

* [x] Project Planning & Architecture
* [ ] Authentication & RBAC
* [ ] Vendor Management
* [ ] Product Catalog
* [ ] Inventory Management
* [ ] Cart System
* [ ] Order Management
* [ ] Payments & Settlements
* [ ] Coupons & Discounts
* [ ] Reviews & Ratings
* [ ] Notifications
* [ ] Redis Caching
* [ ] Analytics Dashboard
* [ ] CI/CD Pipeline

---

## 🧪 Testing

```bash
pytest
```

---

## 🔒 Security

* JWT Authentication
* Role-Based Access Control
* Serializer-Level Validation
* Rate Limiting
* Environment-Based Secrets
* Soft Delete Strategy

---

## 📄 License

This project is licensed under the MIT License.

---

## 👨‍💻 Author

Developed as a production-grade learning and portfolio project to demonstrate scalable backend architecture using Django, DRF, PostgreSQL, Redis, Celery, and Docker.
