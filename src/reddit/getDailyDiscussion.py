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
import time

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

def store_daily_discussion(supabase, post_id, title, subreddit_id):
    """Store a reddit post with its associated subreddit_id"""
    try:
        record = {
            'id': post_id,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'title': title,
            'subreddit_id': subreddit_id
        }
        supabase.table('reddit_posts').upsert(record).execute()
        logger.info(f"Stored post: {post_id} - {title[:30]}... for subreddit_id {subreddit_id}")
    except Exception as e:
        logger.error(f"Error storing post: {e}")

async def get_daily_discussion(reddit: asyncpraw.Reddit, subreddit_name: str, subreddit_id: int) -> str:
    try:
        daily_discussion_id = ''
        # Check if the daily discussion is stickied
        subreddit = await reddit.subreddit(subreddit_name)
        
        try:
            sticky = await subreddit.sticky()
            if sticky.link_flair_text == 'Daily Discussion':
                daily_discussion_id = sticky.id
        except:
            pass  # No sticky found or other error

        if daily_discussion_id:
            # Write the daily discussion ID to the database
            store_daily_discussion(supabase, daily_discussion_id, sticky.link_flair_text, subreddit_id)
            return daily_discussion_id
        else:
            # If the daily discussion is not stickied, get the 50 newest posts
            posts = [post async for post in subreddit.new(limit=50)]
            
            daily_discussion = next(
                (post for post in posts 
                 if 'Daily Discussion' in post.title 
                 or 'Moves Tomorrow' in post.title),
                None
            )
            
            if daily_discussion is None:
                logger.error(f'No daily discussion found in {subreddit_name}')
                return 'No daily discussion found'

            # Write the daily discussion ID to the database
            store_daily_discussion(supabase, daily_discussion.id, daily_discussion.title, subreddit_id)
            
            return daily_discussion.id

    except Exception as error:
        logger.error(f'Error in {subreddit_name}:', error)
        raise

async def get_daily_discussions(
    reddit: asyncpraw.Reddit,
    subreddit_name: str,
    limit: Optional[int] = 100,
    skip: Optional[int] = 200
) -> List[DiscussionPost]:
    try:
        # Get newest posts
        subreddit = await reddit.subreddit(subreddit_name)
        posts = [post async for post in subreddit.new(limit=limit or 100)]
        
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
        logger.error(f'Error in {subreddit_name}:', error)
        raise


async def get_last_20_discussion_ids(reddit: asyncpraw.Reddit, subreddit_name: str) -> List[str]:
    try:
        # Get newest posts - changing to 20 posts
        subreddit = await reddit.subreddit(subreddit_name)
        posts = [post async for post in subreddit.new(limit=20)]
        
        discussion_ids = []

        for post in posts:
            discussion_ids.append(post.id)

        return discussion_ids

    except Exception as error:
        logger.error(f'Error in {subreddit_name}:', error)
        raise

async def get_pinned_posts(reddit: asyncpraw.Reddit, subreddit_name: str) -> List[str]:
    """Get all pinned/stickied posts from a subreddit"""
    try:
        subreddit = await reddit.subreddit(subreddit_name)
        pinned_ids = []
        
        # Try to get both stickied posts (there can be up to 2)
        for i in range(1, 3):
            try:
                sticky = await subreddit.sticky(number=i)
                pinned_ids.append(sticky.id)
                logger.info(f"Found pinned post in {subreddit_name}: {sticky.title}")
            except:
                # No more stickies found
                break
                
        return pinned_ids
        
    except Exception as error:
        logger.error(f'Error getting pinned posts from {subreddit_name}: {error}')
        return []

