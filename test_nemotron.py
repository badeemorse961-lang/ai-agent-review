import os
from openai import OpenAI

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"]
)

prompt = """
أنت مهندس برمجيات كبير تراجع مشروع Python متعدد الملفات.

هذه مهمة تحليل فقط.
لا تعدل الملفات.
لا تدعي أنك شغلت الاختبارات.

المتطلبات:

1. add(a,b) ترجع a+b
2. subtract(a,b) ترجع a-b
3. divide(a,b) ترجع a/b
4. divide(a,0) يجب أن ترفع ZeroDivisionError
5. لا تغير توقيعات الدوال العامة
6. لا إعادة هيكلة غير ضرورية

هيكل المشروع:

shop/
    cart.py
    pricing.py
    orders.py
    app.py
    tests/test_cart.py
    tests/test_orders.py
    README.md

pricing.py:

def discount(total):
    if total > 100:
        return total * 0.10
    return 0

def final_price(total):
    return total - discount(total)

cart.py:

def cart_total(items):
    total = 0
    for item in items:
        total += item["price"] * item["quantity"]
    return total

orders.py:

from pricing import discount

def checkout(items):
    total = 0
    for item in items:
        total += item["price"] * item["quantity"]

    return total - discount(total)

app.py:

from cart import cart_total
from orders import checkout

def create_order(items):
    total = cart_total(items)

    return {
        "total": total,
        "payable": checkout(items)
    }

tests/test_orders.py:

from orders import checkout

def test_checkout_discount():
    items = [
        {"price": 60, "quantity": 1},
        {"price": 40, "quantity": 1},
    ]

    assert checkout(items) == 90

المطلوب:

- اكتشف كل المخالفات الحقيقية فقط.
- انتبه إلى أن الخصم يجب أن يبدأ عند 100 بالضبط.
- تتبع تأثير المشكلة عبر الملفات.
- حدد الملفات التي تحتاج تغييرًا.
- حدد الملفات التي لا تحتاج تغييرًا.
- اقترح أقل إصلاح آمن.
- لا تخترع مشاكل.
- لا تقترح إعادة هيكلة غير ضرورية.
- لا تدّعي أن الاختبارات تم تشغيلها.

أعطني تقريرًا هندسيًا منظمًا ومختصرًا.
"""

response = client.chat.completions.create(
    model="nvidia/nemotron-3-ultra-550b-a55b:free",
    messages=[
        {
            "role": "user",
            "content": prompt
        }
    ]
)

print(response.choices[0].message.content)