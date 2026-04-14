from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from supabase_client import supabase
from auth.dependencies import auth_required
import httpx
import config

router = APIRouter(prefix="/voice", tags=["Voice Billing"])


# ==========================
# SCHEMAS
# ==========================

class VoiceParseRequest(BaseModel):
    transcript: str          # raw text from Web Speech API
    language: str = "en"     # en | hi | te | gu


class ParsedItem(BaseModel):
    name: str
    quantity: float
    unit: str                # "kg", "gm", "pcs", "litre"
    weight_grams: Optional[float] = None


class VoiceParseResponse(BaseModel):
    success: bool
    transcript: str
    parsed_items: List[dict]
    matched_products: List[dict]
    unmatched: List[str]


# ==========================
# GROQ API HELPER
# Free tier: 14,400 requests/day
# Model: llama3-8b-8192 (fast + accurate)
# ==========================

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are a billing assistant for an Indian kirana store POS system.
Your job is to parse voice commands into structured cart items.

The user will say something like:
- "2 kg rice, 500gm wheat, 3 Parle-G, ek litre doodh"
- "teen kg aata, do soap, paanch soo gram dal"
- "1 kg chini aur 2 Maggi"

Extract each item and return ONLY a JSON array. No explanation, no markdown.
Format:
[
  {"name": "rice", "quantity": 2, "unit": "kg"},
  {"name": "wheat", "quantity": 500, "unit": "gm"},
  {"name": "Parle-G", "quantity": 3, "unit": "pcs"},
  {"name": "milk", "quantity": 1, "unit": "litre"}
]