async def process_subreddit(reddit: asyncpraw.Reddit, subreddit_data) -> int:
    """Process a single subreddit and return the number of comments found"""
    try:
        subreddit_name = subreddit_data["name"]
        subreddit_id = subreddit_data["id"]
        
        logger.info(f"Processing subreddit: {subreddit_name} (ID: {subreddit_id})")
        send_slack_message(f"🔍 Starting to process subreddit: r/{subreddit_name}")
        
        # Get daily discussion (prioritize stickied ones)
        logger.info(f"Getting daily discussion for {subreddit_name}...")
        discussion_id = await get_daily_discussion(reddit, subreddit_name, subreddit_id)
        
        # Get pinned posts
        pinned_post_ids = await get_pinned_posts(reddit, subreddit_name)
        
        # Get the last 20 posts
        last_20_discussion_ids = await get_last_20_discussion_ids(reddit, subreddit_name)
        
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
        
        logger.info(f"Collected {len(unique_post_ids)} post IDs from {subreddit_name}")
        send_slack_message(f"📝 Found {len(unique_post_ids)} posts to process in r/{subreddit_name}")
        
        if not unique_post_ids:
            logger.warning(f"No posts found in {subreddit_name}")
            send_slack_message(f"⚠️ No posts found in r/{subreddit_name}")
            return 0

        # Process all posts
        numberOfCommentsFounds = 0
        total_ticker_mentions = 0
        processed_posts = 0
        
        for post_id in unique_post_ids:
            if post_id == 'No daily discussion found': 
                continue
                
            # Store post in database
            submission = await reddit.submission(id=post_id)
            store_daily_discussion(supabase, post_id, submission.title, subreddit_id)
            
            # Get and process comments
            post_start_time = time.time()
            comments = await get_comments(post_id, reddit)
            post_end_time = time.time()
            
            # Count unique tickers in this post
            post_tickers = set()
            for comment in comments:
                post_tickers.update(comment.get('tickers', []))
            
            numberOfCommentsFounds += len(comments)
            total_ticker_mentions += len(post_tickers)
            processed_posts += 1
            
            # Send progress update for each post
            post_msg = (
                f"📊 Post {processed_posts}/{len(unique_post_ids)} in r/{subreddit_name}:\n"
                f"• Title: {submission.title[:50]}...\n"
                f"• Comments with tickers: {len(comments)}\n"
                f"• Unique tickers found: {len(post_tickers)}\n"
                f"• Processing time: {post_end_time - post_start_time:.2f}s"
            )
            send_slack_message(post_msg)
        
        # Update last_scraped_at timestamp for this subreddit
        try:
            supabase.table("subreddits").update({"last_scraped_at": datetime.now().isoformat()}).eq("id", subreddit_id).execute()
        except Exception as e:
            logger.error(f"Failed to update last_scraped_at for subreddit {subreddit_name}: {e}")
        
        # Send summary for this subreddit
        summary_msg = (
            f"✅ Completed r/{subreddit_name}:\n"
            f"• Total posts processed: {processed_posts}\n"
            f"• Total comments with tickers: {numberOfCommentsFounds}\n"
            f"• Total unique ticker mentions: {total_ticker_mentions}"
        )
        send_slack_message(summary_msg)
        
        logger.info(f"Found {numberOfCommentsFounds} comments across {len(unique_post_ids)} posts in {subreddit_name}")
        return numberOfCommentsFounds
        
    except Exception as e:
        error_msg = f"❌ Error processing subreddit r/{subreddit_data.get('name', 'unknown')}: {str(e)}"
        logger.error(error_msg)
        send_slack_message(error_msg)
        return 0

async def main():
    load_dotenv()  # Load environment variables
    
    # Initialize the Reddit instance
    reddit = asyncpraw.Reddit(
        client_id=os.getenv('REDDIT_CLIENT_ID'),
        client_secret=os.getenv('REDDIT_CLIENT_SECRET'),
        user_agent=os.getenv('REDDIT_USER_AGENT', 'MyBot/1.0')
    )
    
    try:
        script_start_time = time.time()
        send_slack_message("🚀 Starting Reddit scraper")
        
        # Get subreddits from database
        logger.info("Fetching subreddits from database...")
        response = supabase.table("subreddits").select("*").execute()
        subreddits = response.data
        
        if not subreddits:
            # Fallback to wallstreetbets if no subreddits in database
            logger.warning("No subreddits found in database, using wallstreetbets as fallback")
            send_slack_message("⚠️ No subreddits found in database, using wallstreetbets as fallback")
            subreddits = [{"id": 0, "name": "wallstreetbets"}]
        
        logger.info(f"Found {len(subreddits)} subreddits to process")
        send_slack_message(f"🌐 Found {len(subreddits)} subreddits to process")
        
        # Process each subreddit
        total_comments = 0
        processed_subreddits = []
        
        for idx, subreddit in enumerate(subreddits):
            if not subreddit.get("name"):
                logger.warning(f"Skipping subreddit with no name: {subreddit}")
                continue
                
            try:
                send_slack_message(f"⏱️ Processing subreddit {idx+1}/{len(subreddits)}: r/{subreddit['name']}")
                num_comments = await process_subreddit(reddit, subreddit)
                total_comments += num_comments
                processed_subreddits.append(subreddit["name"])
            except Exception as e:
                error_msg = f"❌ Failed to process subreddit r/{subreddit.get('name', 'unknown')}: {str(e)}"
                logger.error(error_msg)
                send_slack_message(error_msg)
                
        # Send success message
        script_end_time = time.time()
        total_time = script_end_time - script_start_time
        
        if processed_subreddits:
            subreddits_str = ", ".join(f"r/{s}" for s in processed_subreddits)
            success_msg = (
                f"✅ Reddit Script Complete!\n"
                f"• Total time: {total_time:.2f} seconds\n"
                f"• Total comments processed: {total_comments}\n"
                f"• Processed subreddits: {subreddits_str}"
            )
            send_slack_message(success_msg)
            logger.info(f"Found {total_comments} comments across {len(processed_subreddits)} subreddits")
        else:
            error_msg = "❌ No subreddits were successfully processed"
            logger.error(error_msg)
            send_slack_message(error_msg)

    except Exception as e:
        error_msg = f"❌ Error in Reddit script: {str(e)}"
        logger.error(error_msg)
        send_slack_message(error_msg)
        raise
    finally:
        await reddit.close()

if __name__ == "__main__":
    asyncio.run(main())