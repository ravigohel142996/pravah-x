"""
Agent-readable catalog.

This is the "agent-readable catalog" piece the track brief asks for:
a structured, queryable representation of a merchant's products that
an AI agent (ours, or in future any AI buyer) can reason over --
instead of an AI having to scrape an HTML storefront.
"""

from typing import Optional
from pydantic import BaseModel


class Product(BaseModel):
    id: str
    name: str
    description: str
    price_inr: int          # in rupees for readability; converted to paise for the payment gateway
    stock: int
    tags: list[str] = []


# In a real merchant integration this would come from the merchant's DB / product API.
# Kept in-memory here so the whole demo runs with zero external DB setup.
CATALOG: dict[str, Product] = {
    p.id: p
    for p in [
        Product(
            id="sku_001",
            name="Wireless Mechanical Keyboard",
            description="75% layout, hot-swappable switches, USB-C",
            price_inr=3499,
            stock=12,
            tags=["keyboard", "wireless", "mechanical", "electronics"],
        ),
        Product(
            id="sku_002",
            name="Ergonomic Mouse",
            description="Vertical design, reduces wrist strain",
            price_inr=1299,
            stock=25,
            tags=["mouse", "ergonomic", "electronics"],
        ),
        Product(
            id="sku_003",
            name="27-inch 4K Monitor",
            description="IPS panel, 60Hz, USB-C with 65W power delivery",
            price_inr=21999,
            stock=5,
            tags=["monitor", "display", "electronics"],
        ),
        Product(
            id="sku_004",
            name="Laptop Stand (Aluminium)",
            description="Adjustable height, foldable, fits 11-17 inch laptops",
            price_inr=1799,
            stock=40,
            tags=["stand", "accessory", "ergonomic"],
        ),
    ]
}


def get_catalog() -> list[Product]:
    """Return the full catalog. This is what an AI buyer/agent would query."""
    return list(CATALOG.values())


def find_product(query: str) -> Optional[Product]:
    """
    Very simple keyword matcher: looks for the query text inside product
    name, description or tags. Swap this for embeddings/vector search
    later -- kept simple so the demo is easy to follow and debug live.
    """
    query_lower = query.lower()
    for product in CATALOG.values():
        haystack = f"{product.name} {product.description} {' '.join(product.tags)}".lower()
        if any(word in haystack for word in query_lower.split()):
            return product
    return None


def get_product(product_id: str) -> Optional[Product]:
    return CATALOG.get(product_id)
