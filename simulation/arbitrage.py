import numpy as np
import random
from .utils import price_to_sqrtp
from .logger import logger
from .constants import q96, eth

class Arbitrage:
    """
    Arbitrage agent that detects and exploits price discrepancies between
    an external price and the pool price.

    Attributes:
        minGasPrice (float): Minimum profit to gas cost ratio to execute trade.
        profitToGasRatio (float): Ratio of profit burned to gas fees.
        pool (Pool): Reference to the liquidity pool instance.
        fee_outside (float): Fee applied on external market trades.
        skip (float): Probability to skip deal attempts (0 to 1).
    """

    def __init__(self, minGasPrice, profitToGasRatio, pool, fee_outside=0.001, skip=0):
        self.skip = skip
        self.minGasPrice = minGasPrice
        self.profitToGasRatio = profitToGasRatio
        self.pool = pool
        self.fee_outside = fee_outside

        self.cumulativeProfit = 0
        self.cumulativeVolume = 0
        self.cumulativeBurn = 0
        self.numDeals = 0

        self.lastPriceInPool = None
        self.lastPriceOutside = None

    def deal(self, currentPriceOutside):
        """
        Executes an arbitrage deal if price deviation is profitable.

        Args:
            currentPriceOutside (float): External market price.

        Returns:
            bool or 0: False if no deal executed, 0 if skipped due to random chance.
        """
        if random.random() < self.skip:
            return 0

        currentPricePool = self.pool.currentPrice
        fee = self.pool.fee

        left_ntr = currentPricePool * (1 - fee - self.fee_outside)
        right_ntr = currentPricePool * (1 + fee + self.fee_outside)

        if self.lastPriceInPool == currentPricePool and self.lastPriceOutside == currentPriceOutside:
            logger.info('Arb: No price change, skipping deals.')
            return False

        self.lastPriceInPool = currentPricePool
        self.lastPriceOutside = currentPriceOutside

        logger.info(f'Arb: No-trade region [{left_ntr:.2f} - {right_ntr:.2f}], Pool price: {currentPricePool:.2f}, Outside price: {currentPriceOutside:.2f}')

        # Price below lower no-trade boundary — buy from pool, sell outside
        if currentPriceOutside < left_ntr:
            price_after_arb = currentPriceOutside / (1 - fee - self.fee_outside)
            result = self._optimize_trade(price_after_arb, ZtO=True)
            if not result:
                return False

            delta_x, delta_y = result  # sell dx, buy dy (price drops)
            x_return = -delta_y / currentPriceOutside * (1 - self.fee_outside)
            arb_profit = (x_return - delta_x) * currentPriceOutside
            real_profit = arb_profit * (1 - self.profitToGasRatio)
            burned_profit = arb_profit * self.profitToGasRatio

            logger.info(f'Arb profit potential: buy {delta_y:.2f}y, sell for {x_return:.2f}x; gross profit {arb_profit:.2f}y, net {real_profit:.2f}y')

            if burned_profit < self.minGasPrice:
                logger.info(f'Arb profit {burned_profit:.2f} below min gas price {self.minGasPrice}')
                return False

            logger.info(f'Arb: Executing swap dx={delta_x}, ZtO=True')
            self.pool.swap(delta_x, ZtO=True, simulate=False)
            self._update_stats(real_profit, delta_x * currentPricePool, burned_profit)

        # Price above upper no-trade boundary — buy from outside, sell in pool
        elif currentPriceOutside > right_ntr:
            price_after_arb = currentPriceOutside / (1 + fee + self.fee_outside)
            result = self._optimize_trade(price_after_arb, ZtO=False)
            if not result:
                return False

            delta_y, delta_x = result  # buy dx, sell dy (price rises)
            y_return = -delta_x * currentPriceOutside * (1 - self.fee_outside)
            arb_profit = y_return - delta_y
            real_profit = arb_profit * (1 - self.profitToGasRatio)
            burned_profit = arb_profit * self.profitToGasRatio

            logger.info(f'Arb profit potential: buy {delta_x:.2f}x, sell for {y_return:.2f}y; gross profit {arb_profit:.2f}y, net {real_profit:.2f}y')

            if burned_profit < self.minGasPrice:
                logger.info(f'Arb profit {burned_profit:.2f} below min gas price {self.minGasPrice}')
                return False

            logger.info(f'Arb: Executing swap dy={delta_y}, ZtO=False')
            self.pool.swap(delta_y, ZtO=False, simulate=False)
            self._update_stats(real_profit, delta_y, burned_profit)

        else:
            logger.info('Arb: Price within no-trade region, no action taken.')

    def _optimize_trade(self, idealPrice, ZtO=True):
        """
        Calculates optimal trade amounts to move pool price to idealPrice.

        Args:
            idealPrice (float): Target pool price after trade.
            ZtO (bool): Direction of swap (True: token0->token1).

        Returns:
            tuple or None: Amounts to swap (delta_x, delta_y) or None if not feasible.
        """
        sum_delta_x = 0
        sum_delta_y = 0
        idealPrice = price_to_sqrtp(idealPrice)
        new_price = self.pool.currentSqrtPrice

        while new_price != idealPrice:
            nearestPrice, activePositions, totalLiq = self._find_L_and_nearest_range(new_price, ZtO)

            if ZtO:
                if nearestPrice <= idealPrice:
                    delta_price_yx = idealPrice - new_price
                    delta_price_xy = 1 / idealPrice - 1 / new_price
                    delta_y = delta_price_yx * totalLiq / q96
                    delta_x = delta_price_xy * totalLiq * (1 + self.pool.fee) * q96
                    return sum_delta_x / eth + delta_x / eth, sum_delta_y / eth + delta_y / eth
                else:
                    delta_price_yx = nearestPrice - new_price
                    delta_price_xy = 1 / nearestPrice - 1 / new_price
                    delta_y = delta_price_yx * totalLiq / q96
                    delta_x = delta_price_xy * totalLiq * (1 + self.pool.fee) * q96
                    sum_delta_y += delta_y
                    sum_delta_x += delta_x
                    new_price = nearestPrice

            else:
                if nearestPrice >= idealPrice:
                    delta_price_yx = idealPrice - new_price
                    delta_price_xy = 1 / idealPrice - 1 / new_price
                    delta_y = delta_price_yx * totalLiq * (1 + self.pool.fee) / q96
                    delta_x = delta_price_xy * totalLiq * q96
                    return sum_delta_y / eth + delta_y / eth, sum_delta_x / eth + delta_x / eth
                else:
                    delta_price_yx = nearestPrice - new_price
                    delta_price_xy = 1 / nearestPrice - 1 / new_price
                    delta_y = delta_price_yx * totalLiq * (1 + self.pool.fee) / q96
                    delta_x = delta_price_xy * totalLiq * q96
                    sum_delta_y += delta_y
                    sum_delta_x += delta_x
                    new_price = nearestPrice

    def _find_L_and_nearest_range(self, price, ZtO=True):
        """
        Finds nearest initialized price boundary and active liquidity positions.

        Args:
            price (float): Reference sqrt price.
            ZtO (bool): Direction (True: token0->token1).

        Returns:
            tuple: (nearestInitializedPrice, activePositions, totalLiquidity)
        """
        if ZtO:
            nearestPrice = 0
        else:
            nearestPrice = 1e12 * q96  # Large number

        activePositions = {}
        totalLiq = 0

        for id, pos in self.pool.liq_bitmap.items():
            pa = pos['pa']
            pb = pos['pb']

            if ZtO:
                if pb < price and price - pb < price - nearestPrice:
                    nearestPrice = pb
                if pa < price and price - pa < price - nearestPrice:
                    nearestPrice = pa
                if pa < price <= pb:
                    activePositions[id] = pos
                    totalLiq += pos['L']
            else:
                if pb > price and pb - price < nearestPrice - price:
                    nearestPrice = pb
                if pa > price and pa - price < nearestPrice - price:
                    nearestPrice = pa
                if pa <= price < pb:
                    activePositions[id] = pos
                    totalLiq += pos['L']

        # Clean edge case of single position ending exactly at price
        if len(activePositions) == 1:
            pos = next(iter(activePositions.values()))
            if ZtO and pos['pa'] == price:
                activePositions.clear()
                totalLiq = 0
            elif not ZtO and pos['pb'] == price:
                activePositions.clear()
                totalLiq = 0

        return nearestPrice, activePositions, totalLiq

    def _update_stats(self, profit, volume, burned):
        """Updates cumulative statistics after a successful trade."""
        self.cumulativeProfit += profit
        self.cumulativeVolume += volume
        self.cumulativeBurn += burned
        self.numDeals += 1
