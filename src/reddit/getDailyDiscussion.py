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
    """Store a reddit post"""
    try:
        record = {
            'id': post_id,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'title': title
        }
        supabase.table('reddit_posts').upsert(record).execute()
        logger.info(f"Stored post: {post_id} - {title[:30]}...")
    except Exception as e:
        logger.error(f"Error storing post: {e}")

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


async def get_last_20_discussion_ids(reddit: asyncpraw.Reddit) -> List[str]:
    try:
        # Get newest posts - changing to 20 posts
        wsb = await reddit.subreddit('wallstreetbets')
        posts = [post async for post in wsb.new(limit=20)]
        
        discussion_ids = []

        for post in posts:
            discussion_ids.append(post.id)

        return discussion_ids

    except Exception as error:
        logger.error('Error:', error)
        raise

async def get_pinned_posts(reddit: asyncpraw.Reddit) -> List[str]:
    """Get all pinned/stickied posts from WSB"""
    try:
        wsb = await reddit.subreddit('wallstreetbets')
        pinned_ids = []
        
        # Try to get both stickied posts (there can be up to 2)
        for i in range(1, 3):
            try:
                sticky = await wsb.sticky(number=i)
                pinned_ids.append(sticky.id)
                logger.info(f"Found pinned post: {sticky.title}")
            except:
                # No more stickies found
                break
                
        return pinned_ids
        
    except Exception as error:
        logger.error(f'Error getting pinned posts: {error}')
        return []

async def main():
    load_dotenv()  # Load environment variables
    
    # Initialize the Reddit instance
    reddit = asyncpraw.Reddit(
        client_id=os.getenv('REDDIT_CLIENT_ID'),
        client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
        user_agent=os.getenv('REDDIT_USER_AGENT', 'MyBot/1.0')
    )
    
    try:
        # Get daily discussion (prioritize stickied ones)
        logger.info("Getting daily discussion...")
        discussion_id = await get_daily_discussion(reddit)
        
        # Get pinned posts
        pinned_post_ids = await get_pinned_posts(reddit)
        
        # Get the last 20 posts
        last_20_discussion_ids = await get_last_20_discussion_ids(reddit)
        
        # Combine all IDs, prioritizing pinned posts and daily discussion
        all_post_ids = []
        
        # First add daily discussion if found
        if discussion_id and discussion_id != 'No daily discussion found':
            all_post_ids.append(discussion_id)
            
        # Then add all pinned posts
        all_post_ids.extend(pinned_post_ids)
        
        # Finally add the most recent posts
        all_post_ids.extend(last_20_discussion_ids)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_post_ids = [x for x in all_post_ids if not (x in seen or seen.add(x))]
        
        logger.info(f"Collected post IDs: {unique_post_ids}")
        
        if not unique_post_ids:
            error_msg = '❌ No posts found. Exiting...'
            logger.error(error_msg)
            send_slack_message(error_msg)
            return

        # Process all posts
        numberOfCommentsFounds = 0
        for post_id in unique_post_ids:
            if post_id == 'No daily discussion found': 
                continue
                
            # Store post in database
            submission = await reddit.submission(id=post_id)
            store_daily_discussion(supabase, post_id, submission.title)
            
            # Get and process comments
            comments = await get_comments(post_id, reddit)
            numberOfCommentsFounds += len(comments)
            
        success_msg = f"✅ Reddit Script Complete!\nFound {numberOfCommentsFounds} comments\nProcessed {len(unique_post_ids)} posts"
        send_slack_message(success_msg)
        logger.info(f"Found {numberOfCommentsFounds} comments across {len(unique_post_ids)} posts")   

    except Exception as e:
        error_msg = f"❌ Error in Reddit script: {str(e)}"
        logger.error(error_msg)
        send_slack_message(error_msg)
        raise
    finally:
        await reddit.close()

if __name__ == "__main__":
    asyncio.run(main())