"""Seed the database with a few sample companies + products so the marketplace
isn't empty on first run. Idempotent: skips anything that already exists (by
company email / product name).

Usage (from productiq/backend/):
    ./.venv/bin/python seed.py        # or: python seed.py inside your env
"""
from sqlmodel import Session, select

from app.db import engine, init_db
from app.models import Company, Product


COMPANIES = [
    {
        "name": "Velocity Mobility",
        "email": "support@velocitymobility.example",
        "products": [
            {
                "name": "Velocity V2 Electric Scooter",
                "category": "Personal Mobility",
                "description": (
                    "Urban electric scooter with a 350W motor, regenerative braking, "
                    "front headlight, horn, and a 25 km range. Common service items: "
                    "fuses (F1–F4), brake pads, and battery health checks."
                ),
            },
            {
                "name": "Velocity Pro Helmet Cam",
                "category": "Accessories",
                "description": "Helmet-mounted 1080p camera with fall detection and Bluetooth.",
            },
        ],
    },
    {
        "name": "ClearStream Appliances",
        "email": "care@clearstream.example",
        "products": [
            {
                "name": "ClearStream RO Water Purifier",
                "category": "Home Appliances",
                "description": (
                    "Reverse-osmosis water purifier with a 4-stage filter, UV sterilization, "
                    "and a 10L storage tank. Filters should be replaced every 6–12 months."
                ),
            },
            {
                "name": "ClearStream FrostFree Refrigerator 280L",
                "category": "Home Appliances",
                "description": "Double-door frost-free refrigerator with inverter compressor and humidity control.",
            },
        ],
    },
]


def run() -> None:
    init_db()
    created_c = created_p = 0
    with Session(engine) as session:
        for c in COMPANIES:
            company = session.exec(
                select(Company).where(Company.email == c["email"])
            ).first()
            if not company:
                company = Company(name=c["name"], email=c["email"])
                session.add(company)
                session.commit()
                session.refresh(company)
                created_c += 1

            for p in c["products"]:
                exists = session.exec(
                    select(Product).where(
                        Product.company_id == company.id,
                        Product.name == p["name"],
                    )
                ).first()
                if exists:
                    continue
                session.add(Product(company_id=company.id, **p))
                created_p += 1
            session.commit()

    print(f">> seed complete: +{created_c} companies, +{created_p} products")


if __name__ == "__main__":
    run()
