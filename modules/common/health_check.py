"""
Ritzz Studio
Health Check Module

Purpose:
- Verify OpenAI configuration
- Verify API connectivity
"""

import os

from dotenv import load_dotenv
from openai import OpenAI


def main():
    print("=" * 60)
    print("Ritzz Studio - Health Check")
    print("=" * 60)

    # Load environment variables
    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        print("❌ OPENAI_API_KEY not found in .env")
        return

    print("✅ API key found")

    try:
        client = OpenAI(api_key=api_key)

        response = client.models.list()

        print("✅ Connected to OpenAI")

        print("\nAvailable Models:")

        for model in response.data[:10]:
            print(f"   • {model.id}")

        print("\n🎉 Health Check Passed!")

    except Exception as ex:
        print("\n❌ Connection Failed")
        print(ex)


if __name__ == "__main__":
    main()