import aiohttp
from config import config

INDIAN_CITIES = {
    "mumbai": {"lat": 19.0760, "lon": 72.8777},
    "delhi": {"lat": 28.6139, "lon": 77.2090},
    "bangalore": {"lat": 12.9716, "lon": 77.5946},
    "kolkata": {"lat": 22.5726, "lon": 88.3639},
    "chennai": {"lat": 13.0827, "lon": 80.2707},
    "hyderabad": {"lat": 17.3850, "lon": 78.4867},
    "pune": {"lat": 18.5204, "lon": 73.8567},
    "ahmedabad": {"lat": 23.0225, "lon": 72.5714},
    "jaipur": {"lat": 26.9124, "lon": 75.7873},
    "lucknow": {"lat": 26.8467, "lon": 80.9462}
}

async def get_weather(city: str) -> str:
    """Get weather from OpenWeatherMap API"""
    try:
        if not config.WEATHER_API_KEY:
            return "❌ Weather API key not configured!"
        
        city_lower = city.lower().strip()
        
        # Check if city in our database
        if city_lower in INDIAN_CITIES:
            coords = INDIAN_CITIES[city_lower]
            city_display = city.title()
        else:
            # Geocode city
            async with aiohttp.ClientSession() as session:
                geo_url = f"http://api.openweathermap.org/geo/1.0/direct?q={city},IN&limit=1&appid={config.WEATHER_API_KEY}"
                async with session.get(geo_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data:
                            coords = {"lat": data[0]["lat"], "lon": data[0]["lon"]}
                            city_display = data[0].get("name", city.title())
                        else:
                            return f"❌ City '{city}' not found!"
                    else:
                        return "❌ Geocoding failed!"
        
        # Get weather
        async with aiohttp.ClientSession() as session:
            url = (
                f"https://api.openweathermap.org/data/2.5/weather?"
                f"lat={coords['lat']}&lon={coords['lon']}&"
                f"appid={config.WEATHER_API_KEY}&units=metric"
            )
            
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    weather_main = data["weather"][0]["main"]
                    weather_desc = data["weather"][0]["description"].title()
                    temp = data["main"]["temp"]
                    feels_like = data["main"]["feels_like"]
                    humidity = data["main"]["humidity"]
                    wind = data["wind"]["speed"]
                    
                    # Emoji mapping
                    emojis = {
                        "Clear": "☀️", "Clouds": "☁️", "Rain": "🌧️",
                        "Drizzle": "🌦️", "Thunderstorm": "⛈️", "Snow": "❄️",
                        "Mist": "🌫️", "Fog": "🌫️", "Haze": "🌫️"
                    }
                    emoji = emojis.get(weather_main, "🌡️")
                    
                    return (
                        f"🌤️ **Weather Report for {city_display}**\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"{emoji} **Condition:** {weather_desc}\n"
                        f"🌡️ **Temperature:** {temp}°C\n"
                        f"😮‍💨 **Feels Like:** {feels_like}°C\n"
                        f"💧 **Humidity:** {humidity}%\n"
                        f"💨 **Wind Speed:** {wind} m/s\n\n"
                        f"📍 **Source:** Alita Weather API"
                    )
                else:
                    return "❌ Weather service unavailable!"
                    
    except Exception as e:
        print(f"Weather error: {e}")
        return f"❌ Error fetching weather: {str(e)}"
