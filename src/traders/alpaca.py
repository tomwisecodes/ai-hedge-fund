from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
import os

class AlpacaExecutor:
    def __init__(self, fixed_trade_amount: float = 100000):
        """
        Initialize Alpaca trading client
        :param fixed_trade_amount: Amount to use for each buy order
        """
        # Get API keys from environment
        api_key = os.getenv('ALPACA_API_KEY')
        api_secret = os.getenv('ALPACA_API_SECRET')
        
        if not api_key or not api_secret:
            raise ValueError("Please set ALPACA_API_KEY and ALPACA_API_SECRET environment variables")

        self.client = TradingClient(api_key, api_secret, paper=True)
        self.fixed_trade_amount = fixed_trade_amount

    def get_position_quantity(self, symbol: str) -> int:
        """Get current position quantity for a symbol"""
        try:
            position = self.client.get_open_position(symbol)
            return int(float(position.qty))
        except Exception:
            return 0

    def calculate_buy_quantity(self, symbol: str) -> int:
        """Calculate quantity to buy based on fixed amount"""
        try:
            # Get latest trade
            position = self.client.get_latest_trade(symbol)
            price = float(position.price)
            return int(self.fixed_trade_amount / price)
        except Exception as e:
            print(f"Error calculating quantity for {symbol}: {str(e)}")
            return 0

    def execute_trades(self, decisions: dict) -> dict:
        """
        Execute trades based on the hedge fund decisions
        :param decisions: Dictionary of trading decisions
        :return: Dictionary of execution results
        """
        results = {}
        
        for symbol, decision in decisions.items():
            action = decision.get('action', 'hold').lower()
            
            if action == 'hold':
                results[symbol] = {'status': 'no_action', 'message': 'HOLD position'}
                continue

            try:
                if action == 'buy':
                    quantity = self.calculate_buy_quantity(symbol)
                    side = OrderSide.BUY
                else:  # sell
                    quantity = self.get_position_quantity(symbol)
                    side = OrderSide.SELL

                if quantity <= 0:
                    results[symbol] = {
                        'status': 'skipped',
                        'message': f'No quantity to {action} (quantity={quantity})'
                    }
                    continue

                # Create and submit order
                order_details = MarketOrderRequest(
                    symbol=symbol,
                    qty=quantity,
                    side=side,
                    time_in_force=TimeInForce.DAY
                )

                order = self.client.submit_order(order_details)
                
                results[symbol] = {
                    'status': 'submitted',
                    'order_id': order.id,
                    'action': action,
                    'quantity': quantity,
                    'message': f'Order submitted: {action.upper()} {quantity} shares'
                }
                
            except Exception as e:
                results[symbol] = {
                    'status': 'error',
                    'message': str(e)
                }

        return results

def execute_trades(decisions: dict, fixed_amount: float = 100000) -> dict:
    """
    Wrapper function to execute trades
    :param decisions: Dictionary of trading decisions
    :param fixed_amount: Amount to use for each buy order
    :return: Dictionary of execution results
    """
    try:
        executor = AlpacaExecutor(fixed_trade_amount=fixed_amount)
        return executor.execute_trades(decisions)
    except Exception as e:
        return {'error': str(e)}