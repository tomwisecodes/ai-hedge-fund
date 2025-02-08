from src.reddit.getDailyDiscussion import send_slack_message
from supabase import create_client, Client
from typing import TypedDict, List
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from pathlib import Path
from datetime import datetime, timedelta

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


# Get tickers from database
response = supabase.table("stocks").select("*").execute()

# Get all stocks from the database

stocks = response.data



from datetime import datetime, timedelta

for stock in stocks:
    # Get all stock mentions in the last 7 days
    response = (
        supabase.table("stock_mentions")
        .select("*", count="exact")  # Selecting all rows but also requesting a count
        .eq("ticker", stock["ticker"])
        .gt("mentioned_at", (datetime.now() - timedelta(days=7)).isoformat())
        .execute()
    )

    number_of_mentions = response.count  
    upsert_data = {
        **stock,
        "mention_count_7d": number_of_mentions  
    }    
    supabase.table("stocks").upsert(upsert_data).execute()


# Send Slack message with results
success_msg = f":man-cartwheeling: hot stocks counted successfully"
send_slack_message(success_msg)