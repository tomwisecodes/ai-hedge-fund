import subprocess
import requests
import json
import time
from src.db.functions import get_hot_stocks
from src.reddit.getDailyDiscussion import send_slack_message
from supabase import create_client, Client
from typing import TypedDict, List
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from pathlib import Path
from src.utils.ticker_utils import get_sec_tickers
from alpaca.trading.client import TradingClient

# Get project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent

load_dotenv()

# Retrieve Supabase URL and Key from environment variables
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_KEY")

# Initialize Alpaca client
alpaca_api_key = os.getenv('ALPACA_API_KEY')
alpaca_api_secret = os.getenv('ALPACA_API_SECRET')
trading_client = TradingClient(alpaca_api_key, alpaca_api_secret, paper=True)

supabase: Client = create_client(url, key)

class StockEntry(TypedDict):
    ticker: str
    created_at: datetime
    updated_at: datetime
    name: str

# Manually set the headers at the PostgREST level
supabase.postgrest.auth(token=key)

def get_recent_tickers(response_data, days=30):
    """Filters tickers mentioned in the last days days."""
    recent_tickers = []
    cutoff_date = datetime.utcnow() - timedelta(days=days)

    for stock in response_data:
        last_mentioned_raw = stock.get('last_mentioned')
        
        if last_mentioned_raw is None:
            continue
            
        # Handle datetime object
        if isinstance(last_mentioned_raw, datetime):
            last_mentioned = last_mentioned_raw
        else:
            try:
                # Try direct fromisoformat first
                last_mentioned = datetime.fromisoformat(str(last_mentioned_raw))
            except ValueError:
                # If that fails, pad the microseconds to 6 digits
                timestamp_str = str(last_mentioned_raw)
                if '.' in timestamp_str:
                    main_part, microseconds = timestamp_str.rsplit('.', 1)
                    # Pad microseconds with zeros if needed
                    microseconds = microseconds.ljust(6, '0')
                    timestamp_str = f"{main_part}.{microseconds}"
                last_mentioned = datetime.fromisoformat(timestamp_str)
                
        if last_mentioned >= cutoff_date:
            recent_tickers.append(stock['ticker'])
    
    return recent_tickers

# Get currently owned positions from Alpaca
try:
    owned_positions = trading_client.get_all_positions()
    owned_tickers = [position.symbol for position in owned_positions]
    print(f"Currently owned stocks: {', '.join(owned_tickers)}")
except Exception as e:
    print(f"Error fetching Alpaca positions: {e}")
    owned_tickers = []

# Get tickers from database
response = supabase.table("stocks").select("*").execute()
response_data: List[StockEntry] = response.data

# Get tickers mentioned in the last 30 days
# db_tickers = get_recent_tickers(response_data)
db_tickers_hot = get_hot_stocks(supabase)


print(f"Owned tickers: {len(owned_tickers)}")
print(f"Total unique tickers to process: {len(db_tickers_hot)}")

# Combine DB tickers with owned positions and remove duplicates
tickers = list(set(owned_tickers + db_tickers_hot))
max_100_tickers = tickers[:100]
print(f"Total unique tickers to process: {len(max_100_tickers)}")
success_msg = f":bar_chart: :alien: Starting hedge fund bot for {len(max_100_tickers)} tickers"

success_array = []
error_array = []
for ticker in max_100_tickers:
    print(f"Processing ticker: {ticker}")
    try:
        # print(f"*******Processing {ticker}")
        sec_tickers = get_sec_tickers()
        ticker_valid = ticker in sec_tickers
        
        if not ticker_valid:
            print(f"Warning: {ticker} not found in SEC tickers")
            continue
            
        cmd = f'echo -e "a\n" | poetry run python src/main.py --ticker {ticker} --execute-trades --trade-amount 2000 --leverage 1'

        subprocess.run(cmd, shell=True, cwd=str(PROJECT_ROOT))
        time.sleep(1)  # Rate limiting
        success_array.append(ticker)
    except Exception as e:
        print(f"Error processing {ticker}: {str(e)}")
        error_array.append({{ticker}: {str(e)}})
        time.sleep(5)  # Longer delay on error
        continue

# Send Slack message with results
success_msg = f":bar_chart: :alien: Hedge fund bot finished processing {len(success_array)} tickers: {', '.join(success_array)} and encountered errors with {len(error_array)} tickers: {', '.join(error_array)}"
# send_slack_message(success_msg)