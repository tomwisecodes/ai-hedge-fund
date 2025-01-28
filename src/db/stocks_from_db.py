import subprocess
import requests
import json
import time
from supabase import create_client, Client
from typing import TypedDict, List
from datetime import datetime
from dotenv import load_dotenv
import os
from pathlib import Path

from utils.ticker_utils import get_sec_tickers

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

response = supabase.table("stocks").select("*").execute()
response_data: List[StockEntry] = response.data

#organise into array of tickers

tickers = []
for stock in response_data:
    tickers.append(stock['ticker'])

short_list_tickers = tickers[20:40]
print(short_list_tickers)

# short_list_tickers = ["NVDA", "GOOGL"]



for ticker in short_list_tickers:
    print("Processing ticker:", ticker)
    try:
        sec_tickers = get_sec_tickers()
        ticker_valid = any(company['ticker'] == ticker 
                         for company in sec_tickers.values())
        
        if not ticker_valid:
            print(f"Warning: {ticker} not found")
            continue
            
        cmd = f'echo -e "a\\n" | poetry run python src/main.py --ticker {ticker}'
        subprocess.run(cmd, shell=True, cwd=str(PROJECT_ROOT))
        time.sleep(1)  # Rate limiting
        
    except Exception as e:
        print(f"Error processing {ticker}: {str(e)}")
        time.sleep(5)  # Longer delay on error
        continue
