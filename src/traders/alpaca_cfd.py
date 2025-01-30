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

class AlpacaCFDTrader:
    def __init__(self, 
                 fixed_trade_amount: float = 100000, 
                 leverage: int = 1,
                 max_position_size: float = 500000):
        """
        Initialize Alpaca trading client
        """
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
        # Initialize API clients
        self.api_key = os.getenv('ALPACA_API_KEY') or os.environ.get('ALPACA_API_KEY')
        self.api_secret = os.getenv('ALPACA_API_SECRET') or os.environ.get('ALPACA_API_SECRET')
        
        if not self.api_key or not self.api_secret:
            raise ValueError("Missing Alpaca API credentials")

        self.trading_client = TradingClient(self.api_key, self.api_secret, paper=True)
        self.data_client = StockHistoricalDataClient(self.api_key, self.api_secret)
        
        account = self.trading_client.get_account()
        print(f"Account Status: {account.status}")
        print(f"Trading Account Type: Paper Trading")

    def execute_trades(self, decisions: Dict) -> Dict:
        """
        Execute trades based on the enhanced decisions
        
        Args:
            decisions (Dict): Dictionary of trading decisions with quantities
            
        Returns:
            Dict: Dictionary of execution results
        """
        results = {}
        
        self.logger.info("=== Starting Trade Execution ===")
        print("\n=== Starting Trade Execution ===")
        
        for symbol, decision in decisions.items():
            self.logger.info(f"\nProcessing trade for {symbol}")
            print(f"\nProcessing trade for {symbol}")
            
            action = decision.get('action', 'hold').lower()
            quantity = decision.get('quantity', 0)
            
            if action == 'hold' or quantity <= 0:
                message = f"HOLD position for {symbol}"
                self.logger.info(message)
                results[symbol] = {'status': 'no_action', 'message': message}
                continue

            try:
                # Create the order
                order_details = MarketOrderRequest(
                    symbol=symbol,
                    qty=quantity,
                    side=OrderSide.BUY if action == 'buy' else OrderSide.SELL,
                    time_in_force=TimeInForce.DAY
                )
                
                self.logger.info(f"Submitting order: {order_details}")
                print(f"Submitting order: {order_details}")

                # Submit the order
                order = self.trading_client.submit_order(order_details)
                
                message = f"Order submitted for {symbol}: {action.upper()} {quantity} shares"
                self.logger.info(message)
                
                results[symbol] = {
                    'status': 'submitted',
                    'order_id': order.id,
                    'order_status': order.status,
                    'action': action,
                    'quantity': quantity,
                    'message': message
                }
                
            except Exception as e:
                error_message = f"Error executing trade for {symbol}: {str(e)}"
                self.logger.error(error_message)
                results[symbol] = {
                    'status': 'error',
                    'message': error_message
                }

        # Print final summary
        self.logger.info("\n=== Trade Execution Summary ===")
        print("\n=== Trade Execution Summary ===")
        for symbol, result in results.items():
            summary = f"{symbol}: {result['status']} - {result['message']}"
            self.logger.info(summary)
            print(summary)
        
        return results

def execute_trades(decisions: dict, 
                  fixed_amount: float = 100000,
                  leverage: int = 1,
                  max_position_size: float = 500000) -> dict:
    """
    Wrapper function to execute trades
    """
    try:
        trader = AlpacaCFDTrader(
            fixed_trade_amount=fixed_amount,
            leverage=leverage,
            max_position_size=max_position_size
        )
        
        print("\nExecuting trades...")
        results = trader.execute_trades(decisions)
        
        print("\nTrade execution completed.")
        return results
        
    except Exception as e:
        error_message = f"Failed to execute trades: {str(e)}"
        print(f"ERROR: {error_message}")
        return {'error': error_message}