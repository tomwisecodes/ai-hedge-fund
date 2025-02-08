from asyncio.log import logger
from datetime import datetime
from typing import Optional, List, Dict, Union
from supabase import create_client, Client
import asyncpraw
from typing import TypedDict
import asyncio
import os
import requests
from dotenv import load_dotenv
from src.reddit.getComments import get_comments

# Load environment variables from .env file
load_dotenv()

# Retrieve Supabase URL and Key from environment variables
url = os.getenv("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL') or os.environ.get('SLACK_WEBHOOK_URL')

if not url or not key:
    raise ValueError("Please set SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables.")

if not SLACK_WEBHOOK_URL:
    raise ValueError("Please set SLACK_WEBHOOK_URL environment variable")

# Initialize Supabase client
supabase: Client = create_client(url, key)
supabase.postgrest.auth(token=key)

def send_slack_message(message: str):
    """Send a message to Slack using webhook"""
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": message})
        logger.info(f"Slack notification sent: {message}")
    except Exception as e:
        logger.error(f"Error sending Slack notification: {e}")

class DiscussionPost(TypedDict):
    postId: str
    created_at: float
    title: str

def store_daily_discussion(supabase, post_id, title):
    """Store a single daily discussion post"""
    try:
        record = {
            'id': post_id,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'title': title
        }
        supabase.table('reddit_posts').upsert(record).execute()
        logger.info(f"Stored daily discussion: {post_id}")
    except Exception as e:
        logger.error(f"Error storing daily discussion: {e}")

async def get_daily_discussion(reddit: asyncpraw.Reddit) -> str:
    try:
        daily_discussion_id = ''
        # Check if the daily discussion is stickied
        wsb = await reddit.subreddit('wallstreetbets')
        
        try:
            sticky = await wsb.sticky()
            if sticky.link_flair_text == 'Daily Discussion':
                daily_discussion_id = sticky.id
        except:
            pass  # No sticky found or other error

        if daily_discussion_id:
            # Write the daily discussion ID to the database
            store_daily_discussion(supabase, daily_discussion_id, sticky.link_flair_text)
            return daily_discussion_id
        else:
            # If the daily discussion is not stickied, get the 10 newest posts
            posts = [post async for post in wsb.new(limit=50)]
            
            daily_discussion = next(
                (post for post in posts 
                 if 'Daily Discussion' in post.title 
                 or 'Moves Tomorrow' in post.title),
                None
            )
            
            if daily_discussion is None:
                logger.error('No daily discussion found')
                return 'No daily discussion found'

            # Write the daily discussion ID to the database
            store_daily_discussion(supabase, daily_discussion.id, daily_discussion.title)
            
            return daily_discussion.id

    except Exception as error:
        logger.error('Error:', error)
        raise

async def get_daily_discussions(
    reddit: asyncpraw.Reddit,
    limit: Optional[int] = 100,
    skip: Optional[int] = 200
) -> List[DiscussionPost]:
    try:
        # Get newest posts
        wsb = await reddit.subreddit('wallstreetbets')
        posts = [post async for post in wsb.new(limit=limit or 100)]
        
        # Skip posts if needed
        if skip:
            posts = posts[skip:]

        daily_discussions = []

        for post in posts:
            if ('Daily Discussion' in post.title 
                or 'Moves Tomorrow' in post.title):
                daily_discussions.append({
                    'postId': post.id,
                    'title': post.title,
                    'created_at': post.created_utc
                })

        return daily_discussions

    except Exception as error:
        logger.error('Error:', error)
        raise


async def get_last_10_discussion_ids(reddit: asyncpraw.Reddit) -> List[str]:
    try:
        # Get newest posts
        wsb = await reddit.subreddit('wallstreetbets')
        posts = [post async for post in wsb.new(limit=10)]
        
        daily_discussion_ids = []

        for post in posts:
            daily_discussion_ids.append(post.id)

        return daily_discussion_ids

    except Exception as error:
        logger.error('Error:', error)
        raise

async def main():
    load_dotenv()  # Load environment variables
    
    # Initialize the Reddit instance
    reddit = asyncpraw.Reddit(
        client_id=os.getenv('REDDIT_CLIENT_ID'),
        client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
        user_agent=os.getenv('REDDIT_USER_AGENT', 'MyBot/1.0')
    )
    
    try:
        # Call the functions
        logger.info("Getting daily discussion...")
        discussion_id = await get_daily_discussion(reddit)
        last_10_discussion_ids = await get_last_10_discussion_ids(reddit)
        print("last_10_discussion_ids", last_10_discussion_ids)
        arrayOfDiscussionIds = [discussion_id, *last_10_discussion_ids]    
        
        # Remove duplicates in the array

        discussion_ids_set = set(arrayOfDiscussionIds)

        logger.info(f"Daily discussion ID: {discussion_ids_set}")
        if len(discussion_ids_set) == 0:
            error_msg = '❌ No daily discussion found. Exiting...'
            logger.error(error_msg)
            send_slack_message(error_msg)
            return

        logger.info(f"Daily discussion ID: {discussion_id}")
        numberOfCommentsFounds = 0
        for post_id in discussion_ids_set:
            if post_id == 'No daily discussion found': 
                continue
            store_daily_discussion(supabase, post_id, 'Daily Discussion')
            comments = await get_comments(post_id, reddit)
            numberOfCommentsFounds += len(comments)
            
        success_msg = f"✅ Reddit Script Complete!\nFound {numberOfCommentsFounds} comments\nDiscussion ID: {discussion_id}"
        send_slack_message(success_msg)
        logger.info(f"Found {numberOfCommentsFounds} comments in the daily discussion")   

    except Exception as e:
        error_msg = f"❌ Error in Reddit script: {str(e)}"
        logger.error(error_msg)
        # send_slack_message(error_msg)
        raise
    finally:
        await reddit.close()

if __name__ == "__main__":
    asyncio.run(main())