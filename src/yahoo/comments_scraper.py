import argparse
import requests
from bs4 import BeautifulSoup
import json

def get_comments():
    #### variables
    url = 'https://finance.yahoo.com/quote/TSLA/community?p=TSLA'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/110.0'}

    comments_array = []  # Initialize array to store comments

    #### perform the request to retrieve the page content
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    #### parse the response
    soup = BeautifulSoup(response.text, 'html.parser')

    config_script = soup.select_one('#spotim-config')
    if config_script:
        config_text = config_script.get_text(strip=True)
        data = json.loads(config_text)['config']

        #### define the URL and payload for the POST request
        api_url = "https://api-2-0.spot.im/v1.0.0/conversation/read"
        payload = json.dumps({
          "conversation_id": data['spotId'] + data['uuid'].replace('_', '$'),
          "count": 50,  # Increased count to get more comments
          "offset": 0
        })

        #### define headers for the POST request
        post_headers = {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/110.0',
          'Content-Type': 'application/json',
          'x-spot-id': data['spotId'],
          'x-post-id': data['uuid'].replace('_', '$'),
        }

        #### perform the POST request
        post_response = requests.post(api_url, headers=post_headers, data=payload)
        post_response.raise_for_status()

        # Parse the response
        conversation_data = post_response.json()
        
        # Extract comments and store in array
        if 'conversation' in conversation_data and 'comments' in conversation_data['conversation']:
            for comment in conversation_data['conversation']['comments']:
                comment_obj = {
                    'comment_id': comment.get('id', ''),
                    'root_comment': comment.get('root_comment', ''),
                    'user_id': comment.get('user_id', ''),
                    'text': ' '.join([c.get('text', '') for c in comment.get('content', []) if c.get('type') == 'text']),
                    'timestamp': comment.get('written_at', ''),
                    'replies_count': comment.get('replies_count', 0),
                    'rank': comment.get('rank', {}),
                    'rank_score': comment.get('rank_score', 0),
                    'status': comment.get('status', ''),
                    'best_score': comment.get('best_score', 0),
                    'user_reputation': comment.get('user_reputation', 0),
                }
                comments_array.append(comment_obj)

        # Print the array of comments
        print(json.dumps(comments_array, indent=2))
        return comments_array
    else:
        print("Failed to find the configuration script on the page.")
        return []

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Yahoo Finance comments and stock data")
    parser.add_argument("--initial-cash", type=float, default=100000.0, help="Initial cash position")
    parser.add_argument("--ticker", type=str, help="Stock ticker symbol (e.g., NVDA)")

    args = parser.parse_args()

    # Call your existing function here
    get_comments()