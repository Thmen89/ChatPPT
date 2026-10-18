import asyncio
import os
import sys

from services.export_task_service import ExportTaskService
from services.liteparse_service import LiteParseService
from utils.runtime_limits import BoundedTextBuffer


def test_bounded_text_buffer_keeps_only_tail():
    buffer = BoundedTextBuffer(limit=5)
    buffer.append("abcdef")
    buffer.append("gh")

    value = buffer.get()

    assert "defgh" in value
    assert "truncated 3 chars" in value


def test_liteparse_plain_bridge_keeps_stdout_and_bounds_stderr(tmp_path):
    service = LiteParseService(timeout_seconds=10)
    service._npm_project_root = str(tmp_path)

    process = service._run_plain_bridge_to_text(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('x' * 5000); sys.stderr.write('e' * 10000)",
        ]
    )

    assert process.returncode == 0
    assert len(process.stdout) == 5000
    assert "truncated" in process.stderr


def test_export_child_output_is_bounded(tmp_path):
    service = ExportTaskService(timeout_seconds=10)

    result = asyncio.run(
        service._run_bounded_child(
            [
                sys.executable,
                "-c",
                "import sys; sys.stdout.write('o' * 10000); sys.stderr.write('e' * 10000); sys.exit(7)",
            ],
            cwd=str(tmp_path),
            env=os.environ.copy(),
            timeout=10,
        )
    )

    assert result["returncode"] == 7
    assert "truncated" in str(result["stdout"])
    assert "truncated" in str(result["stderr"])


def test_export_output_path_accepts_file_path_key(tmp_path):
    output_path = tmp_path / "preview.png"
    output_path.write_bytes(b"png")

    assert ExportTaskService._resolve_output_path({"file_path": str(output_path)}) == str(output_path)


def test_render_html_to_image_sends_html_task_payload(tmp_path):
    output_path = tmp_path / "preview.png"
    output_path.write_bytes(b"png")
    service = ExportTaskService(timeout_seconds=10)
    captured = {}

    async def fake_run_task(task_payload, response_error_detail):
        captured["task_payload"] = task_payload
        captured["response_error_detail"] = response_error_detail
        return {"file_path": str(output_path)}

    service._run_task = fake_run_task

    result = asyncio.run(service.render_html_to_image("<html></html>", 320, 180))

    assert result.path == str(output_path)
    assert captured["task_payload"] == {
        "type": "html-to-image",
        "html": "<html></html>",
        "width": 320,
        "height": 180,
    }
    assert "HTML-to-image" in captured["response_error_detail"]
