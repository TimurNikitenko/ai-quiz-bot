import asyncio
import logging
from parser.scheduler import main as scheduler_main

if __name__ == "__main__":
    asyncio.run(scheduler_main())