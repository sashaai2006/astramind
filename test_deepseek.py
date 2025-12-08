#!/usr/bin/env python3
"""Тестовый скрипт для проверки DeepSeek API"""

import os
import sys

# Добавляем путь к backend
sys.path.insert(0, '/Users/sasii/Code/projects/AstraMind')

os.environ['LLM_MODE'] = 'deepseek'
os.environ['DEEPSEEK_API_KEY'] = 'sk-63dc97e4fa46466583fdd8018a96fe4c'

from backend.llm.adapter import get_llm_adapter
import asyncio

async def test():
    print("🔍 Проверка DeepSeek...")
    print(f"LLM_MODE: {os.getenv('LLM_MODE')}")
    print(f"API Key: {os.getenv('DEEPSEEK_API_KEY')[:15]}...")
    
    adapter = get_llm_adapter()
    print(f"\n✅ Adapter type: {type(adapter).__name__}")
    
    if "DeepSeek" in type(adapter).__name__:
        print("✅ DeepSeek adapter загружен!")
        
        # Тестовый запрос
        print("\n📡 Отправляю тестовый запрос...")
        try:
            response = await adapter.acomplete("Say 'Hello from DeepSeek!'", json_mode=False)
            print(f"✅ Ответ получен: {response[:100]}...")
            print("\n🎉 DeepSeek работает идеально!")
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    else:
        print(f"❌ Неправильный adapter: {type(adapter).__name__}")
        print("   Ожидался: DeepSeekAdapter")

if __name__ == "__main__":
    asyncio.run(test())

