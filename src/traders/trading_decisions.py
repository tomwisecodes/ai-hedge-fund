from asyncio.log import logger
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
import os
from typing import Dict
import logging
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Debug environment variables
print("\nDebugging Environment Variables:")
print(f"ALPACA_API_KEY exists: {'ALPACA_API_KEY' in os.environ}")
print(f"ALPACA_API_SECRET exists: {'ALPACA_API_SECRET' in os.environ}")
        
        
ALPACA_API_KEY = (
    os.getenv('ALPACA_API_KEY') or 
    os.environ.get('ALPACA_API_KEY') or 
    os.getenv('APCA_API_KEY_ID')
    )
ALPACA_API_SECRET = (
    os.getenv('ALPACA_API_SECRET') or 
    os.environ.get('ALPACA_API_SECRET') or 
    os.getenv('APCA_API_SECRET_KEY')
    )
        
# Print diagnostic information
print("\nAPI Key Status:")
print(f"API Key length: {len(ALPACA_API_KEY) if ALPACA_API_KEY else 0}")
print(f"API Secret length: {len(ALPACA_API_SECRET) if ALPACA_API_SECRET else 0}")
        
if not ALPACA_API_KEY or not ALPACA_API_SECRET:
    error_msg = """
    Missing Alpaca API credentials. Please ensure either:
    1. ALPACA_API_KEY and ALPACA_API_SECRET are set in your environment
    2. APCA_API_KEY_ID and APCA_API_SECRET_KEY are set in your environment
    3. These variables are properly set in your .env file
    """
    logger.error(error_msg)
    raise ValueError(error_msg)

def enhance_trading_decisions(decisions, portfolio_value, owned_positions):
    enhanced_decisions = {}
    
    # Get account info for risk calculations
    trading_client = TradingClient(os.getenv('ALPACA_API_KEY'), os.getenv('ALPACA_API_SECRET'), paper=True)
    account = trading_client.get_account()
    available_cash = float(account.cash)
    
    # Risk parameters
    MAX_POSITION_PCT = 0.2  # No position > 20% of portfolio
    MIN_CASH_BUFFER = 0.1   # Keep 10% in cash
    
    for symbol, decision in decisions.items():
        action = decision.get('action', 'hold')
        
        # Get current position if any
        current_position = next((p for p in owned_positions if p.symbol == symbol), None)
        
        if action == 'sell' and current_position:
            # If selling, liquidate entire position
            enhanced_decisions[symbol] = {
                'action': 'sell',
                'quantity': float(current_position.qty)
            }
            
        elif action == 'buy':
            # Calculate maximum position size
            max_position_value = portfolio_value * MAX_POSITION_PCT
            current_value = float(current_position.market_value) if current_position else 0
            
            # Get latest price
            data_client = StockHistoricalDataClient(os.getenv('ALPACA_API_KEY'), os.getenv('ALPACA_API_SECRET'))
            quote = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))
            price = float(quote[symbol].ask_price)
            
            # Calculate how much more we can buy
            available_position_value = max_position_value - current_value
            cash_available = available_cash * (1 - MIN_CASH_BUFFER)
            
            # Calculate quantity
            quantity = min(
                int(available_position_value / price),
                int(cash_available / price)
            )
            
            if quantity > 0:
                enhanced_decisions[symbol] = {
                    'action': 'buy',
                    'quantity': quantity
                }
            else:
                enhanced_decisions[symbol] = {'action': 'hold'}
        
        else:
            enhanced_decisions[symbol] = {'action': 'hold'}
    
    return enhanced_decisions