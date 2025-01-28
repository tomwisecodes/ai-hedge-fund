import subprocess
import requests
import json
import time
from supabase import create_client, Client
from typing import TypedDict, List
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from pathlib import Path

from src.utils.ticker_utils import get_sec_tickers

# Get project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent

load_dotenv()

# Retrieve Supabase URL and Key from environment variables
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_KEY")

supabase: Client = create_client(url, key)

class StockEntry(TypedDict):
   ticker: str
   created_at: datetime  
   updated_at: datetime
   name: str

# Manually set the headers at the PostgREST level
supabase.postgrest.auth(token=key)

def get_recent_tickers(response_data, days=30):
    """Filters tickers mentioned in the last `days` days."""
    recent_tickers = []
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    for stock in response_data:
        last_mentioned_raw = stock.get('last_mentioned')  # Use .get() to avoid KeyError
        
        if last_mentioned_raw is None:
            continue  # Skip entries with no last_mentioned date
        
        # Ensure last_mentioned is a datetime object
        if isinstance(last_mentioned_raw, datetime):
            last_mentioned = last_mentioned_raw
        else:
            last_mentioned = datetime.fromisoformat(str(last_mentioned_raw))

        if last_mentioned >= cutoff_date:
            recent_tickers.append(stock['ticker'])
    
    return recent_tickers


response = supabase.table("stocks").select("*").execute()
response_data: List[StockEntry] = response.data

# Get tickers mentioned in the last 30 days
tickers = get_recent_tickers(response_data)
print("tickers length", len(tickers))
for ticker in tickers[:5]:
    print("Processing ticker:", ticker)
    try:
        print(f"*******Processing {ticker}")
        sec_tickers = get_sec_tickers()
        ticker_valid = any(company['ticker'] == ticker 
                         for company in sec_tickers.values())
        
        if not ticker_valid:
            print(f"Warning: {ticker} not found")
            continue

        cmd = f'echo -e "a\n" | poetry run python src/main.py --ticker {ticker} --execute-trades --trade-amount 2000 --leverage 1'
        subprocess.run(cmd, shell=True, cwd=str(PROJECT_ROOT))
        time.sleep(1)  # Rate limiting
        
    except Exception as e:
        print(f"Error processing {ticker}: {str(e)}")
        time.sleep(5)  # Longer delay on error
        continue
