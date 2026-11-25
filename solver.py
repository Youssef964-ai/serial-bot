import os
import google.generativeai as genai
from telegram import Update
from io import BytesIO

genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
model = genai.GenerativeModel('gemini-1.5-flash')

async def solve_question(message):
    try:
        prompt = """أنت مساعد ذكي لحل أسئلة منصة Qureo (Sprix) التعليمية.
        الطالب بيبعتلك سؤال (نص أو صورة).
        لو المشكلة برمجة (Python أو JavaScript)، اكتب الكود كامل وسليم.
        لو ثقافة مالية، اشرح الإجابة واختار الاختيار الصح.
        ردك لازم يكون واضح ومختصر ومفيد بالعربي."""

        if message.photo:
            photo_file = await message.photo[-1].get_file()
            image_bytes = await photo_file.download_as_bytearray()
            content = [prompt, {"mime_type": "image/jpeg", "data": bytes(image_bytes)}]
        else:
            content = [prompt, f"السؤال: {message.text}"]

        response = model.generate_content(content)
        return f"✅ <b>الإجابة:</b>\n\n{response.text}"

    except Exception as e:
        return f"❌ حدث خطأ أثناء الحل: {e}\nتأكد من مفتاح Gemini."
