Sure! Here's a concise and clear README for your simulation project:

---

# Dex Simulator

A Python simulation framework modeling an AMM liquidity pool, arbitrage opportunities, and external market price dynamics. Designed to simulate Uniswap V3-like pools with concentrated liquidity and arbitrage bots acting on price discrepancies.

## Features

* **Pool**: Implements liquidity management, swaps, and price ticks.
* **Arbitrage**: Simulates arbitrage trading based on external price vs pool price.
* **Simulation**: Runs timed steps with configurable block time and saves data.
* Modular design with separate components for clear extensibility and testing.

## Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/yourusername/dex-simulator.git
cd dex-simulator
pip install -r requirements.txt
```

## Usage

Typical workflow to run the simulation:

1. **Load and prepare price data**
   Load historical OHLC data (e.g., from CSV), convert timestamps, and select the time interval for simulation.

   ```python
   price_data_all = OHLC_data.set_index('timestamp')['close']

   # Select slice (e.g. last day)
   left, right = -1000, 0  # seconds relative to the end
   price_data_slice = price_data_all[left:right] if right != 0 else price_data_all[left:]
   ```

2. **Calculate initial liquidity position parameters**
   Define pool bounds and initial token amounts based on Uniswap V3 formula.

   ```python
   from simulation.utils import price_to_sqrtp, liquidity0

   pa, pb = 2000, 5000
   x = 10 * eth
   pc = price_data[0]

   sqrt_pa = price_to_sqrtp(pa)
   sqrt_pb = price_to_sqrtp(pb)
   sqrt_pc = price_to_sqrtp(pc)

   liq0 = liquidity0(x, sqrt_pc, sqrt_pb)
   y = liq0 * (sqrt_pc - sqrt_pa) / q96
   ```

3. **Configure and run the simulation**
   Instantiate pool, arbitrage, and simulation classes. Add liquidity position and iterate over price data.

   ```python
   sim = Simulation(poolClass=Pool, arbClass=Arbitrage, 
                    blockPerSecondMoreThanOne=False, blockPerSecondOrSecondsPerBlock=4, 
                    filename='result.csv', save_block_info=True)

   sim.configure_pool(first_price=pc, fee=0)
   sim.configure_arb(minGasPrice=0.002, profitToGasRatio=0.1, fee_outside=0, skip=0)

   sim.poolClass.add_liquidity(id=0, x=x/eth, y=y/eth, pa=pa, pb=pb)

   start = time.time()
   for i, (timestamp, currentPriceOutside) in enumerate(zip(timestamps_data, price_data)):
       sim.step_second(currentPriceOutside=currentPriceOutside, timestamp=timestamp)
       if i % 100000 == 0:
           logger.critical(f'Iteration {i}, timestamp: {timestamp}, price: {currentPriceOutside:.2f}, poolPrice: {sim.poolClass.currentPrice:.2f}')

   logger.critical(f'Simulation of {i} iterations took {time.time()-start:.2f} seconds')

   sim.close_file()
   ```

4. **Analyze results**
   Load the CSV output and plot relevant metrics (e.g., cumulative volume, pool and external prices).

   ```python
   res = pd.read_csv('result.csv')
   plt.plot(res.timestamp, res.cumulativeVolume)
   plt.plot(res.timestamp, res.currentPriceOutside)
   plt.plot(res.timestamp, res.currentPrice)
   plt.show()
   ```

---

For a detailed step-by-step example, see the Jupyter Notebook:
[Simulation Example Notebook](https://github.com/cvvcvccvvcvc/dex-simulator/notebooks/simulation_example.ipynb)

## Project Structure

* `pool.py` — liquidity pool logic, swap calculations.
* `arbitrage.py` — arbitrage opportunity detection and execution.
* `simulation.py` — runs the time-stepped simulation and logs results.
* `utils.py` — helper functions like price conversion.
* `constants.py` — fixed constants like Q96 and ETH scaling.
* `logger.py` — logging configuration.

## Contributing

Feel free to open issues or submit pull requests. Please keep code clear and documented.

## License

MIT License
