import os
import uuid
import time
import base64
from io import BytesIO
from typing import Optional, Dict, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

import qrcode
from bakong_khqr import KHQR

load_dotenv()

# =========================
# CONFIG (.env recommended)
# =========================
BAKONG_TOKEN = os.getenv("BAKONG_TOKEN", "").strip()

BANK_ACCOUNT = os.getenv("BANK_ACCOUNT", "yourname@aba").strip()
MERCHANT_NAME = os.getenv("MERCHANT_NAME", "My Shop").strip()
MERCHANT_CITY = os.getenv("MERCHANT_CITY", "Phnom Penh").strip()
STORE_LABEL = os.getenv("STORE_LABEL", "Shop").strip()
PHONE = os.getenv("PHONE", "").strip()
TERMINAL = os.getenv("TERMINAL", "POS-01").strip()
DEFAULT_CURRENCY = os.getenv("CURRENCY", "USD").strip()  # "USD" or "KHR"
SALE_TTL_SECONDS = int(os.getenv("SALE_TTL_SECONDS", "300"))  # default 5 minutes

# Create KHQR instance (token needed only for check_payment)
khqr = KHQR(BAKONG_TOKEN) if BAKONG_TOKEN else KHQR()

app = FastAPI(title="POS KHQR Backend", version="1.0.0")

# =========================
# CORS FIX (IMPORTANT)
# =========================
# Allow your HTML server (Live Server usually uses 5500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:5173",   # optional (Vite)
        "http://localhost:5173",  # optional (Vite)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# In-memory storage (demo)
# =========================
SALES: Dict[str, dict] = {}


def _refresh_sale_expiry(sale: dict) -> None:
    """Mark sale EXPIRED if TTL passed and not already finalized."""
    if sale.get("status") in ("PAID", "CANCELLED"):
        return
    now = int(time.time())
    if now > int(sale.get("expired_at", 0)):
        sale["status"] = "EXPIRED"


def qr_png_base64(payload: str) -> str:
    img = qrcode.make(payload)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# =========================
# Models
# =========================
class SaleCreateReq(BaseModel):
    amount: float = Field(..., gt=0, examples=[10])
    currency: Literal["USD", "KHR"] = Field(default="USD")
    note: Optional[str] = Field(default=None, examples=["Coke x2"])
    cashier_id: Optional[str] = Field(default=None, examples=["C01"])


class SaleCreateRes(BaseModel):
    sale_id: str
    amount: float
    currency: str
    md5: str
    qr_png_base64: str
    status: str
    created_at: int
    expired_at: int


class SaleStatusRes(BaseModel):
    sale_id: str
    status: str
    md5: str


# =========================
# Routes
# =========================
@app.get("/health")
def health():
    return {"ok": True, "payment_check_enabled": bool(BAKONG_TOKEN)}


@app.post("/pos/sale", response_model=SaleCreateRes)
def create_sale(req: SaleCreateReq):
    sale_id = str(uuid.uuid4())
    created_at = int(time.time())

    # Unique bill number per sale
    bill_number = f"POS-{created_at}-{sale_id[:8]}"

    # Expiry time (seconds)
    expired_at = created_at + SALE_TTL_SECONDS

    try:
        qr_string = khqr.create_qr(
            BANK_ACCOUNT,
            MERCHANT_NAME,
            MERCHANT_CITY,
            float(req.amount),
            req.currency or DEFAULT_CURRENCY,
            STORE_LABEL,
            PHONE,
            bill_number,
            TERMINAL,
            False,  # static=False => dynamic (fixed amount)
        )

        md5 = khqr.generate_md5(qr_string)

        SALES[sale_id] = {
            "sale_id": sale_id,
            "amount": float(req.amount),
            "currency": req.currency,
            "note": req.note,
            "cashier_id": req.cashier_id,
            "bill_number": bill_number,
            "md5": md5,
            "status": "PENDING",
            "created_at": created_at,
            "expired_at": expired_at,
            "paid_at": None,
        }

        return SaleCreateRes(
            sale_id=sale_id,
            amount=float(req.amount),
            currency=req.currency,
            md5=md5,
            qr_png_base64=qr_png_base64(qr_string),
            status="PENDING",
            created_at=created_at,
            expired_at=expired_at,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"KHQR create failed: {e}")


@app.get("/pos/sale/{sale_id}")
def get_sale(sale_id: str):
    sale = SALES.get(sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    _refresh_sale_expiry(sale)

    return {
        "sale_id": sale["sale_id"],
        "amount": sale["amount"],
        "currency": sale["currency"],
        "note": sale["note"],
        "cashier_id": sale["cashier_id"],
        "bill_number": sale["bill_number"],
        "md5": sale["md5"],
        "status": sale["status"],
        "created_at": sale["created_at"],
        "paid_at": sale["paid_at"],
        "expired_at": sale["expired_at"],
    }


@app.get("/pos/sale/{sale_id}/status", response_model=SaleStatusRes)
def check_sale_status(sale_id: str):
    sale = SALES.get(sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")

    # Always refresh expiry here too (important for polling clients)
    _refresh_sale_expiry(sale)

    # If the sale expired, don't check payment, just mark it as expired
    if sale["status"] == "EXPIRED":
        return SaleStatusRes(sale_id=sale_id, status="EXPIRED", md5=sale["md5"])

    # If already done, return quickly
    if sale["status"] in ("PAID", "CANCELLED"):
        return SaleStatusRes(sale_id=sale_id, status=sale["status"], md5=sale["md5"])

    # No token => cannot verify payment (still return PENDING)
    if not BAKONG_TOKEN:
        return SaleStatusRes(sale_id=sale_id, status="PENDING", md5=sale["md5"])

    try:
        result = khqr.check_payment(sale["md5"])

        # bakong-khqr typically returns strings like "UNPAID" / "PAID" (see PyPI docs).
        # Make parsing robust in case a future version returns dict/objects.
        if isinstance(result, str):
            result_str = result.strip().strip('"').upper()
        else:
            result_str = str(result).strip().strip('"').upper()

        # IMPORTANT: do NOT use substring checks like "PAID" in result_str
        # because "UNPAID" contains "PAID" and would be treated as PAID.
        if result_str in ("PAID", "SUCCESS", "SUCCESSFUL", "COMPLETED"):
            sale["status"] = "PAID"
            sale["paid_at"] = int(time.time())
        # else: keep PENDING (covers UNPAID / NOT_FOUND etc.)

        return SaleStatusRes(sale_id=sale_id, status=sale["status"], md5=sale["md5"])

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Payment check failed: {e}")


@app.post("/pos/sale/{sale_id}/mark-cancelled")
def cancel_sale(sale_id: str):
    sale = SALES.get(sale_id)
    if not sale:
        raise HTTPException(status_code=404, detail="Sale not found")
    if sale["status"] == "PAID":
        raise HTTPException(status_code=400, detail="Cannot cancel a PAID sale")

    sale["status"] = "CANCELLED"
    return {"sale_id": sale_id, "status": "CANCELLED"}