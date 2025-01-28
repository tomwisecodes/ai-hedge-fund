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
                 leverage: int = 1,  # Default to no leverage
                 max_position_size: float = 500000):
        """
        Initialize Alpaca trading client
        
        Args:
            fixed_trade_amount (float): Base amount for position sizing
            leverage (int): Leverage ratio (defaults to 1 for no leverage)
            max_position_size (float): Maximum total exposure allowed
        """
        # Initialize logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
        # Debug environment variables
        print("\nDebugging Environment Variables:")
        print(f"ALPACA_API_KEY exists: {'ALPACA_API_KEY' in os.environ}")
        print(f"ALPACA_API_SECRET exists: {'ALPACA_API_SECRET' in os.environ}")
        
        # Try multiple ways to get the API credentials
        self.api_key = (
            os.getenv('ALPACA_API_KEY') or 
            os.environ.get('ALPACA_API_KEY') or 
            os.getenv('APCA_API_KEY_ID')
        )
        self.api_secret = (
            os.getenv('ALPACA_API_SECRET') or 
            os.environ.get('ALPACA_API_SECRET') or 
            os.getenv('APCA_API_SECRET_KEY')
        )
        
        # Print diagnostic information
        print("\nAPI Key Status:")
        print(f"API Key length: {len(self.api_key) if self.api_key else 0}")
        print(f"API Secret length: {len(self.api_secret) if self.api_secret else 0}")
        
        if not self.api_key or not self.api_secret:
            error_msg = """
            Missing Alpaca API credentials. Please ensure either:
            1. ALPACA_API_KEY and ALPACA_API_SECRET are set in your environment
            2. APCA_API_KEY_ID and APCA_API_SECRET_KEY are set in your environment
            3. These variables are properly set in your .env file
            """
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        # Initialize both trading and data clients
        self.trading_client = TradingClient(self.api_key, self.api_secret, paper=True)
        self.data_client = StockHistoricalDataClient(self.api_key, self.api_secret)
        
        print("\nInitializing Trading Account:")
        account = self.trading_client.get_account()
        print(f"Account ID: {account.id}")
        print(f"Account Status: {account.status}")
        print(f"Trading Account Type: Paper Trading")
        print(f"Pattern Day Trader Status: {account.pattern_day_trader}")
        
        self.fixed_trade_amount = fixed_trade_amount
        self.leverage = leverage
        self.max_position_size = max_position_size
        
        self.logger.info(f"Initialized Alpaca Trader with trade amount ${fixed_trade_amount:,.2f}")
        print(f"Initialized Alpaca Trader with trade amount ${fixed_trade_amount:,.2f}")

    def get_latest_price(self, symbol: str) -> float:
        """
        Get the latest price for a symbol
        
        Args:
            symbol (str): The stock symbol
            
        Returns:
            float: Latest price for the symbol
        """
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quote = self.data_client.get_stock_latest_quote(request)
            # Use ask price for buying
            price = float(quote[symbol].ask_price)
            print(f"Latest price for {symbol}: ${price:.2f}")
            return price
        except Exception as e:
            self.logger.error(f"Error getting price for {symbol}: {e}")
            raise

    def get_account_info(self) -> Dict:
        """
        Get current account information
        
        Returns:
            Dict: Account information including buying power and equity
        """
        try:
            account = self.trading_client.get_account()
            account_info = {
                'buying_power': float(account.buying_power),
                'equity': float(account.equity),
                'cash': float(account.cash),
                'timestamp': datetime.now().isoformat()
            }
            self.logger.info(f"Account Info: {account_info}")
            print(f"Account Info: {account_info}")
            return account_info
        except Exception as e:
            self.logger.error(f"Error getting account info: {e}")
            print(f"Error getting account info: {e}")
            return {}

    def calculate_position_size(self, symbol: str, action: str) -> tuple:
        """
        Calculate position size for standard trading
        
        Args:
            symbol (str): Trading symbol
            action (str): Trading action ('buy' or 'sell')
            
        Returns:
            tuple: (quantity, cash_required)
        """
        self.logger.info(f"Calculating position size for {symbol} - Action: {action}")
        print(f"Calculating position size for {symbol} - Action: {action}")
        
        try:
            # Get latest price using the data client
            price = self.get_latest_price(symbol)
            
            if action == 'buy':
                # Calculate position size without leverage
                cash_required = min(self.fixed_trade_amount, self.max_position_size)
                quantity = int(cash_required / price)  # Integer number of shares
                
                self.logger.info(f"Calculated position: {quantity} shares, Cash required: ${cash_required:,.2f}")
                print(f"Calculated position: {quantity} shares, Cash required: ${cash_required:,.2f}")
                return quantity, cash_required
            
            elif action == 'sell':
                try:
                    position = self.trading_client.get_open_position(symbol)
                    quantity = int(float(position.qty))
                    self.logger.info(f"Current position for {symbol}: {quantity} shares")
                    print(f"Current position for {symbol}: {quantity} shares")
                    return quantity, 0
                except Exception as e:
                    self.logger.warning(f"No existing position found for {symbol}: {e}")
                    print(f"No existing position found for {symbol}: {e}")
                    return 0, 0
                    
            return 0, 0
            
        except Exception as e:
            self.logger.error(f"Error calculating position size for {symbol}: {e}")
            print(f"Error calculating position size for {symbol}: {e}")
            raise

    def check_risk_limits(self, cash_required: float) -> bool:
        """
        Check if trade meets risk management criteria
        
        Args:
            cash_required (float): Required cash for the trade
            
        Returns:
            bool: Whether trade passes risk checks
        """
        self.logger.info(f"Checking risk limits for cash requirement: ${cash_required:,.2f}")
        print(f"Checking risk limits for cash requirement: ${cash_required:,.2f}")
        
        account_info = self.get_account_info()
        
        if not account_info:
            self.logger.error("Failed to get account info for risk check")
            print("Failed to get account info for risk check")
            return False
            
        # Check if we have enough buying power
        if cash_required > float(account_info['buying_power']):
            self.logger.warning(
                f"Insufficient buying power: ${cash_required:,.2f} required, "
                f"${account_info['buying_power']:,.2f} available"
            )
            print(
                f"Insufficient buying power: ${cash_required:,.2f} required, "
                f"${account_info['buying_power']:,.2f} available"
            )
            return False
            
        self.logger.info("Risk checks passed")
        print("Risk checks passed")
        return True

    def execute_trades(self, decisions: Dict) -> Dict:
        """
        Execute trades based on the hedge fund decisions
        
        Args:
            decisions (Dict): Dictionary of trading decisions
            
        Returns:
            Dict: Dictionary of execution results
        """
        results = {}
        
        self.logger.info("=== Starting Trade Execution ===")
        print("\n=== Starting Trade Execution ===")
        account_info = self.get_account_info()
        print(f"Initial Account Info: {account_info}")
        
        for symbol, decision in decisions.items():
            self.logger.info(f"\nProcessing trade for {symbol}")
            print(f"\nProcessing trade for {symbol}")
            
            action = decision.get('action', 'hold').lower()
            self.logger.info(f"Action: {action}")
            print(f"Action: {action}")
            
            if action == 'hold':
                message = f"HOLD position for {symbol}"
                self.logger.info(message)
                print(message)
                results[symbol] = {'status': 'no_action', 'message': message}
                continue

            try:
                # Calculate position size
                quantity, cash_required = self.calculate_position_size(symbol, action)
                
                if quantity <= 0:
                    message = f"Invalid quantity calculated for {symbol}: {quantity}"
                    self.logger.warning(message)
                    print(message)
                    results[symbol] = {'status': 'skipped', 'message': message}
                    continue

                # For buys, check risk limits
                if action == 'buy' and not self.check_risk_limits(cash_required):
                    message = f"Failed risk management checks for {symbol}"
                    self.logger.warning(message)
                    print(message)
                    results[symbol] = {'status': 'rejected', 'message': message}
                    continue

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
                print(message)
                print(f"Order ID: {order.id}")
                print(f"Order Status: {order.status}")
                
                results[symbol] = {
                    'status': 'submitted',
                    'order_id': order.id,
                    'order_status': order.status,
                    'action': action,
                    'quantity': quantity,
                    'cash_required': cash_required if action == 'buy' else 0,
                    'message': message
                }
                
            except Exception as e:
                error_message = f"Error executing trade for {symbol}: {str(e)}"
                self.logger.error(error_message)
                print(f"ERROR: {error_message}")
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
        
        # Get final account state
        final_account = self.get_account_info()
        self.logger.info(f"Final Account Info: {final_account}")
        print(f"Final Account Info: {final_account}")
        
        return results

def execute_trades(decisions: dict, 
                  fixed_amount: float = 100000,
                  leverage: int = 1,  # Default to no leverage
                  max_position_size: float = 500000) -> dict:
    """
    Wrapper function to execute trades
    
    Args:
        decisions (dict): Dictionary of trading decisions
        fixed_amount (float): Base amount for position sizing
        leverage (int): Leverage ratio (defaults to 1 for no leverage)
        max_position_size (float): Maximum total exposure allowed
        
    Returns:
        dict: Dictionary of execution results
    """
    try:
        print(f"\nInitializing trader with:")
        print(f"- Fixed amount: ${fixed_amount:,.2f}")
        print(f"- Max position size: ${max_position_size:,.2f}")
        
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