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
    # unique_tickers = set()
    non_unique_tickers = []
    for comment in comments_with_tickers:
        non_unique_tickers.extend(comment['tickers'])
        # unique_tickers.update(comment['tickers'])

    logger.info(f"Found {len(non_unique_tickers)} non unique tickers")


    # Write the unique tickers to the db
    

    for ticker in list(non_unique_tickers):
        
        try:
            company_name = get_company_name(ticker)
            logger.info(f"Storing stock record for {ticker} - {company_name}")
            store_stock_record(supabase, ticker, company_name)
        except Exception as e:
            logger.error(f"Error processing ticker£: {e}")
    logger.info(f"Stored {len(non_unique_tickers)} non unique tickers")

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
        # Replace more MoreComments objects to get deeper comment threads
        # Increase limit to 20 to get more comments, with a threshold of 2 to get less popular comments
        await submission.comments.replace_more(limit=20, threshold=2)
        logger.info("Finished replacing MoreComments")
    except Exception as e:
        logger.error(f"Error replacing MoreComments: {e}")
    
    # Get all comments recursively
    logger.info("Getting comments recursively...")
    try:
        all_comments = []
        
        # Helper function to recursively collect comments and their replies
        def collect_comments_recursively(comment_forest):
            for comment in comment_forest:
                if hasattr(comment, 'body'):
                    all_comments.append(comment)
                    if hasattr(comment, 'replies') and len(comment.replies) > 0:
                        collect_comments_recursively(comment.replies)
        
        # Start collection from top-level comments
        collect_comments_recursively(submission.comments)
        
        if all_comments:
            first_comment = all_comments[0].body
            logger.info(f"First comment: {first_comment[:100]}...")  
        logger.info(f"Found {len(all_comments)} comments total")
        
        # Check for existing comment IDs in the database if none were provided
        if not existing_comment_ids:
            try:
                # Fetch all comment IDs for this post from the database
                response = supabase.table('reddit_comments').select('id').eq('postId', post_id).execute()
                if response.data:
                    existing_comment_ids = [comment['id'] for comment in response.data]
                    logger.info(f"Found {len(existing_comment_ids)} existing comment IDs in database")
            except Exception as e:
                logger.error(f"Error fetching existing comments: {e}")
        
        # Filter out existing comments to avoid duplicates
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
        
        comments_with_tickers = await get_comments(post_id, reddit, existing_ids)
        
        print(f"Found {len(comments_with_tickers)} new comments")
        for comment in comments_with_tickers[:5]:  # Print first 5 comments as example
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