Rules:
- Convert Hindi/Telugu/Gujarati numbers to digits (ek=1, do=2, teen=3, char=4, paanch=5)
- Convert units: kilo/kg/killo=kg, gram/grm/gm=gm, litre/liter/ltr=litre, piece/pcs/nos=pcs
- If no unit mentioned for grocery items, assume pcs
- If quantity not mentioned, assume 1
- Return ONLY the JSON array, nothing else"""


async def parse_voice_with_groq(transcript: str, language: str = "en") -> list:
    """
    Send transcript to Groq API and get structured items back.
    Uses llama3-8b-8192 model — fast and free.
    """
    if not config.GROQ_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Voice billing not configured. Please add GROQ_API_KEY."
        )

    lang_hint = {
        "hi": "The input may contain Hindi words.",
        "te": "The input may contain Telugu words.",
        "gu": "The input may contain Gujarati words.",
        "en": ""
    }.get(language, "")

    user_message = f"{lang_hint}\nParse this voice command: {transcript}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {config.GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama3-8b-8192",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ],
                "temperature": 0.1,  # low temp for consistent parsing
                "max_tokens": 500
            }
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=503,
                detail=f"Voice parsing failed: {response.text}"
            )

        result = response.json()
        content = result["choices"][0]["message"]["content"].strip()

        # Parse JSON response
        import json
        try:
            # Strip any markdown if present
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            items = json.loads(content.strip())
            return items if isinstance(items, list) else []
        except json.JSONDecodeError:
            return []


# ==========================
# ✅ PARSE VOICE TRANSCRIPT
# Frontend sends text from Web Speech API
# We parse it and match to store products
# ==========================

@router.post("/parse")
async def parse_voice(payload: VoiceParseRequest, user=Depends(auth_required)):
    """
    Parse voice transcript into cart items.

    Flow:
    1. Frontend records voice → Web Speech API → text
    2. Frontend sends text to this endpoint
    3. We use Groq LLM to parse text → structured items
    4. We match each item to store products
    5. Return matched products ready for cart

    Frontend shows:
    - Matched items with checkboxes (pre-selected)
    - Unmatched items in red (need manual selection)
    - "Add all to cart" button
    """
    store_id = user["store_id"]

    if not payload.transcript.strip():
        raise HTTPException(status_code=400, detail="Empty transcript")

    # Step 1: Parse with Groq
    parsed_items = await parse_voice_with_groq(
        payload.transcript,
        payload.language
    )

    if not parsed_items:
        return {
            "success": False,
            "transcript": payload.transcript,
            "message": "Could not understand the voice command. Please try again.",
            "parsed_items": [],
            "matched_products": [],
            "unmatched": []
        }

    # Step 2: Match each parsed item to store products
    matched_products = []
    unmatched = []

    for item in parsed_items:
        item_name = item.get("name", "").strip()
        quantity = float(item.get("quantity", 1))
        unit = item.get("unit", "pcs").lower()

        # Search product in store
        search_res = supabase.table("products") \
            .select("product_id, name, price, quantity, unit, has_variants, barcode") \
            .eq("store_id", store_id) \
            .ilike("name", f"%{item_name}%") \
            .limit(1) \
            .execute()

        if search_res.data:
            product = search_res.data[0]
            unit_price = float(product["price"])

            # Handle weight-based items
            weight_grams = None
            cart_label = product["name"]
            calculated_price = unit_price

            if unit in ("kg", "gm", "gram", "grm"):
                if unit == "kg":
                    weight_grams = quantity * 1000
                else:
                    weight_grams = quantity

                calculated_price = round((weight_grams / 1000) * unit_price, 2)
                weight_label = f"{int(weight_grams)}gm" if weight_grams < 1000 \
                    else f"{weight_grams/1000:.1f}kg"
                cart_label = f"{product['name']} ({weight_label})"
            elif unit == "litre":
                weight_grams = quantity * 1000
                calculated_price = round(quantity * unit_price, 2)
                cart_label = f"{product['name']} ({quantity}L)"

            # Check stock
            in_stock = int(product.get("quantity", 0)) > 0

            matched_products.append({
                "product_id": product["product_id"],
                "name": product["name"],
                "cart_label": cart_label,
                "price": unit_price,
                "calculated_price": calculated_price,
                "quantity": 1,  # always 1 cart item (weight handled separately)
                "line_total": calculated_price,
                "unit": unit,
                "weight_grams": weight_grams,
                "weight_label": weight_label if weight_grams else None,
                "in_stock": in_stock,
                "barcode": product.get("barcode"),
                "has_variants": product.get("has_variants", False),
                "voice_input": item_name,    # what user said
                "confidence": "high"
            })
        else:
            unmatched.append(item_name)

    total_estimate = sum(p["calculated_price"] for p in matched_products)

    return {
        "success": True,
        "transcript": payload.transcript,
        "parsed_items": parsed_items,
        "matched_products": matched_products,
        "unmatched": unmatched,
        "total_estimate": round(total_estimate, 2),
        "message": f"Found {len(matched_products)} items. "
                   f"{len(unmatched)} not found in inventory."
                   if unmatched else
                   f"Found all {len(matched_products)} items! ✅"
    }


# ==========================
# ✅ TEXT TO SPEECH SCRIPT
# Returns text for browser to announce
# Uses Web Speech API on frontend
# ==========================

@router.post("/announce")
def get_announcement_text(
    payload: dict,
    user=Depends(auth_required)
):
    """
    Generate text to be announced via browser's
    Web Speech API (SpeechSynthesis).

    Types:
    - bill_total: announce bill total
    - payment_received: confirm payment
    - item_added: confirm item added to cart
    """
    announce_type = payload.get("type", "bill_total")
    language = payload.get("language", "en")

    if announce_type == "bill_total":
        amount = payload.get("amount", 0)
        customer = payload.get("customer_name", "")
        payment_mode = payload.get("payment_mode", "cash").upper()

        scripts = {
            "en": f"Total amount is {amount} rupees. Payment mode {payment_mode}."
                  + (f" Thank you {customer}!" if customer else " Thank you!"),
            "hi": f"Kul rakam {amount} rupaye hai. Bhugtaan {payment_mode} se."
                  + (f" Dhanyavaad {customer}!" if customer else " Dhanyavaad!"),
            "te": f"Mొత్తం {amount} rupaayalu. Chellimpu {payment_mode}."
                  + (f" Dhanyavadaalu {customer}!" if customer else " Dhanyavadaalu!"),
            "gu": f"Kul rakam {amount} rupiya chhe. Payment {payment_mode}."
                  + (f" Aabhar {customer}!" if customer else " Aabhar!")
        }

    elif announce_type == "item_added":
        item_name = payload.get("item_name", "item")
        price = payload.get("price", 0)

        scripts = {
            "en": f"{item_name} added. {price} rupees.",
            "hi": f"{item_name} add kiya. {price} rupaye.",
            "te": f"{item_name} add chesaamu. {price} rupaayalu.",
            "gu": f"{item_name} add karyu. {price} rupiya."
        }

    elif announce_type == "payment_received":
        amount = payload.get("amount", 0)
        change = payload.get("change", 0)

        scripts = {
            "en": f"Payment received. " +
                  (f"Change is {change} rupees." if change > 0 else ""),
            "hi": f"Payment mila. " +
                  (f"Wapsi {change} rupaye." if change > 0 else ""),
            "te": f"Payment andinchi. " +
                  (f"Thirige {change} rupaayalu." if change > 0 else ""),
            "gu": f"Payment malyu. " +
                  (f"Baaki {change} rupiya." if change > 0 else "")
        }
    else:
        scripts = {"en": payload.get("text", "")}

    text = scripts.get(language, scripts.get("en", ""))

    return {
        "success": True,
        "text": text,
        "language": language
    }