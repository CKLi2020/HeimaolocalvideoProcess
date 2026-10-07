"""Exercise Qixia inside its owning application and protected release host."""

from pathlib import Path
import time

from PySide6.QtWidgets import QApplication

from app.pages.local_processor_page import LocalProcessorPage
from core.runner import verify_output
from engine.native_core import core


def run_self_test(tool_root: Path, source: Path) -> dict:
    if not source.is_file():
        raise ValueError(f"Qixia self-test input does not exist: {source}")
    app = QApplication.instance() or QApplication([])
    page = LocalProcessorPage(tool_root)
    logs = []
    results = []
    page.done_received.disconnect(page._on_done)
    page.log_received.connect(logs.append)
    page.done_received.connect(lambda *result: results.append(result))
    try:
        if page.service.mode_errors:
            raise RuntimeError(f"Mode loading failed: {page.service.mode_errors}")
        combo = page._platforms["视频号处理"][1]
        ids = [combo.itemData(index).id for index in range(combo.count())]
        if ids.count("shipinhao/qixia_mode5") != 1:
            raise RuntimeError(f"Qixia registration is not unique: {ids}")
        index = ids.index("shipinhao/qixia_mode5")
        if index != 0:
            raise RuntimeError(f"Qixia is not first in the platform list: {index}")
        combo.setCurrentIndex(index)
        page._activate("视频号处理")
        if page.current_mode.name != "栖霞1007" or page.aux_edit.isEnabled():
            raise RuntimeError("Qixia name or single-input UI is incorrect")
        capture = tool_root.resolve() / "capture"
        if page.output_edit.isReadOnly() or not all(
            button.isEnabled() for button in page.output_edit._path_buttons
        ):
            raise RuntimeError("Qixia output folder selection is disabled")
        output_directory = tool_root.resolve() / "output" / "qixia-self-test"
        page.output_edit.setText(str(output_directory))
        page.main_edit.setText(str(source))
        page.mode5_lasong.setChecked(True)
        page.mode5_ronghe.setChecked(True)
        page.mode5_daoli.setChecked(True)
        page.mode5_opacity.setValue(25)
        if not page.mode5_opacity.isEnabled():
            raise RuntimeError("Qixia opacity setting is disabled")
        page.copies_spin.setValue(1)
        cpu_index = page.processor.findData(False)
        if cpu_index < 0:
            raise RuntimeError("CPU execution is not selectable")
        page.processor.setCurrentIndex(cpu_index)
        before = set(output_directory.glob("*.mp4"))
        page.start()
        if page.service._thread is None:
            raise RuntimeError("Qixia task did not start")
        deadline = time.monotonic() + 180
        while page.service.is_running:
            app.processEvents()
            if time.monotonic() > deadline:
                page.service.stop()
                raise TimeoutError("Qixia release conversion timed out")
            time.sleep(0.02)
        app.processEvents()
        if len(results) != 1 or results[0][:3] != (1, 0, 1):
            raise RuntimeError(f"Qixia conversion failed: {results}; logs={logs}")
        outputs = set(output_directory.glob("*.mp4")) - before
        if len(outputs) != 1:
            raise RuntimeError(f"Expected one new Qixia output: {outputs}")
        output = outputs.pop().resolve()
        if output.parent != output_directory:
            raise RuntimeError(f"Output did not use the selected folder: {output}")
        valid, message = verify_output(page.service.config, str(output), expected_audio_tracks=1)
        if not valid:
            raise RuntimeError(f"Qixia output verification failed: {message}")
        commands = [line for line in logs if "A*0.25+B*0.75" in line]
        if not commands or not any("vflip" in line and "b-adapt=0" in line for line in commands):
            raise RuntimeError(f"UI settings were not passed to the worker: {logs}")
        report = {
            "passed": True,
            "tool_root": str(tool_root.resolve()),
            "capture": str(capture),
            "output_directory": str(output_directory),
            "source": str(source.resolve()),
            "output": str(output),
            "channel_id": page.current_mode.id,
            "channel_name": page.current_mode.name,
            "channel_index": index,
            "channel_ids": ids,
            "needs_aux": page.current_mode.needs_aux,
            "opacity": page.mode5_opacity.value(),
            "core_module": core.__name__,
            "result": results[0],
            "verification": message,
            "logs": logs,
        }
        if hasattr(core, "host_gate_status"):
            report["host_gate"] = core.host_gate_status()
        return report
    finally:
        if page.service.is_running:
            page.service.stop()
        page.close()
