import asyncio
from android_tester.device_bridge import DeviceBridge
from android_tester.test_engine import TestEngine

async def main():
    print("Initializing DeviceBridge...")
    bridge = DeviceBridge()
    
    print("Checking connection...")
    connected = await bridge.check_connection()
    if connected:
        print(f"Connected to device: {bridge.device_id}")
        info = await bridge.get_hardware_info()
        print(f"Hardware Info: {info}")
        
        engine = TestEngine(bridge)
        print("Running Network Test...")
        await engine.run_network_test(lambda msg: print(f"LOG: {msg}"))
    else:
        print("No device connected. Tests skipped, but modules loaded successfully!")

if __name__ == "__main__":
    asyncio.run(main())
