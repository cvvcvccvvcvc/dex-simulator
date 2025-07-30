import csv
from .logger import logger

class Simulation:
    """
    Simulation engine to run arbitrage trading steps over time blocks.

    Args:
        poolClass (class): Pool class to instantiate liquidity pool.
        arbClass (class): Arbitrage class to instantiate arbitrage agent.
        blockPerSecondMoreThanOne (bool): True if blocks per sec > 1, else False. False is currently not working.
        blockPerSecondOrSecondsPerBlock (int): Number of blocks per second (if blockPerSecondMoreThanOne==True) or seconds per block.
        save_block_info (bool): Whether to save each block info to CSV.
        filename (str): CSV filename to save simulation data.
    """

    def __init__(self, poolClass, arbClass, blockPerSecondMoreThanOne,
                 blockPerSecondOrSecondsPerBlock, filename, save_block_info=False):
        logger.info('Simulation initiated')

        self.poolClass = poolClass
        self.arbClass = arbClass
        self.currentBlock = 0

        self.blockPerSecondMoreThanOne = blockPerSecondMoreThanOne
        self.blockPerSecondOrSecondsPerBlock = blockPerSecondOrSecondsPerBlock
        self.counter = blockPerSecondOrSecondsPerBlock - 1  # start counter

        self.filename = filename
        self.save_block_info = save_block_info

        if self.save_block_info:
            self.file = open(self.filename, mode='w', newline='')
            self.writer = csv.writer(self.file)
            self.writer.writerow(['timestamp', 'currentPriceOutside', 'currentPrice', 'cumulativeVolume'])

    def close_file(self):
        """Close CSV file if open."""
        if self.save_block_info:
            self.file.close()
            logger.info(f"Simulation data saved to {self.filename}")

    def configure_pool(self, first_price, fee):
        """Instantiate pool with initial price and fee."""
        self.poolClass = self.poolClass(first_price, fee)

    def configure_arb(self, minGasPrice, profitToGasRatio, fee_outside, skip):
        """Instantiate arbitrage agent with parameters."""
        self.arbClass = self.arbClass(
            minGasPrice=minGasPrice,
            profitToGasRatio=profitToGasRatio,
            pool=self.poolClass,
            fee_outside=fee_outside,
            skip=skip
        )

    def step_second(self, currentPriceOutside, timestamp):
        """
        Simulate one second.

        Args:
            currentPriceOutside (float): External market price at this step.
            timestamp (str/int): Timestamp associated with the step.
        """
        self.counter += 1
        if self.counter >= self.blockPerSecondOrSecondsPerBlock:
            self.currentBlock += 1

            # Execute arbitrage deal attempt
            self.arbClass.deal(currentPriceOutside)

            # Save block info if enabled
            if self.save_block_info:
                self.writer.writerow([
                    timestamp,
                    currentPriceOutside,
                    self.poolClass.currentPrice,
                    self.arbClass.cumulativeVolume
                ])

            self.counter = 0
