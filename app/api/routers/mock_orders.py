"""Mock Orders API for testing inbound-order-status template."""

from fastapi import APIRouter, HTTPException

router = APIRouter()

MOCK_ORDERS = {
    "ORD-1001": {
        "order_id": "ORD-1001",
        "status": "PAYMENT_RECEIVED",
        "items": [
            {"name": "Dolo 650mg", "quantity": 2, "price": 30.0},
            {"name": "Crocin Advance", "quantity": 1, "price": 25.0},
        ],
        "total_price": 85.0,
        "delivery_address": "42 MG Road, Koramangala, Bangalore, 560034",
        "estimated_delivery_date": "2026-04-18",
        "payment_method": "UPI",
    },
    "ORD-1002": {
        "order_id": "ORD-1002",
        "status": "PACKED",
        "items": [
            {"name": "Azithromycin 500mg", "quantity": 1, "price": 120.0},
            {"name": "Vitamin D3 Capsules", "quantity": 1, "price": 350.0},
        ],
        "total_price": 470.0,
        "delivery_address": "15 Sector 62, Noida, 201301",
        "estimated_delivery_date": "2026-04-17",
        "payment_method": "Credit Card",
    },
    "ORD-1003": {
        "order_id": "ORD-1003",
        "status": "IN_TRANSIT",
        "items": [
            {"name": "Pantoprazole 40mg", "quantity": 3, "price": 45.0},
            {"name": "ORS Sachets", "quantity": 10, "price": 10.0},
        ],
        "total_price": 235.0,
        "delivery_address": "78 Anna Nagar, Chennai, 600040",
        "estimated_delivery_date": "2026-04-16",
        "payment_method": "COD",
    },
    "ORD-1004": {
        "order_id": "ORD-1004",
        "status": "OUT_FOR_DELIVERY",
        "items": [
            {"name": "Cetirizine 10mg", "quantity": 1, "price": 35.0},
            {"name": "Betadine Ointment", "quantity": 1, "price": 80.0},
        ],
        "total_price": 115.0,
        "delivery_address": "23 Banjara Hills, Hyderabad, 500034",
        "estimated_delivery_date": "2026-04-16",
        "payment_method": "UPI",
    },
    "ORD-1005": {
        "order_id": "ORD-1005",
        "status": "DELIVERED",
        "items": [
            {"name": "Metformin 500mg", "quantity": 2, "price": 55.0},
            {"name": "B-Complex Tablets", "quantity": 1, "price": 120.0},
        ],
        "total_price": 230.0,
        "delivery_address": "9 Connaught Place, New Delhi, 110001",
        "estimated_delivery_date": "2026-04-14",
        "payment_method": "Debit Card",
        "delivered_at": "2026-04-14T14:30:00Z",
    },
    "ORD-1006": {
        "order_id": "ORD-1006",
        "status": "CANCELLED",
        "items": [
            {"name": "Amoxicillin 250mg", "quantity": 1, "price": 90.0},
        ],
        "total_price": 90.0,
        "delivery_address": "56 Salt Lake, Kolkata, 700091",
        "estimated_delivery_date": None,
        "payment_method": "UPI",
        "cancellation_reason": "Customer requested",
    },
    "ORD-1007": {
        "order_id": "ORD-1007",
        "status": "RETURN_INITIATED",
        "items": [
            {"name": "Calcium Tablets", "quantity": 1, "price": 200.0},
            {"name": "Iron Supplements", "quantity": 1, "price": 150.0},
        ],
        "total_price": 350.0,
        "delivery_address": "31 Viman Nagar, Pune, 411014",
        "estimated_delivery_date": "2026-04-12",
        "payment_method": "COD",
        "return_reason": "Wrong item delivered",
    },
}


@router.get("/api/mock/orders/{order_id}")
async def get_order(order_id: str):
    """Get a single mock order by ID."""
    order = MOCK_ORDERS.get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return order


@router.get("/api/mock/orders")
async def list_orders():
    """List all mock orders."""
    return {"orders": list(MOCK_ORDERS.values())}


@router.get("/api/mock/send-cart/{mobile_number}")
async def send_cart(mobile_number: str):
    """Mock send cart link to customer."""
    return {
        "success": True,
        "message": f"Cart link sent to {mobile_number}",
        "cart_url": f"https://example.com/cart?phone={mobile_number}",
    }
