import asyncio
import sys

def main():
    if "--headless" in sys.argv or "--full" in sys.argv:
        from android_tester.device_bridge import DeviceBridge
        from android_tester.test_engine import TestEngine

        async def _run():
            b = DeviceBridge()
            if not await b.check_connection():
                print("No device connected.")
                return 1
            e = TestEngine(b)
            await e.run_full_scale(print)
            return 0
        raise SystemExit(asyncio.run(_run()))
    from android_tester.tui import AndroidTesterTUI
    AndroidTesterTUI().run()

if __name__ == "__main__":
    main()
