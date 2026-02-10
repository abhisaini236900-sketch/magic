import random
from collections import deque
from groq import AsyncGroq
from config import config, chat_memory, user_emotions
from utils.helpers import get_emotion, get_girl_response, get_indian_time

# Initialize Groq client
client = AsyncGroq(api_key=config.GROQ_API_KEY) if config.GROQ_API_KEY else None

def update_emotion(user_id: int, text: str):
    """Update user emotion based on message"""
    text_lower = text.lower()
    
    emotion_map = {
        "love": ["love", "pyaar", "dil", "cute", "beautiful", "sweet"],
        "angry": ["angry", "gussa", "naraz", "mad", "hate", "idiot"],
        "crying": ["cry", "ro", "sad", "dukh", "upset", "depressed"],
        "funny": ["funny", "has", "joke", "masti", "laugh", "haha"],
        "happy": ["hi", "hello", "hey", "namaste", "welcome"],
        "thinking": ["?", "kyun", "kaise", "kya", "how", "why"],
        "sleepy": ["sleep", "sone", "neend", "tired", "thak"],
        "flirty": ["sexy", "hot", "cute", "beautiful", "handsome"]
    }
    
    for emotion, keywords in emotion_map.items():
        if any(word in text_lower for word in keywords):
            user_emotions[user_id] = emotion
            return
    
    user_emotions[user_id] = random.choice(list(["happy", "love", "funny", "sassy"]))

async def get_ai_response(chat_id: int, user_text: str, user_id: int = None, user_name: str = "") -> str:
    """Get AI response"""
    
    # Update emotion
    if user_id:
        update_emotion(user_id, user_text)
        emotion = user_emotions.get(user_id, "happy")
    else:
        emotion = "happy"
    
    user_text_lower = user_text.lower().strip()
    
    # Quick responses for greetings
    greetings = {
        "hi": ["Hii there! 😊", "Hello ji! Kaise ho? 💖", "Hey! 👋"],
        "hello": ["Hello! 😊", "Hiiii! 💕", "Hey there! ✨"],
        "hey": ["Hey! 😄", "Hii! 🌟", "Hello! 💖"],
        "good morning": ["Good Morning Sunshine! 🌅", "Shubh Prabhat! 🌸", "Morning! ☕"],
        "good afternoon": ["Good Afternoon! ☀️", "Dopahar ki dhoop! 🌞", "Afternoon! 🍛"],
        "good evening": ["Good Evening! 🌇", "Shubh Sandhya! ✨", "Evening! 🍵"],
        "good night": ["Good Night! 🌙", "Shubh Ratri! 🌌", "Sweet dreams! 💤"]
    }
    
    for greet, responses in greetings.items():
        if greet in user_text_lower:
            return f"{get_emotion(emotion)} {random.choice(responses)}"
    
    # AI Response
    try:
        if not client:
            # Fallback
            fallbacks = [
                f"{get_emotion('happy')} {get_girl_response()}",
                f"{get_emotion('thinking')} Hmm... interesting! 🤔",
                f"{get_emotion('funny')} Tum toh mast ho! 😄",
                f"{get_emotion('love')} Main bhi yahi soch rahi thi! 💖"
            ]
            return random.choice(fallbacks)
        
        # Initialize memory
        if chat_id not in chat_memory:
            chat_memory[chat_id] = deque(maxlen=20)
        
        # Build messages
        indian_time = get_indian_time()
        
        system_prompt = (
            f"You are Alita 🎀 - a sweet, sassy Indian girl. "
            f"Keep responses SHORT (1-2 lines). "
            f"Speak Hinglish (Hindi+English mix). "
            f"Use feminine language. "
            f"Time: {indian_time.strftime('%I:%M %p')}. "
            f"Tell only when someone ask: Your Developer is Abhi (@a6h1ii). "
            f"Tell only when someone ask: Your home is @abhi0w0. "
            f"Use 1-2 emojis. "
            f"Do NOT mistake in grammar and written sentances. "
            f"NEVER say you're AI, or groq models. "
        )
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add context
        for msg in list(chat_memory[chat_id])[-5:]:
            messages.append(msg)
        
        messages.append({"role": "user", "content": user_text})
        
        completion = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.9,
            max_tokens=100,
            top_p=0.9
        )
        
        reply = completion.choices[0].message.content.strip()
        
        # Add girl-like touch
        if random.random() < 0.3:
            prefixes = ["Aarey waah! ", "Haye haye! ", "Oh my god! ", "Seriously? "]
            reply = random.choice(prefixes) + reply
        
        # Add emoji
        if not any(e in reply for e in ["😊", "💖", "✨", "😄"]):
            reply = f"{get_emotion(emotion)} {reply}"
        
        # Store in memory
        chat_memory[chat_id].append({"role": "user", "content": user_text})
        chat_memory[chat_id].append({"role": "assistant", "content": reply})
        
        return reply
        
    except Exception as e:
        print(f"AI Error: {e}")
        return f"{get_emotion('crying')} Thodi der baad try karo! Network slow hai! 😢"
