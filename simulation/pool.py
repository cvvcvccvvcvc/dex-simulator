from .utils import price_to_sqrtp, liquidity0, liquidity1
from .constants import q96, eth
from .logger import logger
import copy

class Pool:
    """
    Uniswap V3-style liquidity pool simulation.
    Manages liquidity positions, fees, price updates, and swaps.
    """

    def __init__(self, first_price, fee):
        self.first_price = first_price
        self.currentPrice = first_price
        self.currentSqrtPrice = price_to_sqrtp(first_price)

        self.fee = fee
        self.last_fee = 0
        self.currentL = 0
        self.currentActiveID = {}
        self.liq_bitmap = {}  # position_id: {pa, pb, L, fees, balances...}
        self._fees_x = 0

        logger.info('Pool initialized')

    def add_liquidity(self, id, x=0, y=0, pa=0, pb=0):
        """
        Add liquidity position with token amounts x, y and price range [pa, pb].
        Price boundaries and amounts are converted internally.
        """
        x *= eth
        y *= eth
        pa = price_to_sqrtp(pa)
        pb = price_to_sqrtp(pb)
        if pa > pb:
            pa, pb = pb, pa

        if id not in self.liq_bitmap:
            self.liq_bitmap[id] = {}

        self.liq_bitmap[id].update({'pa': pa, 'pb': pb})

        if pa < self.currentSqrtPrice < pb:
            liq0 = liquidity0(x, pb, self.currentSqrtPrice)
            liq1 = liquidity1(y, self.currentSqrtPrice, pa)
            position_liquidity = int(min(liq0, liq1))
        elif self.currentSqrtPrice <= pa:
            position_liquidity = liquidity0(x, pb, pa)
        else:  # self.currentSqrtPrice >= pb
            position_liquidity = liquidity1(y, pb, pa)

        self.liq_bitmap[id]['L'] = position_liquidity
        self.liq_bitmap[id].update({
            'fee_in_y': 0,
            'fee_x': 0,
            'fee_y': 0,
            'x_real': x,
            'y_real': y,
            'first_price': self.currentPrice,
            'x_real_start': x / eth,
            'y_real_start': y / eth
        })

        if pa <= self.currentSqrtPrice <= pb:
            self.currentL += position_liquidity

        logger.info(f'Added liquidity: {self.liq_bitmap[id]}')

    def burn_liquidity(self, id):
        """
        Remove liquidity position by id.
        Returns removed position info or logs critical if not found.
        """
        if id in self.liq_bitmap:
            logger.info(f'Burn liquidity id={id} {self.liq_bitmap[id]}')
            return self.liq_bitmap.pop(id)
        else:
            logger.critical(f'Tried to remove non-existent liquidity id={id}')

    def swap(self, amnt=0, ZtO=True, simulate=False):
        """
        Execute or simulate swap.
        ZtO=True for token0 -> token1, False for token1 -> token0.
        Returns output amount and new price if simulate=True.
        """
        logger.debug(f'Start swap: simulate={simulate}, amnt={amnt}, ZtO={ZtO}')

        saved_fee = self.fee
        self.fee = self._hook_before_swap(amnt, ZtO)
        self.last_fee = self.fee

        if ZtO:
            return self._swap_token0_to_token1(amnt, simulate, saved_fee)
        else:
            return self._swap_token1_to_token0(amnt, simulate, saved_fee)

    def _swap_token0_to_token1(self, amnt, simulate, saved_fee):
        nearestPrice, activePositions, totalLiq = self._find_L_and_nearest_range(ZtO=True)
        delta_x_left = amnt * eth
        sum_delta_y = 0
        saved_liq_bitmap = copy.deepcopy(self.liq_bitmap)
        saved_price = self.currentPrice
        saved_sqrtPrice = self.currentSqrtPrice

        if delta_x_left == 0:
            logger.warning('delta_x_left = 0')
            return False

        while delta_x_left != 0:
            if totalLiq == 0:
                logger.info('No liquidity. Reverting swap.')
                self.liq_bitmap = saved_liq_bitmap
                self.currentPrice = saved_price
                self.currentSqrtPrice = saved_sqrtPrice
                return False

            delta_price_xy = delta_x_left / (1 + self.fee) / totalLiq / q96
            new_price_xy = 1 / self.currentSqrtPrice + delta_price_xy
            new_price = 1 / new_price_xy

            if new_price > nearestPrice:
                delta_price_yx = new_price - self.currentSqrtPrice
                delta_y = delta_price_yx * totalLiq / q96
                self._update_state_after_swap(delta_x_left, delta_y, totalLiq, new_price, activePositions, ZtO=True, last=True)
                delta_x_left = 0
                sum_delta_y += delta_y
            else:
                delta_x = totalLiq * (1 / nearestPrice - 1 / self.currentSqrtPrice)
                delta_x *= (1 + self.fee) * q96
                delta_price_yx = nearestPrice - self.currentSqrtPrice
                delta_y = delta_price_yx * totalLiq / q96
                self._update_state_after_swap(delta_x, delta_y, totalLiq, nearestPrice, activePositions, ZtO=True, last=False)
                delta_x_left -= delta_x
                sum_delta_y += delta_y
                nearestPrice, activePositions, totalLiq = self._find_L_and_nearest_range(ZtO=True)

        if simulate:
            self.liq_bitmap = saved_liq_bitmap
            self.currentPrice = saved_price
            self.currentSqrtPrice = saved_sqrtPrice
            return sum_delta_y, new_price
        else:
            self._hook_after_swap(amnt, True)
            logger.info(f'Swap done: {amnt} x -> {sum_delta_y / eth} y, price after swap={(new_price / q96) ** 2:.3f}')

    def _swap_token1_to_token0(self, amnt, simulate, saved_fee):
        nearestPrice, activePositions, totalLiq = self._find_L_and_nearest_range(ZtO=False)
        delta_y_left = amnt * eth
        sum_delta_x = 0
        saved_liq_bitmap = copy.deepcopy(self.liq_bitmap)
        saved_price = self.currentPrice
        saved_sqrtPrice = self.currentSqrtPrice

        if delta_y_left == 0:
            logger.warning('delta_y_left = 0')
            return False

        while delta_y_left != 0:
            if totalLiq == 0:
                logger.info('No liquidity. Reverting swap.')
                self.liq_bitmap = saved_liq_bitmap
                self.currentPrice = saved_price
                self.currentSqrtPrice = saved_sqrtPrice
                return False

            delta_price_yx = delta_y_left / (1 + self.fee) / totalLiq * q96
            new_price = self.currentSqrtPrice + delta_price_yx

            if new_price < nearestPrice:
                delta_price_xy = 1 / new_price - 1 / self.currentSqrtPrice
                delta_x = delta_price_xy * totalLiq * q96
                self._update_state_after_swap(delta_x, delta_y_left, totalLiq, new_price, activePositions, ZtO=False, last=True)
                delta_y_left = 0
                sum_delta_x += delta_x
            else:
                delta_y = totalLiq * (nearestPrice - self.currentSqrtPrice) / q96
                delta_y *= (1 + self.fee)
                delta_price_xy = 1 / nearestPrice - 1 / self.currentSqrtPrice
                delta_x = delta_price_xy * totalLiq * q96
                self._update_state_after_swap(delta_x, delta_y, totalLiq, nearestPrice, activePositions, ZtO=False, last=False)
                delta_y_left -= delta_y
                sum_delta_x += delta_x
                nearestPrice, activePositions, totalLiq = self._find_L_and_nearest_range(ZtO=False)

        if simulate:
            self.liq_bitmap = saved_liq_bitmap
            self.currentPrice = saved_price
            self.currentSqrtPrice = saved_sqrtPrice
            return sum_delta_x, new_price
        else:
            self._hook_after_swap(amnt, False)
            self.fee = saved_fee
            logger.info(f'Swap done: {amnt} y -> {sum_delta_x / eth} x, price after swap={(new_price / q96) ** 2:.3f}')

    def _hook_after_swap(self, amnt, ZtO):
        pass

    def _hook_before_swap(self, amnt, ZtO):
        return self.fee

    def _find_L_and_nearest_range(self, ZtO=True):
        """
        Find active liquidity positions and the nearest initialized tick price in swap direction.
        Returns (nearestPrice, activePositions, totalLiquidity).
        """
        nearestPrice = 0 if ZtO else 1e12 * q96
        activePositions = {}
        totalLiq = 0

        for id, pos in self.liq_bitmap.items():
            pa, pb = pos['pa'], pos['pb']

            if ZtO:
                if pb < self.currentSqrtPrice and (self.currentSqrtPrice - pb) < (self.currentSqrtPrice - nearestPrice):
                    nearestPrice = pb
                if pa < self.currentSqrtPrice and (self.currentSqrtPrice - pa) < (self.currentSqrtPrice - nearestPrice):
                    nearestPrice = pa
                if pa < self.currentSqrtPrice <= pb:
                    activePositions[id] = pos
                    totalLiq += pos['L']
            else:
                if pb > self.currentSqrtPrice and (pb - self.currentSqrtPrice) < (nearestPrice - self.currentSqrtPrice):
                    nearestPrice = pb
                if pa > self.currentSqrtPrice and (pa - self.currentSqrtPrice) < (nearestPrice - self.currentSqrtPrice):
                    nearestPrice = pa
                if pa <= self.currentSqrtPrice < pb:
                    activePositions[id] = pos
                    totalLiq += pos['L']

        # Remove single active position if it ends exactly at current price
        if len(activePositions) == 1:
            pos = next(iter(activePositions.values()))
            if (ZtO and pos['pa'] == self.currentSqrtPrice) or (not ZtO and pos['pb'] == self.currentSqrtPrice):
                activePositions = {}
                totalLiq = 0

        return nearestPrice, activePositions, totalLiq

    def _update_state_after_swap(self, delta_x, delta_y, totalActiveLiq, new_price, activePositions, ZtO=True, last=True):
        """
        Update pool state after swap step.
        Distributes deltas and fees among active liquidity providers proportionally.
        """
        logger.debug(f'Updating pool state: price {self.currentPrice} -> {(new_price / q96) ** 2}')
        self.currentPrice = (new_price / q96) ** 2
        self.currentSqrtPrice = new_price

        for id, pos in activePositions.items():
            share = pos['L'] / totalActiveLiq
            if ZtO:
                pos['x_real'] += delta_x * share * (1 - self.fee)
                pos['y_real'] += delta_y * share
                fees_x = delta_x / eth * share * self.fee
                pos['fee_x'] += fees_x
                pos['fee_in_y'] += fees_x * self.currentPrice
            else:
                pos['x_real'] += delta_x * share
                pos['y_real'] += delta_y * share * (1 - self.fee)
                fees_y = delta_y / eth * share * self.fee
                pos['fee_y'] += fees_y
                pos['fee_in_y'] += fees_y
