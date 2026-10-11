import asyncio
import re
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll, Vertical
from textual.widgets import Header, Footer, Static, Button, RichLog, Label
from textual.reactive import reactive

from .device_bridge import DeviceBridge
from .test_engine import TestEngine

class DeviceStatus(Static):
    status_text = reactive("Checking connection...")

    def render(self) -> str:
        return self.status_text

class CapabilityMatrix(Static):
    matrix_text = reactive("Loading capability matrix...")
    def render(self) -> str:
        return self.matrix_text

class AndroidTesterTUI(App):
    CSS = """
    Screen {
        background: $surface;
    }
    #main_container {
        layout: horizontal;
        height: 100%;
    }
    #left_panel {
        width: 30%;
        border-right: solid $primary;
        padding: 1;
    }
    #right_panel {
        width: 70%;
        layout: vertical;
        padding: 1;
    }
    #device_status {
        height: auto;
        border: solid $secondary;
        padding: 1;
        margin-bottom: 1;
    }
    #capability_matrix {
        height: auto;
        border: solid $secondary;
        padding: 1;
        margin-bottom: 1;
    }
    #test_controls {
        height: auto;
        border: solid $accent;
        padding: 1;
    }
    Button {
        width: 100%;
        margin-bottom: 1;
    }
    #action_log {
        height: 50%;
        border: solid $success;
        margin-bottom: 1;
    }
    #crash_log {
        height: 50%;
        border: solid $error;
        background: $error-muted;
    }
    .title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    """

    BINDINGS = [("d", "toggle_dark", "Toggle dark mode"), ("q", "quit", "Quit")]

    def __init__(self):
        super().__init__()
        self.bridge = DeviceBridge()
        self.engine = TestEngine(self.bridge)
        self.logcat_task = None
        self.stop_event = asyncio.Event()
        self.log_queue = asyncio.Queue()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main_container"):
            with VerticalScroll(id="left_panel"):
                yield Label("DEVICE STATUS", classes="title")
                yield DeviceStatus(id="device_status")
                
                yield Label("CAPABILITY MATRIX", classes="title")
                yield CapabilityMatrix(id="capability_matrix")
                
                yield Label("TEST CONTROLS", classes="title")
                with Vertical(id="test_controls"):
                    yield Button("Run Deep Scale System Audit", id="btn_full", variant="primary")
                    yield Button("Probe Root Elevation", id="btn_probe_root", variant="warning")
                    yield Button("Authenticity & Spoof Check", id="btn_authenticity")
                    yield Button("Storage I/O Health", id="btn_storage")
                    yield Button("CPU Benchmark", id="btn_cpu")
                    yield Button("GPU Stress", id="btn_gpu")
                    yield Button("Thermal Stress", id="btn_thermal")
                    yield Button("Battery Health", id="btn_battery")
                    yield Button("Sensor Audit", id="btn_sensor")
                    yield Button("Display & Touch Panel", id="btn_display")
                    yield Button("Biometric (FP/Face)", id="btn_biometric")
                    yield Button("Hardware Presence", id="btn_presence")
                    yield Button("Memory Health", id="btn_memory")
                    yield Button("Network Latency/Speed", id="btn_network")
                    
                    yield Label("--- Aux Tests ---", classes="title")
                    yield Button("Monkey UI Test", id="btn_monkey")
                    yield Button("EXTREME Monkey Stress (50k)", id="btn_monkey_extreme", variant="error")
                    yield Button("OOM Drop Caches", id="btn_oom", variant="error")
                    
            with Vertical(id="right_panel"):
                yield Label("ACTION & EVENT LOG", classes="title")
                yield RichLog(id="action_log", highlight=True, markup=True)
                yield Label("CRASH & FATAL LOGS", classes="title")
                yield RichLog(id="crash_log", highlight=True, markup=True)
        yield Footer()

    async def _update_status(self):
        connected = await self.bridge.check_connection()
        status_widget = self.query_one("#device_status", DeviceStatus)
        matrix_widget = self.query_one("#capability_matrix", CapabilityMatrix)
        
        if connected:
            info = await self.bridge.get_hardware_info()
            # We don't automatically trigger root check since we want a toggle/button for it.
            # but we can show current known state
            is_rooted = self.engine.pm.is_rooted
            root_status = "[bold red]YES[/bold red]" if is_rooted else "[bold yellow]NO[/bold yellow]"
            
            status = f"Device ID: {self.bridge.device_id}\nRooted: {root_status}\n"
            for k, v in info.items():
                status += f"{k}: {v}\n"
            status_widget.status_text = status
            
            if is_rooted:
                matrix_widget.matrix_text = "Root-Enhanced Mode Available.\nTests will access raw hardware blocks, sysfs telemetry, and low-level driver details."
            else:
                matrix_widget.matrix_text = "Standard Mode.\nTests limited to userspace filesystem boundaries and standard dumpsys diagnostics."
                
            return True
        else:
            status_widget.status_text = "[bold red]NO DEVICE CONNECTED[/bold red]\nPlease connect a device or start an emulator."
            matrix_widget.matrix_text = "N/A"
            return False

    async def on_mount(self) -> None:
        self.action_logger = self.query_one("#action_log", RichLog)
        self.crash_logger = self.query_one("#crash_log", RichLog)
        
        self.action_logger.write("[bold green]TUI Initialized. Checking ADB connection...[/bold green]")
        
        # Probe for root automatically at startup
        await self.engine.pm.check_root()
        
        connected = await self._update_status()
        if connected:
            self.action_logger.write(f"[bold cyan]Connected to {self.bridge.device_id}[/bold cyan]")
            if self.engine.pm.is_rooted:
                self.action_logger.write(f"[SUCCESS] Root detected automatically: {self.engine.pm.su_impl}")
            
            # Start background logcat listener
            self.logcat_task = asyncio.create_task(self.bridge.listen_logcat(self.log_queue, self.stop_event, is_rooted=self.engine.pm.is_rooted))
            self.set_interval(0.5, self.process_log_queue)
        else:
            self.action_logger.write("[bold red]No ADB devices found.[/bold red]")

    def process_log_queue(self):
        for _ in range(50):
            if self.log_queue.empty():
                break
            line = self.log_queue.get_nowait()
            
            if self.engine.is_running:
                self.engine.auditor.add_log(line)
            
            crash_patterns = [r'FATAL EXCEPTION', r'ANR in', r'CRASH:']
            if any(re.search(p, line, re.IGNORECASE) for p in crash_patterns):
                self.crash_logger.write(f"[bold red]{line}[/bold red]")

    def log_cb(self, message: str):
        if "[ERROR]" in message or "[FATAL]" in message:
            self.action_logger.write(f"[red]{message}[/red]")
        elif "[SUCCESS]" in message:
            self.action_logger.write(f"[green]{message}[/green]")
        elif "[WARNING]" in message:
            self.action_logger.write(f"[yellow]{message}[/yellow]")
        else:
            self.action_logger.write(message)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if not self.bridge.device_id:
            self.action_logger.write("[bold red]Cannot run test: No device connected.[/bold red]")
            return
            
        if self.engine.is_running:
            self.action_logger.write("[bold yellow]A test is already running. Please wait.[/bold yellow]")
            return

        button_id = event.button.id
        self.action_logger.write(f"\n--- Starting {button_id} ---")
        
        if button_id == "btn_probe_root":
            self.action_logger.write("[INFO] Probing for root elevation...")
            rooted = await self.engine.pm.check_root()
            if rooted:
                self.action_logger.write(f"[SUCCESS] Root found! Implementation: {self.engine.pm.su_impl}")
            else:
                self.action_logger.write("[WARNING] No functional root found.")
            await self._update_status()
            
            # Restart logcat to potentially include dmesg
            self.stop_event.set()
            if self.logcat_task:
                await self.logcat_task
            self.stop_event.clear()
            self.logcat_task = asyncio.create_task(self.bridge.listen_logcat(self.log_queue, self.stop_event, is_rooted=self.engine.pm.is_rooted))
            return
        
        # Test Execution
        if button_id == "btn_full":
            asyncio.create_task(self.engine.run_full_scale(self.log_cb))
        elif button_id == "btn_authenticity":
            asyncio.create_task(self.engine.run_authenticity_test(self.log_cb))
        elif button_id == "btn_storage":
            asyncio.create_task(self.engine.run_storage_test(self.log_cb))
        elif button_id == "btn_cpu":
            asyncio.create_task(self.engine.run_cpu_test(self.log_cb))
        elif button_id == "btn_gpu":
            asyncio.create_task(self.engine.run_gpu_test(self.log_cb))
        elif button_id == "btn_thermal":
            asyncio.create_task(self.engine.run_thermal_stress(self.log_cb))
        elif button_id == "btn_battery":
            asyncio.create_task(self.engine.run_battery_test(self.log_cb))
        elif button_id == "btn_sensor":
            asyncio.create_task(self.engine.run_sensor_test(self.log_cb))
        elif button_id == "btn_display":
            asyncio.create_task(self.engine.run_display_touch_test(self.log_cb))
        elif button_id == "btn_biometric":
            asyncio.create_task(self.engine.run_biometric_test(self.log_cb))
        elif button_id == "btn_presence":
            asyncio.create_task(self.engine.run_hardware_presence_test(self.log_cb))
        elif button_id == "btn_memory":
            asyncio.create_task(self.engine.run_memory_test(self.log_cb))
        elif button_id == "btn_network":
            asyncio.create_task(self.engine.run_network_test(self.log_cb))
        elif button_id == "btn_monkey":
            asyncio.create_task(self.engine.run_ui_monkey_test(self.log_cb))
        elif button_id == "btn_monkey_extreme":
            asyncio.create_task(self.engine.run_ui_monkey_test(self.log_cb, event_count=50000))
        elif button_id == "btn_oom":
            asyncio.create_task(self.engine.run_oom_test(self.log_cb))

    async def on_unmount(self) -> None:
        self.stop_event.set()
        if self.logcat_task:
            await self.logcat_task

def main():
    app = AndroidTesterTUI()
    app.run()

if __name__ == "__main__":
    main()

