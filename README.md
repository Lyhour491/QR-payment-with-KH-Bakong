## 💳 QR Payment with KH-Bakong — Description

**KH-Bakong QR (KHQR)** is Cambodia’s national QR payment standard created by the National Bank of Cambodia.
It allows customers to pay using any supported banking app (ABA, ACLEDA, Wing, etc.) by scanning one QR code.

### How it works (POS shop flow)

1. POS system generates a KHQR with amount
2. Customer scans QR using mobile banking app
3. Customer confirms payment
4. Bank sends transaction to Bakong network
5. Your backend checks payment using **MD5 transaction hash**
6. If paid → POS shows **PAID**

KHQR supports:

- USD or KHR
- Static QR (customer enters amount)
- Dynamic QR (amount fixed)
- Real-time payment check via Bakong API

---

# 🧠 API Flow (Your backend)

### Step 1 — Create QR

Backend generates KHQR + MD5

### Step 2 — Customer pays

Scan with mobile banking

### Step 3 — Check payment

Backend checks payment using md5

---

# 🧪 HOW TO USE IN POSTMAN

## ▶️ 1. Start backend first

Run server:

```bash
uvicorn main:app --reload
```

Server:

```
http://127.0.0.1:8000
```

---

# 🟢 2. Create QR payment (POSTMAN)

Open Postman
Click **POST**

URL:

```
http://127.0.0.1:8000/pos/sale
```

### Body → JSON

```json
{
  "amount": 1,
  "currency": "USD"
}
```

Press **Send**

You will get:

```json
{
  "sale_id": "a123",
  "amount": 1,
  "currency": "USD",
  "md5": "9a8b7c6d",
  "qr_png_base64": "iVBORw0KGgoAAA...",
  "status": "PENDING"
}
```

Copy:

```
sale_id
```

---

# 🟡 3. Check payment status (Postman)

Create new GET request:

```
http://127.0.0.1:8000/pos/sale/YOUR_SALE_ID/status
```

Example:

```
http://127.0.0.1:8000/pos/sale/a123/status
```

Press **Send**

Result:

```json
{
  "sale_id": "a123",
  "status": "PENDING",
  "md5": "xxxx"
}
```

After payment:

```json
{
  "sale_id": "a123",
  "status": "PAID",
  "md5": "xxxx"
}
```

---

# 🔴 4. Test without real payment (demo)

If no real bank token yet:

Open browser or Postman GET:

```
http://127.0.0.1:8000/test/paid/YOUR_SALE_ID
```

Then check status again → will show PAID

---

# 📌 POSTMAN COLLECTION FLOW (BEST)

### Request 1 — Create payment

POST `/pos/sale`

### Request 2 — Check status

GET `/pos/sale/{id}/status`

### Request 3 — (optional demo)

GET `/test/paid/{id}`
