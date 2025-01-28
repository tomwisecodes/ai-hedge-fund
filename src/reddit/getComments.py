from src.db.functions import store_stock_record
from supabase import create_client, Client
from dotenv import load_dotenv
from typing import List, Dict, Optional
from datetime import datetime
import asyncpraw
import logging
import time
import os
from src.utils.ticker_utils import find_tickers, get_sec_tickers, get_company_name

# Load environment variables from .env file
load_dotenv()

# Retrieve Supabase URL and Key from environment variables
url = os.getenv("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")

if not url or not key:
    raise ValueError("Please set SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables.")


# Initialize Supabase client
supabase: Client = create_client(url, key)
supabase.postgrest.auth(token=key)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_comments(
    post_id: str,
    reddit: asyncpraw.Reddit,
    existing_comment_ids: List[str] = []
) -> List[Dict[str, any]]:
    """
    Get the comments of a post on Reddit
    Returns: List of restructured comments with ticker information
    """
    logger.info(f"Starting to get comments for post {post_id}")
    start_time = time.time()
    
    comments = await grab_set_number_of_comments(
        post_id,
        reddit,
        existing_comment_ids
    )
    
    # Load ticker set once
    ticker_set = get_sec_tickers()
    
    logger.info(f"Processing {len(comments)} comments into final format...")
    comment_array = [
        {
            'id': comment.id,
            'content': comment.body,
            'createdAt': comment.created_utc,
            'updatedAt': comment.created_utc,
            'postId': post_id,
            'tickers': find_tickers(comment.body, ticker_set)
        }
        for comment in comments
    ]


    # Filter to only comments with tickers
    comments_with_tickers = [
        comment for comment in comment_array 
        if comment['tickers']
    ]

    # # Make an Set of unique tickers
    unique_tickers = set()
    for comment in comments_with_tickers:
        unique_tickers.update(comment['tickers'])

    logger.info(f"Found {len(unique_tickers)} unique tickers")


    # Write the unique tickers to the db
    for ticker in list(unique_tickers):
        
        try:
            company_name = get_company_name(ticker)
            store_stock_record(supabase, ticker, company_name)
        except Exception as e:
            logger.error(f"Error processing ticker: {e}")

    logger.info(f"Stored {len(unique_tickers)} unique tickers")

    # Write the comments to the db 

    for comment in comments_with_tickers:    
        try:
            data = {
                'id': comment['id'],
                'content': comment['content'],
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'postId': post_id,
            }
            supabase.table('reddit_comments').upsert(data).execute()      
        except Exception as e:
            logger.error(f"Error processing comment: {e}")

    logger.info(f"Stored {len(comments_with_tickers)} comments")

    end_time = time.time()
    logger.info(f"Found {len(comments_with_tickers)} comments with tickers")
    logger.info(f"Finished processing comments in {end_time - start_time:.2f} seconds")
    
    return comments_with_tickers

def convert_utc_to_date_and_time(utc: float) -> str:
    """Convert UTC timestamp to local date and time string"""
    date = datetime.fromtimestamp(utc)
    return date.strftime('%Y-%m-%d %H:%M:%S')

async def grab_set_number_of_comments(
    post_id: str,
    reddit: asyncpraw.Reddit,
    existing_comment_ids: List[str]
) -> List[asyncpraw.models.Comment]:
    """Fetch all comments from a post and filter out existing ones"""
    logger.info("Starting to fetch submission...")
    submission = await reddit.submission(id=post_id)
    logger.info(f"Submission title: {submission.title}")
    logger.info(f"Total comments: {submission.num_comments}")
    
    # Set a reasonable limit for comment fetching
    logger.info("Starting to replace MoreComments objects...")
    try:
        # Only replace up to 10 MoreComments objects, with a minimum score of 5
        await submission.comments.replace_more(limit=10, threshold=5)
        logger.info("Finished replacing MoreComments")
    except Exception as e:
        logger.error(f"Error replacing MoreComments: {e}")
    
    # Get top-level comments only
    logger.info("Getting comments...")
    try:
        all_comments = []
        for top_comment in submission.comments:
            if hasattr(top_comment, 'body'):  # Check if it's a real comment
                all_comments.append(top_comment)
                # Get replies
                if hasattr(top_comment, 'replies'):
                    for reply in top_comment.replies.list():
                        if hasattr(reply, 'body'):
                            all_comments.append(reply)
        

        first_comment = all_comments[0].body
        logger.info(f"First comment: {first_comment[:100]}...")  
        logger.info(f"Found {len(all_comments)} comments")
        
        # Filter out existing comments
        filtered_comments = [
            comment for comment in all_comments 
            if comment.id not in existing_comment_ids
        ]
        
        logger.info(f"After filtering, processing {len(filtered_comments)} new comments")
        return filtered_comments
        
    except Exception as e:
        logger.error(f"Error processing comments: {e}")
        return []

# For testing individually
async def main():
    # Initialize Reddit instance (you'll need to add your credentials)
    reddit = asyncpraw.Reddit(
        client_id=os.getenv('REDDIT_CLIENT_ID'),
        client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
        user_agent=os.getenv('REDDIT_USER_AGENT', 'MyBot/1.0')
    )
    
    try:
        # Example post ID
        post_id = "example_post_id"
        existing_ids = []  # Add any existing comment IDs here
        
        comments = await get_comments(post_id, reddit, existing_ids)
        
        print(f"Found {len(comments)} new comments")
        for comment in comments[:5]:  # Print first 5 comments as example
            created_time = convert_utc_to_date_and_time(comment['createdAt'])
            print(f"Comment ID: {comment['id']}")
            print(f"Created at: {created_time}")
            print(f"Content: {comment['content'][:100]}...")  # First 100 chars
            print("---")
            
    finally:
        await reddit.close()

if __name__ == "__main__":
    import asyncio
    import os
    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(main())